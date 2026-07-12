"""Adversarial reward-hacking tests for CrossyChickenEnv.

The reward contract (see games/crossy_chicken/env.py) is: +1 (PROGRESS_REWARD)
ONLY when the chicken reaches a NEW furthest row (self.max_row strictly
increases), -0.01 (STEP_PENALTY) every step, and -1 (DEATH_PENALTY) on death
(car, water, or stuck-timeout). The thesis under test: an agent cannot
accumulate positive reward without genuinely making forward progress. These
tests try to break that guarantee — jittering, revisiting rows, farming a
river log, racing the stuck timer, and dying exactly on a new furthest row —
and assert the env resists every one of them.

This file complements tests/unit/test_crossy_chicken.py (which already covers
basic oscillation/backtracking); the cases here go deeper: exact reward-sum
bounds over long adversarial rollouts, path-independence of cumulative
progress, and the critical ordering guarantee that danger is checked BEFORE
progress is awarded (so death on a brand-new row pays zero progress, not +1).
"""
import sys
from pathlib import Path

import numpy as np
import pytest

# Make the repo root importable so `games.crossy_chicken` resolves under pytest.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from games.crossy_chicken.env import CrossyChickenEnv

OBS = 36  # small enough for fast CPU, large enough for the policy CNN kernels

_CHANNEL_KEYS = {"progress", "death", "step"}

# Fully-lethal road: every column is a car at every t (car_len == period).
_FULL_ROAD = {"kind": "road", "dir": 1, "speed": 1, "car_len": 3, "gap": 0, "period": 3, "phase": 0}
# Fully-lethal river: no column is ever a log (car_len == 0), so every cell is water.
_FULL_WATER = {"kind": "river", "dir": 1, "speed": 1, "car_len": 0, "gap": 3, "period": 3, "phase": 0}


def _grass(env, rows):
    for r in rows:
        env._lanes[r] = {"kind": "grass"}


def _assert_known_channels(info):
    assert set(info["reward_channels"].keys()) == _CHANNEL_KEYS


# --------------------------------------------------------------------------
# 1. Total-reward bound under adversarial jittering.
# --------------------------------------------------------------------------
def test_adversarial_jitter_never_yields_positive_reward():
    """A long sequence of LEFT/RIGHT/DOWN/NOOP (never UP) on grass must never
    set a new furthest row, so total reward is exactly the sum of step
    penalties (<= 0) and the progress channel sums to exactly 0."""
    n_steps = 300
    env = CrossyChickenEnv(obs_size=OBS, stuck_limit=n_steps + 100)
    env.reset(seed=0)
    _grass(env, [0])

    jitter_actions = [0, 3, 4, 2]  # NOOP, LEFT, RIGHT, DOWN — never UP
    total_reward = 0.0
    total_progress = 0.0
    for i in range(n_steps):
        a = jitter_actions[i % len(jitter_actions)]
        _, reward, term, trunc, info = env.step([a])
        _assert_known_channels(info)
        assert not term, f"unexpected death at step {i}: {info}"
        total_reward += reward
        total_progress += info["reward_channels"]["progress"]

    assert total_progress == pytest.approx(0.0)
    assert total_reward == pytest.approx(-0.01 * n_steps)
    assert total_reward <= 0.0
    assert env.row == 0 and env.max_row == 0


# --------------------------------------------------------------------------
# 2. Progress is monotonic-gated: only exceeding max_row ever pays again.
# --------------------------------------------------------------------------
def test_progress_only_pays_on_strictly_new_max_row():
    env = CrossyChickenEnv(obs_size=OBS, stuck_limit=1000)
    env.reset(seed=0)
    _grass(env, range(0, 6))

    # Climb straight to row 3: each step pays exactly once.
    for expected_row in (1, 2, 3):
        _, reward, term, trunc, info = env.step([1])  # UP
        assert not term and not trunc
        assert info["reward_channels"]["progress"] == pytest.approx(1.0)
        assert env.row == expected_row and env.max_row == expected_row

    # Oscillate strictly below/at the current max_row (3): down, up, down, up.
    # row visits: 2, 3, 2, 3 — 3 is a revisit (not a new max), never exceeds
    # it, so every one of these must pay zero progress. Ends back at row 3.
    for a in (2, 1, 2, 1):
        _, reward, term, trunc, info = env.step([a])
        assert not term
        assert info["reward_channels"]["progress"] == pytest.approx(0.0)
    assert env.row == 3 and env.max_row == 3

    # Sideways jitter at the oscillation floor also pays nothing.
    for a in (3, 4, 3, 4):
        _, _, _, _, info = env.step([a])
        assert info["reward_channels"]["progress"] == pytest.approx(0.0)
    assert env.row == 3 and env.max_row == 3

    # Only now exceeding the old max_row (going to row 4) pays again.
    _, reward, term, trunc, info = env.step([1])  # UP: row 3 -> 4, new max
    assert info["reward_channels"]["progress"] == pytest.approx(1.0)
    assert env.row == 4 and env.max_row == 4


