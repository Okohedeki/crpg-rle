"""Live proof for one-shot build persistence and mutation lock."""
import os
import uuid

import pytest

from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter
from crpg_rle.adapters.tyranny.config import TyrannyConfig
from crpg_rle.core.bridge import BridgeRequestError
from crpg_rle.core.env import CRPGEnv

pytestmark = pytest.mark.live

DEFAULT_SAVE = "RL1 d3b051952d6742c3b0d46e413aa0e841 .savegame"


@pytest.mark.live
def test_build_is_saved_reloaded_and_locked_for_run():
    working = f"RL_CODEX_LOCKTEST_{uuid.uuid4().hex}.savegame"
    spec = {
        "attributes": {"Might": 16, "Wits": 14},
        "skills": {"Dodge": 25},
        "abilities": ["Abl_PC_Power_Sunder"],
        "reputation": [
            {"faction": "ScarletChorus", "axis": "positive", "strength": 1}
        ],
        "globals": {"RL_LOCK_TEST": 7},
    }
    cfg = TyrannyConfig(
        start_mode="act1_save",
        save_start=os.environ.get("CRPG_TEST_SAVE", DEFAULT_SAVE),
        working_save=working,
        build_spec=spec,
        dialogue_randomizer=False,
        obs_width=640,
        obs_height=360,
        max_steps=10,
    )
    env = CRPGEnv(TyrannyAdapter(cfg))
    try:
        _obs, info = env.reset(seed=17)
        assert info["build"] == {
            "locked": True,
            "verified": True,
            "working_save": working,
        }
        assert env._bridge.request("build_status") == {
            "id": env._bridge._next_id - 1,
            "ok": True,
            "open": False,
            "locked": True,
            "cheats": False,
        }
        stats = env._bridge.request("stats")
        assert stats["attributes"]["Might"] == 16
        assert stats["attributes"]["Wits"] == 14
        assert stats["skill_ranks"]["Dodge"] == 25
        ability_names = {name.replace("(Clone)", "").strip() for name in stats["abilities"]}
        assert "Abl_PC_Power_Sunder" in ability_names
        assert env._bridge.request("get_global", name="RL_LOCK_TEST")["value"] == 7

        with pytest.raises(BridgeRequestError, match="build mutation is locked"):
            env._bridge.request("console", cmd="AttributeScore player Might 10")

        # A later episode reset reuses the frozen run save; setup is not reopened.
        _obs, info2 = env.reset(seed=18)
        assert info2["build"]["working_save"] == working
        stats2 = env._bridge.request("stats")
        assert stats2["attributes"]["Might"] == 16
        assert stats2["attributes"]["Wits"] == 14
        assert stats2["skill_ranks"]["Dodge"] == 25
        assert env._bridge.request("build_status")["locked"] is True

        # Gameplay starts normally after lock.
        _obs, _reward, _done, _truncated, step_info = env.step(env.action_space.sample())
        assert "mode" in step_info
    finally:
        env.close()