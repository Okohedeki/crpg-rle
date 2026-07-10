"""Deterministic PRNG (SplitMix64) mirrored on the C# side.

Used for all env-owned randomness: paraphrase variant selection, dialogue
option shuffling, target-faction sampling, save selection. The C# mod
(Corpus.cs) implements the identical algorithm so that a given (seed, node)
derives the same permutation on both sides; cross-language golden-vector
tests pin the two implementations together.

SplitMix64 reference: Steele, Lea & Flood (2014). 64-bit state, no warmup.
"""
from __future__ import annotations

_MASK64 = (1 << 64) - 1


class SplitMix64:
    """Minimal SplitMix64 generator. Deterministic, seedable, fast."""

    __slots__ = ("_state",)

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK64

    def next_u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
        return (z ^ (z >> 31)) & _MASK64

    def next_float(self) -> float:
        """Uniform in [0, 1) using the top 53 bits."""
        return (self.next_u64() >> 11) / float(1 << 53)

    def randint(self, n: int) -> int:
        """Uniform integer in [0, n). Rejection-free (modulo bias negligible
        for the small n used here; kept identical to the C# port)."""
        if n <= 0:
            raise ValueError("n must be positive")
        return self.next_u64() % n

    def shuffle(self, seq: list) -> list:
        """In-place Fisher-Yates using this generator; returns the list.

        Iterates i from high to low, matching the C# DialogueInterceptor so
        both derive the identical permutation for a given seed.
        """
        for i in range(len(seq) - 1, 0, -1):
            j = self.next_u64() % (i + 1)
            seq[i], seq[j] = seq[j], seq[i]
        return seq


def hash64(text: str) -> int:
    """FNV-1a 64-bit hash of a UTF-8 string. Mirrored in C# for deriving
    per-conversation PRNG streams from (seed XOR hash64(conv_id) XOR node)."""
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h = ((h ^ b) * 0x100000001B3) & _MASK64
    return h
