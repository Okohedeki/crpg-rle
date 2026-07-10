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
        "abilities": ["Sunder_Armor"],
        "reputation": [{"faction": "ScarletChorus", "axis": "positive", "strength": 4}],
        "globals": {"RL_FLAG": 1},
    })
    cmds = [kw.get("cmd") for op, kw in b.calls if op == "console"]
    assert "AttributeScore player Might 16" in cmds
    assert "AttributeScore player Wits 14" in cmds
    assert "Skill player Dodge 25" in cmds
    assert "AddAbility player Sunder_Armor" in cmds
    assert any(c.startswith("reputationaddpoints ScarletChorus positive 4") for c in cmds)
    assert ("set_global", {"name": "RL_FLAG", "value": 1}) in b.calls


def test_apply_build_none_is_noop():
    a = TyrannyAdapter()
    b = FakeBridge()
    a.apply_build(b, None)
    a.apply_build(b, {})
    assert b.calls == []
