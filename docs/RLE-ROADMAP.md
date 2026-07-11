# RLE Roadmap — from "game hooked to gym" to a research-grade CRPG environment

User-set direction (2026-07-10). Eight pillars, each mapped to what exists today
and the concrete next build. Overriding instruction: **make it easier to see and
understand what's going on** (observability first).

## 1. Fast, reliable save-state reset and reproducibility
**Have:** save-load reset ~5s; seeded episode RNG with C#↔Python SplitMix64
parity; one-shot frozen build verified across save/reload; boot-retry +
crash-relaunch recovery.
**Build:** fix the mid-run reload plugin-sweep (reload from gameplay kills the
BepInEx plugin — reset via a menu round-trip or make the plugin survive);
a **save-bank** (N verified start states, sampled per episode); a **state
fingerprint** op (hash of quests+globals+party) asserted after every reset so
reproducibility is *checked*, not assumed.

## 2. Structured action API alongside GUI control
**Have:** raw player-input action space (cursor/click/keys); structured ops
already exist for creation (`creation_options/choose`), level-up
(`levelup_*`), dialogue (number keys), revive/recenter.
**Build:** a parallel **semantic action mode** — `list_interactables` (from the
engine's Tab-highlight set: NPCs, doors, containers with world/screen pos) +
`interact {id}`, `move_to {x,z}`, `dialogue_choose {i}`, `attack {target}`.
Same env, two action interfaces (GUI for the pixels thesis, structured for
agent/LLM research). The CreationChoices pattern is the template.

## 3. Instrumentation of everything
**Have:** quests (started/advanced/completed/end-state events), reputation
(favor/wrath per faction), party HP/pos/selected/dead, combat flag,
conversation file/node/options, level_up, player_dead, player_on_screen, area.
**Build:** **inventory** (items + equipped), **companion relationships**
(affinity/loyalty), **dialogue flags / global variables snapshot** (bulk
`get_globals` matching a prefix), **enemy positions/HP in combat**, **edict
timer** (world clock vs Day of Swords — today unpopulated), NPC alive/dead
registry (needed for pillar 6).

## 4. Auto-generated task distributions (not a fixed benchmark)
**Have:** per-episode goal-faction sampling + dialogue paraphrase/shuffle.
**Build:** a **task sampler**: per episode draw (start save from bank, target
objective, constraints) — e.g. "reach area X", "raise favor F to rank R",
"complete quest Q without party deaths", "gold ≥ G". Emit task spec into the
goal vector/obs; reward from the task's verifier (pillar 5).

## 5. Verifiers that check state transitions
**Have:** milestone detectors are event/transition-based; build verification
snapshots + asserts; blind re-tag corpus safeguard.
**Build:** a **Verifier interface** per task type: precondition snapshot →
postcondition check on instrumented state (quest DB, globals, inventory,
NPC-alive set), never on text. Verifiers double as reward emitters for
pillar-4 tasks.

## 6. Adversarial reward-hacking tests
**Have (found live this week):** pause-farm exploit found+fixed via channel
logging; edge-triggered bonuses; dedup-per-episode novelty; favor counted only
in dialogue; console lockdown.
**Build:** an **adversarial suite**: scripted trajectories that complete the
nominal objective while (a) killing quest-critical NPCs, (b) corrupting future
quest state (wrong globals), (c) farming any shaping channel — each must score
LOW. Run in CI against the reward stack using recorded event streams (no live
game needed).

## 7. Difficulty calibration
**Have:** per-episode metrics (milestones reached, terminal kind, mode
occupancy, per-channel reward) already wired to trainer logging + CSV.
**Build:** per-task success-rate aggregation → difficulty tags → curriculum
sampling (task sampler weights by measured success band). Trajectory store
(actions+events per episode) for analysis.

## 8. Train / hidden-eval split
**Build:** split on three axes — **seeds** (held-out eval seed range),
**paraphrase variants** (corpus split: train variants vs held-out variants per
option), **tasks/saves** (held-out start states + objective combos). Eval
config refuses train-set members; report both scores.

## Observability ("see and understand what's going on") — cross-cutting, do first
- **Live dashboard**: one screen showing current mode, quest states, party HP,
  reputation, recent events, per-channel reward accumulation, action histogram,
  and the last N env interventions (revive/recenter/unpause) — fed from the
  existing observe stream + run CSV.
- **Intervention log**: every scripted-infrastructure action the env takes is
  logged with step + reason (today they're silent warnings).
- **Episode replay dump**: JSONL of (step, action, mode, events, channels) per
  episode for post-hoc "why did it do that" analysis.

## Suggested order
Observability dashboard+logs → 3 (instrumentation gaps) → 1 (reset hardening +
save-bank) → 2 (semantic actions) → 5 (verifiers) → 4 (task sampler) → 6
(adversarial suite) → 8 (splits) → 7 (calibration loop).
