"""Per-episode reset invariants for TyrannyAdapter."""
from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter


def test_dialogue_seed_fits_signed_long():
    # The dialogue seed crosses JSON to the C# bridge as a number; a value above
    # 2**63 overflows the signed-long path there and crashed the engine. Every
    # seed must yield a dialogue_seed in [0, 2**63).
    a = TyrannyAdapter()
    for seed in range(0, 5000):
        ds = a.reset(seed)["dialogue_seed"]
        assert 0 <= ds < (1 << 63), f"seed {seed} -> dialogue_seed {ds} out of range"


def test_reset_varies_target_and_seed_across_seeds():
    a = TyrannyAdapter()
    cfgs = [a.reset(s) for s in range(20)]
    assert len({c["target_faction"] for c in cfgs}) > 1  # goal varies
    assert len({c["dialogue_seed"] for c in cfgs}) == len(cfgs)  # distinct seeds
