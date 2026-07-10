from crpg_rle.adapters.tyranny.milestones import MilestoneChain


def q(name, event="advanced"):
    return {"type": "quest", "quest": name, "event": event}


def qend(name, end_state=1, failed=False):
    return {"type": "quest_end_state", "quest": name, "end_state": end_state, "failed": failed}


def area(name):
    return {"type": "area", "event": "loaded", "area": name}


def test_m0_fires_once_immediately():
    ch = MilestoneChain()
    r, fired = ch.update([], {})
    assert "creation_conquest" in fired
    assert "m0" in ch.fired
    # second update does not re-fire m0
    r2, fired2 = ch.update([], {})
    assert "creation_conquest" not in fired2


def test_enter_well_via_area():
    ch = MilestoneChain()
    ch.update([], {})
    r, fired = ch.update([area("AR_0801_EdgeringRuins")], {})
    assert "enter_vendriens_well" in fired
    assert r == ch.base_reward


def test_edict_two_camps_order_tolerant():
    ch = MilestoneChain()
    ch.update([], {})
    _, f1 = ch.update([q("08_qst_vendrienswell_edict_quest", "advanced")], {})
    assert "edict_to_camp_1" in f1
    _, f2 = ch.update([q("08_qst_vendrienswell_edict_quest", "advanced")], {})
    assert "edict_to_camp_2" in f2


def test_milestone_fires_once():
    ch = MilestoneChain()
    ch.update([], {})
    ch.update([area("AR_0801")], {})
    _, again = ch.update([area("AR_0801")], {})
    assert "enter_vendriens_well" not in again


def test_fine_granularity_splits_m5():
    coarse = MilestoneChain(granularity="coarse")
    fine = MilestoneChain(granularity="fine")
    assert fine.count == coarse.count + 2  # m5 -> m5a/b/c
    ch = MilestoneChain(granularity="fine")
    ch.update([], {})
    _, fired = ch.update([q("08_qst_echocallcrossing_main_quest", "completed")], {})
    assert "echocall_crossing" in fired


def test_success_terminal_on_spire():
    ch = MilestoneChain()
    ch.update([], {})
    ch.update([q("08_qst_vendrienswell_region_quest", "completed")], {})
    done, kind, penalty = ch.terminal({})
    assert done and kind == "success"


def test_failure_terminal_game_over():
    ch = MilestoneChain()
    ch.update([], {})
    done, kind, penalty = ch.terminal({"game_over": True})
    assert done and kind == "failure"
    assert penalty == ch.failure_penalty


def test_failure_terminal_edict_timer():
    ch = MilestoneChain()
    ch.update([], {})
    done, kind, _ = ch.terminal({"edict_days_remaining": 0.0})
    assert done and kind == "failure_timer"


def test_no_terminal_normally():
    ch = MilestoneChain()
    ch.update([], {})
    done, kind, _ = ch.terminal({"edict_days_remaining": 5.0})
    assert not done
