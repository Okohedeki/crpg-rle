from crpg_rle.adapters.tyranny.mode_detect import detect_mode
from crpg_rle.core.modes import Mode


def test_loading_wins_over_everything():
    assert detect_mode({"loading": True, "in_combat": True,
                        "conversation": {"active": True}}) == Mode.LOADING


def test_game_over():
    assert detect_mode({"game_over": True}) == Mode.GAME_OVER
    assert detect_mode({"party_dead": True}) == Mode.GAME_OVER


def test_creation():
    assert detect_mode({"in_creation": True, "in_combat": True}) == Mode.CREATION


def test_dialogue_before_combat():
    assert detect_mode({"conversation": {"active": True}, "in_combat": True}) == Mode.DIALOGUE


def test_combat():
    assert detect_mode({"in_combat": True, "conversation": {"active": False}}) == Mode.COMBAT


def test_overworld_default():
    assert detect_mode({}) == Mode.OVERWORLD
    assert detect_mode({"conversation": {"active": False}, "in_combat": False}) == Mode.OVERWORLD


def test_missing_conversation_key():
    assert detect_mode({"in_combat": False}) == Mode.OVERWORLD
