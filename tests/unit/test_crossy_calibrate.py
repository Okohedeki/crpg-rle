"""Unit tests for the Crossy Chicken difficulty calibration harness.

Fast, CPU-only, no trained agent needed. Two kinds of checks:

* Structural validity of ``calibrate()``'s return dict (right keys, death
  histogram sums to n_episodes, lane-mix fractions sum to ~1) for both
  reference policies.
* A monotonicity sanity check on the *lane mix* (grass fraction strictly
  decreasing easy > normal > hard). This is deterministic from the
  DIFFICULTY presets and independent of policy/episode noise, so it's the
  robust signal that the difficulty ladder is actually calibrated — episode
  survival stats are left as structural-only assertions since 8 episodes is
  too small a sample to be a reliable ordering signal.
"""
import sys
from pathlib import Path

import pytest

# Make the repo root importable so `games.crossy_chicken` resolves under pytest.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from games.crossy_chicken.calibrate import DEATH_CAUSES, calibrate, format_table  # noqa: E402

OBS = 36  # small enough for fast CPU
DIFFICULTIES = ("easy", "normal", "hard")
N_EPISODES = 8


def _env_kwargs():
    return {"obs_size": OBS, "max_steps": 200}


@pytest.mark.parametrize("policy", ["random", "greedy_up"])
def test_calibrate_returns_well_formed_dict(policy):
    results = calibrate(
        difficulties=DIFFICULTIES,
        n_episodes=N_EPISODES,
        seeds=0,
        policy=policy,
        env_kwargs=_env_kwargs(),
        lane_sample_rows=100,
    )

    assert set(results.keys()) == set(DIFFICULTIES)
    for difficulty in DIFFICULTIES:
        stats = results[difficulty]
        assert stats["n_episodes"] == N_EPISODES
        assert stats["policy"] == policy

        # furthest_row / episode_length: structural validity only (noisy at
        # this sample size, not asserted on for ordering).
        fr = stats["furthest_row"]
        assert set(fr.keys()) == {"mean", "median", "min", "max"}
        assert fr["min"] <= fr["mean"] <= fr["max"]
        assert fr["min"] >= 0

        el = stats["episode_length"]
        assert set(el.keys()) == {"mean", "median"}
        assert el["mean"] > 0

        # Death-cause histogram must sum to n_episodes (every episode ends
        # in exactly one of car/water/stuck/timeout).
        dc = stats["death_causes"]
        assert set(dc.keys()) == set(DEATH_CAUSES)
        assert sum(dc.values()) == N_EPISODES
        assert all(v >= 0 for v in dc.values())

        # Lane mix fractions must sum to ~1.
        lm = stats["lane_mix"]
        assert set(lm.keys()) == {"grass", "road", "river"}
        assert lm["grass"] + lm["road"] + lm["river"] == pytest.approx(1.0)
        assert all(0.0 <= v <= 1.0 for v in lm.values())


def test_lane_mix_grass_fraction_is_monotonic_easy_to_hard():
    # Deterministic given (preset, seed) — independent of policy and episode
    # noise, so this is the robust monotonicity signal for the ladder.
    results = calibrate(
        difficulties=DIFFICULTIES,
        n_episodes=N_EPISODES,
        seeds=0,
        policy="random",
        env_kwargs=_env_kwargs(),
        lane_sample_rows=300,
    )
    grass = {d: results[d]["lane_mix"]["grass"] for d in DIFFICULTIES}
    assert grass["easy"] > grass["normal"] > grass["hard"]

    # And river fraction (among hazard lanes it eats into) should trend the
    # other way: hard leans harder into rivers than easy does.
    river = {d: results[d]["lane_mix"]["river"] for d in DIFFICULTIES}
    assert river["hard"] > river["easy"]


def test_calibrate_seed_reproducibility():
    kwargs = dict(
        difficulties=DIFFICULTIES,
        n_episodes=N_EPISODES,
        seeds=42,
        policy="greedy_up",
        env_kwargs=_env_kwargs(),
        lane_sample_rows=100,
    )
    a = calibrate(**kwargs)
    b = calibrate(**kwargs)
    for difficulty in DIFFICULTIES:
        assert a[difficulty]["furthest_row"] == b[difficulty]["furthest_row"]
        assert a[difficulty]["death_causes"] == b[difficulty]["death_causes"]
        assert a[difficulty]["lane_mix"] == b[difficulty]["lane_mix"]


def test_calibrate_accepts_explicit_seed_list():
    seeds = list(range(100, 100 + N_EPISODES))
    results = calibrate(
        difficulties=["normal"],
        n_episodes=N_EPISODES,
        seeds=seeds,
        policy="random",
        env_kwargs=_env_kwargs(),
        lane_sample_rows=50,
    )
    assert results["normal"]["n_episodes"] == N_EPISODES


def test_calibrate_rejects_bad_policy():
    with pytest.raises(ValueError):
        calibrate(difficulties=["easy"], n_episodes=2, seeds=0, policy="not_a_policy")


def test_calibrate_rejects_mismatched_seed_list_length():
    with pytest.raises(ValueError):
        calibrate(difficulties=["easy"], n_episodes=4, seeds=[1, 2], policy="random")


def test_format_table_contains_all_difficulties():
    results = calibrate(
        difficulties=DIFFICULTIES,
        n_episodes=N_EPISODES,
        seeds=0,
        policy="random",
        env_kwargs=_env_kwargs(),
        lane_sample_rows=50,
    )
    table = format_table(results, DIFFICULTIES)
    for difficulty in DIFFICULTIES:
        assert difficulty in table
