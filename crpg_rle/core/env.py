"""CRPGEnv — the generic, game-agnostic Gymnasium environment.

Owns the observation/action contract, the episode lifecycle, reward-channel
summing, and the bridge/launch plumbing. Contains nothing game-specific: all
of that comes from the injected adapter (mode detection, milestones, favor,
state packing, key vocabulary, reset config).
"""
from __future__ import annotations

import logging
import time

import gymnasium as gym
import numpy as np

from crpg_rle.core import spaces as S
from crpg_rle.core.bridge import BridgeDied, TcpBridgeClient
from crpg_rle.core.capture import capture_window
from crpg_rle.core.launcher import GameProcess
from crpg_rle.core.modes import Mode
from crpg_rle.core.reward import RewardChannels

logger = logging.getLogger(__name__)


class CRPGEnv(gym.Env):
    """Gymnasium env driving a live isometric CRPG through a bridge.

    The adapter supplies everything game-specific. The env is constructed with
    a config carrying paths, obs sizes, frame_skip, time_scale, reward weights,
    and the episode start mode.
    """

    metadata = {"render_modes": []}

    def __init__(self, adapter, *, launch: bool = True):
        self.adapter = adapter
        self.config = adapter.config
        self._launch = launch

        self.action_space = S.build_action_space(len(adapter.action_key_list()))
        self.observation_space = S.build_observation_space(
            obs_height=self.config.obs_height,
            obs_width=self.config.obs_width,
            state_size=adapter.state_vector_size(),
            n_modes=Mode.count(),
            n_factions=len(adapter.factions()),
        )

        self.rewards = RewardChannels(weights=dict(self.config.reward_weights))
        self._proc: GameProcess | None = None
        self._bridge: TcpBridgeClient | None = None
        self._hwnd = None
        self._steps = 0

    # ------------------------------------------------------------------ setup
    def _ensure_process(self) -> None:
        if self._bridge is not None:
            return
        if self._launch:
            self._proc = GameProcess(
                self.config.exe_path,
                instance_id=self.config.instance_id,
                port=self.config.port,
                window=(self.config.obs_width, self.config.obs_height),
            )
            self._proc.launch()
            self._hwnd = self._proc.find_window()
        self._bridge = TcpBridgeClient(port=self.config.port)
        self._bridge.connect()
        self._bridge.handshake()
        self._bridge.request("speed", time_scale=self.config.time_scale, uncap_fps=self.config.time_scale > 1.0)

    def _wait_menu(self, timeout: float = 120.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._bridge.request("diag_asm").get("scene") == "MainMenu":
                return
            time.sleep(1.0)

    def _wait_loaded(self, want_party: bool, timeout: float = 180.0) -> dict:
        deadline = time.time() + timeout
        state = {}
        while time.time() < deadline:
            state = self._bridge.observe()["state"]
            if not state.get("loading") and (not want_party or state.get("party")):
                return state
            time.sleep(0.5)
        return state

    # --------------------------------------------------------------- gym API
    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        seed = seed if seed is not None else 0
        self._ensure_process()

        episode_cfg = self.adapter.reset(seed)
        self.rewards.reset()
        self._steps = 0

        # Arm the per-episode dialogue randomizer (paraphrase swap + shuffle).
        dr = getattr(self.config, "dialogue_randomizer", False)
        corpus_path = getattr(self.config, "corpus_path", None)
        if dr and corpus_path:
            self._bridge.request(
                "dialogue",
                active=True,
                seed=episode_cfg["dialogue_seed"],
                corpus_path=corpus_path,
            )

        if self.config.start_mode == "act1_save" and self.config.save_start:
            self._wait_menu()
            for _ in range(30):
                try:
                    if self._bridge.request("load", file=self.config.save_start).get("accepted"):
                        break
                except Exception:
                    pass
                time.sleep(1.0)
            state = self._wait_loaded(want_party=True)
            # Programmatic build on top of the base save (game-specific; the
            # adapter translates the spec into engine calls). Per-episode spec
            # via reset options wins over the config default.
            spec = (options or {}).get("build_spec", getattr(self.config, "build_spec", None))
            apply_build = getattr(self.adapter, "apply_build", None)
            if apply_build is not None and spec:
                apply_build(self._bridge, spec)
                state = self._bridge.observe()["state"]
        else:
            # creation start: env scripts nav to New Game; agent drives creation.
            self._wait_menu()
            self._bridge.request("new_game")
            state = self._wait_loaded(want_party=False)

        obs = self._build_obs(state)
        info = {"target_faction": episode_cfg["target_faction"], "mode": int(self.adapter.mode(state))}
        return obs, info

    def step(self, action):
        inputs = S.decode_action(action, self.adapter.action_key_list())
        try:
            self._bridge.request("input", active=True)
            self._bridge.act(inputs, frames=self.config.frame_skip)
            resp = self._bridge.observe()
        except BridgeDied:
            logger.warning("bridge died mid-step; terminating episode")
            blank = self._blank_obs()
            return blank, 0.0, True, False, {"bridge_died": True}

        state = resp["state"]
        events = resp.get("events", [])
        mode = self.adapter.mode(state)

        channel_deltas = self.adapter.reward(mode, events, state)
        scalar, weighted = self.rewards.step(channel_deltas)

        done, kind, penalty = self.adapter.terminal(state)
        if penalty:
            pscalar, pweighted = self.rewards.step({"milestone": penalty})
            scalar += pscalar
            for k, v in pweighted.items():
                weighted[k] = weighted.get(k, 0.0) + v

        self._steps += 1
        truncated = self._steps >= self.config.max_steps

        obs = self._build_obs(state)
        info = {
            "mode": int(mode),
            "reward_channels": weighted,
            "milestones_fired": sorted(self.adapter.milestones.fired),
            "target_faction": self.adapter.target_faction,
        }
        if done:
            info["terminal_kind"] = kind
            info["episode_reward_channels"] = self.rewards.episode_totals
        return obs, scalar, done, truncated, info

    # ------------------------------------------------------------- obs build
    def _build_obs(self, state: dict) -> dict:
        return {
            "pixels": self._capture(),
            "state": self.adapter.pack_observation_state(state),
            "mode": int(self.adapter.mode(state)),
            "goal": self.adapter.goal_vector(),
        }

    def _capture(self) -> np.ndarray:
        if self._hwnd is None:
            return np.zeros((self.config.obs_height, self.config.obs_width, 3), dtype=np.uint8)
        return capture_window(self._hwnd, out_size=(self.config.obs_width, self.config.obs_height))

    def _blank_obs(self) -> dict:
        return {
            "pixels": np.zeros((self.config.obs_height, self.config.obs_width, 3), dtype=np.uint8),
            "state": np.zeros(self.adapter.state_vector_size(), dtype=np.float32),
            "mode": int(Mode.GAME_OVER),
            "goal": self.adapter.goal_vector(),
        }

    def close(self):
        if self._bridge is not None:
            try:
                self._bridge.request("shutdown")
            except Exception:
                pass
            self._bridge.close()
            self._bridge = None
        if self._proc is not None:
            self._proc.kill()
            self._proc = None
