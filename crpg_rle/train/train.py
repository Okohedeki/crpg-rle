"""Launch a single-agent training run and watch the loss mature.

    # fast proxy (validates the scaffolding in seconds):
    python -m crpg_rle.train.train --algo ppo  --env proxy --steps 100000 --csv runs/ppo_proxy.csv
    python -m crpg_rle.train.train --algo grpo --env proxy --steps 100000 --csv runs/grpo_proxy.csv

    # live game (slow; drives the real env through the same policy):
    python -m crpg_rle.train.train --algo ppo --env live --save "<save>.savegame" --steps 5000
"""
from __future__ import annotations

import argparse
from pathlib import Path

from crpg_rle.train.buffer import Logger
from crpg_rle.train.grpo import GRPOConfig, GRPOTrainer
from crpg_rle.train.observer import make_observer
from crpg_rle.train.ppo import PPOConfig, PPOTrainer
from crpg_rle.train.proxy_env import ProxyCRPGEnv


def make_env(args):
    if args.env == "proxy":
        return ProxyCRPGEnv(obs_size=args.obs_size, episode_len=args.episode_len,
                            sparse=args.sparse)
    # live game
    from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter
    from crpg_rle.adapters.tyranny.config import TyrannyConfig
    from crpg_rle.core.env import CRPGEnv

    cfg = TyrannyConfig(
        start_mode="act1_save", save_start=args.save,
        corpus_path=args.corpus, obs_width=args.obs_size, obs_height=args.obs_size,
        time_scale=args.time_scale, max_steps=args.episode_len,
    )
    return CRPGEnv(TyrannyAdapter(cfg))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--algo", choices=["ppo", "grpo"], default="ppo")
    ap.add_argument("--env", choices=["proxy", "live"], default="proxy")
    ap.add_argument("--steps", type=int, default=100_000)
    ap.add_argument("--rollout-steps", type=int, default=512,
                    help="PPO steps per update (use small, e.g. 64, for slow live runs)")
    ap.add_argument("--obs-size", type=int, default=84)
    ap.add_argument("--episode-len", type=int, default=64)
    ap.add_argument("--sparse", action="store_true", help="proxy: reward only on the last step")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--csv", default=None, help="write per-update metrics to this CSV")
    ap.add_argument("--status-dir", default=None,
                    help="run-observability dir: live_status.json + replay_ep<N>.jsonl "
                         "(default: <csv path minus .csv>/ when --csv is set; "
                         "watch with: python tools/dashboard.py --dir <dir>)")
    ap.add_argument("--status-every", type=int, default=1,
                    help="write live_status.json at most every N steps (time-throttled)")
    ap.add_argument("--no-observer", action="store_true",
                    help="disable the replay/status observer even when --csv is set")
    ap.add_argument("--seed", type=int, default=0)
    # live-only
    ap.add_argument("--save", default=None)
    ap.add_argument("--corpus", default=None)
    ap.add_argument("--time-scale", type=float, default=4.0)
    args = ap.parse_args()

    env = make_env(args)
    logger = Logger(args.csv)

    # Run observability (replay JSONL + live_status.json for tools/dashboard.py).
    status_dir = args.status_dir
    if status_dir is None and args.csv and not args.no_observer:
        status_dir = str(Path(args.csv).with_suffix(""))
    observer = None
    if status_dir and not args.no_observer:
        adapter = getattr(env, "adapter", None)
        key_names = adapter.action_key_list() if adapter is not None else None
        observer = make_observer(status_dir, csv_path=args.csv,
                                 key_names=key_names, every=args.status_every)
        print(f"observer: status+replay -> {status_dir}  "
              f"(dashboard: python tools/dashboard.py --dir {status_dir})")

    try:
        if args.algo == "ppo":
            cfg = PPOConfig(total_steps=args.steps, seed=args.seed,
                            rollout_steps=args.rollout_steps)
            PPOTrainer(env, cfg, device=args.device, logger=logger,
                       observer=observer).train()
        else:
            cfg = GRPOConfig(total_steps=args.steps, seed=args.seed,
                             max_episode_steps=args.episode_len)
            GRPOTrainer(env, cfg, device=args.device, logger=logger).train()
    finally:
        logger.close()
        if observer is not None:
            observer.close()
        close = getattr(env, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
