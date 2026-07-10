"""Multi-input actor-critic for the CRPG observation/action contract.

Observation is the CRPGEnv Dict {pixels (H,W,3), state (S,), mode Discrete(M),
goal (F,)}; action is MultiDiscrete([cursor_x, cursor_y, button, key]). The net
encodes pixels with a small CNN, concatenates the structured state + goal +
a mode embedding, and emits one categorical head per action factor plus a value.

Shared by both the PPO and GRPO trainers (GRPO simply ignores the value head).
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn


def obs_to_tensor(obs, device: torch.device) -> dict:
    """Batch one or many Dict observations into device tensors.

    Accepts a single obs (numpy arrays) or a list of them; returns a dict of
    batched tensors with a leading batch dim.
    """
    batch = obs if isinstance(obs, (list, tuple)) else [obs]
    pixels = torch.as_tensor(np.stack([o["pixels"] for o in batch]), device=device)
    state = torch.as_tensor(np.stack([o["state"] for o in batch]), dtype=torch.float32, device=device)
    mode = torch.as_tensor(np.asarray([int(o["mode"]) for o in batch]), dtype=torch.long, device=device)
    goal = torch.as_tensor(np.stack([o["goal"] for o in batch]), dtype=torch.float32, device=device)
    return {"pixels": pixels, "state": state, "mode": mode, "goal": goal}


class MultiInputActorCritic(nn.Module):
    def __init__(self, obs_space, action_nvec, hidden: int = 256):
        super().__init__()
        h, w, c = obs_space["pixels"].shape
        state_dim = int(obs_space["state"].shape[0])
        n_modes = int(obs_space["mode"].n)
        goal_dim = int(obs_space["goal"].shape[0])
        self.action_nvec = [int(n) for n in action_nvec]

        self.cnn = nn.Sequential(
            nn.Conv2d(c, 16, kernel_size=8, stride=4), nn.ReLU(),
            nn.Conv2d(16, 32, kernel_size=4, stride=2), nn.ReLU(),
            nn.Conv2d(32, 32, kernel_size=3, stride=1), nn.ReLU(),
            nn.Flatten(),
        )
        with torch.no_grad():
            cnn_out = self.cnn(torch.zeros(1, c, h, w)).shape[1]

        self.mode_emb = nn.Embedding(n_modes, 16)
        trunk_in = cnn_out + state_dim + goal_dim + 16
        self.trunk = nn.Sequential(
            nn.Linear(trunk_in, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
        )
        self.heads = nn.ModuleList([nn.Linear(hidden, n) for n in self.action_nvec])
        self.value_head = nn.Linear(hidden, 1)

    def _encode(self, obs: dict) -> torch.Tensor:
        px = obs["pixels"].float() / 255.0          # (B,H,W,C) -> normalized
        px = px.permute(0, 3, 1, 2).contiguous()    # -> (B,C,H,W)
        feats = self.cnn(px)
        mode = self.mode_emb(obs["mode"])
        x = torch.cat([feats, obs["state"], obs["goal"], mode], dim=1)
        return self.trunk(x)

    def forward(self, obs: dict):
        h = self._encode(obs)
        logits = [head(h) for head in self.heads]
        value = self.value_head(h).squeeze(-1)
        return logits, value

    @staticmethod
    def _dists(logits):
        return [torch.distributions.Categorical(logits=lg) for lg in logits]

    def act(self, obs: dict, deterministic: bool = False):
        """Sample an action; returns (action, logprob, value, entropy)."""
        logits, value = self.forward(obs)
        dists = self._dists(logits)
        if deterministic:
            action = torch.stack([torch.argmax(lg, dim=-1) for lg in logits], dim=1)
        else:
            action = torch.stack([d.sample() for d in dists], dim=1)
        logp = sum(d.log_prob(action[:, i]) for i, d in enumerate(dists))
        entropy = sum(d.entropy() for d in dists)
        return action, logp, value, entropy

    def evaluate(self, obs: dict, action: torch.Tensor):
        """Re-evaluate stored actions under the current policy (for the update)."""
        logits, value = self.forward(obs)
        dists = self._dists(logits)
        logp = sum(d.log_prob(action[:, i]) for i, d in enumerate(dists))
        entropy = sum(d.entropy() for d in dists)
        return logp, entropy, value
