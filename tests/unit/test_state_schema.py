import numpy as np

from crpg_rle.adapters.tyranny.state_schema import (
    pack_state,
    state_field_layout,
    state_vector_size,
)

FACTIONS = ["ScarletChorus", "Disfavored"]


def test_vector_size_stable():
    # 6 party * 7 + 2 factions * 4 + 3 globals
    assert state_vector_size(FACTIONS, max_party=6) == 6 * 7 + 2 * 4 + 3


def test_pack_length_matches():
    vec = pack_state({}, FACTIONS, max_party=6)
    assert vec.shape == (state_vector_size(FACTIONS, 6),)
    assert vec.dtype == np.float32


def test_party_and_faction_values_land_at_offsets():
    layout = state_field_layout(FACTIONS, max_party=6)
    state = {
        "party": [{"hp": 50, "max_hp": 60, "pos": [1.0, 2.0, 3.0], "selected": True, "dead": False}],
        "reputation": {"Disfavored": {"favor": 165, "wrath": 5, "favor_rank": 2, "wrath_rank": 0}},
        "in_combat": True,
    }
    vec = pack_state(state, FACTIONS, max_party=6)
    assert vec[layout["party0.hp"]] == 50
    assert vec[layout["party0.max_hp"]] == 60
    assert vec[layout["party0.x"]] == 1.0
    assert vec[layout["party0.selected"]] == 1.0
    assert vec[layout["Disfavored.favor"]] == 165
    assert vec[layout["in_combat"]] == 1.0
    assert vec[layout["edict_days_remaining"]] == -1.0  # default


def test_padding_when_fewer_party():
    layout = state_field_layout(FACTIONS, max_party=6)
    vec = pack_state({"party": []}, FACTIONS, max_party=6)
    assert vec[layout["party5.hp"]] == 0.0
