"""Unit tests for the Crossy Chicken train/eval seed split and evaluator.

CPU-only, fast: no torch, no checkpoints — just a random act_fn driven
through games.crossy_chicken.evaluate.evaluate() over a handful of the
frozen EVAL_SEEDS.
"""
import math
import random
import sys
from pathlib import Path

# Make the repo root importable so `games.crossy_chicken` resolves under pytest.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from games.crossy_chicken.evaluate import TERMINAL_KINDS, evaluate  # noqa: E402
from games.crossy_chicken.seeds import EVAL_SEEDS, TRAIN_SEEDS, assert_disjoint  # noqa: E402

OBS = 36  # small enough for a fast CPU run


def test_train_and_eval_seeds_are_disjoint():
    assert_disjoint()  # should not raise
    assert set(TRAIN_SEEDS).isdisjoint(set(EVAL_SEEDS))


def test_eval_seeds_stable_sorted_and_nonempty():
    assert isinstance(EVAL_SEEDS, tuple)
    assert len(EVAL_SEEDS) > 0
    assert list(EVAL_SEEDS) == sorted(EVAL_SEEDS)
    assert len(set(EVAL_SEEDS)) == len(EVAL_SEEDS)  # no duplicates


def test_evaluate_random_policy_returns_well_formed_report():
    rng = random.Random(0)

    def random_act_fn(obs):
        return rng.randrange(5)

    seeds = EVAL_SEEDS[:5]
    env_kwargs = dict(obs_size=OBS, difficulty="easy", max_steps=40, stuck_limit=20)

    report = evaluate(random_act_fn, seeds, env_kwargs, survival_row_threshold=5)

    # Required keys present.
    for key in (
        "episodes", "terminal_counts", "mean_max_row", "max_max_row",
        "mean_reward", "survival_rate", "survival_row_threshold",
        "max_rows", "rewards",
    ):
        assert key in report

    assert report["episodes"] == len(seeds)

    # Terminal counts sum to the number of episodes.
    assert sum(report["terminal_counts"].values()) == report["episodes"]
    # Every episode terminates via one of the known kinds for this env.
    for kind in report["terminal_counts"]:
        assert kind in TERMINAL_KINDS

    # Rows / reward are finite numbers.
    assert math.isfinite(report["mean_max_row"])
    assert math.isfinite(report["mean_reward"])
    assert report["max_max_row"] >= 0
    assert all(math.isfinite(r) for r in report["rewards"])
    assert len(report["max_rows"]) == report["episodes"]
    assert len(report["rewards"]) == report["episodes"]

    assert 0.0 <= report["survival_rate"] <= 1.0


def test_evaluate_is_deterministic_given_fixed_seeds_and_act_fn():
    def act_fn(obs):
        return 1  # always UP

    seeds = EVAL_SEEDS[:5]
    env_kwargs = dict(obs_size=OBS, difficulty="easy", max_steps=30, stuck_limit=15)

    report_a = evaluate(act_fn, seeds, env_kwargs)
    report_b = evaluate(act_fn, seeds, env_kwargs)

    assert report_a["max_rows"] == report_b["max_rows"]
    assert report_a["rewards"] == report_b["rewards"]
    assert report_a["terminal_counts"] == report_b["terminal_counts"]
