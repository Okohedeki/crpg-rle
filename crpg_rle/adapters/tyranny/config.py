"""Tyranny adapter configuration and Act 1 constants."""
from __future__ import annotations

from dataclasses import dataclass, field

# Factions surfaced in observations/rewards (must match the C# StateReader set).
FACTIONS: list[str] = [
    "ScarletChorus",
    "Disfavored",
    "SK_Tunon",
    "SK_GravenAshe",
    "SK_VoicesSoldak",
    "SK_BledenMark",
]

# Factions eligible as a per-episode goal target (§6 goal-conditioned favor).
TARGET_FACTIONS: list[str] = ["Disfavored", "ScarletChorus"]

# Act 1 quest filenames (without extension) used by the milestone detectors.
QUEST_EDICT = "08_qst_vendrienswell_edict_quest"
QUEST_EDGERING = "08_qst_edgeringruins"          # matches starting/return by substring
QUEST_ASSAULT = "08_qst_vendrienswell_assault_quest"
QUEST_REGION = "08_qst_vendrienswell_region_quest"
QUEST_REBEL = "08_qst_vendrienswell_rebel_quest"
QUEST_ECHOCALL = "08_qst_echocallcrossing_main_quest"
QUEST_MATANI = "08_qst_controlmataniriver_quest"
QUEST_TRIPNETTLE = "08_qst_tripnettlewilderness_main_quest"


@dataclass
class TyrannyConfig:
    """All knobs for a Tyranny episode. Paths point at the user's own install."""

    game_dir: str = r"C:\Program Files (x86)\Steam\steamapps\common\Tyranny"
    exe_path: str = r"C:\Program Files (x86)\Steam\steamapps\common\Tyranny\Tyranny.exe"
    port_base: int = 5555
    instance_id: int = 0

    obs_width: int = 1280
    obs_height: int = 720
    frame_skip: int = 6
    time_scale: float = 1.0

    milestone_granularity: str = "coarse"   # "coarse" | "fine"
    reward_weights: dict[str, float] = field(
        default_factory=lambda: {
            "milestone": 1.0, "faction_favor": 1.0, "death": 1.0,
            "explore": 1.0, "pause": 1.0,
        }
    )

    # Exploration shaping (count-based novelty — drives movement toward new ground
    # without being gameable by jittering, since each cell is rewarded once/episode).
    explore_bonus: float = 0.1
    explore_cell_size: float = 3.0        # world units per novelty cell

    # Pause shaping: a small cost for toggling pause (discourages the pause loop),
    # and a bonus for issuing a command while paused in combat (tactical pause).
    pause_penalty: float = 0.02
    tactical_pause_bonus: float = 0.25
    # Minimum real seconds between executed pause toggles (breaks the pause loop
    # mechanically). The agent may still choose pause; extra presses are dropped.
    pause_cooldown_seconds: float = 5.0

    edict_fail_days: float = 0.0

    # Party-wipe handling (build brief: death recovery is scripted infrastructure).
    #   "terminal"   — a wipe ends the episode as a failure (benchmark semantics).
    #   "revive"     — heal the party in place and continue (watchable curriculum).
    #   "checkpoint" — reload the run's working save and continue.
    # Default "revive": self-contained (no save plumbing) and directly fixes the
    # "exit at first combat" symptom so gameplay is watchable past Edgering.
    death_mode: str = "revive"
    # Negative reward charged once each time the main character dies, on a
    # dedicated "death" channel. Trains toward a deathless-MC run: with
    # death_mode="revive" the MC is revived and the episode continues, but every
    # death costs this much, so the agent learns to keep the MC alive.
    death_penalty: float = -10.0

    # Episode start. The character build is predefined infrastructure, not part
    # of the agent's problem: episodes reset by loading a pre-made Act-1-start
    # save (~5s, proven). "creation" reaches the creation wizard for tooling /
    # save-bank generation only. save_start names a .savegame in the game's
    # save dir; a future save-bank manifest allows seeded sampling of builds.
    start_mode: str = "act1_save"
    save_start: str | None = "RL1 d3b051952d6742c3b0d46e413aa0e841 .savegame"

    max_party: int = 6
    max_steps: int = 20000

    # Real-time seconds to wait after a save's loading flag clears before driving
    # the game. The old engine can crash if stepped before the scene finishes
    # initializing (AI/physics) even though `loading` already went false.
    load_settle_seconds: float = 2.5

    # Dialogue randomizer (§9). When corpus_path is set and dialogue_randomizer
    # is True, the mod swaps option text + shuffles order per episode.
    corpus_path: str | None = None
    dialogue_randomizer: bool = True

    # Programmatic character build applied on top of the loaded base save at
    # reset (attributes/skills/abilities/reputation/globals). See
    # TyrannyAdapter.apply_build. The first reset freezes this declaration for
    # the process; subsequent episode resets reuse the verified working save.
    build_spec: dict | None = None
    # Optional run-save name. When omitted, CRPGEnv generates a unique name.
    # The pristine save_start is never overwritten.
    working_save: str | None = None
    verify_build_reload: bool = True

    @property
    def port(self) -> int:
        return self.port_base + self.instance_id
