# Definition of Done — build brief §12

Each v1 done-criterion, its status, and the evidence.

| # | Criterion (brief §12) | Status | Evidence |
|---|---|---|---|
| 1 | `TyrannyAdapter` runs a full Act 1 episode driven by player-input actions, from creation to milestone 9 (or timer-failure), on the live game | Env lifecycle proven end-to-end; a *policy* is out of scope (we build the env, not the agent) | `CRPGEnv` reset→step verified live (non-black pixels, reward channels, combat entered by random actions). Creation-start reset reaches character creation (LifePath) in ~7s; save-start reset in ~5s. Milestone chain fires on detected events (unit-tested + live event stream). Reaching milestone 9 requires a trained agent. |
| 2 | Observation includes screen (± structured state) + mode flag + goal vector | Done | `crpg_rle/core/spaces.py` builds `Dict{pixels, state, mode, goal}`; live capture non-black; `test_spaces.py`, `test_state_schema.py`. |
| 3 | Reward emits milestone events + goal-conditioned faction favor on separate channels, dialogue randomizer active with tag-consistency safeguard | Done | `reward.py` (channels), `milestones.py`, `favor.py` (dialogue-only, target-faction); randomizer live-verified (paraphrase swap across seeds); safeguard = `verify_tags.tags_consistent` (blind re-tag). `test_milestones.py`, `test_favor.py`, `test_randomizer.py`. |
| 4 | `reset()` restores a clean Act 1 start faster than a cold launch; time-scaling and (ideally) parallel instances work | Done (single-instance); parallel parked | Save-load reset median **4.7s** vs ~2–3 min cold launch; new-game reset ~7s; **4× time-scale** confirmed. Multi-instance is task #9 (design in place: per-instance ports/save dirs). |
| 5 | Core contains zero Tyranny-specific logic | Done | `tests/unit/test_core_purity.py` (grep + import-isolation). |

## Reward model conformance (brief §6)

- Exactly two sources: milestone (sparse backbone) + goal-conditioned target-faction favor. Separate logged channels, summed with configurable weights (`RewardChannels`, `info["reward_channels"]`).
- Faction favor counted only in dialogue mode (prevents non-dialogue leakage).
- Everything else (build, skill tree, movement) unrewarded; combat only where a milestone gates it.

## Dialogue randomizer conformance (brief §9)

