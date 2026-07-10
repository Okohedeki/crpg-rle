"""Flat-binary TCP env server — the bridge between a PufferLib 4.0 C shim and a
Python CRPGEnv.

PufferLib 4.0 has no out-of-process env path: envs are C compiled into _C.so and
stepped in a synchronous OpenMP loop. To drive a live game from that
trainer we run this server on the game host; the 4.0 C shim connects and, inside
its blocking c_step, sends the action ints and receives a flat observation +
reward + terminal frame. All game logic stays in the injected env (Python).

Protocol (little-endian, one client):
  handshake:  client -> {magic 'CRPG', proto u32}
              server -> {obs_size u32, n_actions u32, base_seed u64}
  step:       client -> int32[n_actions] actions
              server -> float32[obs_size] obs, float32 reward, u8 terminal, u8 truncated
  On terminal the server auto-resets (seed = base_seed + episode_index) and the
  returned obs is the first obs of the next episode (4.0's in-c_step reset model).

The flat obs is the CRPGEnv Dict flattened deterministically; the layout is
written to a sidecar JSON so the policy can slice it back.
"""
from __future__ import annotations

import json
import logging
import socket
import struct

import numpy as np

logger = logging.getLogger(__name__)

MAGIC = b"CRPG"


def flatten_obs(obs: dict) -> np.ndarray:
    """Flatten the Dict observation into one float32 vector (pixels scaled to
    [0,1]). Order: pixels, state, mode(one-hot-ish scalar), goal."""
    parts = [
        obs["pixels"].astype(np.float32).ravel() / 255.0,
        obs["state"].astype(np.float32).ravel(),
        np.asarray([obs["mode"]], dtype=np.float32),
        obs["goal"].astype(np.float32).ravel(),
    ]
    return np.concatenate(parts)


def obs_layout(obs: dict) -> dict:
    p = obs["pixels"]
    return {
        "pixels": {"offset": 0, "shape": list(p.shape), "scale": 255.0},
        "state": {"offset": int(p.size), "shape": list(obs["state"].shape)},
        "mode": {"offset": int(p.size + obs["state"].size), "shape": [1]},
        "goal": {"offset": int(p.size + obs["state"].size + 1), "shape": list(obs["goal"].shape)},
    }


class EnvServer:
    """Serves one CRPGEnv over the flat-binary protocol."""

    def __init__(self, env, host: str = "127.0.0.1", port: int = 7000,
                 base_seed: int = 0, layout_path: str | None = None):
        self.env = env
        self.host = host
        self.port = port
        self.base_seed = base_seed
        self.layout_path = layout_path
        self._episode = 0

    def _recv_exact(self, conn: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("client closed")
            buf += chunk
        return buf

    def serve_forever(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((self.host, self.port))
        srv.listen(1)
        logger.info("env_server listening on %s:%d", self.host, self.port)
        while True:
            conn, addr = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            logger.info("client connected from %s", addr)
            try:
                self._serve_client(conn)
            except (ConnectionError, OSError) as e:
                logger.warning("client dropped: %s", e)
            finally:
                conn.close()

    def _serve_client(self, conn: socket.socket) -> None:
        magic = self._recv_exact(conn, 4)
        if magic != MAGIC:
            raise ConnectionError(f"bad magic {magic!r}")
        (_proto,) = struct.unpack("<I", self._recv_exact(conn, 4))

        self._episode = 0
        obs, _info = self.env.reset(seed=self.base_seed)
        flat = flatten_obs(obs)
        n_actions = int(np.asarray(self.env.action_space.nvec).size)

        if self.layout_path:
            with open(self.layout_path, "w") as f:
                json.dump({"obs_size": int(flat.size), "n_actions": n_actions,
                           "layout": obs_layout(obs)}, f, indent=2)

        conn.sendall(struct.pack("<IIQ", int(flat.size), n_actions, self.base_seed & ((1 << 64) - 1)))
        conn.sendall(flat.tobytes())

        while True:
            raw = self._recv_exact(conn, 4 * n_actions)
            actions = np.frombuffer(raw, dtype=np.int32)
            obs, reward, terminated, truncated, _info = self.env.step(actions)
            done = bool(terminated or truncated)
            if done:
                self._episode += 1
                obs, _info = self.env.reset(seed=self.base_seed + self._episode)
            flat = flatten_obs(obs)
            conn.sendall(flat.tobytes())
            conn.sendall(struct.pack("<fBB", float(reward), 1 if terminated else 0, 1 if truncated else 0))
