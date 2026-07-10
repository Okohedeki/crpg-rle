"""Shared helpers for the dialogue-randomizer pipeline (NO API at import time).

Holds the semantic-axis definitions, the pydantic tag schema, option IO, the
Anthropic client bootstrap (with graceful no-key handling), and a small JSON
extraction helper used by every LLM-facing stage.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, Field, field_validator

# --- Model + paths -----------------------------------------------------------
MODEL_ID = "claude-opus-4-8"

PIPELINE_DIR = Path(__file__).resolve().parent
OUT_DIR = PIPELINE_DIR / "out"
OPTIONS_JSONL = OUT_DIR / "options.jsonl"
TAGS_JSON = OUT_DIR / "tags.json"
VARIANTS_RAW_JSON = OUT_DIR / "variants_raw.json"
VARIANTS_VERIFIED_JSON = OUT_DIR / "variants_verified.json"

# --- Semantic axes -----------------------------------------------------------
# The four numeric axes are the invariant meaning of an option. Each is scored
# in [-2, 2]; the left pole is negative, the right pole is positive.
AXES: tuple[str, ...] = (
    "ruthless_merciful",   # -2 ruthless ........ +2 merciful
    "lawful_chaotic",      # -2 lawful ........... +2 chaotic
    "honor_pragmatic",     # -2 honor-bound ...... +2 pragmatic
    "deferential_defiant",  # -2 deferential ...... +2 defiant
)

FACTIONS: tuple[str, ...] = (
    "Disfavored",
    "ScarletChorus",
    "Rebels",
    "Anarchist",
    "None",
)


class OptionTags(BaseModel):
    """Validated tag record for one dialogue option."""

    ruthless_merciful: int = Field(ge=-2, le=2)
    lawful_chaotic: int = Field(ge=-2, le=2)
    honor_pragmatic: int = Field(ge=-2, le=2)
    deferential_defiant: int = Field(ge=-2, le=2)
    faction_signal: str
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("faction_signal")
    @classmethod
    def _known_faction(cls, v: str) -> str:
        if v not in FACTIONS:
            raise ValueError(f"faction_signal must be one of {FACTIONS}, got {v!r}")
        return v

    def axis_dict(self) -> dict[str, int]:
        return {a: getattr(self, a) for a in AXES}


# --- Option IO ---------------------------------------------------------------
def option_key(rec: dict) -> str:
    """Canonical 'conv:node' string key for an option record."""
    return f"{rec['key']['conv']}:{rec['key']['node']}"


def load_options(path: Path = OPTIONS_JSONL) -> list[dict]:
    """Read options.jsonl into a list of records."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run extract_options.py first (no API key needed)."
        )
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def iter_options(path: Path = OPTIONS_JSONL, limit: int | None = None) -> Iterator[dict]:
    recs = load_options(path)
    for i, rec in enumerate(recs):
        if limit is not None and i >= limit:
            return
        yield rec


# --- Anthropic client --------------------------------------------------------
def require_client():
    """Return an anthropic.Anthropic client or exit(2) if no API key is set.

    Import of anthropic is deferred so the offline stages never need it.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY is not set. This stage requires the Anthropic "
            "API.\nExport a key (e.g. `export ANTHROPIC_API_KEY=sk-...`) and re-run.\n"
            "Offline stages (extract_options.py, build_corpus.py) run without a key.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    import anthropic  # local import: optional dependency

    return anthropic.Anthropic()


_JSON_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


def extract_json(text: str):
    """Parse the first JSON object/array embedded in model output."""
    text = text.strip()
    # Strip markdown code fences if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if not m:
            raise
        return json.loads(m.group(0))


def message_text(response) -> str:
    """Concatenate all text blocks of a Messages API response."""
    return "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
