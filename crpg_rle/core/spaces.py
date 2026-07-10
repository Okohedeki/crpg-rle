"""Build the unified action space and the hybrid observation space.

The action space is ONE flat MultiDiscrete for the whole episode (never
mode-switched): discretized cursor x/y bins, a mouse-button selector, and a
key selector. It is decoded into concrete input events inside the env's step().
This single flat space is required for PufferLib compatibility (mixed Dict
actions are unsupported) and satisfies the brief's unified-input mandate.

The observation is a Dict of {pixels, state, mode, goal} — pixels high enough
res that dialogue text is legible (no separate text channel).
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np

# Action sub-space sizes.
CURSOR_X_BINS = 64
CURSOR_Y_BINS = 36
# Button selector: 0 none, 1 left click, 2 right click, 3 left double-click.
BUTTON_CHOICES = 4


def build_action_space(n_keys: int) -> gym.spaces.MultiDiscrete:
    """MultiDiscrete([cursor_x, cursor_y, button, key])."""
    return gym.spaces.MultiDiscrete(
        [CURSOR_X_BINS, CURSOR_Y_BINS, BUTTON_CHOICES, n_keys]
    )


def build_observation_space(
    obs_height: int,
    obs_width: int,
    state_size: int,
    n_modes: int,
    n_factions: int,
) -> gym.spaces.Dict:
    return gym.spaces.Dict(
        {
            "pixels": gym.spaces.Box(
                low=0, high=255, shape=(obs_height, obs_width, 3), dtype=np.uint8
            ),
            "state": gym.spaces.Box(
                low=-np.inf, high=np.inf, shape=(state_size,), dtype=np.float32
            ),
            "mode": gym.spaces.Discrete(n_modes),
            "goal": gym.spaces.Box(low=0.0, high=1.0, shape=(n_factions,), dtype=np.float32),
        }
    )


def decode_action(action, key_list: list[str]) -> list[dict]:
    """Turn a MultiDiscrete action into bridge input events.

    action = [cursor_x_bin, cursor_y_bin, button_choice, key_index].
    Cursor bins map to normalized [0,1] window coordinates (Unity y is
    bottom-origin; the bridge expects normalized coords and flips internally).
    Returns the ``inputs`` list for an ``act`` request; may be empty (no-op).
    """
    cx, cy, button, key_idx = (int(action[0]), int(action[1]), int(action[2]), int(action[3]))
    inputs: list[dict] = []

    x_norm = (cx + 0.5) / CURSOR_X_BINS
    y_norm = (cy + 0.5) / CURSOR_Y_BINS
    inputs.append({"t": "cursor", "x": x_norm, "y": y_norm})

    if button == 1:
        inputs.append({"t": "button", "btn": "left", "action": "press"})
    elif button == 2:
        inputs.append({"t": "button", "btn": "right", "action": "press"})
    elif button == 3:
        # Double-click: two quick presses; the bridge schedules each over frames.
        inputs.append({"t": "button", "btn": "left", "action": "press"})
        inputs.append({"t": "button", "btn": "left", "action": "press"})

    key_name = key_list[key_idx] if 0 <= key_idx < len(key_list) else ""
    if key_name:
        inputs.append({"t": "key", "key": key_name, "action": "press"})

    return inputs
