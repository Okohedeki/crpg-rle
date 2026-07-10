"""TyrannyAdapter — wires the generic core to Tyranny specifics.

Holds all game-specific policy: the action key vocabulary, mode detection,
state packing, the milestone chain, and the goal-conditioned favor reward.
The core CRPGEnv talks to this through a small, game-agnostic surface.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np

from crpg_rle.core.modes import Mode
from crpg_rle.core.rng import SplitMix64
from crpg_rle.adapters.tyranny import config as C
from crpg_rle.adapters.tyranny.favor import FavorReward
from crpg_rle.adapters.tyranny.milestones import MilestoneChain
from crpg_rle.adapters.tyranny.mode_detect import detect_mode
from crpg_rle.adapters.tyranny.state_schema import pack_state, state_vector_size

# Keys the agent can emit (action-space key slot). Index 0 = no key.
# Number keys drive dialogue option selection; Space pauses; Tab highlights.
ACTION_KEYS: list[str] = [
    "", "Escape", "Space", "Tab",
    "Alpha1", "Alpha2", "Alpha3", "Alpha4", "Alpha5",
    "Alpha6", "Alpha7", "Alpha8", "Alpha9",
]

_BUILD_KEYS = {"attributes", "skills", "abilities", "reputation", "globals"}
_ATTRIBUTE_NAMES = {
    name.lower(): name
    for name in ("Might", "Finesse", "Quickness", "Vitality", "Wits", "Resolve")
}
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _int_value(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return value


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a safe game identifier")
    return value


class TyrannyAdapter:
    def __init__(self, config: C.TyrannyConfig | None = None) -> None:
        self.config = config or C.TyrannyConfig()
        self.milestones = MilestoneChain(granularity=self.config.milestone_granularity)
        self.favor = FavorReward()
        self._target_faction: str | None = None

    # --- spaces --------------------------------------------------------------
    def action_key_list(self) -> list[str]:
        return ACTION_KEYS

    def factions(self) -> list[str]:
        return C.FACTIONS

    def target_factions(self) -> list[str]:
        return C.TARGET_FACTIONS

    def target_faction_index(self, name: str) -> int:
        return C.FACTIONS.index(name)

    def state_vector_size(self) -> int:
        return state_vector_size(C.FACTIONS, self.config.max_party)

    # --- per-step ------------------------------------------------------------
    def mode(self, state: dict) -> Mode:
        return detect_mode(state)

    def pack_observation_state(self, state: dict) -> np.ndarray:
        return pack_state(state, C.FACTIONS, self.config.max_party)

    def goal_vector(self) -> np.ndarray:
        """One-hot over FACTIONS marking the episode's target faction."""
        vec = np.zeros(len(C.FACTIONS), dtype=np.float32)
        if self._target_faction is not None:
            vec[self.target_faction_index(self._target_faction)] = 1.0
        return vec

    def reward(self, mode: Mode, events: list[dict], state: dict) -> dict[str, float]:
        """RewardRouter contract: per-channel deltas for this step."""
        milestone_r, _fired = self.milestones.update(events, state)
        favor_r = self.favor.update(events, mode)
        return {"milestone": milestone_r, "faction_favor": favor_r}

    def terminal(self, state: dict) -> tuple[bool, str | None, float]:
        return self.milestones.terminal(state)

    # --- lifecycle -----------------------------------------------------------
    def reset(self, seed: int) -> dict:
        """Seed all env-owned randomness. Returns the per-episode config the
        env forwards to the bridge reset (target faction + dialogue seed)."""
        rng = SplitMix64(seed)
        targets = self.target_factions()
        self._target_faction = targets[rng.randint(len(targets))]
        dialogue_seed = rng.next_u64()

        self.milestones.reset()
        self.favor.reset(self._target_faction)
        return {"target_faction": self._target_faction, "dialogue_seed": dialogue_seed}

    def validate_build_spec(self, spec: dict | None) -> dict | None:
        """Validate and canonicalize a run-scoped build declaration."""
        if spec is None:
            return None
        if not isinstance(spec, dict):
            raise ValueError("build_spec must be a mapping")
        unknown = set(spec) - _BUILD_KEYS
        if unknown:
            raise ValueError(f"unknown build_spec sections: {sorted(unknown)}")

        result: dict[str, Any] = {}
        raw_attributes = spec.get("attributes") or {}
        if not isinstance(raw_attributes, dict):
            raise ValueError("attributes must be a mapping")
        attributes: dict[str, int] = {}
        for raw_name, raw_value in raw_attributes.items():
            name = _ATTRIBUTE_NAMES.get(str(raw_name).lower())
            if name is None:
                raise ValueError(f"unknown attribute: {raw_name}")
            attributes[name] = _int_value(raw_value, f"attribute {name}", 1, 100)
        if attributes:
            result["attributes"] = attributes

        raw_skills = spec.get("skills") or {}
        if not isinstance(raw_skills, dict):
            raise ValueError("skills must be a mapping")
        skills = {
            _identifier(name, "skill name"): _int_value(value, f"skill {name}", 0, 200)
            for name, value in raw_skills.items()
        }
        if skills:
            result["skills"] = skills

        raw_abilities = spec.get("abilities") or []
        if not isinstance(raw_abilities, list):
            raise ValueError("abilities must be a list")
        abilities = list(dict.fromkeys(_identifier(value, "ability name") for value in raw_abilities))
        if abilities:
            result["abilities"] = abilities

        raw_reputation = spec.get("reputation") or []
        if not isinstance(raw_reputation, list):
            raise ValueError("reputation must be a list")
        reputation = []
        for index, entry in enumerate(raw_reputation):
            if not isinstance(entry, dict):
                raise ValueError(f"reputation[{index}] must be a mapping")
            faction = _identifier(entry.get("faction"), f"reputation[{index}].faction")
            axis = entry.get("axis", "positive")
            if axis not in {"positive", "negative"}:
                raise ValueError(f"reputation[{index}].axis must be positive or negative")
            strength = _int_value(entry.get("strength", 1), f"reputation[{index}].strength", 1, 10)
            reputation.append({"faction": faction, "axis": axis, "strength": strength})
        if reputation:
            result["reputation"] = reputation

        raw_globals = spec.get("globals") or {}
        if not isinstance(raw_globals, dict):
            raise ValueError("globals must be a mapping")
        globals_spec = {
            _identifier(name, "global name"): _int_value(value, f"global {name}", -(2**31), 2**31 - 1)
            for name, value in raw_globals.items()
        }
        if globals_spec:
            result["globals"] = globals_spec
        return result

    def snapshot_build(self, bridge, spec: dict) -> dict:
        """Capture declared build components plus reputation for reload checks."""
        stats = bridge.request("stats")
        globals_state = {
            name: int(bridge.request("get_global", name=name)["value"])
            for name in (spec.get("globals") or {})
        }
        reputation = bridge.observe()["state"].get("reputation", {})
        return {
            "attributes": dict(stats.get("attributes") or {}),
            "skill_ranks": dict(stats.get("skill_ranks") or {}),
            "abilities": sorted(stats.get("abilities") or []),
            "globals": globals_state,
            "reputation": reputation,
        }

    @staticmethod
    def assert_build_matches_spec(snapshot: dict, spec: dict) -> None:
        for name, expected in (spec.get("attributes") or {}).items():
            actual = snapshot["attributes"].get(name)
            if actual != expected:
                raise RuntimeError(f"attribute {name} verification failed: {actual} != {expected}")
        for name, expected in (spec.get("skills") or {}).items():
            actual = snapshot["skill_ranks"].get(name)
            if actual != expected:
                raise RuntimeError(f"skill {name} verification failed: {actual} != {expected}")
        actual_abilities = {name.replace("(Clone)", "").strip().lower() for name in snapshot["abilities"]}
        for name in spec.get("abilities") or []:
            if name.lower() not in actual_abilities:
                raise RuntimeError(f"ability {name} verification failed")
        for name, expected in (spec.get("globals") or {}).items():
            actual = snapshot["globals"].get(name)
            if actual != expected:
                raise RuntimeError(f"global {name} verification failed: {actual} != {expected}")

    @staticmethod
    def assert_build_persisted(before: dict, after: dict) -> None:
        if before != after:
            changed = [key for key in before if before.get(key) != after.get(key)]
            raise RuntimeError(f"build changed across save/reload: {changed}")

    def apply_build(self, bridge, spec: dict | None) -> None:
        """Apply a programmatic character build on top of the loaded base save.

        spec = {"attributes": {"Might": 16, ...},        # set exactly
                "skills": {"Dodge": 25, ...},            # base rank set exactly
                "abilities": ["Abl_PC_Power_Sunder", ...],
                "reputation": [{"faction": "ScarletChorus", "axis": "positive",
                                 "strength": 4}, ...],
                "globals": {"NAME": 1, ...}}
        Uses the game's own console commands (validated engine paths), verified
        live: attributes exact, skills/reputation applied, deriveds recompute.
        """
        if not spec:
            return
        for attr, value in (spec.get("attributes") or {}).items():
            bridge.request("console", cmd=f"AttributeScore player {attr} {int(value)}")
        for skill, value in (spec.get("skills") or {}).items():
            bridge.request("console", cmd=f"Skill player {skill} {int(value)}")
        for ability in spec.get("abilities") or []:
            bridge.request("console", cmd=f"AddAbility player {ability}")
        for rep in spec.get("reputation") or []:
            bridge.request("console", cmd=(
                f"reputationaddpoints {rep['faction']} {rep.get('axis', 'positive')} "
                f"{int(rep.get('strength', 1))} 585"))
        for name, value in (spec.get("globals") or {}).items():
            bridge.request("set_global", name=name, value=int(value))

    @property
    def target_faction(self) -> str | None:
        return self._target_faction

    @property
    def favor_log(self) -> dict[str, float]:
        return self.favor.logged_deltas
