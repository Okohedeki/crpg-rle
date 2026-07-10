"""Env-server wire-protocol test. A mock client speaks exactly what the
PufferLib 4.0 C shim (ocean/tyranny) sends/receives, against a dummy env.
Proves the flat-binary protocol end-to-end without needing the Linux C build.
"""
import socket
import struct
import threading
import time

import numpy as np
import gymnasium as gym

from crpg_rle.core.env_server import EnvServer, MAGIC, flatten_obs


class DummyEnv(gym.Env):
    """Minimal CRPGEnv-shaped env: Dict obs {pixels,state,mode,goal}, MultiDiscrete action."""

    def __init__(self):
        self.action_space = gym.spaces.MultiDiscrete([64, 36, 4, 13])
        self.observation_space = gym.spaces.Dict({
            "pixels": gym.spaces.Box(0, 255, (4, 4, 3), np.uint8),
            "state": gym.spaces.Box(-np.inf, np.inf, (5,), np.float32),
            "mode": gym.spaces.Discrete(9),
            "goal": gym.spaces.Box(0, 1, (6,), np.float32),
        })
        self._t = 0
        self._seed = 0

    def _obs(self):
        return {
            "pixels": np.full((4, 4, 3), self._t % 256, dtype=np.uint8),
            "state": np.arange(5, dtype=np.float32) + self._t,
            "mode": self._t % 9,
            "goal": np.eye(6, dtype=np.float32)[self._seed % 6],
        }

    def reset(self, *, seed=None, options=None):
        self._seed = seed or 0
        self._t = 0
        return self._obs(), {}

    def step(self, action):
        self._t += 1
        reward = float(np.sum(action))
        terminated = self._t >= 3   # short episodes to exercise auto-reset
        return self._obs(), reward, terminated, False, {}


class MetricsEnv(DummyEnv):
    """DummyEnv that also declares learning metrics (exercises the trailer)."""

    def log_metric_names(self):
        return ["a", "b", "c"]

    def step(self, action):
        obs, reward, terminated, truncated, info = super().step(action)
        if terminated or truncated:
            info["log_metrics"] = {"a": 1.5, "b": 2.5, "c": 3.5}
        return obs, reward, terminated, truncated, info


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            raise ConnectionError
        buf += c
    return buf


def test_env_server_protocol_roundtrip():
    env = DummyEnv()
    server = EnvServer(env, port=7731, base_seed=42)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)

    sock = socket.create_connection(("127.0.0.1", 7731), timeout=5)
    sock.sendall(MAGIC + struct.pack("<I", 2))

    obs_size, n_actions, base_seed, n_extra = struct.unpack("<IIQI", _recv_exact(sock, 20))
    # dummy obs flat size: 4*4*3 + 5 + 1 + 6 = 60
    assert obs_size == 60
    assert n_actions == 4
    assert base_seed == 42
    assert n_extra == 0  # DummyEnv declares no metrics

    first_obs = np.frombuffer(_recv_exact(sock, obs_size * 4), dtype=np.float32)
    assert first_obs.shape == (60,)

    # Step several times; episode terminates at t=3, server auto-resets.
    saw_terminal = False
    for i in range(8):
        action = np.array([1, 2, 3, 4], dtype=np.int32)
        sock.sendall(action.tobytes())
        obs = np.frombuffer(_recv_exact(sock, obs_size * 4), dtype=np.float32)
        reward, term, trunc = struct.unpack("<fBB", _recv_exact(sock, 6))
        assert obs.shape == (60,)
        assert reward == 10.0  # sum([1,2,3,4])
        if term:
            saw_terminal = True
    assert saw_terminal, "expected an episode terminal within 8 steps"
    sock.close()


def test_env_server_metrics_trailer():
    env = MetricsEnv()
    server = EnvServer(env, port=7732, base_seed=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)

    sock = socket.create_connection(("127.0.0.1", 7732), timeout=5)
    sock.sendall(MAGIC + struct.pack("<I", 2))
    obs_size, n_actions, base_seed, n_extra = struct.unpack("<IIQI", _recv_exact(sock, 20))
    assert n_extra == 3
    _recv_exact(sock, obs_size * 4)  # first obs

    saw_metrics = False
    for _ in range(8):
        sock.sendall(np.array([0, 0, 0, 0], dtype=np.int32).tobytes())
        _recv_exact(sock, obs_size * 4)
        reward, term, trunc = struct.unpack("<fBB", _recv_exact(sock, 6))
        extra = np.frombuffer(_recv_exact(sock, n_extra * 4), dtype=np.float32)
        if term or trunc:
            assert list(extra) == [1.5, 2.5, 3.5], f"metrics trailer wrong: {extra}"
            saw_metrics = True
        else:
            assert list(extra) == [0.0, 0.0, 0.0], "non-terminal trailer must be zero"
    assert saw_metrics, "expected an episode terminal within 8 steps"
    sock.close()


def test_flatten_obs_layout():
    env = DummyEnv()
    obs, _ = env.reset(seed=1)
    flat = flatten_obs(obs)
    assert flat.shape == (60,)
    assert flat.dtype == np.float32
    # pixels scaled to [0,1]
    assert flat[:48].max() <= 1.0
