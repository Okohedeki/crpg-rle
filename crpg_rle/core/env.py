"""CRPGEnv — the generic, game-agnostic Gymnasium environment.

Owns the observation/action contract, the episode lifecycle, reward-channel
summing, and the bridge/launch plumbing. Contains nothing game-specific: all
of that comes from the injected adapter (mode detection, milestones, favor,
state packing, key vocabulary, reset config).
"""
from __future__ import annotations

import logging
import time
import uuid

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
        self._mode_counts: dict[int, int] = {}
        self._boot_ready = False
        self._dialogue_preloaded = False
        self._bridge_dead = False
        self._run_initialized = False
        self._run_save: str | None = None
        self._run_build_spec: dict | None = None
        self._build_info: dict = {"locked": False, "verified": False}

    # ------------------------------------------------------------------ setup
    def _ensure_process(self, attempts: int = 3) -> None:
        if self._bridge is not None:
            return
        last_err: Exception | None = None
        for attempt in range(attempts):
            try:
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
                self._bridge.request("speed", time_scale=self.config.time_scale,
                                     uncap_fps=self.config.time_scale > 1.0)
                return
            except (BridgeDied, OSError) as exc:
                last_err = exc
                logger.warning("boot attempt %d/%d failed (%s); relaunching",
                               attempt + 1, attempts, exc)
                if self._bridge is not None:
                    self._bridge.close()
                    self._bridge = None
                if self._proc is not None:
                    self._proc.kill()
                    self._proc = None
                self._hwnd = None
                self._boot_ready = False
                self._dialogue_preloaded = False
                time.sleep(3.0)
        raise BridgeDied(f"game failed to boot after {attempts} attempts: {last_err}")

    def _relaunch(self) -> None:
        """Recover from a dead bridge (game crash / plugin swept on reload) by
        tearing down and relaunching the game. The run save persists, so the next
        _load_game restores the frozen build; only the process is rebuilt."""
        logger.warning("bridge died — relaunching the game and reloading the run save")
        if self._bridge is not None:
            self._bridge.close()
            self._bridge = None
        if self._proc is not None:
            self._proc.kill()
            self._proc = None
        self._hwnd = None
        self._boot_ready = False
        self._dialogue_preloaded = False
        self._bridge_dead = False

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

    def _load_game(self, filename: str) -> dict:
        """Load a save on boot or directly from a running episode."""
        assert self._bridge is not None
        if not self._boot_ready:
            self._wait_menu()
            self._boot_ready = True
            self._preload_dialogue()
        accepted = False
        for _ in range(30):
            try:
                accepted = bool(self._bridge.request("load", file=filename).get("accepted"))
                if accepted:
                    break
            except Exception:
                pass
            time.sleep(1.0)
        if not accepted:
            raise RuntimeError(f"game refused to load save {filename!r}")
        state = self._wait_loaded(want_party=True)
        if state.get("loading") or not state.get("party"):
            raise RuntimeError(f"save {filename!r} did not finish loading")
        # Settle: the loading flag can clear before the scene finishes initializing
        # (AI/physics), and driving the old engine in that window has crashed it.
        # Wait a fixed real-time beat, then confirm state is still coherent.
        settle = getattr(self.config, "load_settle_seconds", 2.5)
        if settle > 0:
            time.sleep(settle)
            state = self._wait_loaded(want_party=True)
        return state

    def _initialize_run_build(self, base_save: str, spec: dict) -> dict:
        """Apply, persist, reload, verify, and permanently lock one run build."""
        assert self._bridge is not None
        working = getattr(self.config, "working_save", None)
        if not working:
            working = f"RL_RUN_{self.config.instance_id}_{uuid.uuid4().hex}.savegame"
        if working.casefold() == base_save.casefold():
            raise ValueError("working_save must not overwrite save_start")

        opened = self._bridge.request("build_begin")
        if not opened.get("open") or opened.get("locked"):
            raise RuntimeError("bridge did not open the build setup window")
        try:
            self.adapter.apply_build(self._bridge, spec)
            before = self.adapter.snapshot_build(self._bridge, spec)
            self.adapter.assert_build_matches_spec(before, spec)

            saved = self._bridge.request("save", file=working, label="RL locked build")
            if not saved.get("saved"):
                raise RuntimeError(f"game refused to save initialized build as {working!r}")
            state = self._load_game(working)

            after = self.adapter.snapshot_build(self._bridge, spec)
            self.adapter.assert_build_matches_spec(after, spec)
            if getattr(self.config, "verify_build_reload", True):
                self.adapter.assert_build_persisted(before, after)

            locked = self._bridge.request("build_lock")
            if not locked.get("locked") or locked.get("open") or locked.get("cheats"):
                raise RuntimeError("bridge failed to lock build mutation")
        except Exception:
            try:
                status = self._bridge.request("build_status")
                if status.get("open") and not status.get("locked"):
                    self._bridge.request("build_lock")
            except Exception:
                pass
            raise

        self._run_save = working
        self._run_build_spec = spec
        self._build_info = {
            "locked": True,
            "verified": True,
            "working_save": working,
        }
        return state

    def _preload_dialogue(self) -> None:
        """Load the paraphrase corpus once, while the engine is quiescent at the
        main menu. Main-thread file IO in the window right after a save load has
        crashed the old engine, so we do it here (before any load) and only flip
        the seed/active flag per episode in _arm_dialogue."""
        if self._dialogue_preloaded:
            return
        self._dialogue_preloaded = True
        assert self._bridge is not None
        dr = getattr(self.config, "dialogue_randomizer", False)
        corpus_path = getattr(self.config, "corpus_path", None)
        if dr and corpus_path:
            self._bridge.request("dialogue", active=False, seed=0, corpus_path=corpus_path)

    def _arm_dialogue(self, episode_cfg: dict) -> None:
        """Per-episode: set the seed and enable the randomizer. The corpus is
        already loaded by _preload_dialogue, so no file IO happens here."""
        assert self._bridge is not None
        dr = getattr(self.config, "dialogue_randomizer", False)
        corpus_path = getattr(self.config, "corpus_path", None)
        if dr and corpus_path:
            self._bridge.request("dialogue", active=True, seed=episode_cfg["dialogue_seed"])

    # --------------------------------------------------------------- gym API
    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        seed = seed if seed is not None else 0
        if self._bridge_dead:
            self._relaunch()
        self._ensure_process()

        episode_cfg = self.adapter.reset(seed)
        self.rewards.reset()
        self._steps = 0
        self._mode_counts = {}

        if self.config.start_mode == "act1_save" and self.config.save_start:
            requested = (options or {}).get("build_spec", getattr(self.config, "build_spec", None))
            validate = getattr(self.adapter, "validate_build_spec", None)
            declared = validate(requested) if validate is not None else requested

            if not self._run_initialized:
                state = self._load_game(self.config.save_start)
                if declared:
                    state = self._initialize_run_build(self.config.save_start, declared)
                else:
                    self._run_save = self.config.save_start
                    self._run_build_spec = declared
                self._run_initialized = True
            else:
                if declared is not None and declared != self._run_build_spec:
                    raise RuntimeError("build_spec is frozen for this training run")
                assert self._run_save is not None
                state = self._load_game(self._run_save)
        else:
            if self._run_initialized:
                raise RuntimeError("creation-mode run cannot be reset after initialization")
            self._wait_menu()
            self._boot_ready = True
            self._preload_dialogue()
            self._bridge.request("new_game")
            state = self._wait_loaded(want_party=False)
            self._run_initialized = True

        self._arm_dialogue(episode_cfg)
        obs = self._build_obs(state)
        info = {
            "target_faction": episode_cfg["target_faction"],
            "mode": int(self.adapter.mode(state)),
            "build": dict(self._build_info),
        }
        return obs, info

    def step(self, action):
        inputs = S.decode_action(action, self.adapter.action_key_list())
        gate = getattr(self.adapter, "gate_inputs", None)
        if callable(gate):
            inputs = gate(action, inputs)
        try:
            self._bridge.request("input", active=True)
            self._bridge.act(inputs, frames=self.config.frame_skip)
            resp = self._bridge.observe()
        except BridgeDied:
            logger.warning("bridge died mid-step; ending episode (will relaunch on reset)")
            self._bridge_dead = True
            blank = self._blank_obs()
            return blank, 0.0, True, False, {"bridge_died": True}

        state = resp["state"]
        events = resp.get("events", [])

        # Scripted infrastructure between agent actions: the adapter may detect a
        # config-needed moment (level-up screen, party wipe, ...) and apply the
        # predefined choice/recovery through the bridge, then re-observe. The core
        # stays game-agnostic — it only merges whatever fresh obs/events it gets.
        intercept = getattr(self.adapter, "intercept", None)
        if callable(intercept):
            reobs = intercept(self._bridge, state, events)
            if reobs is not None:
                state = reobs.get("state", state)
                events = events + list(reobs.get("events", []))

        mode = self.adapter.mode(state)
        self._mode_counts[int(mode)] = self._mode_counts.get(int(mode), 0) + 1

        channel_deltas = self.adapter.reward(mode, events, state, action)
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
        if done or truncated:
            info["terminal_kind"] = kind
            info["episode_reward_channels"] = self.rewards.episode_totals
            info["log_metrics"] = self._episode_metrics(kind)
        return obs, scalar, done, truncated, info

    # --------------------------------------------------------- learning metrics
    def log_metric_names(self) -> list[str]:
        """Ordered names of the per-episode learning metrics the adapter emits.

        Game-agnostic: the core forwards whatever the adapter declares (empty if
        the adapter declares none), so the env-server can size the wire trailer
        and label the sidecar without knowing any game specifics.
        """
        names = getattr(self.adapter, "log_metric_names", None)
        return list(names()) if callable(names) else []

    def _episode_metrics(self, terminal_kind: str | None) -> dict[str, float]:
        """Ask the adapter to summarize the finished episode into named scalars.

        The core supplies only generic material (mode occupancy, length, the
        weighted reward-channel totals, terminal kind); the adapter names and
        computes the metrics. Returns {} when the adapter opts out.
        """
        summary = getattr(self.adapter, "episode_metrics", None)
        if not callable(summary):
            return {}
        return dict(summary({
            "mode_counts": dict(self._mode_counts),
            "ep_len": self._steps,
            "reward_channel_totals": self.rewards.episode_totals,
            "terminal_kind": terminal_kind,
        }))

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
