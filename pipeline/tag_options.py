"""Tag each Act 1 dialogue option along faction-relevant semantic axes (uses API).

Reads ``out/options.jsonl`` and asks Claude to score each player option on four
axes in [-2, 2] -- ruthless<->merciful, lawful<->chaotic, honor-bound<->pragmatic,
deferential<->defiant -- plus a ``faction_signal`` and a ``confidence``. Output is
validated with pydantic and written to ``out/tags.json`` as ``"conv:node" -> tags``.

Requires ANTHROPIC_API_KEY. Offline stages (extract_options.py, build_corpus.py)
run without a key; this stage exits 2 if the key is absent.

Example usage::

    export ANTHROPIC_API_KEY=sk-...
    C:\\Python311\\python.exe H:\\RL\\pipeline\\tag_options.py --limit 5   # cheap test
    C:\\Python311\\python.exe H:\\RL\\pipeline\\tag_options.py             # full run
    C:\\Python311\\python.exe H:\\RL\\pipeline\\tag_options.py --batch     # Message Batches API
"""
from __future__ import annotations

import argparse
import json
import sys

from concurrent.futures import ThreadPoolExecutor

from _common import (
    AXES,
    FACTIONS,
    OLLAMA_MODEL,
    TAGS_JSON,
    OptionTags,
    extract_json,
    load_options,
    ollama_chat,
    option_key,
)

MAX_TOKENS = 1024

SYSTEM_PROMPT = (
    "You are a game-writing analyst for the CRPG Tyranny. You read a single "
    "player dialogue option and judge its MEANING along fixed semantic axes. "
    "Judge the speech-act and stance, not the surface wording. Respond with a "
    "single JSON object and nothing else."
)

_INSTRUCTIONS = f"""Score this Tyranny player dialogue option on four axes, each an
integer in [-2, 2]:
- ruthless_merciful: -2 = ruthless/cruel, 0 = neutral, +2 = merciful/compassionate
- lawful_chaotic: -2 = lawful/order-respecting, 0 = neutral, +2 = chaotic/rule-breaking
- honor_pragmatic: -2 = honor-bound/principled, 0 = neutral, +2 = pragmatic/expedient
- deferential_defiant: -2 = deferential/submissive, 0 = neutral, +2 = defiant/challenging

Also provide:
- faction_signal: which faction the stance most serves, one of {list(FACTIONS)}
  (Disfavored = lawful, honor-bound, disciplined; ScarletChorus = chaotic, ruthless,
  anything-goes; Rebels = defiant against Kyros; Anarchist = tears down all authority;
  None = no clear signal)
- confidence: float in [0, 1]

Return ONLY JSON: {{"ruthless_merciful": int, "lawful_chaotic": int,
"honor_pragmatic": int, "deferential_defiant": int, "faction_signal": str,
"confidence": float}}"""


def build_prompt(text: str) -> str:
    return f'{_INSTRUCTIONS}\n\nOPTION TEXT:\n"""{text}"""'


def _parse_tags(raw: str) -> dict:
    data = extract_json(raw)
    return OptionTags(**data).model_dump()


def _tag_one(rec: dict, model: str) -> tuple[str, dict | None]:
    try:
        raw = ollama_chat(SYSTEM_PROMPT, build_prompt(rec["text"]),
                          model=model, json_mode=True, num_predict=MAX_TOKENS)
        return option_key(rec), _parse_tags(raw)
    except Exception as exc:  # noqa: BLE001 - report and continue
        print(f"  ! {option_key(rec)}: {exc}", file=sys.stderr)
        return option_key(rec), None


def tag_all(options: list[dict], model: str, workers: int) -> dict[str, dict]:
    tags: dict[str, dict] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, rec_tags in pool.map(lambda r: _tag_one(r, model), options):
            done += 1
            if rec_tags is not None:
                tags[key] = rec_tags
            if done % 25 == 0:
                print(f"  tagged {done}/{len(options)}")
    return tags


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="Tag only the first N options.")
    ap.add_argument("--model", default=OLLAMA_MODEL, help="Ollama model to use.")
    ap.add_argument("--workers", type=int, default=2, help="Concurrent requests.")
    ap.add_argument("--out", type=str, default=str(TAGS_JSON))
    args = ap.parse_args(argv)

    options = load_options()
    if args.limit is not None:
        options = options[: args.limit]
    print(f"tagging {len(options)} options with {args.model} (workers={args.workers})")

    tags = tag_all(options, args.model, args.workers)

    from pathlib import Path

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(tags, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(tags)} tag records to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
