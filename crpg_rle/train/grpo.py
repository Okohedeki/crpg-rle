"""Single-agent GRPO for CRPGEnv (or the proxy). Standalone PyTorch.

Group Relative Policy Optimization: for each prompt (an env reset — same seed, so
the same goal/faction), sample a GROUP of full episodes under the current policy,
then use the group-normalized episode return as the advantage for every step of
each episode. No critic. A KL penalty to a frozen reference policy (unbiased
estimator) keeps the policy from drifting — a built-in anti-reward-hacking guard.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn

from crpg_rle.train.buffer import Logger
from crpg_rle.train.policy import MultiInputActorCritic, obs_to_tensor


@dataclass
class GRPOConfig:
    total_steps: int = 200_000
    prompts_per_iter: int = 8      # distinct resets (goals) sampled per iteration
    group_size: int = 8           # episodes sampled per prompt (the "group")
    epochs: int = 2
    minibatches: int = 8
    clip_coef: float = 0.2
    kl_coef: float = 0.02          # penalty toward the frozen reference policy
    ent_coef: float = 0.01
    max_grad_norm: float = 0.5
    lr: float = 2.5e-4
    ref_sync_every: int = 20       # refresh the reference policy every N iters
    max_episode_steps: int = 128   # safety cap for episodes that never terminate
    seed: int = 0


class GRPOTrainer:
    def __init__(self, env, config: GRPOConfig, device: str = "cuda", logger: Logger | None = None):
        self.env = env
        self.cfg = config
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        self.policy = MultiInputActorCritic(env.observation_space, env.action_space.nvec).to(self.device)
        self.ref = copy.deepcopy(self.policy).to(self.device)
        for p in self.ref.parameters():
            p.requires_grad_(False)
        self.opt = torch.optim.Adam(self.policy.parameters(), lr=config.lr, eps=1e-5)
        self.logger = logger or Logger()
        self._global_step = 0
        self._iter = 0

    def _rollout_episode(self, seed: int):
        """Run one full episode under the current policy from a seeded reset."""
        obs, _ = self.env.reset(seed=seed)
        obs_buf, act_buf, logp_buf = [], [], []
        ep_return = 0.0
        for _ in range(self.cfg.max_episode_steps):
            ot = obs_to_tensor(obs, self.device)
            with torch.no_grad():
                action, logp, _v, _e = self.policy.act(ot)
            a = action[0].cpu().numpy()
            obs_buf.append(obs)
            act_buf.append(a)
            logp_buf.append(float(logp.item()))
            obs, reward, terminated, truncated, _info = self.env.step(a)
            ep_return += float(reward)
            if terminated or truncated:
                break
        return obs_buf, act_buf, logp_buf, ep_return

    def collect(self):
        cfg = self.cfg
        obs_all, act_all, logp_all, adv_all = [], [], [], []
        group_returns: list[float] = []
        for p in range(cfg.prompts_per_iter):
            seed = cfg.seed + self._global_step + p * 100_003
            episodes = [self._rollout_episode(seed) for _ in range(cfg.group_size)]
            returns = np.asarray([ep[3] for ep in episodes], dtype=np.float32)
            group_returns.extend(returns.tolist())
            adv = (returns - returns.mean()) / (returns.std() + 1e-8)  # group-relative
            for i, (obs_b, act_b, logp_b, _ret) in enumerate(episodes):
                obs_all.extend(obs_b)
                act_all.extend(act_b)
                logp_all.extend(logp_b)
                adv_all.extend([float(adv[i])] * len(obs_b))
                self._global_step += len(obs_b)
        return {
            "obs": obs_all,
            "actions": np.asarray(act_all, dtype=np.int64),
            "logp": np.asarray(logp_all, dtype=np.float32),
            "adv": np.asarray(adv_all, dtype=np.float32),
            "group_return_mean": float(np.mean(group_returns)) if group_returns else float("nan"),
        }

    def update(self, batch) -> dict:
        cfg = self.cfg
        n = len(batch["obs"])
        actions = torch.as_tensor(batch["actions"], device=self.device)
        old_logp = torch.as_tensor(batch["logp"], device=self.device)
        adv = torch.as_tensor(batch["adv"], device=self.device)
        obs_list = batch["obs"]

        mb_size = max(1, n // cfg.minibatches)
        idx = np.arange(n)
        stats = {"pg_loss": 0.0, "kl": 0.0, "entropy": 0.0}
        n_mb = 0
        for _epoch in range(cfg.epochs):
            np.random.shuffle(idx)
            for start in range(0, n, mb_size):
                mb = idx[start:start + mb_size]
                mb_obs = obs_to_tensor([obs_list[i] for i in mb], self.device)
                new_logp, entropy, _v = self.policy.evaluate(mb_obs, actions[mb])
                with torch.no_grad():
                    ref_logp, _re, _rv = self.ref.evaluate(mb_obs, actions[mb])

                mb_adv = adv[mb]
                ratio = torch.exp(new_logp - old_logp[mb])
                surr = torch.min(ratio * mb_adv,
                                 torch.clamp(ratio, 1 - cfg.clip_coef, 1 + cfg.clip_coef) * mb_adv)
                # Unbiased KL estimator k3 (Schulman): exp(d) - d - 1, d = ref - new.
                d = ref_logp - new_logp
                kl = (torch.exp(d) - d - 1.0).mean()
                ent = entropy.mean()
                loss = -(surr.mean()) + cfg.kl_coef * kl - cfg.ent_coef * ent

                self.opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.policy.parameters(), cfg.max_grad_norm)
                self.opt.step()

                stats["pg_loss"] += -surr.mean().item()
                stats["kl"] += kl.item()
                stats["entropy"] += ent.item()
                n_mb += 1
        for k in stats:
            stats[k] /= max(1, n_mb)
        return stats

    def train(self) -> None:
        cfg = self.cfg
        while self._global_step < cfg.total_steps:
            self._iter += 1
            batch = self.collect()
            stats = self.update(batch)
            if self._iter % cfg.ref_sync_every == 0:
                self.ref.load_state_dict(self.policy.state_dict())
            self.logger.log({
                "iter": self._iter, "step": self._global_step,
                "group_return": batch["group_return_mean"],
                "pg_loss": stats["pg_loss"], "kl": stats["kl"],
                "entropy": stats["entropy"],
            })
