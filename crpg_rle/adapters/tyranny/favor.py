"""Goal-conditioned faction-favor reward (build brief §6 source 2).

Reward = positive-axis (Favor) reputation gained with the *target* faction,
counted ONLY while the agent is in dialogue mode (so quest turn-in favor and
other non-dialogue sources don't leak reward — the randomizer's whole point is
that this measures reading the option's meaning). Wrath and non-target factions
are logged but never rewarded.
"""
from __future__ import annotations

from crpg_rle.core.modes import Mode

# ChangeStrength enum (Reputation.ChangeStrength) -> scalar magnitude.
# 0 None, 1 VeryMinor, 2 Minor, 3 Average, 4 Major, 5 VeryMajor.
_STRENGTH_SCALE = {0: 0.0, 1: 1.0, 2: 2.0, 3: 4.0, 4: 8.0, 5: 16.0}


class FavorReward:
    def __init__(self) -> None:
        self._target: str | None = None
        self._log: dict[str, float] = {}

    def reset(self, target_faction: str) -> None:
        self._target = target_faction
        self._log = {}

    def update(self, events: list[dict], mode: Mode) -> float:
        """Return the favor reward for this step (0 unless in dialogue)."""
        reward = 0.0
        for ev in events:
            if ev.get("type") != "reputation":
                continue
            faction = ev.get("faction", "")
            axis = ev.get("axis", "")
            magnitude = _STRENGTH_SCALE.get(int(ev.get("strength", 0)), 0.0)
            signed = magnitude if ev.get("event") == "add" else -magnitude
            # Log every applied reputation delta for interpretability.
            if ev.get("applied"):
                key = f"{faction}.{axis}"
                self._log[key] = self._log.get(key, 0.0) + signed
            # Reward only: dialogue mode, target faction, positive (favor) axis.
            if (
                mode == Mode.DIALOGUE
                and faction == self._target
                and axis == "positive"
                and ev.get("applied")
            ):
                reward += signed
        return reward

    @property
    def logged_deltas(self) -> dict[str, float]:
        return dict(self._log)

    @property
    def target(self) -> str | None:
        return self._target
