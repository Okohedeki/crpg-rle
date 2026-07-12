"""Runtime dialogue randomizer — Python mirror of the C# DialogueInterceptor.

The C# mod is what actually swaps text and shuffles order in the live game;
this module reproduces the *same* deterministic choices so Python-side tools
(tests, offline analysis, the favor calibration) can predict exactly what the
agent saw. Both sides derive from (seed, conv, node) via SplitMix64/hash64.

Keep the algorithm identical to games/tyranny/bridge_mod/src/CRPGBridge/DialogueInterceptor.cs:
  - variant pick:   stream = seed ^ hash64(conv) ^ node;              idx = next % n
  - order shuffle:  stream = seed ^ hash64(conv) ^ qnode ^ SALT;      Fisher-Yates
"""
from __future__ import annotations

from crpg_rle.core.rng import SplitMix64, hash64

SHUFFLE_SALT = 0xA5A5A5A5A5A5A5A5
_MASK64 = (1 << 64) - 1


def pick_variant(conv: str, node: int, seed: int, variants: list[str]) -> str | None:
    """Deterministically choose one paraphrase for an option node."""
    if not variants:
        return None
    stream = (seed ^ hash64(conv.lower()) ^ (node & _MASK64)) & _MASK64
    rng = SplitMix64(stream)
    return variants[rng.next_u64() % len(variants)]


def shuffle_order(conv: str, question_node: int, seed: int, options: list) -> list:
    """Return options permuted in the same order the mod displays them."""
    stream = (seed ^ hash64(conv.lower()) ^ ((question_node & 0xFFFFFFFF)) ^ SHUFFLE_SALT) & _MASK64
    rng = SplitMix64(stream)
    return rng.shuffle(list(options))
