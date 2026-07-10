"""Single-agent PPO for CRPGEnv (or the proxy). Standalone PyTorch.

Collects a fixed-length rollout from one environment (handling auto-reset and
truncation bootstrapping), computes GAE, and runs clipped-surrogate PPO updates
with a value loss and an entropy bonus. Logs per-update policy/value/entropy
loss, approx-KL, clip fraction, and mean episode return so the loss can be
watched maturing.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn

import collections

from crpg_rle.train.buffer import Logger, RunningMeanStd, action_stats, compute_gae
from crpg_rle.train.policy import MultiInputActorCritic, obs_to_tensor


@dataclass
class PPOConfig:
    total_steps: int = 200_000
    rollout_steps: int = 512
    epochs: int = 4
    minibatches: int = 4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_coef: float = 0.2
    ent_coef: float = 0.01           # entropy bonus — discourages premature collapse
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    lr: float = 2.5e-4
    normalize_adv: bool = True
    normalize_reward: bool = True     # reward-scale normalization (anti-hacking)
    target_kl: float | None = 0.03    # early-stop an update if KL blows past this
    seed: int = 0


class PPOTrainer:
    def __init__(self, env, config: PPOConfig, device: str = "cuda", logger: Logger | None = None):
        self.env = env
        self.cfg = config
        self.device = torch.device(device if torch.cuda.is_available() else "cpu")
        self.policy = MultiInputActorCritic(env.observation_space, env.action_space.nvec).to(self.device)
        self.opt = torch.optim.Adam(self.policy.parameters(), lr=config.lr, eps=1e-5)
        self.logger = logger or Logger()
        self.ret_rms = RunningMeanStd()
        self._obs, _ = env.reset(seed=config.seed)
        self._ep_return = 0.0
        self._ep_returns: list[float] = []
        self._global_step = 0

    def _value(self, obs) -> float:
        with torch.no_grad():
            _, v = self.policy.forward(obs_to_tensor(obs, self.device))
        return float(v.item())

    def collect(self):
        cfg, n = self.cfg, self.cfg.rollout_steps
        obs_buf, act_buf, logp_buf, val_buf = [], [], [], []
        rew_buf, term_buf, done_buf = [], [], []
        boot = np.zeros(n, dtype=np.float32)
        term_boot: dict[int, float] = {}
        self._ep_returns = []
        channel_sums: dict[str, float] = collections.defaultdict(float)

        obs = self._obs
        for t in range(n):
            ot = obs_to_tensor(obs, self.device)
            with torch.no_grad():
                action, logp, value, _ = self.policy.act(ot)
            a = action[0].cpu().numpy()
            next_obs, reward, terminated, truncated, info = self.env.step(a)
            for ch, val in (info.get("reward_channels") or {}).items():
                channel_sums[ch] += float(val)
            done = bool(terminated or truncated)

            obs_buf.append(obs)
            act_buf.append(a)
            logp_buf.append(float(logp.item()))
            val_buf.append(float(value.item()))
            rew_buf.append(float(reward))
            term_buf.append(float(terminated))
            done_buf.append(float(done))

            self._ep_return += float(reward)
            if done:
                term_boot[t] = 0.0 if terminated else self._value(next_obs)
                self._ep_returns.append(self._ep_return)
                self._ep_return = 0.0
                next_obs, _ = self.env.reset(seed=cfg.seed + self._global_step + t + 1)
            obs = next_obs
        self._obs = obs

        # Bootstrap value per step: terminal steps use their stored bootstrap;
        # interior steps use the next step's value; a trailing non-done step uses
        # the value of the final observation.
        for t in range(n):
            if done_buf[t]:
                boot[t] = term_boot[t]
            elif t + 1 < n:
                boot[t] = val_buf[t + 1]
            else:
                boot[t] = self._value(obs)

        rewards = np.asarray(rew_buf, dtype=np.float32)
        if cfg.normalize_reward:
            self.ret_rms.update(rewards)
            rewards = rewards / self.ret_rms.std

        adv, returns = compute_gae(rewards, np.asarray(val_buf, dtype=np.float32),
                                   boot, term_buf, done_buf, cfg.gamma, cfg.gae_lambda)
        self._global_step += n
        return {
            "obs": obs_buf,
            "actions": np.asarray(act_buf, dtype=np.int64),
            "logp": np.asarray(logp_buf, dtype=np.float32),
            "values": np.asarray(val_buf, dtype=np.float32),
            "adv": adv, "returns": returns,
            "channel_sums": dict(channel_sums),
            "rollout_reward": float(np.sum(rew_buf)),
        }

    def update(self, batch) -> dict:
        cfg = self.cfg
        n = len(batch["obs"])
        actions = torch.as_tensor(batch["actions"], device=self.device)
        old_logp = torch.as_tensor(batch["logp"], device=self.device)
        old_values = torch.as_tensor(batch["values"], device=self.device)
        adv = torch.as_tensor(batch["adv"], device=self.device)
        returns = torch.as_tensor(batch["returns"], device=self.device)
        obs_list = batch["obs"]

        mb_size = max(1, n // cfg.minibatches)
        idx = np.arange(n)
        stats = {"pg_loss": 0.0, "v_loss": 0.0, "entropy": 0.0, "approx_kl": 0.0, "clipfrac": 0.0}
        n_mb = 0
        stop = False
        for _epoch in range(cfg.epochs):
            np.random.shuffle(idx)
            for start in range(0, n, mb_size):
                mb = idx[start:start + mb_size]
                mb_obs = obs_to_tensor([obs_list[i] for i in mb], self.device)
                new_logp, entropy, value = self.policy.evaluate(mb_obs, actions[mb])

                mb_adv = adv[mb]
                if cfg.normalize_adv:
                    mb_adv = (mb_adv - mb_adv.mean()) / (mb_adv.std() + 1e-8)

                ratio = torch.exp(new_logp - old_logp[mb])
                pg1 = -mb_adv * ratio
                pg2 = -mb_adv * torch.clamp(ratio, 1 - cfg.clip_coef, 1 + cfg.clip_coef)
                pg_loss = torch.max(pg1, pg2).mean()

                # Clipped value loss.
                v_clipped = old_values[mb] + torch.clamp(
                    value - old_values[mb], -cfg.clip_coef, cfg.clip_coef)
                v_loss = 0.5 * torch.max((value - returns[mb]) ** 2,
                                         (v_clipped - returns[mb]) ** 2).mean()
                ent = entropy.mean()
                loss = pg_loss - cfg.ent_coef * ent + cfg.vf_coef * v_loss

                self.opt.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.policy.parameters(), cfg.max_grad_norm)
                self.opt.step()

                with torch.no_grad():
                    approx_kl = (old_logp[mb] - new_logp).mean().item()
                    clipfrac = ((ratio - 1.0).abs() > cfg.clip_coef).float().mean().item()
                stats["pg_loss"] += pg_loss.item()
                stats["v_loss"] += v_loss.item()
                stats["entropy"] += ent.item()
                stats["approx_kl"] += approx_kl
                stats["clipfrac"] += clipfrac
                n_mb += 1
                if cfg.target_kl is not None and approx_kl > cfg.target_kl:
                    stop = True
                    break
            if stop:
                break
        for k in stats:
            stats[k] /= max(1, n_mb)
        return stats

    def train(self) -> None:
        cfg = self.cfg
        n_updates = max(1, cfg.total_steps // cfg.rollout_steps)
        for update in range(1, n_updates + 1):
            batch = self.collect()
            stats = self.update(batch)
            mean_ret = float(np.mean(self._ep_returns)) if self._ep_returns else float("nan")
            row = {
                "update": update, "step": self._global_step,
                "rollout_reward": batch["rollout_reward"],
                "ep_return": mean_ret, "n_ep": len(self._ep_returns),
                "pg_loss": stats["pg_loss"], "v_loss": stats["v_loss"],
                "entropy": stats["entropy"], "approx_kl": stats["approx_kl"],
                "clipfrac": stats["clipfrac"],
            }
            row.update({f"r_{k}": v for k, v in batch["channel_sums"].items()})  # per-channel reward
            row.update(action_stats(batch["actions"]))                          # actions taken
            self.logger.log(row)
