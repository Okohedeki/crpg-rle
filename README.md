# crpg-rle

A reinforcement learning **environment** exposing Act 1 of the CRPG *Tyranny*
(Obsidian, 2016) as a learning problem — character creation, dialogue, faction
politics, exploration, and real-time combat, all driven through raw player input
on the live game. Nothing is abstracted; the real game is the simulator.

This repo is the environment only (no agent, no training loop). A separate agent
is meant to be trained against it later.

## Architecture

Two layers (build brief §2), so the core is reusable for other isometric CRPGs:

- **`crpg_rle/core/`** — generic, game-agnostic Gymnasium env: the unified
  player-input action space, hybrid pixel + structured observation, mode
  detection plumbing, reward channels, bridge/launcher/capture. Contains zero
  Tyranny logic (enforced by `tests/unit/test_core_purity.py`).
- **`crpg_rle/adapters/tyranny/`** — everything Tyranny-specific: the Act 1
  milestone chain, mode detection, state schema, goal-conditioned favor reward,
  and the dialogue randomizer runtime.
- **`bridge_mod/`** — a BepInEx 5 / HarmonyX C# plugin that reads game state,
  injects virtual player input, intercepts dialogue text, controls time-scale,
  and drives save/new-game resets, exposing it all to Python over TCP.
- **`pipeline/`** — offline LLM pipeline that tags and paraphrases Act 1 dialogue
  options with an automated tag-consistency safeguard, freezing a corpus.
- **`puffer_fork/ocean/tyranny/`** + **`crpg_rle/core/env_server.py`** —
  PufferLib 4.0 integration: a C shim that speaks to a Python env-server hosting
  the live env (the trainer runs on Linux/WSL2; see that dir's README).

## What the agent sees and does

- **Action** — one flat `MultiDiscrete([64, 36, 4, 13])` for the whole episode
  (never mode-switched): cursor-x bin, cursor-y bin, mouse button, key. Decoded
  into real input events. Dialogue options are selected with number keys.
- **Observation** — `Dict{pixels (720×720p-class, text legible), state (party/
  enemy HP+positions, favor/wrath per faction, timers), mode flag, goal (target
  faction one-hot)}`.
- **Reward** — two logged channels summed with configurable weights: sparse
  **milestone** progress (the Act 1 beat chain) and goal-conditioned **faction
  favor** with the episode's target faction, counted only during dialogue so it
  measures reading option *meaning* (the randomizer paraphrases + shuffles
  options per episode; the agent never sees originals, tags, or deltas).

## Requirements

- Your own installed copy of **Tyranny** (Steam or GOG). No game assets are
  included or committed; the environment points at your install.
- Windows 10/11 (the game host). Python 3.11. .NET SDK (to build the mod).
- For PufferLib 4.0 training: a Linux/WSL2 host with CUDA (the trainer only).

## Setup

1. **Install the bridge mod** — see `bridge_mod/INSTALL.md` (BepInEx 5.4.22, two
   required `BepInEx.cfg` edits, build + copy the plugin).
2. **Install the Python package**: `pip install -e ".[dev]"`.
3. **(Optional) build the dialogue corpus**: `python pipeline/extract_options.py`
   then, with `ANTHROPIC_API_KEY` set, `tag_options.py` → `paraphrase.py` →
   `verify_tags.py` → `build_corpus.py`. A small demo corpus
   (`corpora/act1_demo/`) is included to exercise the randomizer without an API
   key (`python pipeline/make_demo_corpus.py`).
4. **Run the env**:
   ```python
   from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter
   from crpg_rle.adapters.tyranny.config import TyrannyConfig
   from crpg_rle.core.env import CRPGEnv

   cfg = TyrannyConfig(start_mode="act1_save", save_start="<your_save>.savegame",
                       corpus_path="corpora/act1_demo/corpus.json")
   env = CRPGEnv(TyrannyAdapter(cfg))
   obs, info = env.reset(seed=0)
   obs, reward, done, trunc, info = env.step(env.action_space.sample())
   ```

## Status / definition of done

See `docs/DOD.md` for the build-brief §12 checklist mapped to evidence. Verified
on the live game: BepInEx loads on Unity 5.4.4p4; Python reads live state and
injects input (party movement + dialogue selection); mode + engine-event
detection; save-load reset in ~5s and 4× time-scale; the full `CRPGEnv` runs
reset→step end-to-end with non-black pixels and populated reward channels; the
dialogue randomizer swaps + shuffles options live with C#↔Python RNG parity; the
PufferLib 4.0 wire protocol round-trips. v1 is single-instance (multi-instance
and the WSL2 trainer build are tracked as follow-ups).
