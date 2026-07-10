"""Act 1 milestone chain — the sparse reward backbone (build brief §7).

Each milestone fires exactly once when its detector matches the drained event
stream (or current state). Detectors are small named functions in a data-driven
table so they can be refined after playtest without restructuring the chain.

Several detectors are best-effort until validated on a real playthrough; those
are marked PLAYTEST-TODO. The event substring matching is deliberately loose so
route permutations (kill-envoy paths, rebel path) still trigger the beats.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from . import config as C

# A detector sees (event | None, state) and the chain's own scratch dict.
# It returns True when its milestone should fire this step.
Detector = Callable[[dict | None, dict, dict], bool]


def _quest_event(ev, substr, kinds):
    return (
        ev is not None
        and ev.get("type") in ("quest", "quest_end_state")
        and substr.lower() in (ev.get("quest") or "").lower()
        and (ev.get("event") in kinds if ev.get("type") == "quest" else True)
    )


def _area_contains(ev, needle):
    return (
        ev is not None
        and ev.get("type") == "area"
        and ev.get("event") == "loaded"
        and needle.lower() in (ev.get("area") or "").lower()
    )


# --- individual detectors (named for testability) -------------------------

def det_creation(ev, state, scratch):
    return True  # milestone 0 fires on first update (episode gate)


def det_enter_well(ev, state, scratch):
    if _quest_event(ev, C.QUEST_EDICT, ("started",)):
        return True
    return _area_contains(ev, "AR_08")


def det_edict_first(ev, state, scratch):
    # First "advanced" of the edict quest = first camp delivery.
    if _quest_event(ev, C.QUEST_EDICT, ("advanced", "completed")):
        scratch["edict_advances"] = scratch.get("edict_advances", 0) + 1
        return scratch["edict_advances"] >= 1
    return False


def det_edict_second(ev, state, scratch):
    # Second distinct advance = second camp. PLAYTEST-TODO: distinguish camps by
    # global var once the exact var names are known.
    if _quest_event(ev, C.QUEST_EDICT, ("advanced", "completed")):
        scratch["edict_advances2"] = scratch.get("edict_advances2", 0) + 1
        return scratch["edict_advances2"] >= 2
    return False


def det_edgering(ev, state, scratch):
    return _quest_event(ev, C.QUEST_EDGERING, ("completed", "advanced"))


def det_assault_unlocked(ev, state, scratch):
    return _quest_event(ev, C.QUEST_ASSAULT, ("started",))


def _make_quest_completed(substr):
    def det(ev, state, scratch):
        return _quest_event(ev, substr, ("completed",))
    return det


def det_faction_commit(ev, state, scratch):
    # PLAYTEST-TODO: confirm the real commitment global-var name.
    if ev is not None and ev.get("type") == "global_var" and ev.get("value", 0) >= 1:
        name = (ev.get("name") or "").lower()
        if any(k in name for k in ("commit", "allegiance", "joinedfaction", "anarchist")):
            return True
    return _quest_event(ev, C.QUEST_REBEL, ("started",))


def det_citadel(ev, state, scratch):
    if _area_contains(ev, "citadel"):
        return True
    return _quest_event(ev, C.QUEST_ASSAULT, ("advanced",))


def det_edict_broken(ev, state, scratch):
    if ev is not None and ev.get("type") == "global_var":
        name = (ev.get("name") or "").lower()
        if "edict" in name and ("brok" in name or "break" in name):
            return True
    return _quest_event(ev, C.QUEST_ASSAULT, ("completed",))


def det_spire(ev, state, scratch):
    if _quest_event(ev, C.QUEST_REGION, ("completed",)):
        return True
    return _area_contains(ev, "spire")


@dataclass
class Milestone:
    id: str
    name: str
    reward: float
    detector: Detector
    terminal_success: bool = False


@dataclass
class MilestoneChain:
    granularity: str = "coarse"
    base_reward: float = 1.0
    success_reward: float = 10.0
    failure_penalty: float = -5.0
    _milestones: list[Milestone] = field(default_factory=list, init=False)
    _fired: set[str] = field(default_factory=set, init=False)
    _scratch: dict = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._build()

    def _build(self) -> None:
        r = self.base_reward
        ms: list[Milestone] = [
            Milestone("m0", "creation_conquest", 0.0, det_creation),
            Milestone("m1", "enter_vendriens_well", r, det_enter_well),
            Milestone("m2", "edict_to_camp_1", r, det_edict_first),
            Milestone("m3", "edict_to_camp_2", r, det_edict_second),
            Milestone("m4", "edgering_ruins", r, det_edgering),
        ]
        if self.granularity == "fine":
            ms += [
                Milestone("m5a", "echocall_crossing", r / 3.0,
                          _make_quest_completed(C.QUEST_ECHOCALL)),
                Milestone("m5b", "matani_river", r / 3.0,
                          _make_quest_completed(C.QUEST_MATANI)),
                Milestone("m5c", "tripnettle_wilderness", r / 3.0,
                          _make_quest_completed(C.QUEST_TRIPNETTLE)),
            ]
        else:
            ms.append(Milestone("m5", "assault_unlocked", r, det_assault_unlocked))
        ms += [
            Milestone("m6", "faction_commitment", r, det_faction_commit),
            Milestone("m7", "citadel_assault", r, det_citadel),
            Milestone("m8", "ascension_edict_broken", r, det_edict_broken),
            Milestone("m9", "mountain_spire", self.success_reward, det_spire,
                      terminal_success=True),
        ]
        self._milestones = ms

    def reset(self) -> None:
        self._fired = set()
        self._scratch = {}

    def update(self, events: list[dict], state: dict) -> tuple[float, list[str]]:
        """Process this step's events; fire matching milestones once each."""
        reward = 0.0
        newly: list[str] = []

        def try_fire(ev):
            nonlocal reward
            for m in self._milestones:
                if m.id in self._fired:
                    continue
                # m0 has no event; fire on the sentinel None pass below.
                if m.id == "m0" and ev is not None:
                    continue
                if m.detector(ev, state, self._scratch):
                    self._fired.add(m.id)
                    newly.append(m.name)
                    reward += m.reward

        # Sentinel pass fires m0 on the first update.
        if "m0" not in self._fired:
            try_fire(None)
        for ev in events:
            try_fire(ev)
        return reward, newly

    def terminal(self, state: dict) -> tuple[bool, str | None, float]:
        """Success = milestone 9 fired. Failure = game over / party dead /
        edict timer expired."""
        if "m9" in self._fired:
            return True, "success", 0.0
        if state.get("game_over") or state.get("party_dead"):
            return True, "failure", self.failure_penalty
        days = state.get("edict_days_remaining")
        if days is not None and days >= 0.0 and days <= 0.0:
            return True, "failure_timer", self.failure_penalty
        return False, None, 0.0

    @property
    def fired(self) -> set[str]:
        return set(self._fired)

    @property
    def count(self) -> int:
        return len(self._milestones)
