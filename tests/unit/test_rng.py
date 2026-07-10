from crpg_rle.core.rng import SplitMix64, hash64


def test_splitmix64_golden_vectors():
    # Golden values for seed=0 (canonical SplitMix64 sequence).
    g = SplitMix64(0)
    assert g.next_u64() == 16294208416658607535
    assert g.next_u64() == 7960286522194355700
    assert g.next_u64() == 487617019471545679


def test_deterministic_same_seed():
    a = [SplitMix64(42).next_u64() for _ in range(5)]
    b = [SplitMix64(42).next_u64() for _ in range(5)]
    assert a == b


def test_different_seed_differs():
    a = SplitMix64(1).next_u64()
    b = SplitMix64(2).next_u64()
    assert a != b


def test_next_float_in_range():
    g = SplitMix64(123)
    for _ in range(1000):
        v = g.next_float()
        assert 0.0 <= v < 1.0


def test_shuffle_is_permutation_and_deterministic():
    base = list(range(10))
    s1 = SplitMix64(7).shuffle(list(base))
    s2 = SplitMix64(7).shuffle(list(base))
    assert s1 == s2
    assert sorted(s1) == base
    assert SplitMix64(8).shuffle(list(base)) != s1  # different seed -> different order


def test_hash64_stable():
    assert hash64("") == 0xCBF29CE484222325
    assert hash64("08_cv_test") == hash64("08_cv_test")
    assert hash64("a") != hash64("b")
