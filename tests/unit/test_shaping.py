"""Reward shaping + pause handling: exploration novelty, pause cost/tactical
bonus, and the pause-cooldown input gate."""
import numpy as np

from crpg_rle.adapters.tyranny.adapter import ACTION_KEYS, TyrannyAdapter
from crpg_rle.adapters.tyranny.config import TyrannyConfig
from crpg_rle.core.modes import Mode

SPACE = ACTION_KEYS.index("Space")
ALPHA1 = ACTION_KEYS.index("Alpha1")


def _state(x=0.0, z=0.0, area="AR", **kw):
    s = {"party": [{"pos": [x, 0.0, z]}], "area": area}
    s.update(kw)
    return s


def test_exploration_rewards_new_cells_once():
    a = TyrannyAdapter(TyrannyConfig(explore_bonus=0.1, explore_cell_size=3.0))
    a.reset(0)
    # first visit to a cell → bonus; revisit same cell → 0
    assert a.reward(Mode.OVERWORLD, [], _state(0, 0))["explore"] == 0.1
    assert a.reward(Mode.OVERWORLD, [], _state(1, 1))["explore"] == 0.0   # same cell
    assert a.reward(Mode.OVERWORLD, [], _state(10, 10))["explore"] == 0.1  # new cell
    # a fresh episode clears visited cells
    a.reset(1)
    assert a.reward(Mode.OVERWORLD, [], _state(0, 0))["explore"] == 0.1


def test_pause_press_is_penalized():
    a = TyrannyAdapter(TyrannyConfig(pause_penalty=0.02))
    a.reset(0)
    press_space = np.array([0, 0, 0, SPACE])
    assert a.reward(Mode.OVERWORLD, [], _state(), press_space)["pause"] == -0.02
    no_key = np.array([0, 0, 0, 0])
    assert a.reward(Mode.OVERWORLD, [], _state(), no_key)["pause"] == 0.0


def test_tactical_pause_bonus_in_combat():
    a = TyrannyAdapter(TyrannyConfig(tactical_pause_bonus=0.25, pause_penalty=0.0))
    a.reset(0)
    # issuing an ability (Alpha1) while paused in combat → bonus
    cast = np.array([0, 0, 0, ALPHA1])
    r = a.reward(Mode.COMBAT, [], _state(paused=True, in_combat=True), cast)["pause"]
    assert r == 0.25
    # same action, not paused → no bonus
    r2 = a.reward(Mode.COMBAT, [], _state(paused=False, in_combat=True), cast)["pause"]
    assert r2 == 0.0


def test_pause_cooldown_drops_repeat_presses():
    a = TyrannyAdapter(TyrannyConfig(pause_cooldown_seconds=1000.0))
    a.reset(0)
    press = np.array([0, 0, 0, SPACE])
    inputs = [{"t": "cursor", "x": 0.5, "y": 0.5}, {"t": "key", "key": "Space", "action": "press"}]
    first = a.gate_inputs(press, list(inputs))
    assert any(i.get("key") == "Space" for i in first)      # first press goes through
    second = a.gate_inputs(press, list(inputs))
    assert not any(i.get("key") == "Space" for i in second)  # within cooldown → dropped


def test_action_stats_summary():
    from crpg_rle.train.buffer import action_stats
    actions = np.array([[0, 0, 2, 0], [1, 1, 2, 0], [0, 0, 0, SPACE]])
    st = action_stats(actions)
    assert abs(st["btn_right"] - 2 / 3) < 1e-6   # two right-clicks (move orders)
    assert 0.0 <= st["key_top_frac"] <= 1.0
    assert set(st) >= {"btn_none", "btn_right", "key_active", "cursor_x"}
