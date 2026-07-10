"""ConfigDriver dispatch + the core's game-agnostic intercept hook."""
from crpg_rle.adapters.tyranny.config_driver import ConfigDriver


class FakeBridge:
    def __init__(self, obs=None):
        self.observe_calls = 0
        self._obs = obs or {"state": {}, "events": []}

    def observe(self):
        self.observe_calls += 1
        return self._obs


def test_levelup_plan_lookup():
    d = ConfigDriver({"levelups": [
        {"level": 2, "skills": {"Dodge": 1}},
        {"level": 3, "abilities": ["Abl_Cleave"]},
    ]})
    assert d.levelup_plan_for(2)["skills"] == {"Dodge": 1}
    assert d.levelup_plan_for(3)["abilities"] == ["Abl_Cleave"]
    assert d.levelup_plan_for(4) is None


def test_on_step_noop_when_nothing_triggers():
    d = ConfigDriver({}, death_mode="checkpoint")
    b = FakeBridge()
    # neither level-up nor death present → no mutation, no re-observe
    assert d.on_step(b, {"level_up": False}, []) is None
    assert b.observe_calls == 0


class FakeLevelUpBridge:
    """Simulates the level-up ops: one stage offering skills + an ability, then close."""

    def __init__(self):
        self.calls = []
        self._stage = 0

    def request(self, op, **kw):
        self.calls.append((op, kw))
        if op == "levelup_begin":
            self._stage = 0
            return {"open": True, "stage": 0, "target_level": kw["slot"] + 100}
        if op == "levelup_options":
            if self._stage == 0:
                return {"kind": "build", "options": [{"i": 0, "label": "Abl_Cleave"}],
                        "skills": [{"skill": "Dodge", "adjustment": 1}]}
            return {"options": [], "skills": []}
        if op == "levelup_skill":
            return {"skill": kw["skill"], "applied": kw["delta"]}
        if op == "levelup_choose":
            return {"chosen": "ability"}
        if op == "levelup_advance":
            self._stage += 1
            return {"open": self._stage < 2}  # closes after 2 advances
        return {"ok": True}

    def observe(self):
        return {"state": {"level_up": False}, "events": []}


def test_levelup_driver_applies_plan_and_finalizes():
    d = ConfigDriver({"levelups": [{"level": 3, "skills": {"Dodge": 2},
                                    "abilities": ["Abl_Cleave"]}]})
    b = FakeLevelUpBridge()
    state = {"level_up": True,
             "level_up_detail": {"members": [{"slot": 0, "level": 2}]}}
    reobs = d.on_step(b, state, [])
    ops = [op for op, _ in b.calls]
    assert "levelup_begin" in ops
    assert ("levelup_skill", {"skill": "Dodge", "delta": 2}) in b.calls
    assert ("levelup_choose", {"index": 0}) in b.calls
    assert reobs is not None  # acted → re-observed
    # a second identical step does not re-drive the same (slot, level)
    b.calls.clear()
    assert d.on_step(b, state, []) is None
    assert not any(op == "levelup_begin" for op, _ in b.calls)


def test_levelup_error_does_not_crash():
    class RaisingBridge:
        def request(self, op, **kw):
            if op == "levelup_begin":
                raise RuntimeError("cannot level up in combat")
            return {}
    d = ConfigDriver({})
    state = {"level_up": True, "level_up_detail": {"members": [{"slot": 0, "level": 2}]}}
    # exception is swallowed; no member handled → no re-observe
    assert d.on_step(RaisingBridge(), state, []) is None


def test_death_terminal_mode_never_acts():
    d = ConfigDriver({}, death_mode="terminal")
    b = FakeBridge()
    # even with a wipe, terminal mode leaves recovery to the env terminal
    assert d.on_step(b, {"party_dead": True}, []) is None
    assert b.observe_calls == 0


class RecordBridge:
    def __init__(self):
        self.calls = []

    def request(self, op, **kw):
        self.calls.append((op, kw))
        return {"ok": True, "revived": True}

    def observe(self):
        return {"state": {"party_dead": False}, "events": []}


