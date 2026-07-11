"""Trainer-side run observability: episode replay JSONL + live status JSON.

Game-agnostic on purpose: everything here is computed from what ``env.step``
returns (action, reward, info) plus the per-update metric row the trainer logs
— no adapter imports, so it works identically for the proxy and the live game.

  * ``ReplayRecorder`` — one JSONL file per episode
    (``<run_dir>/replay_ep<N>.jsonl``), one line per step with
    {t, action, mode, reward, reward_channels, events, interventions} for
    post-hoc "why did it do that" analysis.
  * ``StatusWriter`` — ``<run_dir>/live_status.json``, atomically rewritten
    (temp file + os.replace) every step (time-throttled) and on every PPO
    update; the dashboard (tools/dashboard.py) polls it.
  * ``RunObserver`` — composes both behind the two hooks the trainer calls:
    ``on_step(obs, action, reward, info, terminated, truncated)`` and
    ``on_update(row)``.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, deque
from pathlib import Path

import numpy as np

from crpg_rle.core.modes import Mode

_BUTTON_NAMES = ("none", "left", "right", "double")


def _jsonable(value):
    """Coerce numpy scalars/arrays (and nested containers) to JSON-safe types."""
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _mode_name(mode) -> str | None:
    try:
        return Mode(int(mode)).name
    except (ValueError, TypeError):
        return None


class ReplayRecorder:
    """Per-episode JSONL stream: one line per step, one file per episode."""

    def __init__(self, run_dir: str | os.PathLike):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._episode = 0
        self._t = 0
        self._file = None

    def _open_next(self) -> None:
        self._episode += 1
        self._t = 0
        path = self.run_dir / f"replay_ep{self._episode}.jsonl"
        self._file = open(path, "w", encoding="utf-8")

    def on_step(self, obs, action, reward, info, terminated=False, truncated=False) -> None:
        if self._file is None:
            self._open_next()
        info = info or {}
        line = {
            "t": self._t,
            "action": _jsonable(action),
            "mode": _jsonable(info.get("mode")),
            "reward": float(reward),
            "reward_channels": _jsonable(info.get("reward_channels") or {}),
            "events": _jsonable(info.get("events") or []),
            "interventions": _jsonable(info.get("interventions") or []),
        }
        if terminated or truncated:
            line["done"] = "terminated" if terminated else "truncated"
            if info.get("terminal_kind") is not None:
                line["terminal_kind"] = info["terminal_kind"]
        self._file.write(json.dumps(line) + "\n")
        self._t += 1
        if terminated or truncated:
            self._file.close()
            self._file = None
        else:
            self._file.flush()  # keep the stream tail-able during live runs

    def on_update(self, row: dict) -> None:  # replay does not consume update rows
        pass

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


class StatusWriter:
    """Maintains the live run status and atomically writes it as JSON.

    Rollout-scoped accumulators (per-channel reward, action histogram) reset on
    every ``on_update``; episode/step counters and the recent event /
    intervention rings persist for the whole run.
    """

    def __init__(self, run_dir: str | os.PathLike, *, csv_path: str | None = None,
                 key_names: list[str] | None = None, every: int = 1,
                 min_interval: float = 0.3, recent: int = 50):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "live_status.json"
        self.csv_path = str(Path(csv_path).resolve()) if csv_path else None
        self.key_names = list(key_names) if key_names else None
        self.every = max(1, int(every))
        self.min_interval = float(min_interval)
        self._last_write = 0.0
        self._t0 = time.time()

        self.global_step = 0
        self.episode = 1
        self.t_in_episode = 0
        self.update = 0
        self.ep_reward = 0.0
        self.last_ep_reward: float | None = None
        self.mode = None
        self.target_faction = None
        self.milestones: list = []
        self.party = None
        self.rollout_steps = 0
        self.rollout_reward = 0.0
        self.rollout_channels: Counter = Counter()
        self.buttons: Counter = Counter()
        self.keys: Counter = Counter()
        self.last_update_row: dict = {}
        self.recent_events: deque = deque(maxlen=recent)
        self.recent_interventions: deque = deque(maxlen=recent)
        self.intervention_total = 0

    # ------------------------------------------------------------------ hooks
    def on_step(self, obs, action, reward, info, terminated=False, truncated=False) -> None:
        info = info or {}
        self.global_step += 1
        self.t_in_episode += 1
        self.rollout_steps += 1
        self.ep_reward += float(reward)
        self.rollout_reward += float(reward)
        self.mode = info.get("mode")
        self.target_faction = info.get("target_faction", self.target_faction)
        if info.get("milestones_fired") is not None:
            self.milestones = list(info["milestones_fired"])
        if info.get("party") is not None:
            self.party = _jsonable(info["party"])
        for ch, val in (info.get("reward_channels") or {}).items():
            self.rollout_channels[ch] += float(val)
        a = np.asarray(action).ravel()
        if a.size >= 4:
            self.buttons[_BUTTON_NAMES[int(a[2]) % len(_BUTTON_NAMES)]] += 1
            key_idx = int(a[3])
            if self.key_names and 0 <= key_idx < len(self.key_names):
                name = self.key_names[key_idx] or "(none)"
            else:
                name = f"key{key_idx}"
            self.keys[name] += 1
        for ev in info.get("events") or []:
            self.recent_events.append({"step": self.global_step, **_jsonable(ev)})
        for iv in info.get("interventions") or []:
            self.intervention_total += 1
            self.recent_interventions.append({"step": self.global_step, **_jsonable(iv)})

        done = terminated or truncated
        if done:
            self.last_ep_reward = self.ep_reward
            self.ep_reward = 0.0
            self.t_in_episode = 0
            self.episode += 1
        if done or (self.global_step % self.every == 0
                    and time.time() - self._last_write >= self.min_interval):
            self.write()

    def on_update(self, row: dict) -> None:
        self.update = int(row.get("update", self.update + 1))
        self.last_update_row = _jsonable(dict(row))
        # rollout-scoped accumulators restart with the next collect()
        self.rollout_steps = 0
        self.rollout_reward = 0.0
        self.rollout_channels = Counter()
        self.buttons = Counter()
        self.keys = Counter()
        self.write(force=True)

    # ------------------------------------------------------------------ write
    def snapshot(self) -> dict:
        return {
            "ts": time.time(),
            "wall_s": round(time.time() - self._t0, 1),
            "run_dir": str(self.run_dir.resolve()),
            "csv": self.csv_path,
            "global_step": self.global_step,
            "episode": self.episode,
            "t_in_episode": self.t_in_episode,
            "update": self.update,
            "mode": _jsonable(self.mode),
            "mode_name": _mode_name(self.mode),
            "target_faction": self.target_faction,
            "milestones_fired": _jsonable(self.milestones),
            "ep_reward": self.ep_reward,
            "last_ep_reward": self.last_ep_reward,
            "rollout": {
                "steps": self.rollout_steps,
                "reward": self.rollout_reward,
                "channels": dict(self.rollout_channels),
            },
            "actions": {"buttons": dict(self.buttons), "keys": dict(self.keys)},
            "last_update": self.last_update_row,
            "recent_events": list(self.recent_events),
            "recent_interventions": list(self.recent_interventions),
            "intervention_total": self.intervention_total,
            "party": self.party,
        }

    def write(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_write < self.min_interval:
            return
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.snapshot(), fh)
        os.replace(tmp, self.path)  # atomic: readers never see a partial file
        self._last_write = now

    def close(self) -> None:
        self.write(force=True)


class RunObserver:
    """Composite the trainer holds: fans the two hooks out to its recorders."""

    def __init__(self, *recorders):
        self.recorders = [r for r in recorders if r is not None]

    def on_step(self, obs, action, reward, info, terminated=False, truncated=False) -> None:
        for r in self.recorders:
            r.on_step(obs, action, reward, info, terminated, truncated)

    def on_update(self, row: dict) -> None:
        for r in self.recorders:
            r.on_update(row)

    def close(self) -> None:
        for r in self.recorders:
            close = getattr(r, "close", None)
            if callable(close):
                close()


def make_observer(status_dir: str | os.PathLike, *, csv_path: str | None = None,
                  key_names: list[str] | None = None, every: int = 1) -> RunObserver:
    """Standard wiring: replay JSONL + live status JSON into one directory."""
    return RunObserver(
        ReplayRecorder(status_dir),
        StatusWriter(status_dir, csv_path=csv_path, key_names=key_names, every=every),
    )
