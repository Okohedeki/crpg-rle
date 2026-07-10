"""Blind re-tag each paraphrase and reject meaning-drifting variants (uses API).

Safeguard for build-brief section 9: a paraphrase that flips a tag corrupts the
label. For each accepted paraphrase we re-tag it WITHOUT showing the original text
or its tags, then compare to the option's original tags via ``tags_consistent``.

Accept a variant iff, for every axis with |original| >= 1, the re-tag has the same
sign, AND |delta| <= 1 on all four axes. Otherwise reject.

Output ``out/variants_verified.json`` maps ``"conv:node" ->
{"tags": <orig>, "variants": [accepted...]}``. Options with < 2 accepted variants
fall back to just the original text and are flagged in the stdout report.

Requires ANTHROPIC_API_KEY (exits 2 if absent).

Example usage::

    export ANTHROPIC_API_KEY=sk-...
    C:\\Python311\\python.exe H:\\RL\\pipeline\\verify_tags.py --limit 5
    C:\\Python311\\python.exe H:\\RL\\pipeline\\verify_tags.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _common import (
    AXES,
    MODEL_ID,
    OptionTags,
    TAGS_JSON,
    VARIANTS_RAW_JSON,
    VARIANTS_VERIFIED_JSON,
    extract_json,
    load_options,
    message_text,
    option_key,
    require_client,
)
from tag_options import SYSTEM_PROMPT as TAG_SYSTEM_PROMPT
from tag_options import build_prompt as build_tag_prompt


def tags_consistent(original: dict, retag: dict) -> bool:
    """Return True iff a re-tag preserves the original's meaning.

    Pure function (no API). For every axis with |original| >= 1 the re-tag must
    share the same sign, and every axis delta must be <= 1 in magnitude. Only the
    four numeric axes are compared; faction_signal/confidence are ignored.
    """
    for axis in AXES:
        o = int(original[axis])
        r = int(retag[axis])
        if abs(o - r) > 1:
            return False
        if abs(o) >= 1 and (o > 0) != (r > 0):
            # Sign flip on a meaningful axis (0 is treated as no required sign).
            return False
    return True


def _retag(client, variant_text: str) -> dict:
    """Blind re-tag: the model sees only the variant, never the original/tags."""
    resp = client.messages.create(
        model=MODEL_ID,
        max_tokens=1024,
        system=TAG_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_tag_prompt(variant_text)}],
    )
    data = extract_json(message_text(resp))
    return OptionTags(**data).model_dump()


def verify(
    client,
    options: list[dict],
    tags: dict[str, dict],
    raw_variants: dict[str, list[str]],
) -> tuple[dict[str, dict], dict]:
    verified: dict[str, dict] = {}
    n_variants_seen = 0
    n_variants_accepted = 0
    n_flagged = 0

    by_key = {option_key(r): r for r in options}
    for key, rec in by_key.items():
        orig_tags = tags.get(key)
        if orig_tags is None:
            continue  # untagged options can't be verified
        accepted: list[str] = []
        for variant in raw_variants.get(key, []):
            n_variants_seen += 1
            try:
                retag = _retag(client, variant)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {key}: retag failed: {exc}", file=sys.stderr)
                continue
            if tags_consistent(orig_tags, retag):
                accepted.append(variant)
                n_variants_accepted += 1

        if len(accepted) < 2:
            n_flagged += 1
            verified[key] = {"tags": orig_tags, "variants": [rec["text"]], "flagged": True}
        else:
            verified[key] = {"tags": orig_tags, "variants": accepted}

    report = {
        "options": len(verified),
        "variants_seen": n_variants_seen,
        "variants_accepted": n_variants_accepted,
        "acceptance_rate": (n_variants_accepted / n_variants_seen) if n_variants_seen else 0.0,
        "flagged_low_variant": n_flagged,
    }
    return verified, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="Only the first N options.")
    ap.add_argument("--tags", type=str, default=str(TAGS_JSON))
    ap.add_argument("--variants", type=str, default=str(VARIANTS_RAW_JSON))
    ap.add_argument("--out", type=str, default=str(VARIANTS_VERIFIED_JSON))
    args = ap.parse_args(argv)

    options = load_options()
    if args.limit is not None:
        options = options[: args.limit]

    client = require_client()  # exits 2 if no API key (before reading stage inputs)

    tags = json.loads(Path(args.tags).read_text(encoding="utf-8"))
    raw_variants = json.loads(Path(args.variants).read_text(encoding="utf-8"))
    print(f"verifying variants for {len(options)} options with {MODEL_ID}")

    verified, report = verify(client, options, tags, raw_variants)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verified, indent=2, ensure_ascii=False), encoding="utf-8")

    print("--- acceptance report ---")
    print(f"  options verified   : {report['options']}")
    print(f"  variants seen      : {report['variants_seen']}")
    print(f"  variants accepted  : {report['variants_accepted']}")
    print(f"  acceptance rate    : {report['acceptance_rate']:.1%}")
    print(f"  flagged (<2 kept)  : {report['flagged_low_variant']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
