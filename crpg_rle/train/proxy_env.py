"""Fast proxy env with the EXACT CRPGEnv observation/action contract.

Purpose: validate the training scaffolding (PPO/GRPO, loss curves) at thousands
of steps/sec, without waiting on the live game. It reuses the core space builders
so a policy trained here plugs straight into CRPGEnv.

The task mirrors the real environment's core difficulty — goal-conditioned
comprehension: each episode samples a target faction (the ``goal`` one-hot in the
observation), and the agent is rewarded only when its ``key`` action factor
matches the goal-derived target. Position/pixels carry no reliable signal, so the
policy must read the goal. A learnable-but-nontrivial signal → the loss visibly
matures (policy loss down, entropy down, return up).
"""
from __future__ import annotations

import gymnasium as gym
import numpy as np

from crpg_rle.core import spaces as S
from crpg_rle.core.modes import Mode

_STATE_SIZE = 8


class ProxyCRPGEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, obs_size: int = 84, n_factions: int = 6, n_keys: int = 13,
                 episode_len: int = 64, sparse: bool = False):
        self.n_factions = n_factions
        self.n_keys = n_keys
        self.episode_len = episode_len
        self.sparse = sparse

        self.action_space = S.build_action_space(n_keys)
        self.observation_space = S.build_observation_space(
            obs_height=obs_size, obs_width=obs_size, state_size=_STATE_SIZE,
            n_modes=Mode.count(), n_factions=n_factions,
        )
        self._rng = np.random.default_rng(0)
        self._goal_idx = 0
        self._target_key = 1
        self._t = 0

    def _obs(self) -> dict:
        goal = np.zeros(self.n_factions, dtype=np.float32)
        goal[self._goal_idx] = 1.0
        h, w, c = self.observation_space["pixels"].shape
        # Mild deterministic-per-goal texture (exercises the CNN; not required to
        # solve the task, which is fully specified by the goal vector).
        pixels = np.full((h, w, c), (self._goal_idx * 37) % 256, dtype=np.uint8)
        state = np.zeros(_STATE_SIZE, dtype=np.float32)
        state[0] = self._t / self.episode_len
        return {"pixels": pixels, "state": state,
                "mode": int(Mode.DIALOGUE), "goal": goal}

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        self._goal_idx = int(self._rng.integers(self.n_factions))
        # Target key is a fixed function of the goal the agent must learn to map.
        self._target_key = 1 + (self._goal_idx % (self.n_keys - 1))
        self._t = 0
        return self._obs(), {"target_faction": f"F{self._goal_idx}"}

    def step(self, action):
        key = int(action[3])
        correct = key == self._target_key
        if self.sparse:
            reward = 1.0 if (correct and self._t == self.episode_len - 1) else 0.0
        else:
            reward = 1.0 if correct else 0.0
        self._t += 1
        truncated = self._t >= self.episode_len
        info = {"reward_channels": {"goal_favor": reward},
                "target_faction": f"F{self._goal_idx}"}
        return self._obs(), reward, False, truncated, info
