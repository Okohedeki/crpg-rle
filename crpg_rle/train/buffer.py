"""Shared training utilities: reward normalization, GAE, and a run logger."""
from __future__ import annotations

import csv
import time
from pathlib import Path

import numpy as np


class RunningMeanStd:
    """Welford running mean/variance for reward (or return) normalization.

    Normalizing the reward scale is a standard stability + anti-reward-hacking
    measure: it keeps a channel from dominating the update purely by magnitude.
    """

    def __init__(self, eps: float = 1e-4):
        self.mean = 0.0
        self.var = 1.0
        self.count = eps

    def update(self, x: np.ndarray) -> None:
        x = np.asarray(x, dtype=np.float64).ravel()
        if x.size == 0:
            return
        bmean, bvar, bcount = x.mean(), x.var(), x.size
        delta = bmean - self.mean
        tot = self.count + bcount
        self.mean += delta * bcount / tot
        m_a = self.var * self.count
        m_b = bvar * bcount
        self.var = (m_a + m_b + delta ** 2 * self.count * bcount / tot) / tot
        self.count = tot

    @property
    def std(self) -> float:
        return float((self.var + 1e-8) ** 0.5)


def compute_gae(rewards, values, bootstrap, terminated, dones, gamma, lam):
    """Generalized Advantage Estimation over one contiguous rollout.

    ``bootstrap[t]`` = V(s_{t+1}) (the value of the observation that followed
    step t, taken BEFORE any auto-reset). ``terminated[t]`` zeros the bootstrap on
    a true terminal; ``dones[t]`` (terminated OR truncated) breaks the GAE
    recursion at an episode boundary.
    """
    T = len(rewards)
    adv = np.zeros(T, dtype=np.float32)
    last_gae = 0.0
    for t in reversed(range(T)):
        next_nonterminal = 1.0 - float(terminated[t])
        delta = rewards[t] + gamma * bootstrap[t] * next_nonterminal - values[t]
        not_boundary = 1.0 - float(dones[t])
        last_gae = delta + gamma * lam * next_nonterminal * not_boundary * last_gae
        adv[t] = last_gae
    returns = adv + np.asarray(values, dtype=np.float32)
    return adv, returns


def action_stats(actions) -> dict:
    """Compact summary of the actions taken this rollout: mouse-button mix
    (right-click = move order), key usage, and cursor spread. Surfaces failure
    modes like 'stuck on one key' (key_top_frac→1) or 'never moves' (btn_right→0).
    """
    a = np.asarray(actions)
    if a.ndim != 2 or a.shape[1] < 4 or a.shape[0] == 0:
        return {}
    buttons, keys = a[:, 2], a[:, 3]
    n = a.shape[0]
    key_counts = np.bincount(keys, minlength=1)
    return {
        "btn_none": float(np.mean(buttons == 0)),
        "btn_left": float(np.mean(buttons == 1)),
        "btn_right": float(np.mean(buttons == 2)),
        "btn_dbl": float(np.mean(buttons == 3)),
        "key_active": float(np.mean(keys != 0)),
        "key_top_frac": float(key_counts.max() / n),
        "cursor_x": float(np.mean(a[:, 0])),
        "cursor_y": float(np.mean(a[:, 1])),
    }


class Logger:
    """Console + CSV logger for per-update training metrics."""

    def __init__(self, csv_path: str | None = None):
        self.csv_path = csv_path
        self._writer = None
        self._file = None
        self._t0 = time.monotonic()
        if csv_path:
            Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
            self._file = open(csv_path, "w", newline="", encoding="utf-8")

    def log(self, row: dict) -> None:
        row = {"wall_s": round(time.monotonic() - self._t0, 1), **row}
        if self._file is not None:
            if self._writer is None:
                # Fix columns from the first row; ignore any later-appearing keys
                # so a rollout with an extra channel can't crash the run.
                self._writer = csv.DictWriter(self._file, fieldnames=list(row),
                                              extrasaction="ignore")
                self._writer.writeheader()
            self._writer.writerow(row)
            self._file.flush()
        cells = []
        for k, v in row.items():
            cells.append(f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}")
        print("  ".join(cells))

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
