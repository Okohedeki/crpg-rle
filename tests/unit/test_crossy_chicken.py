"""Unit tests for CrossyChickenEnv (CPU-only, no GPU needed).

Covers the obs/action contract, the reward semantics (progress pays out once
per new furthest row, oscillation/backtracking earns nothing, collisions and
standing still are fatal), determinism per seed, and a tiny PPO smoke that the
shared trainer runs on this env and yields finite losses.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

# Make the repo root importable so `games.crossy_chicken` resolves under pytest.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from crpg_rle.core.modes import Mode
from games.crossy_chicken.env import CrossyChickenEnv

OBS = 36  # small enough for fast CPU, large enough for the policy CNN kernels


def _grass(env, rows):
    for r in rows:
        env._lanes[r] = {"kind": "grass"}


def test_reset_step_contract():
    env = CrossyChickenEnv(obs_size=OBS)
    obs, info = env.reset(seed=0)
    assert env.observation_space.contains(obs)
    assert obs["pixels"].shape == (OBS, OBS, 3)
    assert obs["pixels"].dtype == np.uint8
    assert obs["state"].shape == (env.state_size,)
    assert obs["state"].dtype == np.float32
    assert int(obs["mode"]) == int(Mode.OVERWORLD)
    assert obs["goal"].shape == (1,)
    assert info["mode"] == int(Mode.OVERWORLD)

    for a in range(5):
        env.reset(seed=1)
        obs, reward, terminated, truncated, info = env.step([a])
        assert env.observation_space.contains(obs)
        assert set(info["reward_channels"]) == {"progress", "death", "step"}
        assert np.isfinite(reward)


def test_action_space_shape():
    env = CrossyChickenEnv(obs_size=OBS)
    assert list(env.action_space.nvec) == [5]
    a = env.action_space.sample()
    assert 0 <= int(a[0]) < 5


def test_forward_to_new_row_gives_progress():
    env = CrossyChickenEnv(obs_size=OBS)
    env.reset(seed=0)
    _grass(env, [0, 1, 2, 3])
    _, reward, term, trunc, info = env.step([1])  # UP -> row 1 (new furthest)
    assert not term and not trunc
    assert info["reward_channels"]["progress"] == 1.0
    assert info["reward_channels"]["step"] == pytest.approx(-0.01)
    assert reward == pytest.approx(0.99)
    assert env.row == 1 and env.max_row == 1


def test_backward_and_revisit_give_no_progress():
    env = CrossyChickenEnv(obs_size=OBS)
    env.reset(seed=0)
    _grass(env, [0, 1, 2, 3])
    env.step([1])                       # UP -> row 1, +1
    _, _, _, _, info_down = env.step([2])   # DOWN -> row 0
    assert info_down["reward_channels"]["progress"] == 0.0
    _, _, _, _, info_up = env.step([1])     # UP -> row 1 again (already visited)
    assert info_up["reward_channels"]["progress"] == 0.0
    # And a pure sideways jitter never pays out either.
    _, _, _, _, info_side = env.step([3])   # LEFT
    assert info_side["reward_channels"]["progress"] == 0.0


def test_oscillation_is_not_farmable():
    env = CrossyChickenEnv(obs_size=OBS, stuck_limit=1000)
    env.reset(seed=0)
    _grass(env, range(0, 5))
    total_progress = 0.0
    for _ in range(20):
        for a in (1, 2):  # up then back down, repeatedly
            _, _, _, _, info = env.step([a])
            total_progress += info["reward_channels"]["progress"]
    # Only the very first UP to row 1 could ever have paid out.
    assert total_progress == pytest.approx(1.0)


def test_forced_collision_terminates_with_death_penalty():
    env = CrossyChickenEnv(obs_size=OBS)
    env.reset(seed=0)
    # A road lane fully covered by a car (car_len >= period) at the chicken's row.
    env._lanes[env.row] = {
        "kind": "road", "dir": 1, "speed": 1,
        "car_len": 3, "gap": 0, "period": 3, "phase": 0,
    }
    _, reward, term, trunc, info = env.step([0])  # NOOP: cars advance, chicken hit
    assert term and not trunc
    assert info["reward_channels"]["death"] == -1.0
    assert info["terminal_kind"] == "car"
    assert reward == pytest.approx(-1.01)


def test_standing_still_too_long_is_fatal():
    env = CrossyChickenEnv(obs_size=OBS, stuck_limit=5)
    env.reset(seed=0)
    _grass(env, [0, 1])
    term = False
    for _ in range(5):
        _, _, term, _, info = env.step([0])  # NOOP forever on safe grass
    assert term
    assert info["terminal_kind"] == "stuck"
    assert info["reward_channels"]["death"] == -1.0


def test_determinism_same_seed():
    actions = [1, 3, 1, 4, 1, 0, 1, 2, 1, 1, 3, 1]
    def rollout():
        env = CrossyChickenEnv(obs_size=OBS)
        obs, _ = env.reset(seed=1234)
        trace = [(obs["pixels"].sum(), tuple(np.round(obs["state"], 5)))]
        for a in actions:
            obs, r, term, trunc, _ = env.step([a])
            trace.append((float(r), obs["pixels"].sum(), tuple(np.round(obs["state"], 5)),
                          bool(term), bool(trunc)))
            if term or trunc:
                break
        return trace
    a = rollout()
    b = rollout()
    assert a == b


def test_river_water_is_fatal_log_is_safe():
    env = CrossyChickenEnv(obs_size=OBS)
    env.reset(seed=0)
    # A river fully covered by a log at the chicken's row: standing is safe.
    env._lanes[env.row] = {
        "kind": "river", "dir": 1, "speed": 1,
        "car_len": 3, "gap": 0, "period": 3, "phase": 0,
    }
    _, _, term, _, _ = env.step([0])  # NOOP on an all-log river -> survives
    assert not term
    # A river with no logs (all water) kills.
    env.reset(seed=0)
    env._lanes[env.row] = {
        "kind": "river", "dir": 1, "speed": 1,
        "car_len": 0, "gap": 3, "period": 3, "phase": 0,
    }
    _, reward, term, trunc, info = env.step([0])
    assert term and not trunc
    assert info["terminal_kind"] == "water"
    assert info["reward_channels"]["death"] == -1.0
    assert reward == pytest.approx(-1.01)


def test_difficulty_scales_grass_fraction():
    def grass_frac(diff):
        env = CrossyChickenEnv(difficulty=diff)
        env.reset(seed=7)
        kinds = [env._lane(r)["kind"] for r in range(1, 401)]
        return kinds.count("grass") / len(kinds)
    # Deterministic from the presets: easier = more safe grass.
    assert grass_frac("easy") > grass_frac("normal") > grass_frac("hard")


def test_bad_difficulty_rejected():
    with pytest.raises(ValueError):
        CrossyChickenEnv(difficulty="impossible")


def test_render_rgb_array_shape_and_type():
    env = CrossyChickenEnv(obs_size=OBS, view_rows=11, width=11, cell_px=10,
                           render_mode="rgb_array")
    env.reset(seed=2)
    frame = env.render()
    assert frame.shape == (11 * 10, 11 * 10, 3)
    assert frame.dtype == np.uint8
    assert frame.max() > 0  # not an all-black frame
    env.close()


def test_render_none_returns_none():
    env = CrossyChickenEnv(obs_size=OBS)
    env.reset(seed=0)
    assert env.render() is None  # render_mode unset


def test_ppo_one_update_runs():
    torch = pytest.importorskip("torch")
    from crpg_rle.train.ppo import PPOConfig, PPOTrainer

    env = CrossyChickenEnv(obs_size=OBS, max_steps=16, stuck_limit=16)
    cfg = PPOConfig(total_steps=64, rollout_steps=64, epochs=1, minibatches=2)
    trainer = PPOTrainer(env, cfg, device="cpu")
    batch = trainer.collect()
    stats = trainer.update(batch)
    assert np.isfinite(stats["pg_loss"]) and np.isfinite(stats["v_loss"])
    assert np.isfinite(stats["entropy"]) and stats["entropy"] > 0