- Attribute-tagged options along 4 semantic axes (`games/tyranny/pipeline/tag_options.py`).
- Per-episode paraphrase + shuffle applied by the mod pre-render, invisible to the agent (`DialogueInterceptor` + seeded `SplitMix64`; C#↔Python RNG parity live-verified).
- Favor from tag→faction alignment matrix in the corpus; agent sees only paraphrased text (in pixels), never tags/deltas/originals — the structured observation carries no dialogue text at all.
- Safeguard: blind re-tag consistency check rejects paraphrases that drift a tag (`verify_tags.py`).

## Engine interface (brief §10) — de-risk order proven

1. **State read + input injection on the live game** — ✅ (party movement via right-click, dialogue selection via number key, live state stream).
2. **Detect a milestone event and a mode** — ✅ (quest/reputation/global-var/area/combat event stream; mode detection).
3. **Reset fast and run above 1× time-scale** — ✅ (reset ~5s, 4× time-scale).

## Character creation — status (investigated in depth)

The env correctly **reaches** creation (`new_game` → LifePath) and exposes the
wizard's `stage`/`ready` in the observation. Crucially, the creation stages
**gate on real choices**: `PressOkay` (the true "Next") will not advance past
Conquest until choices are made — this is correct RL behavior (the agent must
make the Conquest/class/attribute/**skill** choices; that's the "one-shot build"
part of the thesis). Scaffolding shipped: creation nav ops
(`advance`/`regress`/`begin_conquest`/`quick_start`/`set_name`/`complete`), a
`quick_start` template that satisfies the readiness gate, a telemetry-safety
patch (creation completion otherwise NREs in `TelemetryManager`), and
`diag_creation_ui` (skill-widget screen positions + skill points).

**Not yet closed:** scripted completion (`quick_start`) reaches `ready=True` but
does not cleanly transition to gameplay — bypassing the stage-by-stage flow
leaves the character/player infrastructure half-initialized for
`CloseCharacterCreationOnComplete`. And the skills selector only appears on the
Conquest path (a template pre-fills the build), so verifying an agent's
skill-point click requires full Conquest play. **For v1, `start_mode="act1_save"`
is the reliable reset;** full agent-driven creation completion (incl. the skills
selector) is tracked remaining work (task #12).

## RLE finishing pass (2026-07-10) — metrics, watchable gameplay, real-UI menus, console lockdown

Governing principle: infrastructure ≠ gameplay. Infrastructure (start/load,
death recovery, menus for the predefined build) is scripted; the agent can never
reach the console. Prefer the real in-game UI, console only as a locked-down
fallback. Five workstreams landed, offline-verified (105 unit tests, mod builds,
C shim compiles); items marked ⚠ need a live playtest to confirm.

- **Console + quit lockdown** — `Hooks/LockdownGuards.cs` refuses
  `LoadMainMenu`/`Application.Quit`/`SDK.CommandLine.RunCommand`/`UICommandLine`/
  `UIInGameMenu.Show` while the agent is active (input injecting, no config window
  open); `CheatsEnabled` forced off during play; env keeps a `BridgeBypass` for
  its own menu/shutdown. The agent already had no console key in `ACTION_KEYS`;
  this makes it airtight and stops the historical Esc-quit bridge kill.
- **Learning metrics** — env-server wire proto bumped to v2: a fixed float
  trailer carries per-episode `r_milestone`/`r_faction_favor`/`milestones_reached`
  + terminal one-hot + mode fractions into the C `Log`/`my_log` → PufferLib native
  logging. Core stays game-agnostic (adapter names/computes the vector).
- **Config-driver + intercept hook** — `CRPGEnv.step` calls the adapter's optional
  `intercept` between agent actions; `ConfigDriver` applies the predefined config
  at scripted triggers. `validate_build_spec` extended (specialization/party/
  levelups/equipment/consumables/spells/formation/talents).
- **Level-up + skills via the real UI** — level-up reuses the creation UI
  (`OpenCharacterCreation`); `LevelUpChoices.cs` clones `CreationChoices` +
  `levelup_begin/options/choose/skill/advance`; `StateReader` emits `level_up`.
  ⚠ the level-up *finalize* handler (NGUI binding) needs live confirmation.
- **Death recovery** — `revive` op (`UIDeathManager.OnRespawnClicked` / direct
  heal) + `death_mode` {terminal, revive(default), checkpoint}; a wipe is
  recovered by the intercept before the terminal check (success + edict-timer stay
  terminal), with a one-shot penalty on a `recovery` reward channel. ⚠ confirm
  revive-in-place vs checkpoint feels right in a real Edgering wipe.

Live-playtest items still open: level-up finalize handler; `OpenCharacterCreation`
mid-area for player+companions; skill setter committing off the main flow;
`edict_days_remaining` data source (left unpopulated — timer stays inert, as
before). Redeploy `bin/Release/net35/CRPGBridge.dll` to the BepInEx plugins folder
before live runs.

## Deferred (tracked as follow-ups)

- Multi-instance (task #9) — v1 is single-instance per user decision.
- WSL2/Linux `_C.so` build + PuffeRL smoke run (task #11) — needs a CUDA Linux host; shim + protocol done and unit-tested.
- Click-to-select dialogue options (task #10) — number-key selection works and is the agent's interface.
- Full corpus generation — pipeline built; needs `ANTHROPIC_API_KEY` to tag/paraphrase all 1203 options (demo corpus proves the mechanism).
- Milestone detectors have playtest-TODO refinements (camp-1 vs camp-2 distinction, faction-commit var) noted in `milestones.py`.
