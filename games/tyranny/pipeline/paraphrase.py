"""Generate meaning-preserving paraphrase variants for each option (uses API).

For every option in ``out/options.jsonl`` asks Claude for N paraphrases that keep
the meaning and speech-act, preserve proper nouns, vary wording/register, and stay
within +/-40% of the original length. Output is ``out/variants_raw.json`` mapping
``"conv:node" -> [variant strings]``.

Requires ANTHROPIC_API_KEY (exits 2 if absent).

Example usage::

    export ANTHROPIC_API_KEY=sk-...
    C:\\Python311\\python.exe H:\\RL\\games\\tyranny\\pipeline\\paraphrase.py --limit 5 --n 6
    C:\\Python311\\python.exe H:\\RL\\games\\tyranny\\pipeline\\paraphrase.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor

from _common import (
    OLLAMA_MODEL,
    VARIANTS_RAW_JSON,
    extract_json,
    load_options,
    ollama_chat,
    option_key,
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
        f"Produce exactly {n} distinct paraphrases of the dialogue option below. "
        f"Each must preserve the exact meaning, intent, and speech-act; only the "
        f"wording differs. Keep proper nouns intact.\n"
        f'Respond with a JSON object of EXACTLY this shape: '
        f'{{"paraphrases": ["<text1>", "<text2>", ...]}} containing {n} strings.\n\n'
        f'ORIGINAL OPTION:\n"""{text}"""'
    )


def _parse_variants(raw: str, n: int) -> list[str]:
    data = extract_json(raw)
    # Local models under format=json emit varied shapes: prefer {"paraphrases":[...]},
    # else the first list value, else (the messy case) the dict keys are the texts.
    if isinstance(data, dict):
        if isinstance(data.get("paraphrases"), list):
            data = data["paraphrases"]
        else:
            lists = [v for v in data.values() if isinstance(v, list)]
            if lists:
                data = lists[0]
            else:
                texts = [str(k) for k in data.keys() if len(str(k).strip()) > 3]
                texts += [str(v) for v in data.values() if len(str(v).strip()) > 3]
                data = texts
    if not isinstance(data, list):
        raise ValueError("expected a JSON array")
    seen: set[str] = set()
    variants: list[str] = []
    for v in data:
        s = str(v).strip()
        if s and s not in seen:
            seen.add(s)
            variants.append(s)
    return variants[:n]


def _paraphrase_one(rec: dict, n: int, model: str) -> tuple[str, list[str] | None]:
    try:
        raw = ollama_chat(SYSTEM_PROMPT, build_prompt(rec["text"], n),
                          model=model, json_mode=True, temperature=0.8,
                          num_predict=MAX_TOKENS)
        return option_key(rec), _parse_variants(raw, n)
    except Exception as exc:  # noqa: BLE001
        print(f"  ! {option_key(rec)}: {exc}", file=sys.stderr)
        return option_key(rec), None


def paraphrase(options: list[dict], n: int, model: str, workers: int) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, variants in pool.map(lambda r: _paraphrase_one(r, n, model), options):
            done += 1
            if variants:
                out[key] = variants
            if done % 25 == 0:
                print(f"  paraphrased {done}/{len(options)}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=6, help="Variants per option (default 6).")
    ap.add_argument("--limit", type=int, default=None, help="Only the first N options.")
    ap.add_argument("--model", default=OLLAMA_MODEL, help="Ollama model to use.")
    ap.add_argument("--workers", type=int, default=2, help="Concurrent requests.")
    ap.add_argument("--out", type=str, default=str(VARIANTS_RAW_JSON))
    args = ap.parse_args(argv)

    options = load_options()
    if args.limit is not None:
        options = options[: args.limit]
    print(f"paraphrasing {len(options)} options x {args.n} variants with {args.model}")

    variants = paraphrase(options, args.n, args.model, args.workers)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(variants, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote variants for {len(variants)} options to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
