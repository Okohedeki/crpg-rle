"""Flatten the bridge state dict into a fixed-length float32 vector.

Layout (all float32):
  [ per party slot x max_party: hp, max_hp, x, y, z, selected, dead ]   (7 each)
  [ per faction: favor, wrath, favor_rank, wrath_rank ]                 (4 each)
  [ in_combat, paused, edict_days_remaining ]                          (3)
Missing values are zero-padded; edict_days_remaining defaults to -1.
"""
from __future__ import annotations

import numpy as np

_PARTY_FIELDS = 7
_FACTION_FIELDS = 4
_GLOBAL_FIELDS = 3


def state_vector_size(factions: list[str], max_party: int = 6) -> int:
    return max_party * _PARTY_FIELDS + len(factions) * _FACTION_FIELDS + _GLOBAL_FIELDS


def state_field_layout(factions: list[str], max_party: int = 6) -> dict[str, int]:
    """Human-readable offset map for debugging."""
    layout: dict[str, int] = {}
    off = 0
    for slot in range(max_party):
        for f in ("hp", "max_hp", "x", "y", "z", "selected", "dead"):
            layout[f"party{slot}.{f}"] = off
            off += 1
    for fac in factions:
        for f in ("favor", "wrath", "favor_rank", "wrath_rank"):
            layout[f"{fac}.{f}"] = off
            off += 1
    layout["in_combat"] = off
    layout["paused"] = off + 1
    layout["edict_days_remaining"] = off + 2
    return layout


def pack_state(state: dict, factions: list[str], max_party: int = 6) -> np.ndarray:
    vec = np.zeros(state_vector_size(factions, max_party), dtype=np.float32)
    off = 0

    party = state.get("party") or []
    for slot in range(max_party):
        member = party[slot] if slot < len(party) else None
        if member is not None:
            pos = member.get("pos") or [0.0, 0.0, 0.0]
            vec[off + 0] = float(member.get("hp", 0.0))
            vec[off + 1] = float(member.get("max_hp", 0.0))
            vec[off + 2] = float(pos[0]) if len(pos) > 0 else 0.0
            vec[off + 3] = float(pos[1]) if len(pos) > 1 else 0.0
            vec[off + 4] = float(pos[2]) if len(pos) > 2 else 0.0
            vec[off + 5] = 1.0 if member.get("selected") else 0.0
            vec[off + 6] = 1.0 if member.get("dead") else 0.0
        off += _PARTY_FIELDS

    reputation = state.get("reputation") or {}
    for fac in factions:
        rep = reputation.get(fac) or {}
        vec[off + 0] = float(rep.get("favor", 0.0))
        vec[off + 1] = float(rep.get("wrath", 0.0))
        vec[off + 2] = float(rep.get("favor_rank", 0.0))
        vec[off + 3] = float(rep.get("wrath_rank", 0.0))
        off += _FACTION_FIELDS

    vec[off + 0] = 1.0 if state.get("in_combat") else 0.0
    vec[off + 1] = 1.0 if state.get("paused") else 0.0
    vec[off + 2] = float(state.get("edict_days_remaining", -1.0))
    return vec
