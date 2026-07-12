# Crossy Chicken

A self-contained Crossy Road / Frogger-style RL environment — a chicken crosses
an endless upward-scrolling grid of hazards. Built as a native
pygame/Gymnasium env (no game bridge), it reuses the project's generic
`crpg_rle.core` observation/action contract and the shared `crpg_rle.train`
PPO/GRPO trainers, policy, observer, and live dashboard unchanged. It exists to
validate the full RL stack on an easy, fast, deterministic game.

## The environment (`env.py`)

- **Action** `MultiDiscrete([5])` — 0 noop, 1 up, 2 down, 3 left, 4 right.
- **Observation** the standard `crpg_rle.core.spaces` Dict
  `{pixels HxWx3 uint8, state float32[28], mode Discrete, goal float32[1]}`.
  Pixels are a block render centered on the chicken; state is compact
  hand-features (chicken column, timing, and per-visible-lane
  kind/velocity/nearest-danger/cell-safe features).
- **Hazards**
  - **Grass** — safe.
  - **Road** — cars sweep left/right; a car cell kills (`terminal_kind="car"`).
  - **River** — logs sweep left/right; *water* kills — the chicken survives only
    while standing on a moving log (`terminal_kind="water"`). Logs slide each
    step, so sitting still on a river drowns; you must time the hops.
- **Reward** (non-farmable, progress-toward-goal): **+1 only** on reaching a
  *new* furthest row, **-0.01** per step, **-1** on death (car / water / standing
  still too long → `terminal_kind="stuck"`). Oscillating or backtracking earns
  nothing; dying on a would-be-new row awards **no** progress (the danger check
  precedes the progress award). Channels: `{progress, death, step}`.
- **Difficulty presets** `easy` / `normal` / `hard` tune the grass/road/river mix
  and top speed. Any explicit kwarg (`safe_prob`, `river_frac`, `max_speed`)
  overrides its preset value.
- **Rendering** `render_mode="human"` opens a pygame window; `"rgb_array"`
  returns an upscaled frame (for GIFs / headless).

## Train

```bash
# standalone trainer (writes CSV + live_status.json + replay JSONL + a checkpoint):
python games/crossy_chicken/train_crossy.py --algo ppo --steps 400000 \
    --difficulty normal --csv runs/crossy/run.csv --save runs/crossy/policy.pt

# or via the shared CLI:
python -m crpg_rle.train.train --env crossy --algo ppo --steps 400000 \
    --difficulty normal --csv runs/crossy/run.csv

# watch the loss/metrics live in a browser:
python tools/dashboard.py --dir runs/crossy/run
```

## Watch it play

```bash
# a real pygame window driven by a trained checkpoint:
python games/crossy_chicken/watch.py --checkpoint runs/crossy/policy.pt --episodes 5

# a random agent (no torch needed), harder difficulty:
python games/crossy_chicken/watch.py --random --difficulty hard

# record a shareable GIF (headless, no window):
python games/crossy_chicken/watch.py --checkpoint runs/crossy/policy.pt \
    --episodes 3 --gif runs/crossy/play.gif
```

## Evaluate & calibrate (held-out, reproducible)

```bash
# evaluate a policy on the held-out EVAL_SEEDS (never trained on):
python games/crossy_chicken/evaluate.py --checkpoint runs/crossy/policy.pt

# difficulty-ladder calibration with reference baselines:
python games/crossy_chicken/calibrate.py --episodes 20 --policy greedy_up
```

`seeds.py` defines disjoint `TRAIN_SEEDS` / `EVAL_SEEDS` so evaluation never
reports on seeds the agent trained on. Tests live in
`tests/unit/test_crossy_chicken.py` (env + render), plus adversarial
reward-hacking, held-out-eval, and calibration suites.
