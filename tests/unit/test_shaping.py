"""Reward shaping: exploration novelty, paused-step + offscreen penalties,
tactical-pause bonus, auto-unpause backstop, and the action-stats summary.
Space AND Escape are not agent keys (pause/menus are env infrastructure)."""
import numpy as np

from crpg_rle.adapters.tyranny.adapter import ACTION_KEYS, TyrannyAdapter
from crpg_rle.adapters.tyranny.config import TyrannyConfig
from crpg_rle.core.modes import Mode

ALPHA1 = ACTION_KEYS.index("Alpha1")


def _state(x=0.0, z=0.0, area="AR", **kw):
    s = {"party": [{"pos": [x, 0.0, z]}], "area": area}
    s.update(kw)
    return s


def test_pause_and_menu_keys_removed():
    assert "Space" not in ACTION_KEYS
    assert "Escape" not in ACTION_KEYS


def test_exploration_rewards_new_cells_once():
    a = TyrannyAdapter(TyrannyConfig(explore_bonus=0.1, explore_cell_size=3.0))
    a.reset(0)
    assert a.reward(Mode.OVERWORLD, [], _state(0, 0))["explore"] == 0.1
    assert a.reward(Mode.OVERWORLD, [], _state(1, 1))["explore"] == 0.0   # same cell
    assert a.reward(Mode.OVERWORLD, [], _state(10, 10))["explore"] == 0.1  # new cell
    a.reset(1)
    assert a.reward(Mode.OVERWORLD, [], _state(0, 0))["explore"] == 0.1   # fresh episode


def test_paused_step_penalty_charged_each_step():
    a = TyrannyAdapter(TyrannyConfig(paused_step_penalty=0.05, tactical_pause_bonus=0.0))
    a.reset(0)
    paused = _state(paused=True)
    assert a.reward(Mode.OVERWORLD, [], paused)["pause"] == -0.05
    assert a.reward(Mode.OVERWORLD, [], paused)["pause"] == -0.05  # every step
    assert a.reward(Mode.OVERWORLD, [], _state(paused=False))["pause"] == 0.0


def test_tactical_pause_bonus_edge_triggered():
    a = TyrannyAdapter(TyrannyConfig(tactical_pause_bonus=0.25, paused_step_penalty=0.0))
    a.reset(0)
    cast = np.array([0, 0, 0, ALPHA1])
    combat_paused = _state(paused=True, in_combat=True)
    assert a.reward(Mode.COMBAT, [], combat_paused, cast)["pause"] == 0.25
    assert a.reward(Mode.COMBAT, [], combat_paused, cast)["pause"] == 0.0  # no farming
    a.reward(Mode.COMBAT, [], _state(paused=False, in_combat=True), cast)  # rearm
    assert a.reward(Mode.COMBAT, [], combat_paused, cast)["pause"] == 0.25


def test_offscreen_penalty():
    a = TyrannyAdapter(TyrannyConfig(offscreen_penalty=0.02))
    a.reset(0)
    assert a.reward(Mode.OVERWORLD, [], _state(player_on_screen=False))["offscreen"] == -0.02
    assert a.reward(Mode.OVERWORLD, [], _state(player_on_screen=True))["offscreen"] == 0.0
    # missing field (menus/loading/old mod) counts as on-screen
    assert a.reward(Mode.OVERWORLD, [], _state())["offscreen"] == 0.0


def test_auto_unpause_backstop():
    from crpg_rle.adapters.tyranny.config_driver import ConfigDriver

    class RecordBridge:
        def __init__(self):
            self.calls = []

        def request(self, op, **kw):
            self.calls.append((op, kw))
            return {"ok": True}

        def observe(self):
            return {"state": {"paused": False}, "events": []}

    d = ConfigDriver({}, auto_unpause_steps=3)
    b = RecordBridge()
    paused = {"paused": True}
    assert d.on_step(b, paused, []) is None      # 1
    assert d.on_step(b, paused, []) is None      # 2
    assert d.on_step(b, paused, []) is not None  # 3 -> unpause fires
    assert any(op == "act" for op, _ in b.calls)
    # an unpaused step resets the counter
    d.on_step(b, {"paused": False}, [])
    assert d._paused_steps == 0


def test_offscreen_recenter_backstop():
    from crpg_rle.adapters.tyranny.config_driver import ConfigDriver

    class RecordBridge:
        def __init__(self):
            self.calls = []

        def request(self, op, **kw):
            self.calls.append(op)
            return {"ok": True}

        def observe(self):
            return {"state": {"player_on_screen": True}, "events": []}

    d = ConfigDriver({}, offscreen_recenter_steps=2)
    b = RecordBridge()
    off = {"player_on_screen": False}
    assert d.on_step(b, off, []) is None       # 1
    assert d.on_step(b, off, []) is not None   # 2 -> recenter fires
    assert "recenter" in b.calls
    d.on_step(b, {"player_on_screen": True}, [])
    assert d._offscreen_steps == 0             # visible resets the counter


def test_objective_reward_micro_progress():
    a = TyrannyAdapter(TyrannyConfig(quest_started_bonus=0.25, quest_progress_bonus=0.5,
                                     new_conversation_bonus=0.1, new_area_bonus=0.25))
    a.reset(0)
    events = [
        {"type": "quest", "event": "started", "quest": "q1"},
        {"type": "quest", "event": "advanced", "quest": "q1"},
        {"type": "conversation", "event": "start", "file": "cv_a"},
        {"type": "area", "event": "loaded", "area": "AR_08"},
    ]
    assert abs(a.reward(Mode.OVERWORLD, events, _state())["objective"] - 1.1) < 1e-9
    # repeats of the same conversation/area earn nothing; quest events trust the engine
    assert a._objective_reward([{"type": "conversation", "event": "start", "file": "cv_a"},
                                {"type": "area", "event": "loaded", "area": "AR_08"}]) == 0.0
    # fresh episode rearms the dedupe
    a.reset(1)
    assert a._objective_reward([{"type": "conversation", "event": "start", "file": "cv_a"}]) == 0.1


def test_action_stats_summary():
    from crpg_rle.train.buffer import action_stats
    actions = np.array([[0, 0, 2, 0], [1, 1, 2, 0], [0, 0, 0, 5]])
    st = action_stats(actions)
    assert abs(st["btn_right"] - 2 / 3) < 1e-6
    assert set(st) >= {"btn_none", "btn_right", "key_active", "cursor_x"}
