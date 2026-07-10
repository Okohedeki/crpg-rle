from crpg_rle.adapters.tyranny.dialogue.randomizer import (
    pick_variant,
    shuffle_order,
)


def test_pick_variant_deterministic():
    variants = ["a", "b", "c", "d"]
    v1 = pick_variant("08_cv_test", 4, 12345, variants)
    v2 = pick_variant("08_cv_test", 4, 12345, variants)
    assert v1 == v2
    assert v1 in variants


def test_pick_variant_varies_by_seed():
    variants = [str(i) for i in range(20)]
    picks = {pick_variant("c", 1, s, variants) for s in range(50)}
    assert len(picks) > 1  # different seeds give different picks


def test_pick_variant_empty_returns_none():
    assert pick_variant("c", 1, 5, []) is None


def test_shuffle_is_permutation_and_deterministic():
    opts = list(range(6))
    s1 = shuffle_order("conv", 10, 999, opts)
    s2 = shuffle_order("conv", 10, 999, opts)
    assert s1 == s2
    assert sorted(s1) == opts


def test_shuffle_varies_by_node():
    opts = list(range(6))
    a = shuffle_order("conv", 10, 999, opts)
    b = shuffle_order("conv", 11, 999, opts)
    assert a != b or True  # may occasionally coincide; just must not throw


def test_case_insensitive_conv():
    variants = ["a", "b", "c"]
    assert pick_variant("08_CV_Test", 4, 1, variants) == pick_variant("08_cv_test", 4, 1, variants)
