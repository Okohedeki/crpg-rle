"""Reward channel bookkeeping.

The env keeps reward sources on separate named channels (for interpretability)
and sums them with configurable weights for the scalar the agent receives.
Per-step channel values are exposed in ``info`` and can be streamed to a log.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RewardChannels:
    """Weighted sum of named reward channels with per-episode accounting.

    weights: channel name -> multiplier applied to that channel's delta.
    Channels seen at runtime but absent from ``weights`` default to weight 1.0.
    """

    weights: dict[str, float] = field(default_factory=dict)
    _episode_totals: dict[str, float] = field(default_factory=dict, init=False)

    def reset(self) -> None:
        self._episode_totals = {}

    def step(self, deltas: dict[str, float]) -> tuple[float, dict[str, float]]:
        """Apply one step's channel deltas.

        Returns (scalar_reward, weighted_deltas) where scalar_reward is the
        weighted sum handed to the agent and weighted_deltas is per-channel
        for logging. Episode totals accumulate the *weighted* values.
        """
        weighted: dict[str, float] = {}
        scalar = 0.0
        for name, raw in deltas.items():
            w = self.weights.get(name, 1.0)
            value = w * raw
            weighted[name] = value
            scalar += value
            self._episode_totals[name] = self._episode_totals.get(name, 0.0) + value
        return scalar, weighted

    @property
    def episode_totals(self) -> dict[str, float]:
        return dict(self._episode_totals)
