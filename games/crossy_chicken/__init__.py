"""Crossy Chicken: a self-contained Crossy Road / Frogger-style RL environment.

Fully native (numpy only, no external game / rendering deps). Emits the exact
``crpg_rle.core.spaces`` Dict observation contract {pixels, state, mode, goal}
and a ``MultiDiscrete([5])`` action space, so the shared MultiInputActorCritic
policy and the PPO/GRPO trainers work UNCHANGED.
"""
from __future__ import annotations

from games.crossy_chicken.env import CrossyChickenEnv

__all__ = ["CrossyChickenEnv"]
