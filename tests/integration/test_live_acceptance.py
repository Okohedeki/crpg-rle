"""Live acceptance test — drives the whole CRPGEnv against the real game.

Requires: Tyranny installed, the bridge mod deployed, and a save named by
CRPG_TEST_SAVE (or the default below). Marked 'live' so it is skipped in CI.
Run explicitly:  pytest tests/integration -m live -s
"""
import os

import numpy as np
import pytest

from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter
from crpg_rle.adapters.tyranny.config import TyrannyConfig
from crpg_rle.core.capture import is_mostly_black
from crpg_rle.core.env import CRPGEnv
from crpg_rle.core.modes import Mode

pytestmark = pytest.mark.live

DEFAULT_SAVE = "Coco 338443d6200a419694e5f2d898c756cf 2autosave.savegame"


@pytest.mark.live
def test_full_env_episode():
    save = os.environ.get("CRPG_TEST_SAVE", DEFAULT_SAVE)
    corpus = os.path.join(os.path.dirname(__file__), "..", "..", "games", "tyranny", "corpora", "act1_demo", "corpus.json")
    cfg = TyrannyConfig(
        start_mode="act1_save",
        save_start=save,
        corpus_path=os.path.abspath(corpus),
        obs_width=1280,
        obs_height=720,
        max_steps=30,
    )
    env = CRPGEnv(TyrannyAdapter(cfg))
    try:
        obs, info = env.reset(seed=7)

        # observation contract
        assert obs["pixels"].shape == (720, 1280, 3)
        assert obs["pixels"].dtype == np.uint8
        assert not is_mostly_black(obs["pixels"]), "captured a black frame"
        assert obs["state"].shape[0] == env.adapter.state_vector_size()
        assert obs["goal"].sum() == 1.0, "exactly one target faction"
        assert info["target_faction"] in env.adapter.target_factions()

        # milestone 0 fires on the first step (episode gate)
        modes_seen = set()
        reward_channels_present = False
        for _ in range(20):
            obs, reward, done, trunc, info = env.step(env.action_space.sample())
            modes_seen.add(info["mode"])
            if "reward_channels" in info:
                reward_channels_present = True
                assert set(info["reward_channels"]) <= {"milestone", "faction_favor", "death"}
            assert obs["mode"] in range(Mode.count())
            if done:
                break

        assert reward_channels_present
        assert "m0" in env.adapter.milestones.fired  # creation/Conquest gate fired
    finally:
        env.close()