def test_death_revive_recovers_and_penalizes_once():
    d = ConfigDriver({}, death_mode="revive", recovery_penalty=-2.0)
    b = RecordBridge()
    reobs = d.on_step(b, {"party_dead": True}, [])
    assert ("revive", {}) in b.calls
    assert reobs is not None
    assert d.take_recovery_penalty() == -2.0
    assert d.take_recovery_penalty() == 0.0  # charged exactly once


def test_death_checkpoint_reloads_save():
    d = ConfigDriver({}, death_mode="checkpoint", checkpoint_save="run.savegame")
    b = RecordBridge()
    d.on_step(b, {"game_over": True}, [])
    assert ("load", {"file": "run.savegame"}) in b.calls


def test_adapter_death_mode_terminal_semantics():
    from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter
    from crpg_rle.adapters.tyranny.config import TyrannyConfig

    a = TyrannyAdapter(TyrannyConfig(death_mode="terminal"))
    a.reset(0)
    done, kind, _ = a.terminal({"party_dead": True})
    assert done and kind == "failure"

    a2 = TyrannyAdapter(TyrannyConfig(death_mode="revive"))
    a2.reset(0)
    done2, kind2, _ = a2.terminal({"party_dead": True})
    assert not done2 and kind2 is None
    # success and timer failures remain terminal regardless of death_mode
    a2.milestones._fired.add("m9")
    assert a2.terminal({})[:2] == (True, "success")


def test_adapter_reward_recovery_channel():
    from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter
    from crpg_rle.core.modes import Mode

    a = TyrannyAdapter()
    a.reset(0)
    assert a.reward(Mode.OVERWORLD, [], {})["recovery"] == 0.0
    # after a recovery the penalty flows through the recovery channel once
    a.config_driver._pending_penalty = -1.5
    assert a.reward(Mode.OVERWORLD, [], {})["recovery"] == -1.5
    assert a.reward(Mode.OVERWORLD, [], {})["recovery"] == 0.0


def test_intercept_hook_merges_reobserved_state():
    # Exercise the core hook contract with a stub adapter, independent of Tyranny.
    import numpy as np
    import gymnasium as gym
    from crpg_rle.core.env import CRPGEnv
    from crpg_rle.core.modes import Mode

    class StubAdapter:
        def __init__(self):
            from types import SimpleNamespace
            self.config = SimpleNamespace(
                obs_height=4, obs_width=4, reward_weights={}, start_mode="none",
                save_start=None, frame_skip=1, time_scale=1.0, max_steps=100,
                instance_id=0, port=5599, exe_path="x")
            self.milestones = SimpleNamespace(fired=set())
            self.target_faction = "A"
            self.intercepted = []

        def action_key_list(self): return ["", "Space"]
        def factions(self): return ["A"]
        def state_vector_size(self): return 3
        def mode(self, state): return Mode.OVERWORLD
        def pack_observation_state(self, state): return np.zeros(3, np.float32)
        def goal_vector(self): return np.zeros(1, np.float32)
        def reward(self, mode, events, state): return {"m": 0.0}
        def terminal(self, state): return False, None, 0.0
        def reset(self, seed): return {"target_faction": "A", "dialogue_seed": 0}

        def intercept(self, bridge, state, events):
            self.intercepted.append((dict(state), list(events)))
            # simulate applying a scripted config change and re-observing
            return {"state": {"leveled": True}, "events": [{"type": "levelup"}]}

    class FakeEnvBridge:
        def request(self, op, **kw): return {}
        def act(self, inputs, frames): return {}
        def observe(self):
            return {"state": {"leveled": False}, "events": [{"type": "step"}]}

    adapter = StubAdapter()
    env = CRPGEnv(adapter, launch=False)
    env._bridge = FakeEnvBridge()
    obs, reward, done, trunc, info = env.step([0, 0, 0, 0])
    # intercept saw the pre-observe state and its returned events were merged
    assert adapter.intercepted and adapter.intercepted[0][0] == {"leveled": False}
