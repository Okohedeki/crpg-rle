"""Frozen train/eval seed split for CrossyChickenEnv.

Why this file exists: an RL agent's reward curve on the seeds it trained on
tells you almost nothing about how it will behave on a world it has never
seen — the agent can memorize lane layouts (car/log phases, gaps, timing)
for specific seeds instead of learning a general crossing policy. Reporting
"performance" on training seeds is a train/test leak, exactly like scoring a
supervised model on its own training set.

To make that mistake hard to make by accident, this module hard-codes two
DISJOINT, non-overlapping integer ranges:

* ``TRAIN_SEEDS`` — the low range (0..9999), intended for env.reset(seed=...)
  during training. Nothing here is a contract; training code is free to
  sample any subset (or all) of it, or use seeds outside it entirely — the
  only thing that matters is that TRAIN_SEEDS and EVAL_SEEDS never overlap.
* ``EVAL_SEEDS`` — a fixed, held-out set of 200 seeds far away from the
  training range (100000..100199). This set must stay frozen (never trained
  on, never edited) so evaluation numbers are comparable run over run and
  actually measure generalization instead of memorization.

Dependency-free (stdlib only) so it can be imported from anywhere (env,
training scripts, evaluator, tests) without pulling in torch/numpy.
"""
from __future__ import annotations

# Low range: safe to draw training seeds from. Kept generous (10k) so
# training can sample a large variety of worlds without ever touching the
# held-out eval range below.
TRAIN_SEEDS: tuple[int, ...] = tuple(range(0, 10_000))

# Held-out range: NEVER train on these. Far away from TRAIN_SEEDS (offset by
# 100000) so an accidental off-by-one or range typo in training code cannot
# silently make the two ranges collide. Fixed size (200) and fixed values so
# every evaluation run — today, next month, after retraining — scores the
# policy on the exact same set of worlds.
EVAL_SEEDS: tuple[int, ...] = tuple(sorted(range(100_000, 100_200)))


def assert_disjoint() -> None:
    """Raise AssertionError if TRAIN_SEEDS and EVAL_SEEDS overlap.

    Called at import time (below) so any accidental edit to either range
    that introduces an overlap fails loudly and immediately, rather than
    quietly corrupting eval numbers.
    """
    overlap = set(TRAIN_SEEDS) & set(EVAL_SEEDS)
    assert not overlap, (
        f"TRAIN_SEEDS and EVAL_SEEDS overlap on {len(overlap)} seed(s): "
        f"{sorted(overlap)[:10]}{'...' if len(overlap) > 10 else ''} — "
        "this is a train/test leak, fix the ranges."
    )


# Module-level check: fail fast on import, not just when a test happens to
# call assert_disjoint().
assert_disjoint()
