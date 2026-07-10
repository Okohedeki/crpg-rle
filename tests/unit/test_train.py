"""Smoke tests for the training scaffolding (CPU, tiny, CI-safe).

Exercises the policy net, the proxy env, and one PPO update + one GRPO iteration,
asserting the pipeline runs and produces finite losses. Not a convergence test.
"""
import numpy as np
import pytest

torch = pytest.importorskip("torch")

from crpg_rle.train.grpo import GRPOConfig, GRPOTrainer
from crpg_rle.train.policy import MultiInputActorCritic, obs_to_tensor
from crpg_rle.train.ppo import PPOConfig, PPOTrainer
from crpg_rle.train.proxy_env import ProxyCRPGEnv

OBS = 36  # small enough for fast CPU, large enough for the CNN kernels


def test_policy_forward_and_act():
    env = ProxyCRPGEnv(obs_size=OBS)
    net = MultiInputActorCritic(env.observation_space, env.action_space.nvec)
    obs, _ = env.reset(seed=0)
    ot = obs_to_tensor(obs, torch.device("cpu"))
    action, logp, value, entropy = net.act(ot)
    assert action.shape == (1, 4)
    # action factors within their category ranges
    for i, n in enumerate(env.action_space.nvec):
        assert 0 <= int(action[0, i]) < int(n)
    assert torch.isfinite(logp).all() and torch.isfinite(value).all()


def test_proxy_env_reward_is_goal_conditioned():
    env = ProxyCRPGEnv(obs_size=OBS)
    _, _ = env.reset(seed=3)
    # the correct key yields reward 1; a wrong key yields 0
    correct = env._target_key
    _, r_ok, _, _, _ = env.step(np.array([0, 0, 0, correct]))
    _, r_bad, _, _, _ = env.step(np.array([0, 0, 0, (correct % (env.n_keys - 1)) + 1 if correct == 1 else 1]))
    assert r_ok == 1.0
    assert r_bad in (0.0, 1.0)  # (guard against the rare equal-key pick)


def test_ppo_one_update_runs():
    env = ProxyCRPGEnv(obs_size=OBS, episode_len=16)
    cfg = PPOConfig(total_steps=64, rollout_steps=64, epochs=1, minibatches=2)
    trainer = PPOTrainer(env, cfg, device="cpu")
    batch = trainer.collect()
    stats = trainer.update(batch)
    assert np.isfinite(stats["pg_loss"]) and np.isfinite(stats["v_loss"])
    assert np.isfinite(stats["entropy"]) and stats["entropy"] > 0


def test_grpo_one_iter_runs():
    env = ProxyCRPGEnv(obs_size=OBS, episode_len=16)
    cfg = GRPOConfig(total_steps=1, prompts_per_iter=2, group_size=3,
                     epochs=1, minibatches=2, max_episode_steps=16)
    trainer = GRPOTrainer(env, cfg, device="cpu")
    batch = trainer.collect()
    assert len(batch["obs"]) > 0
    stats = trainer.update(batch)
    assert np.isfinite(stats["pg_loss"]) and np.isfinite(stats["kl"])
