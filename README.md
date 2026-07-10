# crpg-rle

A reinforcement learning **environment** exposing Act 1 of the CRPG *Tyranny* (Obsidian, 2016) as a learning problem — character creation, dialogue, faction politics, exploration, and real-time combat, all driven through raw player input on the live game. Nothing abstracted.

This repo contains the environment only (no agent, no training loop):

- **`crpg_rle/core/`** — generic, game-agnostic Gymnasium environment for isometric party-based CRPGs: unified player-input action space, hybrid pixel + structured observations, mode detection and reward-routing plumbing.
- **`crpg_rle/adapters/tyranny/`** — everything Tyranny-specific: the Act 1 milestone chain, mode detection, and the dialogue randomizer (per-episode paraphrase + shuffle of dialogue options so faction reward measures comprehension, not memorization).
- **`bridge_mod/`** — a BepInEx 5 / HarmonyX plugin that reads game state, injects player input, intercepts dialogue text, and exposes it all to Python over TCP.
- **`puffer_fork/`** — PufferLib 4.0 fork with an `ocean/tyranny` C shim connecting the trainer to the Python env server.
- **`pipeline/`** — offline LLM pipeline that tags and paraphrases Act 1 dialogue options, with an automated tag-consistency safeguard.

**You need your own installed copy of Tyranny.** No game assets are included or ever committed; the environment points at your install.

## Status

Early development. See `tyranny_rle_build_brief.md` for the full specification.
