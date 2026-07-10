"""Runtime loader for the frozen Act 1 dialogue corpus (NO API).

The corpus is produced offline by ``pipeline/build_corpus.py`` and consumed here
at episode time. It carries, per option (keyed ``"conv:node"``): the sha256 of the
original text (asset hygiene -- the original text itself is never shipped), the
invariant semantic tags, and the verified paraphrase variants. The C# mod swaps in
a paraphrase and shuffles option order per episode; faction reward reads meaning
via ``alignment_matrix`` + ``axes``.
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_CORPUS = (
    Path(__file__).resolve().parents[4] / "corpora" / "act1_v1" / "corpus.json"
)


class Corpus:
    """Load and validate a frozen dialogue corpus; look options up by key."""

    def __init__(self, data: dict) -> None:
        self._validate(data)
        self._data = data
        self._options: dict[str, dict] = data["options"]

    # -- construction ---------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path | None = None) -> "Corpus":
        p = Path(path) if path is not None else _DEFAULT_CORPUS
        if not p.exists():
            raise FileNotFoundError(
                f"corpus not found: {p}. Build it with pipeline/build_corpus.py."
            )
        return cls(json.loads(p.read_text(encoding="utf-8")))

    @staticmethod
    def _validate(data: dict) -> None:
        for field in ("version", "axes", "alignment_matrix", "options"):
            if field not in data:
                raise ValueError(f"corpus missing required field: {field!r}")
        if not isinstance(data["axes"], list) or not data["axes"]:
            raise ValueError("corpus 'axes' must be a non-empty list")
        if not isinstance(data["options"], dict):
            raise ValueError("corpus 'options' must be an object")
        axes = set(data["axes"])
        for faction, weights in data["alignment_matrix"].items():
            missing = axes - set(weights)
            if missing:
                raise ValueError(
                    f"alignment_matrix[{faction!r}] missing axes: {sorted(missing)}"
                )
        for key, opt in data["options"].items():
            for field in ("text_sha256", "tags", "variants"):
                if field not in opt:
                    raise ValueError(f"option {key!r} missing field: {field!r}")

    # -- lookups --------------------------------------------------------------
    def get(self, conv: str, node: int) -> dict | None:
        """Return ``{'tags': ..., 'variants': [...]}`` for an option, or None."""
        opt = self._options.get(f"{conv}:{node}")
        if opt is None:
            return None
        return {"tags": opt["tags"], "variants": list(opt["variants"])}

    def __contains__(self, key: object) -> bool:
        return key in self._options

    def __len__(self) -> int:
        return len(self._options)

    # -- metadata -------------------------------------------------------------
    @property
    def version(self) -> str:
        return self._data["version"]

    @property
    def axes(self) -> list[str]:
        return list(self._data["axes"])

    @property
    def alignment_matrix(self) -> dict[str, dict[str, int]]:
        return {f: dict(w) for f, w in self._data["alignment_matrix"].items()}
