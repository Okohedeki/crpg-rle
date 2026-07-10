import numpy as np

from crpg_rle.core import spaces as S


def test_action_space_shape():
    sp = S.build_action_space(n_keys=13)
    assert list(sp.nvec) == [S.CURSOR_X_BINS, S.CURSOR_Y_BINS, S.BUTTON_CHOICES, 13]


def test_observation_space_keys():
    sp = S.build_observation_space(720, 1280, state_size=55, n_modes=9, n_factions=6)
    assert set(sp.spaces.keys()) == {"pixels", "state", "mode", "goal"}
    assert sp["pixels"].shape == (720, 1280, 3)
    assert sp["state"].shape == (55,)
    assert sp["goal"].shape == (6,)


def test_decode_cursor_only():
    keys = ["", "Escape", "Alpha1"]
    inp = S.decode_action([0, 0, 0, 0], keys)
    assert inp == [{"t": "cursor", "x": 0.5 / S.CURSOR_X_BINS, "y": 0.5 / S.CURSOR_Y_BINS}]


def test_decode_left_click_and_key():
    keys = ["", "Escape", "Alpha1"]
    inp = S.decode_action([31, 17, 1, 2], keys)
    types = [(i["t"], i.get("btn") or i.get("key")) for i in inp]
    assert ("cursor", None) in [(t, None) for t, _ in types] or types[0][0] == "cursor"
    assert ("button", "left") in types
    assert ("key", "Alpha1") in types


def test_decode_right_click():
    inp = S.decode_action([10, 10, 2, 0], ["", "Escape"])
    assert any(i.get("btn") == "right" for i in inp)


def test_decode_no_key_index_zero():
    inp = S.decode_action([0, 0, 0, 0], ["", "Escape"])
    assert not any(i["t"] == "key" for i in inp)


def test_cursor_bins_map_into_unit_interval():
    for cx in (0, S.CURSOR_X_BINS - 1):
        inp = S.decode_action([cx, 0, 0, 0], [""])
        x = inp[0]["x"]
        assert 0.0 < x < 1.0
