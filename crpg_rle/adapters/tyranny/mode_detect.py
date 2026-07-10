"""Tyranny mode detection: engine state dict -> Mode.

Consumes the ``state`` payload from the bridge ``observe`` response. Pure
function so it is unit-testable against recorded fixtures. Priority order
matters: a loading screen can co-occur with a stale combat flag, etc.
"""
from __future__ import annotations

from crpg_rle.core.modes import Mode


def detect_mode(state: dict) -> Mode:
    """Map a bridge state snapshot to a Mode.

    Fields used (all optional; treated as falsey when absent):
      loading, game_over, party_dead, in_creation, in_combat,
      conversation.active, level_up
    """
    if state.get("loading"):
        return Mode.LOADING
    if state.get("game_over") or state.get("party_dead"):
        return Mode.GAME_OVER
    if state.get("in_creation"):
        return Mode.CREATION
    if state.get("level_up"):
        return Mode.LEVEL_UP

    conversation = state.get("conversation") or {}
    if conversation.get("active"):
        return Mode.DIALOGUE

    if state.get("in_combat"):
        return Mode.COMBAT

    return Mode.OVERWORLD