# --------------------------------------------------------------------------
# 3. Cumulative progress equals max furthest row K, independent of the path.
# --------------------------------------------------------------------------
def test_cumulative_progress_equals_K_regardless_of_path():
    K = 4

    def rollout(actions):
        env = CrossyChickenEnv(obs_size=OBS, stuck_limit=1000)
        env.reset(seed=0)
        _grass(env, range(0, K + 2))
        total_progress = 0.0
        for a in actions:
            _, _, term, trunc, info = env.step([a])
            assert not term
            total_progress += info["reward_channels"]["progress"]
        return total_progress, env.max_row

    # Path A: straight climb.
    path_a = [1, 1, 1, 1]  # UP x4 -> rows 1,2,3,4
    progress_a, max_row_a = rollout(path_a)

    # Path B: a meandering route (backtracks, sideways jitter, revisits) that
    # still tops out at exactly row K. Hand-verified row trace (from row 0):
    # UP->1(new,+1) UP->2(new,+1) DOWN->1 UP->2(revisit,+0) UP->3(new,+1)
    # DOWN->2 LEFT->2(+0) UP->3(revisit,+0) UP->4(new,+1) RIGHT->4(+0)
    path_b = [1, 1, 2, 1, 1, 2, 3, 1, 1, 4]
    progress_b, max_row_b = rollout(path_b)

    assert max_row_a == K
    assert max_row_b == K
    assert progress_a == pytest.approx(float(K))
    assert progress_b == pytest.approx(float(K))
    assert progress_a == pytest.approx(progress_b)


# --------------------------------------------------------------------------
# 4. Death always nets negative — and dying on a NEW furthest row pays zero
#    progress (danger is checked BEFORE progress is awarded).
# --------------------------------------------------------------------------
def test_forced_car_death_on_current_row_nets_negative():
    env = CrossyChickenEnv(obs_size=OBS)
    env.reset(seed=0)
    env._lanes[env.row] = dict(_FULL_ROAD)
    _, reward, term, trunc, info = env.step([0])  # NOOP: car sweeps over us
    assert term and not trunc
    assert info["terminal_kind"] == "car"
    assert info["reward_channels"]["progress"] == pytest.approx(0.0)
    assert info["reward_channels"]["death"] == pytest.approx(-1.0)
    assert info["reward_channels"]["step"] == pytest.approx(-0.01)
    assert reward == pytest.approx(-1.01)


def test_forced_water_death_on_current_row_nets_negative():
    env = CrossyChickenEnv(obs_size=OBS)
    env.reset(seed=0)
    env._lanes[env.row] = dict(_FULL_WATER)
    _, reward, term, trunc, info = env.step([0])  # NOOP: standing in water
    assert term and not trunc
    assert info["terminal_kind"] == "water"
    assert info["reward_channels"]["progress"] == pytest.approx(0.0)
    assert info["reward_channels"]["death"] == pytest.approx(-1.0)
    assert reward == pytest.approx(-1.01)


def test_dying_on_a_new_furthest_row_awards_zero_progress_car():
    """The key anti-hack property: stepping onto a cell that is BOTH a new
    furthest row AND lethal must pay zero progress, not +1. Otherwise an
    agent could farm net-positive-ish terminal steps by suiciding into new
    territory. Confirms danger is evaluated strictly before progress."""
    env = CrossyChickenEnv(obs_size=OBS)
    env.reset(seed=0)
    _grass(env, [0])
    env._lanes[1] = dict(_FULL_ROAD)  # row 1 is a brand-new row, fully lethal
    assert env.max_row == 0
    _, reward, term, trunc, info = env.step([1])  # UP into row 1 -> dies
    assert term and not trunc
    assert env.row == 1  # did step onto the new row...
    assert info["terminal_kind"] == "car"
    assert info["reward_channels"]["progress"] == pytest.approx(0.0), (
        "BUG: progress was awarded on a lethal cell — reward hackable by "
        "suiciding into new furthest rows"
    )
    assert info["reward_channels"]["death"] == pytest.approx(-1.0)
    assert reward == pytest.approx(-1.01)
    assert env.max_row == 0, "max_row must not advance on a death step"


