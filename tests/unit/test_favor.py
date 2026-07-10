from crpg_rle.adapters.tyranny.favor import FavorReward
from crpg_rle.core.modes import Mode


def rep(faction, axis="positive", event="add", strength=4, applied=True):
    return {"type": "reputation", "faction": faction, "axis": axis,
            "event": event, "strength": strength, "applied": applied}


def test_rewards_target_favor_in_dialogue():
    f = FavorReward()
    f.reset("Disfavored")
    r = f.update([rep("Disfavored")], Mode.DIALOGUE)
    assert r == 8.0  # strength 4 -> 8.0


def test_no_reward_outside_dialogue():
    f = FavorReward()
    f.reset("Disfavored")
    assert f.update([rep("Disfavored")], Mode.OVERWORLD) == 0.0
    assert f.update([rep("Disfavored")], Mode.COMBAT) == 0.0


def test_no_reward_for_nontarget_faction():
    f = FavorReward()
    f.reset("Disfavored")
    assert f.update([rep("ScarletChorus")], Mode.DIALOGUE) == 0.0


def test_wrath_axis_not_rewarded():
    f = FavorReward()
    f.reset("Disfavored")
    assert f.update([rep("Disfavored", axis="negative")], Mode.DIALOGUE) == 0.0


def test_remove_is_negative():
    f = FavorReward()
    f.reset("Disfavored")
    assert f.update([rep("Disfavored", event="remove", strength=3)], Mode.DIALOGUE) == -4.0


def test_unapplied_not_counted():
    f = FavorReward()
    f.reset("Disfavored")
    assert f.update([rep("Disfavored", applied=False)], Mode.DIALOGUE) == 0.0


def test_all_deltas_logged_regardless():
    f = FavorReward()
    f.reset("Disfavored")
    f.update([rep("ScarletChorus"), rep("Disfavored", axis="negative")], Mode.OVERWORLD)
    log = f.logged_deltas
    assert log["ScarletChorus.positive"] == 8.0
    assert log["Disfavored.negative"] == 8.0
