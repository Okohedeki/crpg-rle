"""Evaluate a Crossy Chicken policy on the frozen held-out EVAL_SEEDS.

Standalone CLI (mirrors train_crossy.py's sys.path setup). Runs either a
trained checkpoint (via crpg_rle.train.policy.load_policy) or a uniform
random baseline (--random, no torch needed) over games.crossy_chicken.seeds
.EVAL_SEEDS and prints a report: termination breakdown by terminal_kind
(car/water/stuck/timeout), mean & max furthest row, mean episode reward, and
survival rate (fraction of episodes reaching a configurable row threshold).

Evaluating on EVAL_SEEDS (and never TRAIN_SEEDS) is what makes the numbers
meaningful — see games/crossy_chicken/seeds.py for why.

    # Trained checkpoint:
    python games/crossy_chicken/evaluate.py --checkpoint runs/crossy/policy.pt

    # Random baseline (sanity check / floor):
    python games/crossy_chicken/evaluate.py --random --max-eval-seeds 10 --obs-size 36

The evaluation loop itself is the ``evaluate()`` function below, which takes
a plain ``act_fn(obs) -> int`` callable and a list of seeds; it doesn't know
or care whether actions come from a trained policy or randint(). This keeps
``main()`` a thin CLI wrapper and lets tests drive ``evaluate()`` directly
with a random act_fn instead of shelling out.
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from pathlib import Path

# Allow `python games/crossy_chicken/evaluate.py` from the repo root: the
# repo root must be importable so `games.crossy_chicken` and `crpg_rle` resolve.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from games.crossy_chicken.env import CrossyChickenEnv  # noqa: E402
from games.crossy_chicken.seeds import EVAL_SEEDS  # noqa: E402

TERMINAL_KINDS = ("car", "water", "stuck", "timeout")


def evaluate(act_fn, seeds, env_kwargs: dict, survival_row_threshold: int = 10) -> dict:
    """Run ``act_fn`` for one episode per seed in ``seeds``; return a report.

    Args:
        act_fn: callable ``obs -> action_int`` (0..4), no batching.
        seeds: iterable of ints passed to ``env.reset(seed=...)``.
        env_kwargs: kwargs forwarded to ``CrossyChickenEnv(...)``.
        survival_row_threshold: an episode "survives" if its furthest row
            reached is >= this value.

    Returns a dict with keys: episodes, terminal_counts (dict kind->count,
    summing to episodes), mean_max_row, max_max_row, mean_reward,
    survival_rate, survival_row_threshold, max_rows (per-episode list),
    rewards (per-episode list).
    """
    seeds = list(seeds)
    env = CrossyChickenEnv(**env_kwargs)

    terminal_counts = {k: 0 for k in TERMINAL_KINDS}
    max_rows: list[int] = []
    rewards: list[float] = []
    survived = 0

    for seed in seeds:
        obs, info = env.reset(seed=seed)
        ep_reward = 0.0
        terminated = truncated = False
        while not (terminated or truncated):
            action = int(act_fn(obs))
            obs, reward, terminated, truncated, info = env.step([action])
            ep_reward += reward

        terminal_kind = info.get("terminal_kind") if terminated else "timeout"
        if terminal_kind not in terminal_counts:
            terminal_counts[terminal_kind] = 0
        terminal_counts[terminal_kind] += 1

        max_row = int(info.get("max_row", 0))
        max_rows.append(max_row)
        rewards.append(float(ep_reward))
        if max_row >= survival_row_threshold:
            survived += 1

    episodes = len(seeds)
    return {
        "episodes": episodes,
        "terminal_counts": terminal_counts,
        "mean_max_row": statistics.fmean(max_rows) if max_rows else 0.0,
        "max_max_row": max(max_rows) if max_rows else 0,
        "mean_reward": statistics.fmean(rewards) if rewards else 0.0,
        "survival_rate": (survived / episodes) if episodes else 0.0,
        "survival_row_threshold": survival_row_threshold,
        "max_rows": max_rows,
        "rewards": rewards,
    }


def _print_report(report: dict, difficulty: str, source_desc: str) -> None:
    episodes = report["episodes"]
    print("=" * 60)
    print(f"Crossy Chicken evaluation - {source_desc}")
    print(f"difficulty={difficulty}  episodes={episodes}")
    print("-" * 60)
    print("termination breakdown:")
    for kind in TERMINAL_KINDS:
        n = report["terminal_counts"].get(kind, 0)
        pct = (100.0 * n / episodes) if episodes else 0.0
        print(f"  {kind:8s} {n:5d}  ({pct:5.1f}%)")
    # Any unexpected terminal_kind (shouldn't happen) still gets reported.
    for kind, n in report["terminal_counts"].items():
        if kind not in TERMINAL_KINDS and n:
            pct = (100.0 * n / episodes) if episodes else 0.0
            print(f"  {kind:8s} {n:5d}  ({pct:5.1f}%)  [unexpected]")
    print("-" * 60)
    print(f"  mean furthest row      : {report['mean_max_row']:.2f}")
    print(f"  max  furthest row      : {report['max_max_row']}")
    print(f"  mean episode reward    : {report['mean_reward']:.3f}")
    print(f"  survival rate (row >= {report['survival_row_threshold']}) : "
          f"{report['survival_rate'] * 100:.1f}%")
    print("=" * 60)


def _make_random_act_fn(seed: int):
    rng = random.Random(seed)

    def act_fn(obs):
        return rng.randrange(5)

    return act_fn


def _make_policy_act_fn(checkpoint: str, obs_space, device: str, deterministic: bool):
    import torch

    from crpg_rle.train.policy import load_policy, obs_to_tensor

    policy = load_policy(checkpoint, obs_space, device=device)
    policy.eval()

    def act_fn(obs):
        obs_t = obs_to_tensor(obs, device)
        with torch.no_grad():
            action, _logp, _value, _entropy = policy.act(obs_t, deterministic=deterministic)
        return int(action[0, 0].item())

    return act_fn


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--checkpoint", default=None, help="trained policy checkpoint path")
    source.add_argument("--random", action="store_true", help="uniform random actions (no torch)")

    ap.add_argument("--difficulty", choices=["easy", "normal", "hard"], default="normal")
    ap.add_argument("--max-eval-seeds", "--episodes", dest="max_eval_seeds", type=int,
                    default=None, help="cap how many of EVAL_SEEDS to use (default: all)")
    ap.add_argument("--obs-size", type=int, default=84)
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--stuck-limit", type=int, default=50)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--deterministic", action=argparse.BooleanOptionalAction, default=True,
                    help="greedy actions for the trained policy (default: True)")
    ap.add_argument("--survival-row-threshold", type=int, default=10)
    ap.add_argument("--random-seed", type=int, default=0,
                    help="RNG seed for --random action sampling (run reproducibility)")
    args = ap.parse_args()

    seeds = EVAL_SEEDS
    if args.max_eval_seeds is not None:
        seeds = seeds[: args.max_eval_seeds]
    if not seeds:
        raise SystemExit("no eval seeds selected (--max-eval-seeds must be >= 1)")

    env_kwargs = dict(
        obs_size=args.obs_size,
        difficulty=args.difficulty,
        max_steps=args.max_steps,
        stuck_limit=args.stuck_limit,
    )

    if args.random:
        act_fn = _make_random_act_fn(args.random_seed)
        source_desc = "random baseline"
    else:
        probe_env = CrossyChickenEnv(**env_kwargs)
        act_fn = _make_policy_act_fn(
            args.checkpoint, probe_env.observation_space, args.device, args.deterministic,
        )
        source_desc = f"checkpoint={args.checkpoint}"

    report = evaluate(act_fn, seeds, env_kwargs, survival_row_threshold=args.survival_row_threshold)
    _print_report(report, args.difficulty, source_desc)

    assert math.isfinite(report["mean_reward"])  # sanity: report is well-formed


if __name__ == "__main__":
    main()
