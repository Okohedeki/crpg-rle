"""Game-mode taxonomy and the reward-routing interface.

The mode flag stamped on every observation tells downstream consumers what
kind of screen the agent is looking at. Mode *detection* is game-specific and
lives in an adapter; this module only defines the vocabulary and the routing
contract so the core stays game-agnostic.
"""
from __future__ import annotations

import enum


class Mode(enum.IntEnum):
    """What the player is currently looking at / interacting with.

    Integer values are stable and used directly as the ``mode`` observation
    field (a Discrete space). Do not renumber without versioning the obs
    contract.
    """

    LOADING = 0
    CREATION = 1      # character creation / Conquest choices
    LEVEL_UP = 2
    DIALOGUE = 3
    COMBAT = 4
    OVERWORLD = 5     # normal exploration, real-time, not in combat
    MENU = 6          # main menu / modal system UI
    GAME_OVER = 7
    CUTSCENE = 8

    @classmethod
    def count(cls) -> int:
        return len(cls)


class RewardRouter:
    """Interface an adapter implements to turn detected events into rewards.

    The core calls these each step with the freshly detected mode and the
    drained engine event list; the adapter returns per-channel reward deltas.
    Keeping this abstract lets the core sum/log channels without knowing what
    a milestone or a faction is.
    """

    def route(self, mode: "Mode", events: list[dict], state: dict) -> dict[str, float]:
        """Return a mapping of channel name -> reward delta for this step.

        Must be pure with respect to its inputs plus the adapter's own
        progress bookkeeping; the core does the weighting and logging.
        """
        raise NotImplementedError
