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


# ----------------------------------------------------------- replay recorder
def _fake_info(mode=5, channels=None, events=None, interventions=None):
    info = {"mode": mode, "reward_channels": channels or {"milestone": 0.0},
            "events": events or [], "target_faction": "ScarletChorus",
            "milestones_fired": []}
    if interventions:
        info["interventions"] = interventions
    return info


def test_replay_recorder_writes_valid_jsonl_and_rolls_episodes(tmp_path):
    import json

    from crpg_rle.train.observer import ReplayRecorder

    rec = ReplayRecorder(tmp_path)
    a = np.array([3, 4, 1, 2])
    rec.on_step(None, a, 0.5, _fake_info(events=[{"type": "quest", "event": "started"}]))
    rec.on_step(None, a, -0.1,
                _fake_info(interventions=[{"seq": 1, "kind": "auto_unpause", "detail": {}}]),
                terminated=True)
    rec.on_step(None, a, 0.0, _fake_info())  # first step of episode 2
    rec.close()

    ep1 = (tmp_path / "replay_ep1.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ep1) == 2
    lines = [json.loads(l) for l in ep1]
    assert lines[0] == {"t": 0, "action": [3, 4, 1, 2], "mode": 5, "reward": 0.5,
                        "reward_channels": {"milestone": 0.0},
                        "events": [{"type": "quest", "event": "started"}],
                        "interventions": []}
    assert lines[1]["t"] == 1
    assert lines[1]["done"] == "terminated"
    assert lines[1]["interventions"][0]["kind"] == "auto_unpause"
    ep2 = (tmp_path / "replay_ep2.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(ep2[0])["t"] == 0


# -------------------------------------------------------------- status writer
def test_status_writer_atomic_json(tmp_path):
    import json

    from crpg_rle.train.observer import StatusWriter

    sw = StatusWriter(tmp_path, key_names=["", "Tab", "Alpha1"], min_interval=0.0)
    a = np.array([1, 2, 2, 1])  # right-click + Tab
    sw.on_step(None, a, 1.5, _fake_info(
        channels={"milestone": 1.0, "faction_favor": 0.5},
        events=[{"type": "area", "event": "loaded", "area": "Edgering"}],
        interventions=[{"seq": 1, "kind": "camera_recenter", "detail": {}}]))
    path = tmp_path / "live_status.json"
    assert path.exists()
    assert not (tmp_path / "live_status.json.tmp").exists()  # temp cleaned up
    status = json.loads(path.read_text(encoding="utf-8"))
    assert status["global_step"] == 1
    assert status["mode_name"] == "OVERWORLD"
    assert status["rollout"]["channels"] == {"milestone": 1.0, "faction_favor": 0.5}
    assert status["actions"]["buttons"] == {"right": 1}
    assert status["actions"]["keys"] == {"Tab": 1}
    assert status["recent_events"][0]["area"] == "Edgering"
    assert status["recent_interventions"][0]["kind"] == "camera_recenter"
    assert status["target_faction"] == "ScarletChorus"

    # update resets rollout accumulators and records training metrics
    sw.on_update({"update": 1, "pg_loss": -0.01, "entropy": 9.9})
    status = json.loads(path.read_text(encoding="utf-8"))
    assert status["update"] == 1
    assert status["last_update"]["pg_loss"] == -0.01
    assert status["rollout"]["channels"] == {}
    assert status["actions"]["keys"] == {}
    # ...but run-scoped history persists
    assert status["recent_interventions"][0]["kind"] == "camera_recenter"


def test_status_writer_episode_rollover(tmp_path):
    import json

    from crpg_rle.train.observer import StatusWriter

    sw = StatusWriter(tmp_path, min_interval=0.0)
    a = np.array([0, 0, 0, 0])
    sw.on_step(None, a, 1.0, _fake_info())
    sw.on_step(None, a, 2.0, _fake_info(), truncated=True)
    status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert status["episode"] == 2
    assert status["t_in_episode"] == 0
    assert status["last_ep_reward"] == 3.0
    assert status["ep_reward"] == 0.0


def test_ppo_trainer_drives_observer(tmp_path):
    import json

    pytest_torch = __import__("pytest").importorskip("torch")  # noqa: F841

    from crpg_rle.train.observer import make_observer
    from crpg_rle.train.ppo import PPOConfig, PPOTrainer
    from crpg_rle.train.proxy_env import ProxyCRPGEnv

    env = ProxyCRPGEnv(obs_size=36, episode_len=8)
    obs = make_observer(tmp_path, key_names=[f"K{i}" for i in range(13)])
    cfg = PPOConfig(total_steps=32, rollout_steps=32, epochs=1, minibatches=2)
    PPOTrainer(env, cfg, device="cpu", observer=obs).train()
    obs.close()

    status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert status["global_step"] == 32
    assert status["update"] == 1
    assert "pg_loss" in status["last_update"]
    replays = sorted(tmp_path.glob("replay_ep*.jsonl"))
    assert len(replays) >= 4  # 32 steps / 8-step episodes
    first = json.loads(replays[0].read_text(encoding="utf-8").splitlines()[0])
    assert set(first) >= {"t", "action", "mode", "reward", "reward_channels",
                          "events", "interventions"}


# ------------------------------------------------------------ dashboard HTTP
def test_dashboard_serves_page_status_and_csv(tmp_path):
    import json
    import sys
    import threading
    import urllib.request
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
    try:
        import dashboard
    finally:
        sys.path.pop(0)

    (tmp_path / "live_status.json").write_text(
        json.dumps({"global_step": 7, "mode_name": "DIALOGUE",
                    "csv": str(tmp_path / "run.csv")}), encoding="utf-8")
    (tmp_path / "run.csv").write_text("update,step,pg_loss\n1,512,-0.02\n",
                                      encoding="utf-8")

    httpd = dashboard.serve(tmp_path, port=0)  # port 0: OS picks a free one
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        page = urllib.request.urlopen(f"{base}/", timeout=5).read().decode("utf-8")
        assert "<title>crpg-rle live run</title>" in page
        assert "cdn" not in page.lower()  # self-contained: no external scripts
        status = json.loads(urllib.request.urlopen(
            f"{base}/status.json", timeout=5).read().decode("utf-8"))
        assert status["global_step"] == 7
        csv = urllib.request.urlopen(f"{base}/csv", timeout=5).read().decode("utf-8")
        assert csv.startswith("update,step,pg_loss")
        import urllib.error
        try:
            urllib.request.urlopen(f"{base}/../secrets", timeout=5)
            assert False, "unknown route must 404"
        except urllib.error.HTTPError as err:
            assert err.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
