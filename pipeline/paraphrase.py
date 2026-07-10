"""Generate meaning-preserving paraphrase variants for each option (uses API).

For every option in ``out/options.jsonl`` asks Claude for N paraphrases that keep
the meaning and speech-act, preserve proper nouns, vary wording/register, and stay
within +/-40% of the original length. Output is ``out/variants_raw.json`` mapping
``"conv:node" -> [variant strings]``.

Requires ANTHROPIC_API_KEY (exits 2 if absent).

Example usage::

    export ANTHROPIC_API_KEY=sk-...
    C:\\Python311\\python.exe H:\\RL\\pipeline\\paraphrase.py --limit 5 --n 6
    C:\\Python311\\python.exe H:\\RL\\pipeline\\paraphrase.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _common import (
    MODEL_ID,
    VARIANTS_RAW_JSON,
    extract_json,
    load_options,
    message_text,
    option_key,
    require_client,
)

MAX_TOKENS = 1024

SYSTEM_PROMPT = (
    "You paraphrase player dialogue options for the CRPG Tyranny. Each paraphrase "
    "must preserve the EXACT meaning, intent, tone, and speech-act of the original "
    "so that its faction/moral reading is unchanged -- only the surface wording "
    "differs. Keep every proper noun (names, factions, places, titles) intact. Vary "
    "vocabulary, phrasing, and register. Keep length within +/-40% of the original. "
    "Respond with a single JSON array of strings and nothing else."
)


def build_prompt(text: str, n: int) -> str:
    return (
        f"Produce exactly {n} distinct paraphrases of the dialogue option below.\n"
        f"Return ONLY a JSON array of {n} strings.\n\n"
        f'ORIGINAL OPTION:\n"""{text}"""'
    )


def _parse_variants(raw: str, n: int) -> list[str]:
    data = extract_json(raw)
    if not isinstance(data, list):
        raise ValueError("expected a JSON array")
    variants = [str(v).strip() for v in data if str(v).strip()]
    return variants[:n]


def paraphrase(client, options: list[dict], n: int) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i, rec in enumerate(options, 1):
        resp = client.messages.create(
            model=MODEL_ID,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(rec["text"], n)}],
        )
        try:
            out[option_key(rec)] = _parse_variants(message_text(resp), n)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {option_key(rec)}: {exc}", file=sys.stderr)
        if i % 25 == 0:
            print(f"  paraphrased {i}/{len(options)}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=6, help="Variants per option (default 6).")
    ap.add_argument("--limit", type=int, default=None, help="Only the first N options.")
    ap.add_argument("--out", type=str, default=str(VARIANTS_RAW_JSON))
    args = ap.parse_args(argv)

    options = load_options()
    if args.limit is not None:
        options = options[: args.limit]
    print(f"paraphrasing {len(options)} options x {args.n} variants with {MODEL_ID}")

    client = require_client()  # exits 2 if no API key
    variants = paraphrase(client, options, args.n)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(variants, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote variants for {len(variants)} options to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
