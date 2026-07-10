"""Freeze options + tags + verified variants into a runtime corpus (NO API).

Combines ``out/options.jsonl``, ``out/tags.json`` and ``out/variants_verified.json``
into ``corpora/act1_v1/corpus.json``. Asset hygiene: only the sha256 of each
original option is stored -- never the original text. Paraphrases + tags travel in
the corpus; the C# mod picks a paraphrase and shuffles order per episode.

Example usage::

    C:\\Python311\\python.exe H:\\RL\\pipeline\\build_corpus.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from _common import (
    AXES,
    FACTIONS,
    OPTIONS_JSONL,
    TAGS_JSON,
    VARIANTS_VERIFIED_JSON,
    load_options,
    option_key,
)

VERSION = "act1_v1"
CORPUS_PATH = Path(__file__).resolve().parent.parent / "corpora" / VERSION / "corpus.json"

# Each faction maps preferred axis DIRECTIONS: +1 favors the axis's positive pole,
# -1 favors the negative pole, 0 = the axis carries no signal for that faction.
# Axis poles (from _common.AXES): ruthless(-)/merciful(+), lawful(-)/chaotic(+),
# honor-bound(-)/pragmatic(+), deferential(-)/defiant(+).
ALIGNMENT_MATRIX: dict[str, dict[str, int]] = {
    # Disfavored: Kyros's disciplined legion -- lawful, honor-bound, obedient,
    # and hard but not gratuitously cruel.
    "Disfavored": {
        "ruthless_merciful": -1,   # favor firmness over softness
        "lawful_chaotic": -1,      # lawful/order
        "honor_pragmatic": -1,     # honor-bound
        "deferential_defiant": -1,  # deferential to the chain of command
    },
    # Scarlet Chorus: a chaotic horde -- anything-goes, ruthless, contemptuous of
    # order, and defiant of formal authority.
    "ScarletChorus": {
        "ruthless_merciful": -1,   # ruthless
        "lawful_chaotic": 1,       # chaotic
        "honor_pragmatic": 1,      # pragmatic/expedient
        "deferential_defiant": 1,  # defiant
    },
    # Rebels (Vendrien's Guard): defiant of Kyros's conquest and principled about
    # their homeland; merciful toward their own.
    "Rebels": {
        "ruthless_merciful": 1,    # merciful
        "lawful_chaotic": 0,       # mixed -- order under their own banner
        "honor_pragmatic": -1,     # honor-bound to the cause
        "deferential_defiant": 1,  # defiant of the Overlord
    },
    # Anarchist: tear down every hierarchy -- maximally chaotic and defiant,
    # indifferent to honor.
    "Anarchist": {
        "ruthless_merciful": 0,    # no fixed cruelty/mercy signal
        "lawful_chaotic": 2,       # maximally chaotic
        "honor_pragmatic": 1,      # pragmatic, ends over principles
        "deferential_defiant": 2,  # maximally defiant
    },
    # None: no faction alignment.
    "None": {a: 0 for a in AXES},
}


def build(
    options_path: Path = OPTIONS_JSONL,
    tags_path: Path = TAGS_JSON,
    variants_path: Path = VARIANTS_VERIFIED_JSON,
) -> dict:
    options = load_options(options_path)
    tags = json.loads(tags_path.read_text(encoding="utf-8")) if tags_path.exists() else {}
    verified = (
        json.loads(variants_path.read_text(encoding="utf-8"))
        if variants_path.exists()
        else {}
    )

    out_options: dict[str, dict] = {}
    for rec in options:
        key = option_key(rec)
        tag = tags.get(key)
        if tag is None:
            continue  # only ship options we could tag
        ver = verified.get(key, {})
        # Asset hygiene: never let the ORIGINAL text into the frozen corpus.
        # verify_tags stores the original as a fallback variant for flagged
        # options; drop any variant whose hash matches the original's sha256.
        variants = [
            v
            for v in ver.get("variants", [])
            if hashlib.sha256(v.encode("utf-8")).hexdigest() != rec["text_sha256"]
        ]
        out_options[key] = {
            "text_sha256": rec["text_sha256"],  # hash only -- never the original text
            "tags": tag,
            "variants": variants,
        }

    return {
        "version": VERSION,
        "axes": list(AXES),
        "factions": list(FACTIONS),
        "alignment_matrix": ALIGNMENT_MATRIX,
        "options": out_options,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--options", type=str, default=str(OPTIONS_JSONL))
    ap.add_argument("--tags", type=str, default=str(TAGS_JSON))
    ap.add_argument("--variants", type=str, default=str(VARIANTS_VERIFIED_JSON))
    ap.add_argument("--out", type=str, default=str(CORPUS_PATH))
    args = ap.parse_args(argv)

    corpus = build(Path(args.options), Path(args.tags), Path(args.variants))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(corpus, indent=2, ensure_ascii=False), encoding="utf-8")

    n_opts = len(corpus["options"])
    n_variants = sum(len(o["variants"]) for o in corpus["options"].values())
    n_with_paraphrase = sum(1 for o in corpus["options"].values() if o["variants"])
    print(f"corpus version : {corpus['version']}")
    print(f"options        : {n_opts}")
    print(f"with variants  : {n_with_paraphrase}")
    print(f"total variants : {n_variants}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
