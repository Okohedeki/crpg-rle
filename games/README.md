# Games

This directory holds everything specific to an individual game the RL environment
targets. The generic learning environment itself lives in `crpg_rle/` and stays
game-agnostic — `crpg_rle/core`, `crpg_rle/train`, and `crpg_rle/puffer` contain
**zero** game-specific logic (purity is enforced by
`tests/unit/test_core_purity.py`).

## What a new game must provide

To add a game `<game>`, supply:

- **A Python adapter** under `crpg_rle/adapters/<game>/` that implements the core
  contract consumed by `crpg_rle/core/env.py` (mode detection, state schema,
  reward channels, milestone/goal logic — whatever the core env calls into).
- **Its own control bridge** — the mechanism that reads live game state and
  injects player input (for Tyranny this is a BepInEx/HarmonyX C# mod speaking to
  Python over TCP; another game may use a different transport).
- **Its own assets** under `games/<game>/` — dialogue corpora, offline generation
  pipelines, the control-bridge source, and any game-specific docs. Nothing
  derived from a user's game install is committed.

The core (`crpg_rle/core`, `crpg_rle/train`, `crpg_rle/puffer`) must remain
reusable across games; keep game-specific code in the adapter and in
`games/<game>/`. See [`../docs/RLE-ROADMAP.md`](../docs/RLE-ROADMAP.md) for the
broader multi-game roadmap.

## Reference implementation: `tyranny/`

`tyranny/` is the reference game. It contains:

- `bridge_mod/` — the BepInEx 5 / HarmonyX C# control bridge.
- `pipeline/` — the offline LLM pipeline that tags and paraphrases Act 1 dialogue
  options and freezes a runtime corpus.
- `corpora/` — the frozen dialogue corpora consumed at runtime.
- `tyranny_rle_build_brief.md` — the build brief for the Tyranny environment.

The matching Python adapter lives at `crpg_rle/adapters/tyranny/`.
