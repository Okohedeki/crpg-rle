"""Observability layer: intervention log, env info pass-throughs, replay
recorder, status writer, and the dashboard HTTP server. CPU-only, no live game."""
import numpy as np

from crpg_rle.adapters.tyranny.config_driver import ConfigDriver


# --------------------------------------------------------- intervention log
class RecordBridge:
    def __init__(self):
        self.calls = []

    def request(self, op, **kw):
        self.calls.append((op, kw))
        return {"ok": True}

    def observe(self):
        return {"state": {}, "events": []}


def test_interventions_recorded_and_drained():
    d = ConfigDriver({}, death_mode="revive", death_penalty=-1.0)
    b = RecordBridge()
    d.on_step(b, {"player_dead": True}, [])
    drained = d.interventions_drain()
    assert len(drained) == 1
    entry = drained[0]
    assert entry["kind"] == "death_revive"
    assert entry["seq"] == 1
    assert isinstance(entry["detail"], dict)
    # drain clears
    assert d.interventions_drain() == []


def test_intervention_seq_survives_reset():
    d = ConfigDriver({}, death_mode="revive")
    b = RecordBridge()
    d.on_step(b, {"player_dead": True}, [])
    assert d.interventions_drain()[0]["seq"] == 1
    d.reset()  # per-episode reset must NOT reset the seq counter
    d.on_step(b, {"player_dead": True}, [])
    assert d.interventions_drain()[0]["seq"] == 2


def test_auto_unpause_and_recenter_record_interventions():
    d = ConfigDriver({}, auto_unpause_steps=2, offscreen_recenter_steps=2)
    b = RecordBridge()
    # two consecutive paused steps trigger the unpause backstop
    d.on_step(b, {"paused": True}, [])
    d.on_step(b, {"paused": True}, [])
    kinds = [e["kind"] for e in d.interventions_drain()]
    assert kinds == ["auto_unpause"]
    # two consecutive offscreen steps trigger the recenter backstop
    d.on_step(b, {"player_on_screen": False}, [])
    d.on_step(b, {"player_on_screen": False}, [])
    entries = d.interventions_drain()
    assert [e["kind"] for e in entries] == ["camera_recenter"]
    assert entries[0]["detail"]["offscreen_steps"] == 2


def test_failed_intervention_recorded_with_error():
    class FailBridge:
        def request(self, op, **kw):
            raise RuntimeError("bridge hiccup")

    d = ConfigDriver({}, death_mode="revive")
    d.on_step(FailBridge(), {"player_dead": True}, [])
    entries = d.interventions_drain()
    assert entries[0]["kind"] == "death_recovery"
    assert entries[0]["detail"]["ok"] is False
    assert "bridge hiccup" in entries[0]["detail"]["error"]


def test_levelup_intervention_recorded():
    class LevelBridge:
        def __init__(self):
            self._adv = 0

        def request(self, op, **kw):
            if op == "levelup_begin":
                return {"open": True}
            if op == "levelup_options":
                return {"options": [], "skills": []}
            if op == "levelup_advance":
                return {"open": False}
            return {"ok": True}

        def observe(self):
            return {"state": {}, "events": []}

    d = ConfigDriver({"levelups": [{"level": 3, "skills": {"Dodge": 1}}]})
    state = {"level_up": True,
             "level_up_detail": {"members": [{"slot": 0, "level": 2}]}}
    d.on_step(LevelBridge(), state, [])
    entries = d.interventions_drain()
    assert entries[0]["kind"] == "levelup"
    assert entries[0]["detail"] == {"slot": 0, "target_level": 3, "planned": True}


# ------------------------------------------------- core env info pass-throughs
def _stub_env(intercept_result=None, party=None, events=None):
    """CRPGEnv wired to a stub adapter + fake bridge (no game, no launch)."""
    from types import SimpleNamespace

    from crpg_rle.core.env import CRPGEnv
    from crpg_rle.core.modes import Mode

    class StubAdapter:
        def __init__(self):
            self.config = SimpleNamespace(
                obs_height=4, obs_width=4, reward_weights={}, start_mode="none",
                save_start=None, frame_skip=1, time_scale=1.0, max_steps=100,
                instance_id=0, port=5599, exe_path="x")
            self.milestones = SimpleNamespace(fired=set())
            self.target_faction = "A"
            self.pending_interventions = [
                {"seq": 1, "kind": "auto_unpause", "detail": {"key": "Space"}}]

        def action_key_list(self): return ["", "Space"]
        def factions(self): return ["A"]
        def state_vector_size(self): return 3
        def mode(self, state): return Mode.OVERWORLD
        def pack_observation_state(self, state): return np.zeros(3, np.float32)
        def goal_vector(self): return np.zeros(1, np.float32)
        def reward(self, mode, events, state, action=None): return {"m": 0.0}
        def terminal(self, state): return False, None, 0.0
        def reset(self, seed): return {"target_faction": "A", "dialogue_seed": 0}

        def interventions_drain(self):
            out, self.pending_interventions = self.pending_interventions, []
            return out

    class FakeEnvBridge:
        def request(self, op, **kw): return {}
        def act(self, inputs, frames): return {}
        def observe(self):
            return {"state": {"party": party or []},
                    "events": events if events is not None else [{"type": "quest", "event": "started"}]}

    env = CRPGEnv(StubAdapter(), launch=False)
    env._bridge = FakeEnvBridge()
    return env


def test_env_step_surfaces_events_and_interventions():
    env = _stub_env()
    _, _, _, _, info = env.step([0, 0, 0, 0])
    assert info["events"] == [{"type": "quest", "event": "started"}]
    assert info["interventions"] == [
        {"seq": 1, "kind": "auto_unpause", "detail": {"key": "Space"}}]
    # second step: nothing new to drain → key absent (not an empty list)
    _, _, _, _, info2 = env.step([0, 0, 0, 0])
    assert "interventions" not in info2
    assert info2["events"] == [{"type": "quest", "event": "started"}]


def test_env_step_surfaces_party_when_present():
    party = [{"hp": 40.0, "max_hp": 55.0, "dead": False}]
    env = _stub_env(party=party)
    _, _, _, _, info = env.step([0, 0, 0, 0])
    assert info["party"] == party
    env2 = _stub_env(party=[])
    _, _, _, _, info2 = env2.step([0, 0, 0, 0])
    assert "party" not in info2
