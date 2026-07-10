"""Build a small hand-authored demo corpus to prove the live randomizer without
API calls. The FULL corpus is produced by the tag/paraphrase/verify pipeline
(needs ANTHROPIC_API_KEY). This demo covers a handful of Act 1 options with
meaning-preserving paraphrases so the swap+shuffle can be verified end-to-end.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# (conv, node, original_text, tags, paraphrase variants [meaning-preserving])
DEMO = [
    ("08_cv_scarletchoruscamp_lantry_trial", 4,
     '"Fine, let\'s have this trial you want so much."',
     {"ruthless_merciful": 0, "lawful_chaotic": 1, "honor_pragmatic": 1, "deferential_defiant": 1},
     [
         '"Very well, let\'s proceed with the trial you\'re so set on."',
         '"So be it. We\'ll have your trial, then."',
         '"Alright. Let\'s get on with this trial you crave."',
         '"If you insist on a trial, then let\'s have it."',
     ]),
    ("08_cv_scarletchoruscamp_lantry_trial", 2,
     '"Release this prisoner at once, I\'m taking him into my custody."',
     {"ruthless_merciful": 0, "lawful_chaotic": -2, "honor_pragmatic": -1, "deferential_defiant": 1},
     [
         '"Hand this prisoner over now — he\'s coming into my custody."',
         '"I am taking custody of this prisoner. Release him immediately."',
         '"Turn the prisoner over to me at once."',
         '"Free him now; he answers to me from here on."',
     ]),
    ("08_cv_scarletchoruscamp_lantry_trial", 70,
     '"He obviously has useful information, yet you\'re willing to let him die for sport?"',
     {"ruthless_merciful": 1, "lawful_chaotic": 0, "honor_pragmatic": 2, "deferential_defiant": 0},
     [
         '"He clearly knows something useful, and you\'d let him die for entertainment?"',
         '"This man holds valuable intelligence, yet you\'d waste him on sport?"',
         '"You\'d throw away everything he knows just for a spectacle?"',
     ]),
    ("08_cv_scarletchoruscamp_lantry_trial", 58,
     '"We need the prisoner alive, this is a terrible idea."',
     {"ruthless_merciful": 1, "lawful_chaotic": 0, "honor_pragmatic": 1, "deferential_defiant": 0},
     [
         '"Keeping the prisoner alive matters — this plan is a mistake."',
         '"This is a terrible idea; we need him breathing."',
         '"Killing him would be foolish. We need the prisoner alive."',
     ]),
]

AXES = ["ruthless_merciful", "lawful_chaotic", "honor_pragmatic", "deferential_defiant"]

# Faction preference directions over the axes (sign = preferred direction).
ALIGNMENT = {
    "Disfavored": {"ruthless_merciful": -1, "lawful_chaotic": -1, "honor_pragmatic": -1, "deferential_defiant": -1},
    "ScarletChorus": {"ruthless_merciful": -1, "lawful_chaotic": 1, "honor_pragmatic": 1, "deferential_defiant": 1},
    "Rebels": {"ruthless_merciful": 1, "lawful_chaotic": 1, "honor_pragmatic": 0, "deferential_defiant": 1},
    "Anarchist": {"ruthless_merciful": 0, "lawful_chaotic": 2, "honor_pragmatic": 1, "deferential_defiant": 2},
}


def main() -> None:
    options = {}
    for conv, node, text, tags, variants in DEMO:
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        options[f"{conv}:{node}"] = {
            "text_sha256": sha,
            "tags": tags,
            "variants": variants,
        }
    corpus = {
        "version": "act1_demo",
        "axes": AXES,
        "alignment_matrix": ALIGNMENT,
        "options": options,
    }
    out = Path(__file__).resolve().parents[1] / "corpora" / "act1_demo" / "corpus.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(corpus, indent=2), encoding="utf-8")
    print(f"wrote {out} with {len(options)} options")


if __name__ == "__main__":
    main()
