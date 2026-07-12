"""Difficulty calibration harness for CrossyChickenEnv.

The env's ``difficulty="easy"|"normal"|"hard"`` presets (see ``DIFFICULTY`` in
env.py) are meant to form a monotonic challenge ladder: easy should be
survivably-crossable, hard should be genuinely harder (fewer grass lanes,
more hazard lanes). But that intent lives only in hand-picked numbers
(``safe_prob``, ``river_frac``, ``max_speed``) — nothing actually MEASURES
whether the ladder behaves the way it's supposed to.

This module runs a cheap reference policy (no trained agent required) over
each difficulty and reports:

* furthest row reached (mean/median/min/max) and episode length survived,
* a death-cause histogram (car / water / stuck / timeout),
* the lane mix actually generated (fraction grass/road/river over a sample
  of rows) — this part is deterministic given a preset + seed, independent
  of any policy, so it's the most robust monotonicity signal.

Two reference policies are provided:

* ``"random"`` — uniform-random actions each step. A floor baseline.
* ``"greedy_up"`` — presses UP whenever the row ahead is safe at the time
  the chicken would arrive there; otherwise sidesteps left/right into a
  safe column, or waits in place as a last resort. This is a *calibration*
  baseline, not a trained agent — it peeks at ``env._lane``/``env._danger``
  the same way the env's own state features do, just applied to plan one
  step ahead instead of only reporting distances.

``calibrate()`` is the importable entry point; ``main()`` is a thin CLI
wrapper over it so tests can drive the harness directly without shelling
out.

    # Eyeball the ladder with the smarter baseline:
    python games/crossy_chicken/calibrate.py --episodes 20 --policy greedy_up
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

# Allow `python games/crossy_chicken/calibrate.py` from the repo root: the
# repo root must be importable so `games.crossy_chicken` and `crpg_rle` resolve.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from games.crossy_chicken.env import DIFFICULTY, LEFT, NOOP, RIGHT, UP, CrossyChickenEnv  # noqa: E402

DEATH_CAUSES = ("car", "water", "stuck", "timeout")
POLICIES = ("random", "greedy_up")


# --------------------------------------------------------------------- policy
def _greedy_up_action(env: CrossyChickenEnv, rng: np.random.Generator) -> int:
    """Press UP if the row ahead will be safe; else dodge sideways; else wait.

    Mirrors env.step's own ordering: a move lands on (row', col') and is then
    checked for danger at ``t + 1`` (t advances once per step regardless of
    which action is taken). So "is UP safe" means: is (row+1, col) safe at
    t+1? This peeks at env internals (_lane/_danger) exactly like the env's
    own state-vector features do — it's a calibration baseline, not agent
    intelligence smuggled in through the backdoor.
    """
    row, col, t, width = env.row, env.col, env.t, env.width
    next_t = t + 1

    def safe(r: int, c: int) -> bool:
        if c < 0 or c >= width:
            return False
        lane = env._lane(r)
        return not env._danger(lane, c, next_t)

    if safe(row + 1, col):
        return UP

    left_ok = safe(row, col - 1)
    right_ok = safe(row, col + 1)
    if left_ok and right_ok:
        return int(rng.choice([LEFT, RIGHT]))
    if left_ok:
        return LEFT
    if right_ok:
        return RIGHT
    # Boxed in: stay put if that's not immediately lethal, otherwise UP is no
    # worse than any other move (all candidates are dangerous this instant).
    return NOOP if safe(row, col) else UP


def _random_action(env: CrossyChickenEnv, rng: np.random.Generator) -> int:
    return int(rng.integers(0, 5))


_ACT_FN = {"random": _random_action, "greedy_up": _greedy_up_action}


# --------------------------------------------------------------------- lanes
def _lane_mix(difficulty: str, env_kwargs: dict, seed: int, n_rows: int) -> dict:
    """Fraction of grass/road/river over the first ``n_rows`` generated rows.

    Deterministic given (difficulty preset, seed) — independent of any
    policy or episode outcome, so this is the most robust signal for
    checking the ladder is monotonic (easy has more grass than hard, etc).
    """
    env = CrossyChickenEnv(difficulty=difficulty, **(env_kwargs or {}))
    env.reset(seed=seed)
    counts = {"grass": 0, "road": 0, "river": 0}
    for row in range(1, n_rows + 1):
        counts[env._lane(row)["kind"]] += 1
    env.close()
    total = float(n_rows)
    return {k: v / total for k, v in counts.items()}


# ---------------------------------------------------------------- calibrate
def calibrate(
    difficulties=("easy", "normal", "hard"),
    n_episodes: int = 20,
    seeds=0,
    policy: str = "random",
    env_kwargs: dict | None = None,
    lane_sample_rows: int = 300,
) -> dict:
    """Run ``n_episodes`` of ``policy`` per difficulty and aggregate stats.

    Args:
        difficulties: iterable of difficulty names (subset of DIFFICULTY).
        n_episodes: episodes per difficulty.
        seeds: either a single int (episode i uses seed ``seeds + i``, and
            the lane-mix sample uses ``seeds``) or an explicit sequence of
            ``n_episodes`` ints (episode i uses ``seeds[i]``; lane-mix uses
            ``seeds[0]``). Fixed seeds make runs reproducible.
        policy: "random" or "greedy_up" (see ``_ACT_FN``).
        env_kwargs: extra kwargs forwarded to ``CrossyChickenEnv`` (e.g.
            obs_size, max_steps). ``difficulty`` is always set per-loop and
            must not be included here.
        lane_sample_rows: how many rows to sample for the lane-mix stat.

    Returns:
        ``{difficulty: {"n_episodes", "policy", "furthest_row" (mean/median/
        min/max), "episode_length" (mean/median), "death_causes" (histogram
        over DEATH_CAUSES, sums to n_episodes), "lane_mix" (fractions over
        grass/road/river, sums to ~1.0)}}``.
    """
    if policy not in _ACT_FN:
        raise ValueError(f"policy must be one of {POLICIES}; got {policy!r}")
    for d in difficulties:
        if d not in DIFFICULTY:
            raise ValueError(f"difficulty must be one of {sorted(DIFFICULTY)}; got {d!r}")
    if n_episodes < 1:
        raise ValueError(f"n_episodes must be >= 1; got {n_episodes}")

    if isinstance(seeds, int):
        seed_list = [seeds + i for i in range(n_episodes)]
        lane_seed = seeds
    else:
        seed_list = list(seeds)
        if len(seed_list) != n_episodes:
            raise ValueError(
                f"seeds must be an int or a sequence of length n_episodes "
                f"({n_episodes}); got {len(seed_list)} seeds"
            )
        lane_seed = seed_list[0]

    act_fn = _ACT_FN[policy]
    results: dict = {}
    for difficulty in difficulties:
        env = CrossyChickenEnv(difficulty=difficulty, **(env_kwargs or {}))
        furthest_rows: list[int] = []
        lengths: list[int] = []
        deaths = {k: 0 for k in DEATH_CAUSES}

        for ep_seed in seed_list:
            env.reset(seed=ep_seed)
            rng = np.random.default_rng(ep_seed)
            terminated = truncated = False
            info: dict = {}
            while not (terminated or truncated):
                action = act_fn(env, rng)
                _, _, terminated, truncated, info = env.step([action])

            furthest_rows.append(int(info.get("max_row", 0)))
            lengths.append(int(env.steps))
            if terminated:
                cause = info.get("terminal_kind", "stuck")
                deaths[cause] = deaths.get(cause, 0) + 1
            else:
                deaths["timeout"] += 1

        env.close()
        lane_mix = _lane_mix(difficulty, env_kwargs, lane_seed, lane_sample_rows)

        results[difficulty] = {
            "n_episodes": n_episodes,
            "policy": policy,
            "furthest_row": {
                "mean": float(np.mean(furthest_rows)),
                "median": float(np.median(furthest_rows)),
                "min": int(np.min(furthest_rows)),
                "max": int(np.max(furthest_rows)),
            },
            "episode_length": {
                "mean": float(np.mean(lengths)),
                "median": float(np.median(lengths)),
            },
            "death_causes": deaths,
            "lane_mix": lane_mix,
        }

    return results


# -------------------------------------------------------------------- print
def format_table(results: dict, difficulties) -> str:
    """Render a fixed-width table across difficulties for a human to eyeball."""
    cols = [
        ("difficulty", 10), ("policy", 10), ("eps", 5),
        ("mean_row", 9), ("med_row", 8), ("mean_len", 9),
        ("car%", 6), ("water%", 7), ("stuck%", 7), ("timeout%", 9),
        ("grass%", 7), ("road%", 6), ("river%", 7),
    ]
    header = " ".join(f"{name:<{w}}" for name, w in cols)
    lines = [header, "-" * len(header)]
    for d in difficulties:
        s = results[d]
        n = s["n_episodes"]
        dc = s["death_causes"]
        lm = s["lane_mix"]
        row_vals = [
            d, s["policy"], str(n),
            f"{s['furthest_row']['mean']:.2f}", f"{s['furthest_row']['median']:.2f}",
            f"{s['episode_length']['mean']:.2f}",
            f"{100.0 * dc['car'] / n:.1f}", f"{100.0 * dc['water'] / n:.1f}",
            f"{100.0 * dc['stuck'] / n:.1f}", f"{100.0 * dc['timeout'] / n:.1f}",
            f"{100.0 * lm['grass']:.1f}", f"{100.0 * lm['road']:.1f}", f"{100.0 * lm['river']:.1f}",
        ]
        lines.append(" ".join(f"{v:<{w}}" for v, (_, w) in zip(row_vals, cols)))
    return "\n".join(lines)


# ---------------------------------------------------------------------- CLI
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--difficulties", nargs="+", choices=sorted(DIFFICULTY),
                     default=["easy", "normal", "hard"])
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--policy", choices=POLICIES, default="random")
    ap.add_argument("--obs-size", type=int, default=36)
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--lane-sample-rows", type=int, default=300)
    args = ap.parse_args(argv)

    env_kwargs = {"obs_size": args.obs_size, "max_steps": args.max_steps}
    results = calibrate(
        difficulties=args.difficulties,
        n_episodes=args.episodes,
        seeds=args.seed,
        policy=args.policy,
        env_kwargs=env_kwargs,
        lane_sample_rows=args.lane_sample_rows,
    )
    print(format_table(results, args.difficulties))


if __name__ == "__main__":
    main()