def test_dying_on_a_new_furthest_row_awards_zero_progress_water():
    env = CrossyChickenEnv(obs_size=OBS)
    env.reset(seed=0)
    _grass(env, [0])
    env._lanes[1] = dict(_FULL_WATER)  # row 1 is new, fully water
    assert env.max_row == 0
    _, reward, term, trunc, info = env.step([1])  # UP into row 1 -> drowns
    assert term and not trunc
    assert env.row == 1
    assert info["terminal_kind"] == "water"
    assert info["reward_channels"]["progress"] == pytest.approx(0.0), (
        "BUG: progress was awarded on a lethal cell — reward hackable by "
        "suiciding into new furthest rows"
    )
    assert info["reward_channels"]["death"] == pytest.approx(-1.0)
    assert reward == pytest.approx(-1.01)
    assert env.max_row == 0


# --------------------------------------------------------------------------
# 5. River non-farmability: a log is not a stable farm — it slides away.
# --------------------------------------------------------------------------
def test_river_log_is_not_a_stable_farm():
    """Construct a river lane where the chicken's column is a log at the
    moment it steps on (so it survives and earns progress), but the log has
    slid away one step later — a NOOP on the same cell then drowns. This
    proves you cannot sit on a river collecting step rewards indefinitely."""
    env = CrossyChickenEnv(obs_size=OBS, stuck_limit=1000)
    env.reset(seed=0)
    _grass(env, [0])
    # car_len=1, gap=1, period=2: occupied(col, t) iff (col - t) % 2 == 0.
    env._lanes[1] = {
        "kind": "river", "dir": 1, "speed": 1,
        "car_len": 1, "gap": 1, "period": 2, "phase": 0,
    }
    col = env.col  # width // 2 == 5 by default; (5 - 1) % 2 == 0 -> log at t=1

    # Step 1: UP onto row 1 at t=1 -> our column is a log right now. Survives
    # and this is a brand-new furthest row, so it pays progress.
    _, reward1, term1, trunc1, info1 = env.step([1])
    _assert_known_channels(info1)
    assert not term1
    assert env.row == 1 and env.max_row == 1
    assert info1["reward_channels"]["progress"] == pytest.approx(1.0)
    assert reward1 == pytest.approx(0.99)

    # Step 2: NOOP, same column, t=2 -> (col - 2) % 2 == 1 -> water. The log
    # slid out from under us; standing still is lethal, not a free farm.
    _, reward2, term2, trunc2, info2 = env.step([0])
    _assert_known_channels(info2)
    assert term2 and not trunc2
    assert info2["terminal_kind"] == "water"
    assert info2["reward_channels"]["progress"] == pytest.approx(0.0)
    assert info2["reward_channels"]["death"] == pytest.approx(-1.0)
    assert reward2 == pytest.approx(-1.01)


# --------------------------------------------------------------------------
# 6. Stuck timer cannot be reset without genuine forward progress.
# --------------------------------------------------------------------------
def test_stuck_timer_climbs_and_kills_without_progress_resets():
    stuck_limit = 6
    env = CrossyChickenEnv(obs_size=OBS, stuck_limit=stuck_limit)
    env.reset(seed=0)
    _grass(env, [0, 1])

    # Alternate NOOP/LEFT/RIGHT forever — none of these are UP, so row never
    # changes and since_progress must climb every single step with no reset.
    jitter_actions = [0, 3, 4]
    term = False
    info = None
    for i in range(stuck_limit):
        a = jitter_actions[i % len(jitter_actions)]
        _, reward, term, trunc, info = env.step([a])
        _assert_known_channels(info)
        assert info["reward_channels"]["progress"] == pytest.approx(0.0)
        if i < stuck_limit - 1:
            assert not term
            assert env.since_progress == i + 1, (
                "since_progress must monotonically climb on non-progress "
                "actions, never reset without a genuine new max_row"
            )
    assert term
    assert info["terminal_kind"] == "stuck"
    assert info["reward_channels"]["death"] == pytest.approx(-1.0)
    assert env.max_row == 0
