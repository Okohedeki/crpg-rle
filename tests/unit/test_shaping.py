"""Reward shaping: exploration novelty, tactical-pause bonus (env-paused only),
and the action-stats summary. Pause is no longer an agent action (Space is not in
ACTION_KEYS), so there is no agent pause press to penalize/rate-limit."""
import numpy as np

from crpg_rle.adapters.tyranny.adapter import ACTION_KEYS, TyrannyAdapter
from crpg_rle.adapters.tyranny.config import TyrannyConfig
from crpg_rle.core.modes import Mode

ALPHA1 = ACTION_KEYS.index("Alpha1")


def _state(x=0.0, z=0.0, area="AR", **kw):
    s = {"party": [{"pos": [x, 0.0, z]}], "area": area}
    s.update(kw)
    return s


def test_space_not_in_action_vocabulary():
    assert "Space" not in ACTION_KEYS   # pause is env infrastructure, not learned


def test_exploration_rewards_new_cells_once():
    a = TyrannyAdapter(TyrannyConfig(explore_bonus=0.1, explore_cell_size=3.0))
    a.reset(0)
    assert a.reward(Mode.OVERWORLD, [], _state(0, 0))["explore"] == 0.1
    assert a.reward(Mode.OVERWORLD, [], _state(1, 1))["explore"] == 0.0   # same cell
    assert a.reward(Mode.OVERWORLD, [], _state(10, 10))["explore"] == 0.1  # new cell
    a.reset(1)
    assert a.reward(Mode.OVERWORLD, [], _state(0, 0))["explore"] == 0.1   # fresh episode


def test_tactical_pause_bonus_edge_triggered():
    a = TyrannyAdapter(TyrannyConfig(tactical_pause_bonus=0.25, pause_penalty=0.0))
    a.reset(0)
    cast = np.array([0, 0, 0, ALPHA1])
    combat_paused = _state(paused=True, in_combat=True)
    # first command while env-paused in combat → bonus once
    assert a.reward(Mode.COMBAT, [], combat_paused, cast)["pause"] == 0.25
    # still paused → no repeat (can't be farmed)
    assert a.reward(Mode.COMBAT, [], combat_paused, cast)["pause"] == 0.0
    # combat resumes (unpaused) rearms it
    a.reward(Mode.COMBAT, [], _state(paused=False, in_combat=True), cast)
    assert a.reward(Mode.COMBAT, [], combat_paused, cast)["pause"] == 0.25


def test_action_stats_summary():
    from crpg_rle.train.buffer import action_stats
    actions = np.array([[0, 0, 2, 0], [1, 1, 2, 0], [0, 0, 0, 5]])
    st = action_stats(actions)
    assert abs(st["btn_right"] - 2 / 3) < 1e-6   # two right-clicks (move orders)
    assert 0.0 <= st["key_top_frac"] <= 1.0
    assert set(st) >= {"btn_none", "btn_right", "key_active", "cursor_x"}
