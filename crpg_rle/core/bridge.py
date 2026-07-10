"""TCP IPC bridge client for the Tyranny BepInEx mod.

The game (C#/BepInEx) runs a TCP *server*; Python connects as the *client*.

Wire protocol
-------------
Each message is a 4-byte little-endian unsigned length prefix followed by a
UTF-8 encoded JSON payload of exactly that length. Communication is strictly
request/response: the client sends one request and reads exactly one response.

Every request carries an auto-incrementing integer ``"id"`` and a string
``"op"``. The response echoes the same ``"id"`` and includes a boolean
``"ok"``. When ``ok`` is ``false`` the response also carries an ``"error"``
string.
"""

from __future__ import annotations

import abc
import json
import logging
import socket
import struct
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_LEN_PREFIX = struct.Struct("<I")
_HEADER_SIZE = _LEN_PREFIX.size


class BridgeError(Exception):
    """Base class for all bridge errors."""


class BridgeDied(BridgeError):
    """The connection was lost, timed out, or the peer closed unexpectedly."""


class BridgeRequestError(BridgeError):
    """The peer answered with ``ok: false``.

    Carries the error string reported by the peer and the ``op`` that failed.
    """

    def __init__(self, error: str, op: str) -> None:
        super().__init__(f"request op={op!r} failed: {error}")
        self.error = error
        self.op = op


def encode_frame(obj: Any) -> bytes:
    """Encode ``obj`` as a length-prefixed UTF-8 JSON frame."""
    payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    return _LEN_PREFIX.pack(len(payload)) + payload


def decode_frame(buf: bytes) -> tuple[Any | None, bytes]:
    """Try to decode one frame from ``buf``.

    Returns ``(obj, remainder)``. If ``buf`` does not yet contain a complete
    frame, returns ``(None, buf)`` unchanged.
    """
    if len(buf) < _HEADER_SIZE:
        return None, buf
    (length,) = _LEN_PREFIX.unpack_from(buf)
    end = _HEADER_SIZE + length
    if len(buf) < end:
        return None, buf
    payload = buf[_HEADER_SIZE:end]
    obj = json.loads(payload.decode("utf-8"))
    return obj, buf[end:]


class BridgeClient(abc.ABC):
    """Abstract request/response client to the game bridge.

    Subclasses implement the transport (:meth:`request`, :meth:`close`); the
    concrete convenience methods below are thin wrappers over :meth:`request`.
    """

    @abc.abstractmethod
    def request(self, op: str, **params: Any) -> dict:
        """Send a request with the given ``op`` and params; return the response."""
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """Close the underlying transport."""
        raise NotImplementedError

    # -- convenience operations -------------------------------------------

    def handshake(self, proto: int = 1) -> dict:
        """Negotiate the protocol version with the server."""
        return self.request("handshake", proto=proto)

    def config(self, **settings: Any) -> dict:
        """Push configuration settings to the server."""
        return self.request("config", **settings)

    def reset(self, **params: Any) -> dict:
        """Reset the environment to a starting state."""
        return self.request("reset", **params)

    def act(self, inputs: list[dict], frames: int) -> dict:
        """Apply ``inputs`` and advance the game by ``frames`` frames."""
        return self.request("act", inputs=inputs, frames=frames)

    def observe(self) -> dict:
        """Fetch the current observation."""
        return self.request("observe")

    def ping(self) -> dict:
        """Round-trip liveness check."""
        return self.request("ping")

    def shutdown(self) -> dict:
        """Ask the server to shut down."""
        return self.request("shutdown")


class TcpBridgeClient(BridgeClient):
    """A TCP implementation of :class:`BridgeClient`.

    Thread-safe: a lock serializes each request/response exchange so concurrent
    callers cannot interleave frames on the socket.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5555,
        connect_timeout: float = 30.0,
        request_timeout: float = 60.0,
    ) -> None:
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.request_timeout = request_timeout
        self._sock: socket.socket | None = None
        self._recv_buf = bytearray()
        self._next_id = 1
        self._lock = threading.Lock()

    # -- connection management --------------------------------------------

    def connect(self) -> None:
        """Connect to the server, retrying until ``connect_timeout`` elapses.

        The game takes time to boot, so connection refusals are retried.
        """
        if self._sock is not None:
            return
        deadline = time.monotonic() + self.connect_timeout
        last_err: OSError | None = None
        while True:
            try:
                sock = socket.create_connection(
                    (self.host, self.port), timeout=self.request_timeout
                )
                sock.settimeout(self.request_timeout)
                self._sock = sock
                self._recv_buf.clear()
                logger.debug("connected to bridge at %s:%d", self.host, self.port)
                return
            except OSError as exc:
                last_err = exc
                if time.monotonic() >= deadline:
                    raise BridgeDied(
                        f"could not connect to {self.host}:{self.port} "
                        f"within {self.connect_timeout}s"
                    ) from last_err
                time.sleep(0.25)

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._recv_buf.clear()

    # -- request/response --------------------------------------------------

    def request(self, op: str, **params: Any) -> dict:
        with self._lock:
            if self._sock is None:
                self.connect()
            assert self._sock is not None

            req_id = self._next_id
            self._next_id += 1
            message = {"id": req_id, "op": op, **params}

            try:
                self._sock.sendall(encode_frame(message))
                response = self._recv_frame()
            except (OSError, socket.timeout) as exc:
                self._close_locked()
                raise BridgeDied(f"transport error during op={op!r}: {exc}") from exc

            resp_id = response.get("id")
            if resp_id != req_id:
                self._close_locked()
                raise BridgeDied(
                    f"response id mismatch: expected {req_id}, got {resp_id!r}"
                )
            if not response.get("ok", False):
                error = response.get("error", "<no error message>")
                raise BridgeRequestError(str(error), op)
            return response

    def _recv_frame(self) -> dict:
        """Read exactly one frame from the socket, handling partial recv."""
        assert self._sock is not None
        while True:
            obj, remainder = decode_frame(bytes(self._recv_buf))
            if obj is not None:
                self._recv_buf = bytearray(remainder)
                return obj
            chunk = self._sock.recv(65536)
            if not chunk:
                raise BridgeDied("peer closed the connection mid-response")
            self._recv_buf.extend(chunk)

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> TcpBridgeClient:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
