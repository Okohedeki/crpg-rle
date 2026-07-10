"""Scripted config-driver: applies the predefined character configuration at the
moment each choice is needed, so the agent never spends samples on menu mechanics.

The driver is invoked once per step via ``TyrannyAdapter.intercept`` (the core's
game-agnostic hook). It detects config-needed moments in the bridge ``state`` —
a pending level-up, a party wipe — and drives them through the game's own UI code
paths (preferred) or, only inside the scripted config window, the locked-down
console (fallback for dimensions with no setter-shaped UI).

Design split by workstream:
  * level-up handling (skills/abilities via the real creation UI) — W4.
  * death recovery / checkpoint return — W5.
This module owns the *decision* logic (when to act, which plan to apply); the
bridge round-trips for each are filled in by those workstreams. ``on_step``
returns a fresh ``observe`` payload when it mutated the game (so the core re-reads
state/events), or ``None`` when it did nothing.
"""
from __future__ import annotations

from typing import Any


class ConfigDriver:
    """Owns the frozen run config and applies it via scripted triggers."""

    def __init__(self, spec: dict | None, *, death_mode: str = "terminal") -> None:
        self.spec = spec or {}
        self.death_mode = death_mode
        self._levels_done: set[int] = set()

    def reset(self) -> None:
        """Per-episode reset of trigger bookkeeping (config itself is frozen)."""
        self._levels_done = set()

    # ------------------------------------------------------------------ dispatch
    def on_step(self, bridge, state: dict, events: list[dict]) -> dict | None:
        """Handle at most one config trigger this step; re-observe if we acted."""
        if self._handle_death(bridge, state):
            return bridge.observe()
        if self._handle_levelup(bridge, state):
            return bridge.observe()
        return None

    # ------------------------------------------------------------- level-up (W4)
    def levelup_plan_for(self, level: int) -> dict | None:
        """The predefined choice plan for a given (ending) character level.

        ``levelups`` is an ordered list of ``{level, skills, abilities}``; the
        entry whose ``level`` matches is applied when the character reaches it.
        """
        for entry in self.spec.get("levelups", []):
            if int(entry.get("level", -1)) == int(level):
                return entry
        return None

    def _handle_levelup(self, bridge, state: dict) -> bool:
        if not state.get("level_up"):
            return False
        # W4 fills the levelup_begin/options/choose/advance round-trips here,
        # applying levelup_plan_for(target_level) through the real creation UI.
        return False

    # -------------------------------------------------------- death recovery (W5)
    def _handle_death(self, bridge, state: dict) -> bool:
        if self.death_mode == "terminal":
            return False
        if not (state.get("party_dead") or state.get("game_over")):
            return False
        # W5 fills the revive / checkpoint-load round-trip here (the env's
        # milestone terminal is made non-terminal for these death_modes).
        return False
