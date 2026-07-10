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


def test_death_terminal_mode_never_acts():
    d = ConfigDriver({}, death_mode="terminal")
    b = FakeBridge()
    # even with a wipe, terminal mode leaves recovery to the env terminal
    assert d.on_step(b, {"party_dead": True}, []) is None
    assert b.observe_calls == 0


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
