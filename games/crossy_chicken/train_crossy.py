"""Train a policy on CrossyChickenEnv and watch forward progress rise.

Standalone CLI (does NOT touch crpg_rle.train.train). Builds the env directly,
wires the shared PPO/GRPO trainers and the live-dashboard observer, and writes a
per-update CSV plus live_status.json + replay JSONL under the run directory.

    # PPO (default) — trains fast, thousands of steps/sec:
    python games/crossy_chicken/train_crossy.py --algo ppo  --steps 200000 --csv runs/crossy/run.csv
    # GRPO:
    python games/crossy_chicken/train_crossy.py --algo grpo --steps 200000 --csv runs/crossy/grpo.csv

    # Watch it live (in another terminal), pointing at the run dir (csv path minus .csv):
    python tools/dashboard.py --dir runs/crossy/run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python games/crossy_chicken/train_crossy.py` from the repo root: the
# repo root must be importable so `games.crossy_chicken` and `crpg_rle` resolve.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from games.crossy_chicken.env import CrossyChickenEnv  # noqa: E402

from crpg_rle.train.buffer import Logger  # noqa: E402
from crpg_rle.train.grpo import GRPOConfig, GRPOTrainer  # noqa: E402
from crpg_rle.train.observer import make_observer  # noqa: E402
from crpg_rle.train.ppo import PPOConfig, PPOTrainer  # noqa: E402


def _device(name: str) -> str:
    if name == "cuda":
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"
    return name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--algo", choices=["ppo", "grpo"], default="ppo")
    ap.add_argument("--steps", type=int, default=200_000)
    ap.add_argument("--rollout-steps", type=int, default=512,
                    help="PPO steps per update")
    ap.add_argument("--obs-size", type=int, default=84)
    ap.add_argument("--width", type=int, default=11)
    ap.add_argument("--max-steps", type=int, default=500,
                    help="episode step budget before truncation")
    ap.add_argument("--stuck-limit", type=int, default=50,
                    help="steps without new furthest row before death")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--csv", default=None, help="write per-update metrics to this CSV")
    ap.add_argument("--status-dir", default=None,
                    help="observability dir (default: <csv path minus .csv>/); "
                         "watch with python tools/dashboard.py --dir <dir>")
    ap.add_argument("--status-every", type=int, default=1)
    ap.add_argument("--no-observer", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--difficulty", choices=["easy", "normal", "hard"], default="normal")
    ap.add_argument("--save", default=None, help="checkpoint path (e.g. runs/crossy/policy.pt)")
    ap.add_argument("--save-every", type=int, default=0,
                    help="save every N updates (0 = only at the end)")
    args = ap.parse_args()

    env = CrossyChickenEnv(
        width=args.width, obs_size=args.obs_size,
        max_steps=args.max_steps, stuck_limit=args.stuck_limit,
        difficulty=args.difficulty,
    )
    logger = Logger(args.csv)

    status_dir = args.status_dir
    if status_dir is None and args.csv and not args.no_observer:
        status_dir = str(Path(args.csv).with_suffix(""))
    observer = None
    if status_dir and not args.no_observer:
        observer = make_observer(status_dir, csv_path=args.csv, every=args.status_every)
        print(f"observer: status+replay -> {status_dir}  "
              f"(dashboard: python tools/dashboard.py --dir {status_dir})")

    device = _device(args.device)
    print(f"device={device} algo={args.algo} steps={args.steps}")

    try:
        if args.algo == "ppo":
            cfg = PPOConfig(total_steps=args.steps, seed=args.seed,
                            rollout_steps=args.rollout_steps,
                            save_path=args.save, save_every=args.save_every)
            PPOTrainer(env, cfg, device=device, logger=logger,
                       observer=observer).train()
        else:
            # GRPOTrainer takes no observer hook; the live dashboard is a PPO
            # feature (deferred: add an observer arg to GRPOTrainer upstream).
            cfg = GRPOConfig(total_steps=args.steps, seed=args.seed,
                             max_episode_steps=args.max_steps)
            GRPOTrainer(env, cfg, device=device, logger=logger).train()
    finally:
        logger.close()
        if observer is not None:
            observer.close()


if __name__ == "__main__":
    main()
