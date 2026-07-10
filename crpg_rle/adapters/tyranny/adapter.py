"""TyrannyAdapter — wires the generic core to Tyranny specifics.

Holds all game-specific policy: the action key vocabulary, mode detection,
state packing, the milestone chain, and the goal-conditioned favor reward.
The core CRPGEnv talks to this through a small, game-agnostic surface.
"""
from __future__ import annotations

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

    def apply_build(self, bridge, spec: dict | None) -> None:
        """Apply a programmatic character build on top of the loaded base save.

        spec = {"attributes": {"Might": 16, ...},        # set exactly
                "skills": {"Dodge": 25, ...},            # base points added
                "abilities": ["Sunder_Armor", ...],
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
