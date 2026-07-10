"""Multi-episode RL rollout against the live game — exercises CRPGEnv the way a
trainer would (varying seeds, full reward routing, per-episode metrics) and
reports whether episodes genuinely vary or are replayed identically.

This is NOT a pass/fail smoke test: it drives several episodes with a random
policy and prints, per episode, the sampled goal faction, the per-channel reward
totals, milestones fired, the mode histogram, and the terminal kind — then a
cross-episode variation summary so you can see the environment is stochastic.

    python tools/rl_rollout.py --episodes 3 --steps 250 --time-scale 4
"""
from __future__ import annotations

import argparse
import collections
import os

import numpy as np

from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter
from crpg_rle.adapters.tyranny.config import TyrannyConfig
from crpg_rle.core.env import CRPGEnv
from crpg_rle.core.modes import Mode

DEFAULT_SAVE = "RL1 d3b051952d6742c3b0d46e413aa0e841 .savegame"


def rollout(env: CRPGEnv, seed: int, max_steps: int, rng: np.random.Generator) -> dict:
    obs, info = env.reset(seed=seed)
    target = info["target_faction"]
    channel_totals: dict[str, float] = collections.defaultdict(float)
    modes = collections.Counter()
    favor_events = 0
    signature = []  # coarse per-step world signature, to compare trajectories

    steps = 0
    terminal_kind = None
    for _ in range(max_steps):
        action = env.action_space.sample()  # np-random policy (seeded per call below)
        obs, reward, done, trunc, info = env.step(action)
        steps += 1
        modes[Mode(info["mode"]).name] += 1
        for ch, val in info.get("reward_channels", {}).items():
            channel_totals[ch] += val
            if ch == "faction_favor" and abs(val) > 0:
                favor_events += 1
        # world signature: total party HP + in-combat flag, from the packed state
        st = obs["state"]
        signature.append(round(float(st.sum()), 1))
        if done or trunc:
            terminal_kind = info.get("terminal_kind")
            break

    return {
        "seed": seed,
        "target_faction": target,
        "steps": steps,
        "terminal_kind": terminal_kind,
        "channel_totals": dict(channel_totals),
        "episode_reward_channels": info.get("episode_reward_channels", {}),
        "modes": dict(modes),
        "favor_events": favor_events,
        "signature_head": signature[:10],
        "signature_hash": hash(tuple(signature)),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--steps", type=int, default=250)
    ap.add_argument("--time-scale", type=float, default=4.0)
    ap.add_argument("--save", default=os.environ.get("CRPG_TEST_SAVE", DEFAULT_SAVE))
    ap.add_argument("--death-mode", default="revive")
    ap.add_argument("--no-corpus", action="store_true",
                    help="disable the dialogue randomizer (isolate the corpus-arm)")
    args = ap.parse_args()

    corpus = os.path.join(os.path.dirname(__file__), "..", "corpora", "act1_demo", "corpus.json")
    cfg = TyrannyConfig(
        start_mode="act1_save",
        save_start=args.save,
        corpus_path=None if args.no_corpus else os.path.abspath(corpus),
        dialogue_randomizer=not args.no_corpus,
        obs_width=1280,
        obs_height=720,
        time_scale=args.time_scale,
        max_steps=args.steps,
        death_mode=args.death_mode,
    )
    env = CRPGEnv(TyrannyAdapter(cfg))
    results = []
    try:
        for i in range(args.episodes):
            seed = 1000 + i
            env.action_space.seed(seed)  # reproducible policy per episode
            r = rollout(env, seed=seed, max_steps=args.steps, rng=np.random.default_rng(seed))
            results.append(r)
            print(f"\n=== episode {i} (seed {seed}) ===")
            print(f"  target_faction : {r['target_faction']}")
            print(f"  steps/terminal : {r['steps']} / {r['terminal_kind']}")
            print(f"  reward channels: {({k: round(v,3) for k,v in r['episode_reward_channels'].items()})}")
            print(f"  favor-firing steps: {r['favor_events']}")
            print(f"  mode histogram : {r['modes']}")
    finally:
        env.close()

    print("\n===== cross-episode variation =====")
    factions = [r["target_faction"] for r in results]
    hashes = [r["signature_hash"] for r in results]
    print(f"  target factions : {factions}  (distinct: {len(set(factions))})")
    print(f"  trajectory hashes distinct: {len(set(hashes))}/{len(hashes)}")
    print(f"  reward fired (any channel non-zero): "
          f"{[any(abs(v)>0 for v in r['episode_reward_channels'].values()) for r in results]}")
    if len(set(hashes)) == 1:
        print("  WARNING: every episode produced an identical trajectory — env is a replay!")
    else:
        print("  OK: episodes differ — environment is stochastic, not a replay.")


if __name__ == "__main__":
    main()
