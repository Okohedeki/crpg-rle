"""Watch a chicken play Crossy Chicken in a real window.

Opens a pygame window (``render_mode="human"``) and drives the env with either a
trained policy checkpoint or a random policy, episode after episode, so you can
see it cross traffic and rivers in real time. Optionally records the frames to a
GIF for sharing.

    # watch a trained agent (checkpoint from `train_crossy.py --save ...`):
    python games/crossy_chicken/watch.py --checkpoint runs/crossy/policy.pt

    # watch a random agent (no torch needed):
    python games/crossy_chicken/watch.py --random --difficulty hard

    # record 3 episodes to a GIF (headless-friendly: uses rgb_array):
    python games/crossy_chicken/watch.py --checkpoint runs/crossy/policy.pt \
        --episodes 3 --gif runs/crossy/play.gif
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from games.crossy_chicken.env import CrossyChickenEnv  # noqa: E402


def _load_policy(checkpoint: str, obs_space, device: str):
    """Return a callable obs -> action int, backed by a trained policy."""
    import torch  # local: only needed for the trained path

    from crpg_rle.train.policy import load_policy, obs_to_tensor

    dev = "cuda" if device == "cuda" and torch.cuda.is_available() else "cpu"
    policy = load_policy(checkpoint, obs_space, device=dev)
    policy.eval()

    def act(obs, deterministic: bool) -> int:
        with torch.no_grad():
            a, _, _, _ = policy.act(obs_to_tensor(obs, dev), deterministic=deterministic)
        return int(a[0, 0].item())

    return act


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--checkpoint", default=None, help="trained policy .pt to watch")
    src.add_argument("--random", action="store_true", help="watch a random policy")
    ap.add_argument("--episodes", type=int, default=5)
    ap.add_argument("--difficulty", choices=["easy", "normal", "hard"], default="normal")
    ap.add_argument("--obs-size", type=int, default=84)
    ap.add_argument("--width", type=int, default=11)
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--stuck-limit", type=int, default=50)
    ap.add_argument("--cell-px", type=int, default=28)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--stochastic", action="store_true",
                    help="sample actions instead of taking the argmax (trained policy)")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--gif", default=None, help="record frames to this GIF instead of a window")
    ap.add_argument("--fps", type=int, default=8)
    args = ap.parse_args()

    recording = args.gif is not None
    render_mode = "rgb_array" if recording else "human"
    env = CrossyChickenEnv(
        width=args.width, obs_size=args.obs_size, difficulty=args.difficulty,
        max_steps=args.max_steps, stuck_limit=args.stuck_limit,
        render_mode=render_mode, cell_px=args.cell_px,
    )
    env.metadata["render_fps"] = args.fps

    if args.checkpoint:
        act = _load_policy(args.checkpoint, env.observation_space, args.device)
        deterministic = not args.stochastic
        label = f"checkpoint {args.checkpoint}"
    else:
        rng = np.random.default_rng(args.seed)
        act = lambda obs, deterministic: int(rng.integers(0, 5))  # noqa: E731
        deterministic = True
        label = "random policy"

    print(f"watching {label} — difficulty={args.difficulty}, {args.episodes} episodes"
          + (f", recording -> {args.gif}" if recording else ""))

    frames: list[np.ndarray] = []
    rows, outcomes = [], []
    try:
        for ep in range(args.episodes):
            obs, info = env.reset(seed=args.seed + ep)
            done = False
            ep_reward = 0.0
            while not done:
                if recording:
                    frames.append(env.render())
                a = act(obs, deterministic)
                obs, reward, terminated, truncated, info = env.step([a])
                ep_reward += reward
                done = terminated or truncated
                if not recording:
                    # human render + fps tick already happen inside env.step
                    if env._window is None:  # window closed by the user
                        raise KeyboardInterrupt
            if recording:
                frames.append(env.render())
            kind = info.get("terminal_kind", "timeout")
            rows.append(info.get("max_row", 0))
            outcomes.append(kind)
            print(f"  ep {ep}: furthest row {info.get('max_row', 0):3d}  "
                  f"reward {ep_reward:6.2f}  ended={kind}")
            if not recording:
                time.sleep(0.4)  # brief pause between episodes
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        env.close()

    if rows:
        print(f"\nsummary: mean furthest row {np.mean(rows):.2f}  "
              f"best {max(rows)}  outcomes={dict(_count(outcomes))}")
    if recording and frames:
        _write_gif(frames, args.gif, fps=args.fps)
        print(f"wrote {len(frames)} frames -> {args.gif}")


def _count(items):
    from collections import Counter
    return Counter(items)


def _write_gif(frames, path: str, fps: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    try:
        import imageio.v2 as imageio
        imageio.mimsave(path, frames, duration=1.0 / max(1, fps))
        return
    except Exception:
        pass
    # Fallback: Pillow (no imageio dependency).
    from PIL import Image
    imgs = [Image.fromarray(f) for f in frames]
    imgs[0].save(path, save_all=True, append_images=imgs[1:],
                 duration=int(1000 / max(1, fps)), loop=0)


if __name__ == "__main__":
    main()
