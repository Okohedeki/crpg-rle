"""Launch a single-agent training run and watch the loss mature.

    # fast proxy (validates the scaffolding in seconds):
    python -m crpg_rle.train.train --algo ppo  --env proxy --steps 100000 --csv runs/ppo_proxy.csv
    python -m crpg_rle.train.train --algo grpo --env proxy --steps 100000 --csv runs/grpo_proxy.csv

    # live game (slow; drives the real env through the same policy):
    python -m crpg_rle.train.train --algo ppo --env live --save "<save>.savegame" --steps 5000
"""
from __future__ import annotations

import argparse

from crpg_rle.train.buffer import Logger
from crpg_rle.train.grpo import GRPOConfig, GRPOTrainer
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
    ap.add_argument("--obs-size", type=int, default=84)
    ap.add_argument("--episode-len", type=int, default=64)
    ap.add_argument("--sparse", action="store_true", help="proxy: reward only on the last step")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--csv", default=None, help="write per-update metrics to this CSV")
    ap.add_argument("--seed", type=int, default=0)
    # live-only
    ap.add_argument("--save", default=None)
    ap.add_argument("--corpus", default=None)
    ap.add_argument("--time-scale", type=float, default=4.0)
    args = ap.parse_args()

    env = make_env(args)
    logger = Logger(args.csv)
    try:
        if args.algo == "ppo":
            cfg = PPOConfig(total_steps=args.steps, seed=args.seed)
            PPOTrainer(env, cfg, device=args.device, logger=logger).train()
        else:
            cfg = GRPOConfig(total_steps=args.steps, seed=args.seed,
                             max_episode_steps=args.episode_len)
            GRPOTrainer(env, cfg, device=args.device, logger=logger).train()
    finally:
        logger.close()
        close = getattr(env, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
