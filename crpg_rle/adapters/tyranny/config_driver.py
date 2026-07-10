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

import logging

logger = logging.getLogger(__name__)


class ConfigDriver:
    """Owns the frozen run config and applies it via scripted triggers."""

    def __init__(self, spec: dict | None, *, death_mode: str = "terminal",
                 death_penalty: float = 0.0, checkpoint_save: str | None = None) -> None:
        self.spec = spec or {}
        self.death_mode = death_mode
        self.death_penalty = death_penalty
        self.checkpoint_save = checkpoint_save
        self._levels_done: set[tuple[int, int]] = set()
        self._pending_penalty = 0.0
        self._was_dead = False

    def reset(self) -> None:
        """Per-episode reset of trigger bookkeeping (config itself is frozen)."""
        self._levels_done = set()
        self._pending_penalty = 0.0
        self._was_dead = False

    def take_death_penalty(self) -> float:
        """Consume any pending MC-death penalty (added to the reward this step).
        Cleared on read so it is charged exactly once per death."""
        penalty = self._pending_penalty
        self._pending_penalty = 0.0
        return penalty

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
        detail = state.get("level_up_detail") or {}
        members = detail.get("members") or []
        acted = False
        for member in members:
            slot = int(member.get("slot", -1))
            target_level = int(member.get("level", 0)) + 1
            key = (slot, target_level)
            # Attempt each (member, level) at most once per episode: if the finalize
            # handler proves unreliable (playtest item) this prevents a retry loop.
            if slot < 0 or key in self._levels_done:
                continue
            self._levels_done.add(key)
            try:
                begin = bridge.request("levelup_begin", slot=slot)
                if not begin.get("open"):
                    continue
                self._drive_levelup(bridge, self.levelup_plan_for(target_level))
                acted = True
            except Exception as exc:  # a level-up hiccup must not crash the episode
                logger.warning("level-up for slot %d failed: %s", slot, exc)
        return acted

    def _drive_levelup(self, bridge, plan: dict | None, max_stages: int = 8) -> None:
        """Apply the predefined plan across the level-up wizard's stages, then
        finalize. Skills go through the real skill setters; abilities are matched
        by option label. Best-effort and bounded; the exact stage/finalize flow is
        a live-playtest item (see LevelUpChoices.Advance)."""
        plan = plan or {}
        skills = dict(plan.get("skills") or {})
        abilities = list(plan.get("abilities") or [])
        for _ in range(max_stages):
            opts = bridge.request("levelup_options")
            stage_skills = {o.get("skill") for o in (opts.get("skills") or [])}
            for name in list(skills):
                if name in stage_skills:
                    bridge.request("levelup_skill", skill=name, delta=skills.pop(name))
            for option in (opts.get("options") or []):
                label = str(option.get("label", ""))
                match = next((a for a in abilities if a == label or a in label), None)
                if match is not None:
                    bridge.request("levelup_choose", index=option.get("i"))
                    abilities.remove(match)
            adv = bridge.request("levelup_advance", action="advance")
            if not adv.get("open"):
                return  # wizard closed → level-up finalized
        try:
            bridge.request("levelup_advance", action="complete")
        except Exception as exc:
            logger.warning("level-up finalize failed: %s", exc)

    # -------------------------------------------------------- death recovery (W5)
    def _handle_death(self, bridge, state: dict) -> bool:
        """Charge the MC-death penalty (once, on the rising edge) and, unless
        death_mode is "terminal", recover so the episode continues — training
        toward a deathless MC. Runs via the intercept before the terminal check."""
        dead = bool(state.get("player_dead") or state.get("party_dead")
                    or state.get("game_over"))
        if dead and not self._was_dead:
            self._pending_penalty += self.death_penalty   # deaths are negative reward
        self._was_dead = dead

        if self.death_mode == "terminal" or not dead:
            return False
        try:
            if self.death_mode == "checkpoint" and self.checkpoint_save:
                bridge.request("load", file=self.checkpoint_save)
            else:
                bridge.request("revive")
            self._was_dead = False  # revived — ready to detect the next death
            return True
        except Exception as exc:
            logger.warning("death recovery (%s) failed: %s", self.death_mode, exc)
            return False
