from types import SimpleNamespace

from crpg_rle.core.env import CRPGEnv


class FakeBridge:
    def __init__(self):
        self.calls = []

    def request(self, op, **kwargs):
        self.calls.append((op, kwargs))
        if op == "build_begin":
            return {"open": True, "locked": False, "cheats": True}
        if op == "save":
            return {"saved": True, "file": kwargs["file"]}
        if op == "build_lock":
            return {"open": False, "locked": True, "cheats": False}
        if op == "build_status":
            return {"open": False, "locked": True, "cheats": False}
        return {"ok": True}


class FakeAdapter:
    def __init__(self):
        self.calls = []
        self.snapshots = [
            {"attributes": {"Might": 16}, "skill_ranks": {}, "abilities": [], "globals": {}, "reputation": {}},
            {"attributes": {"Might": 16}, "skill_ranks": {}, "abilities": [], "globals": {}, "reputation": {}},
        ]

    def apply_build(self, bridge, spec):
        self.calls.append(("apply", spec))

    def snapshot_build(self, bridge, spec):
        self.calls.append(("snapshot", spec))
        return self.snapshots.pop(0)

    def assert_build_matches_spec(self, snapshot, spec):
        assert snapshot["attributes"]["Might"] == spec["attributes"]["Might"]

    def assert_build_persisted(self, before, after):
        assert before == after


def test_initialize_run_build_saves_reloads_verifies_then_locks():
    env = CRPGEnv.__new__(CRPGEnv)
    env._bridge = FakeBridge()
    env.adapter = FakeAdapter()
    env.config = SimpleNamespace(instance_id=0, working_save="RL_TEST.savegame", verify_build_reload=True)
    env._run_save = None
    env._run_build_spec = None
    env._build_info = {"locked": False, "verified": False}
    loaded = []
    env._load_game = lambda filename: loaded.append(filename) or {"party": [{"name": "Agent"}]}

    spec = {"attributes": {"Might": 16}}
    state = env._initialize_run_build("RL1.savegame", spec)

    assert state["party"]
    assert loaded == ["RL_TEST.savegame"]
    assert [op for op, _ in env._bridge.calls] == ["build_begin", "save", "build_lock"]
    assert env._run_save == "RL_TEST.savegame"
    assert env._run_build_spec == spec
    assert env._build_info == {
        "locked": True,
        "verified": True,
        "working_save": "RL_TEST.savegame",
    }


def test_initialize_run_build_never_overwrites_pristine_save():
    env = CRPGEnv.__new__(CRPGEnv)
    env._bridge = FakeBridge()
    env.adapter = FakeAdapter()
    env.config = SimpleNamespace(instance_id=0, working_save="RL1.savegame", verify_build_reload=True)

    try:
        env._initialize_run_build("rl1.SAVEGAME", {"attributes": {"Might": 16}})
    except ValueError as exc:
        assert "must not overwrite" in str(exc)
    else:
        raise AssertionError("expected pristine-save protection")
    assert env._bridge.calls == []