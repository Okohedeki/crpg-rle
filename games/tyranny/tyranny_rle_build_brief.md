# Build Brief: Isometric-CRPG Reinforcement Learning Environment (Tyranny Act 1, v1)

You are building a **reinforcement learning environment** (RLE), not an agent. Do not build, train, or design any policy/model. The deliverable is the environment only. Assume the reader (you) has none of the prior planning context — everything needed is in this brief.

---

## 1. Goal & thesis

Build an RL environment that exposes the **first chapter (Act 1) of the CRPG *Tyranny*** as a learning problem. The thesis being tested (later, by a separate agent) is that CRPGs are a categorically harder RL problem than Pokémon/Atari/NetHack because they unify heterogeneous decision types — semantic dialogue, one-shot character build, skill-tree progression, navigation, and real-time combat — under long-horizon, sparse consequence, with **nothing abstracted**.

Your job: make that environment real, correct, and runnable.

## 2. Generality principle (important architectural constraint)

The environment must be **general enough for isometric party-based CRPGs** (Pillars of Eternity, Divinity: Original Sin, Baldur's Gate, Tyranny), even though v1 only implements Tyranny. Enforce a two-layer split:

- **`CRPGEnv` (generic core):** Gymnasium-compatible environment defining the observation contract, the unified action space, the episode/reset lifecycle, and mode-detection + reward-routing plumbing. Contains nothing Tyranny-specific.
- **`TyrannyAdapter` (game-specific):** fills in Tyranny's engine bridge, milestone definitions, conversation data, encounter definitions, and mode-detection rules.

All Tyranny specifics live in the adapter. The core must be reusable for another isometric CRPG by writing a new adapter.

## 3. Scope

- **In scope:** Act 1 (Vendrien's Well) only. The full environment: character creation, skill tree, movement, dialogue/faction, real-time combat — all real, all simulated by the actual game.
- **Out of scope (do NOT build):** the agent/policy, network architecture, training loop, reward shaping beyond what's specified, Acts 2–3.

## 4. Action space (unified — this is a deliberate decision)

The action space is the **player input surface**, exactly what a human uses to play: cursor position, mouse click(s), party-member selection, movement orders, ability/hotbar keys, and menu/dialogue interaction. **There is one action space for the entire episode** — it does NOT switch between dialogue mode and combat mode. The agent always emits player input; the game decides what that input means given its current screen.

This is what makes the environment general across isometric CRPGs (they share this input paradigm). Implement action injection into the live game accordingly.

## 5. Observation

Because actions are raw player input, the observation must include **what a player sees** — i.e., screen pixels (or a hybrid of screen pixels + structured state extracted from the engine, if extraction is feasible). Every observation must additionally carry a **mode flag** (dialogue / combat / overworld / level-up / creation) so downstream consumers know the current context. Mode detection lives in the adapter (see §8).

Prefer a hybrid (pixels + extracted structured state such as party/enemy HP, positions, cooldowns, faction favor/wrath scalars, timer) if you can reliably read it from the engine; fall back to pixels-only if not. Expose structured fields when available; never require them for the action space to function.

## 6. Reward model (exactly two sources — do not add others)

1. **Milestone progress (sparse backbone).** Reward is granted when an Act 1 story milestone is reached (§7). This is the only reward that build, skill tree, movement, and combat earn credit through — they are all instrumental and individually unrewarded.
2. **Goal-conditioned faction favor (via the dialogue randomizer, §9).** A per-episode target faction is sampled and provided to the agent as part of the observation (goal vector). Faction favor with the *target* faction is rewarded — but this reward is only valid because the dialogue randomizer forces the agent to read option *meaning* (see §9). This is what tests "both ways" (max Disfavored OR max Scarlet Chorus on command).

Keep the two reward sources on **separate logged channels** (for later interpretability), summed for the agent. Expose a configurable relative weight between them.

Everything else — character build, skill-tree allocation, movement — is **not rewarded**. Combat is not rewarded for its own sake; it is rewarded only where an encounter is itself a milestone gate.

## 7. Act 1 milestones (the reward backbone — ~10 beats)

Implement as an ordered, event-detected milestone chain in the `TyrannyAdapter`. Each fires once when its in-game condition is detected.

0. **Character creation + Conquest resolved** — episode-start state set (build + pre-set faction standing). Milestone 0; not rewarded but gates the episode.
1. **Enter Vendrien's Well** — valley seals; Edict countdown ("Day of Swords") begins. Starts the fail timer.
2. **Deliver the Edict to the Disfavored.**
3. **Deliver the Edict to the Scarlet Chorus.**
4. **Resolve Edgering Ruins (Tarkis Demos)** — first real combat + first faction-flavored choice.
5. **Complete regional objectives unlocking the citadel assault** (e.g. arrange the meeting with Tarkis Arri / ceasefire line). *Optionally splittable into 2–3 sub-milestones for denser signal — make this configurable.*
6. **Commit to a faction path** (Disfavored / Scarlet Chorus / Rebels / neutral-Anarchist).
7. **Assault the Vendrien's Well Citadel** — climactic combat gate.
8. **Claim Ascension Hall → break the Edict of Execution.**
9. **Gain the Mountain Spire → Act 1 ends.** Success terminal.

**Terminal states:**
- **Success:** milestone 9 reached.
- **Failure:** the Day of Swords timer expires before milestone 9 → episode ends (in-game, everyone in the valley dies). Detect this and terminate with the configured failure penalty.

Make milestone granularity configurable (coarse ~10 vs. fine with milestone 5 exploded).

## 8. Mode detection + reward routing (replaces "mode arbitration")

Because the action space is unified, there is no action-space switching. Instead the adapter must:
- **Detect the current game mode** from screen state and/or extracted state (dialogue screen, combat active, overworld, level-up, creation).
- **Stamp the observation** with that mode flag.
- **Route reward triggers** by mode: milestone flags flip on their detected events; target-faction favor deltas are computed during dialogue (§9).

Keep detection logic entirely in the adapter so the core stays generic.

## 9. Dialogue randomizer (makes faction reward mean comprehension — build carefully)

Purpose: force the agent to *read a dialogue option and map it to the faction it serves*, so faction reward measures understanding rather than positional/text memorization. Three parts:

1. **Attribute-tag every Act 1 dialogue option** along faction-relevant semantic axes (e.g. ruthless↔merciful, lawful↔chaotic, honor-bound↔pragmatic, deferential↔defiant). These tags are the invariant meaning. Generate via an LLM pass over the conversation data, then spot-check. Store as a stable option→tags map.
2. **Per episode, randomize surface text + option order, preserve tags.** Paraphrase each option (different words, identical meaning) and shuffle presentation order. Slot position and exact wording must carry zero reliable signal; only meaning (the tags) does.
3. **Compute target-faction favor from tag→faction alignment.** Favor is earned when the chosen option's tags align with the target faction's preference direction. The agent observes only the paraphrased option text (never the tags, never the favor delta). Deltas and tags must NOT appear in the observation.

**Required safeguard:** paraphrasing must not drift an option's tags (a paraphrase that flips ruthless→merciful corrupts the label). Implement an automated tag-consistency check comparing each paraphrase against the original's tags; reject/regenerate on mismatch.

## 10. Engine interface (you own the design here)

Tyranny is a Unity game (Obsidian's Pillars engine). You need to decide and implement the bridge; the planning left this to you deliberately. Expected shape:

- **C# side:** BepInEx + Harmony to hook the running game — read game/combat/dialogue/faction state, detect modes and milestone events, intercept dialogue option text (for the randomizer), and inject player input (cursor/click/keys). Expose over IPC (socket) to Python.
- **Python side:** the Gymnasium `CRPGEnv`/`TyrannyAdapter` talking to that bridge; `step()` sends input, receives observation + reward + done; `reset()` restores a save-state.
- **Lifecycle concerns to solve early (highest risk):** reliable state read + input injection; fast `reset()` via combat/chapter save-states rather than full restarts; `Time.timeScale` control for faster-than-real-time stepping; disabling rendering when pixels aren't needed; running multiple game instances in parallel. Real-time combat is NOT to be paused or abstracted.
- **Assets:** do not redistribute Tyranny assets. The environment must point at the user's own installed copy.

**De-risk in this order:** (1) can you read game state and inject input on the live game at all? (2) can you detect a milestone event and a mode? (3) can you reset fast and run above 1× time-scale? Prove these on one encounter/one conversation before building the full milestone chain.

## 11. Suggested deliverable structure

```
crpg_rle/
  core/            # generic, game-agnostic
    env.py         # CRPGEnv (Gymnasium): obs contract, unified action space, lifecycle
    modes.py       # mode-flag definitions + reward-routing interfaces
    bridge.py      # abstract IPC contract to a game bridge
  adapters/
    tyranny/
      adapter.py       # TyrannyAdapter: wires core to Tyranny
      milestones.py    # the Act 1 milestone chain + fail timer (§7)
      mode_detect.py   # Tyranny mode detection (§8)
      dialogue/
        tagger.py      # attribute tagging (§9.1)
        randomizer.py  # paraphrase + shuffle + tag-consistency check (§9.2, safeguard)
        favor.py       # tag→faction favor computation (§9.3)
  bridge_mod/        # C# BepInEx/Harmony plugin (state read, input inject, IPC)
  README.md
```

Target a **Gymnasium** `Env` interface for `core/env.py`. Keep the Tyranny-specific code strictly inside `adapters/tyranny/` and `bridge_mod/`.

## 12. Definition of done (v1)

- `TyrannyAdapter` runs a full Act 1 episode driven by player-input actions, from character creation to milestone 9 (or timer-failure), on the live game.
- Observation includes screen (± structured state) + mode flag + goal vector (target faction).
- Reward emits milestone events + goal-conditioned faction favor, on separate channels, with the dialogue randomizer active and its tag-consistency safeguard enforced.
- `reset()` restores a clean Act 1 start faster than a cold game launch; time-scaling and (ideally) parallel instances work.
- Core contains zero Tyranny-specific logic.
