import pytest

from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter


class FakeBridge:
    def __init__(self):
        self.calls = []

    def request(self, op, **kw):
        self.calls.append((op, kw))
        return {"ok": True}


def test_apply_build_translates_spec():
    a = TyrannyAdapter()
    b = FakeBridge()
    a.apply_build(b, {
        "attributes": {"Might": 16, "Wits": 14},
        "skills": {"Dodge": 25},
        "abilities": ["Abl_PC_Power_Sunder"],
        "reputation": [{"faction": "ScarletChorus", "axis": "positive", "strength": 4}],
        "globals": {"RL_FLAG": 1},
    })
    cmds = [kw.get("cmd") for op, kw in b.calls if op == "console"]
    assert "AttributeScore player Might 16" in cmds
    assert "AttributeScore player Wits 14" in cmds
    assert "Skill player Dodge 25" in cmds
    assert "AddAbility player Abl_PC_Power_Sunder" in cmds
    assert any(c.startswith("reputationaddpoints ScarletChorus positive 4") for c in cmds)
    assert ("set_global", {"name": "RL_FLAG", "value": 1}) in b.calls


def test_apply_build_none_is_noop():
    a = TyrannyAdapter()
    b = FakeBridge()
    a.apply_build(b, None)
    a.apply_build(b, {})
    assert b.calls == []


def test_validate_build_spec_canonicalizes_and_rejects_command_injection():
    adapter = TyrannyAdapter()
    spec = adapter.validate_build_spec({
        "attributes": {"might": 16},
        "skills": {"Two_Handed": 30},
        "abilities": ["Abl_PC_Power_Sunder", "Abl_PC_Power_Sunder"],
        "globals": {"RL_FLAG": 7},
    })
    assert spec == {
        "attributes": {"Might": 16},
        "skills": {"Two_Handed": 30},
        "abilities": ["Abl_PC_Power_Sunder"],
        "globals": {"RL_FLAG": 7},
    }
    with pytest.raises(ValueError, match="safe game identifier"):
        adapter.validate_build_spec({"abilities": ["Abl_PC_Power_Sunder; quit"]})
    with pytest.raises(ValueError, match="unknown build_spec"):
        adapter.validate_build_spec({"unlocked_again": True})


def test_build_verification_detects_reload_drift():
    adapter = TyrannyAdapter()
    spec = {
        "attributes": {"Might": 16},
        "skills": {"Dodge": 25},
        "abilities": ["Abl_PC_Power_Sunder"],
        "globals": {"RL_FLAG": 7},
    }
    snapshot = {
        "attributes": {"Might": 16},
        "skill_ranks": {"Dodge": 25},
        "abilities": ["Abl_PC_Power_Sunder(Clone)"],
        "globals": {"RL_FLAG": 7},
        "reputation": {"ScarletChorus": {"favor": 1.0}},
    }
    adapter.assert_build_matches_spec(snapshot, spec)
    adapter.assert_build_persisted(snapshot, dict(snapshot))

    drifted = dict(snapshot)
    drifted["attributes"] = {"Might": 10}
    with pytest.raises(RuntimeError, match="changed across save/reload"):
        adapter.assert_build_persisted(snapshot, drifted)