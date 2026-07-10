"""Unit tests for the TCP bridge client. No running game required."""

from __future__ import annotations

import socket
import struct
import threading

import pytest

from crpg_rle.core.bridge import (
    BridgeDied,
    BridgeRequestError,
    TcpBridgeClient,
    decode_frame,
    encode_frame,
)

_LEN = struct.Struct("<I")


# --------------------------------------------------------------------------
# Frame encode/decode
# --------------------------------------------------------------------------


def test_frame_roundtrip_simple():
    obj = {"id": 1, "op": "ping"}
    frame = encode_frame(obj)
    decoded, remainder = decode_frame(frame)
    assert decoded == obj
    assert remainder == b""


def test_frame_roundtrip_empty_dict():
    frame = encode_frame({})
    decoded, remainder = decode_frame(frame)
    assert decoded == {}
    assert remainder == b""


def test_frame_roundtrip_multibyte_utf8():
    obj = {"text": "café — 日本語 — Ω", "emoji": "🎮"}
    frame = encode_frame(obj)
    # Length prefix must count bytes, not characters.
    (length,) = _LEN.unpack_from(frame)
    assert length == len(frame) - _LEN.size
    decoded, remainder = decode_frame(frame)
    assert decoded == obj
    assert remainder == b""


def test_decode_partial_frame_returns_none():
    frame = encode_frame({"op": "reset"})
    # Missing header bytes.
    assert decode_frame(frame[:2]) == (None, frame[:2])
    # Full header, missing payload.
    assert decode_frame(frame[:5]) == (None, frame[:5])


def test_decode_leaves_remainder():
    a = encode_frame({"a": 1})
    b = encode_frame({"b": 2})
    decoded, remainder = decode_frame(a + b)
    assert decoded == {"a": 1}
    assert remainder == b


# --------------------------------------------------------------------------
# Fake in-process TCP server
# --------------------------------------------------------------------------


class FakeServer:
    """A one-connection TCP server driven by a handler callback.

    The handler receives ``(request_dict, connection_socket)`` for each request
    and returns either a response dict (sent framed) or ``None`` (send nothing).
    """

    def __init__(self, handler):
        self._handler = handler
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.host, self.port = self._sock.getsockname()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        with conn:
            buf = bytearray()
            while True:
                obj, remainder = decode_frame(bytes(buf))
                if obj is None:
                    try:
                        chunk = conn.recv(65536)
                    except OSError:
                        return
                    if not chunk:
                        return
                    buf.extend(chunk)
                    continue
                buf = bytearray(remainder)
                response = self._handler(obj, conn)
                if response is None:
                    return
                try:
                    conn.sendall(encode_frame(response))
                except OSError:
                    return

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


@pytest.fixture
def make_client():
    servers = []
    clients = []

    def _make(handler, **kwargs):
        server = FakeServer(handler)
        servers.append(server)
        client = TcpBridgeClient(
            host=server.host, port=server.port, connect_timeout=5.0, **kwargs
        )
        clients.append(client)
        return client, server

    yield _make

    for c in clients:
        c.close()
    for s in servers:
        s.close()


# --------------------------------------------------------------------------
# Request/response behaviour
# --------------------------------------------------------------------------


def test_request_id_matching_and_echo(make_client):
    def handler(req, _conn):
        return {"id": req["id"], "ok": True, "echo_op": req["op"]}

    client, _ = make_client(handler)
    resp = client.ping()
    assert resp["ok"] is True
    assert resp["id"] == 1
    assert resp["echo_op"] == "ping"


def test_two_sequential_requests(make_client):
    def handler(req, _conn):
        return {"id": req["id"], "ok": True, "op": req["op"]}

    client, _ = make_client(handler)
    r1 = client.handshake(proto=1)
    r2 = client.observe()
    assert r1["id"] == 1
    assert r1["op"] == "handshake"
    assert r2["id"] == 2
    assert r2["op"] == "observe"


def test_ok_false_raises_request_error(make_client):
    def handler(req, _conn):
        return {"id": req["id"], "ok": False, "error": "boom"}

    client, _ = make_client(handler)
    with pytest.raises(BridgeRequestError) as excinfo:
        client.reset()
    assert excinfo.value.error == "boom"
    assert excinfo.value.op == "reset"


def test_id_mismatch_raises_died(make_client):
    def handler(req, _conn):
        return {"id": req["id"] + 999, "ok": True}

    client, _ = make_client(handler)
    with pytest.raises(BridgeDied):
        client.ping()


def test_server_closes_mid_response_raises_died(make_client):
    def handler(req, conn):
        # Send only a partial frame (a length prefix promising more), then
        # close, so the client is left waiting on an incomplete response.
        conn.sendall(_LEN.pack(100) + b"{")
        conn.close()
        return None

    client, _ = make_client(handler)
    with pytest.raises(BridgeDied):
        client.ping()


def test_request_timeout_raises_died(make_client):
    def handler(_req, _conn):
        # Never respond; hold the connection open past the request timeout.
        import time

        time.sleep(5.0)
        return None

    client, _ = make_client(handler, request_timeout=0.3)
    with pytest.raises(BridgeDied):
        client.ping()


def test_connect_failure_raises_died():
    # Bind then immediately close to obtain a port nobody listens on.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    _, port = s.getsockname()
    s.close()

    client = TcpBridgeClient(host="127.0.0.1", port=port, connect_timeout=0.5)
    with pytest.raises(BridgeDied):
        client.ping()


def test_context_manager(make_client):
    def handler(req, _conn):
        return {"id": req["id"], "ok": True}

    client, _ = make_client(handler)
    with client as c:
        assert c.ping()["ok"] is True
