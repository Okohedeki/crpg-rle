"""Offline tests for the dialogue-randomizer pipeline (NO API).

Covers: extract_options XML parsing, the pure tag-consistency predicate, and the
runtime Corpus loader. None of these touch the Anthropic API.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the pipeline scripts importable (they live outside the crpg_rle package).
PIPELINE_DIR = Path(__file__).resolve().parents[2] / "games" / "tyranny" / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

import extract_options  # noqa: E402
from verify_tags import tags_consistent  # noqa: E402
from crpg_rle.adapters.tyranny.dialogue.corpus import Corpus  # noqa: E402


# --- extract_options ---------------------------------------------------------
_CONVERSATION = """<?xml version="1.0" encoding="utf-8"?>
<ConversationData xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Nodes>
    <FlowChartNode xsi:type="TalkNode">
      <NodeID>0</NodeID>
    </FlowChartNode>
    <FlowChartNode xsi:type="PlayerResponseNode">
      <NodeID>4</NodeID>
    </FlowChartNode>
    <FlowChartNode xsi:type="PlayerResponseNode">
      <NodeID>5</NodeID>
    </FlowChartNode>
  </Nodes>
</ConversationData>
"""

_STRINGTABLE = """﻿<?xml version="1.0" encoding="utf-8"?>
<StringTableFile xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <Entries>
    <Entry><ID>0</ID><DefaultText>NPC talks first.</DefaultText></Entry>
    <Entry><ID>4</ID><DefaultText>"Show them no mercy."</DefaultText></Entry>
    <Entry><ID>5</ID><DefaultText>   </DefaultText></Entry>
  </Entries>
</StringTableFile>
"""


def _make_game_dirs(tmp_path: Path) -> tuple[Path, Path]:
    game = tmp_path / "conv"
    text = tmp_path / "text"
    game.mkdir()
    text.mkdir()
    (game / "sample.conversation").write_text(_CONVERSATION, encoding="utf-8")
    (text / "sample.stringtable").write_text(_STRINGTABLE, encoding="utf-8")
    return game, text


def test_extract_options_parses_player_nodes(tmp_path):
    game, text = _make_game_dirs(tmp_path)
    records = extract_options.extract(game, text)

    # Node 0 is a TalkNode (not a player option); node 5 is whitespace -> skipped.
    assert len(records) == 1
    rec = records[0]
    assert rec["key"] == {"conv": "sample", "node": 4}
    assert rec["text"] == '"Show them no mercy."'
    assert len(rec["text_sha256"]) == 64  # sha256 hex digest


def test_extract_options_bom_and_missing_stringtable(tmp_path):
    game, text = _make_game_dirs(tmp_path)
    # BOM handled (stringtable starts with ﻿): text resolved despite BOM.
    records = extract_options.extract(game, text)
    assert records[0]["text"] == '"Show them no mercy."'

    # A conversation whose stringtable is absent yields no records (no crash).
    (game / "orphan.conversation").write_text(_CONVERSATION, encoding="utf-8")
    records2 = extract_options.extract(game, text)
    assert len(records2) == 1  # orphan contributes nothing


def test_extract_options_main_writes_jsonl(tmp_path):
    game, text = _make_game_dirs(tmp_path)
    out = tmp_path / "out" / "options.jsonl"
    rc = extract_options.main(
        ["--game-dir", str(game), "--text-dir", str(text), "--out", str(out)]
    )
    assert rc == 0
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["key"]["node"] == 4


# --- tags_consistent ---------------------------------------------------------
def _tags(rm, lc, hp, dd):
    return {
        "ruthless_merciful": rm,
        "lawful_chaotic": lc,
        "honor_pragmatic": hp,
        "deferential_defiant": dd,
    }


def test_tags_consistent_identical():
    t = _tags(-2, 1, 0, 2)
    assert tags_consistent(t, t) is True


def test_tags_consistent_small_delta_ok():
    orig = _tags(-2, 1, 0, 2)
    # Meaningful axes keep their sign; the |orig|==0 axis (honor) may drift by 1.
    retag = _tags(-2, 1, 1, 2)
    assert tags_consistent(orig, retag) is True


def test_tags_consistent_weakening_to_zero_rejected():
    # A meaningful axis (|orig|>=1) that re-tags to 0 loses its sign -> reject,
    # even though the delta is only 1.
    orig = _tags(0, 1, 0, 0)
    assert tags_consistent(orig, _tags(0, 0, 0, 0)) is False


def test_tags_consistent_sign_flip_rejected():
    orig = _tags(2, 0, 0, 0)      # merciful
    retag = _tags(1, 0, 0, 0)     # same positive sign, delta 1 -> consistent
    assert tags_consistent(orig, retag) is True
    # Real flip: original positive, retag negative on a meaningful axis.
    assert tags_consistent(_tags(1, 0, 0, 0), _tags(-1, 0, 0, 0)) is False


def test_tags_consistent_large_delta_rejected():
    orig = _tags(-2, 0, 0, 0)
    retag = _tags(0, 0, 0, 0)  # delta 2 on axis 0 -> reject
    assert tags_consistent(orig, retag) is False


def test_tags_consistent_zero_axis_ignores_sign():
    # |original| == 0 imposes no sign requirement, only the delta bound.
    orig = _tags(0, 0, 0, 0)
    assert tags_consistent(orig, _tags(1, -1, 1, -1)) is True
    assert tags_consistent(orig, _tags(2, 0, 0, 0)) is False  # delta 2


# --- Corpus ------------------------------------------------------------------
_FIXTURE_CORPUS = {
    "version": "test_v1",
    "axes": [
        "ruthless_merciful",
        "lawful_chaotic",
        "honor_pragmatic",
        "deferential_defiant",
    ],
    "factions": ["Disfavored", "None"],
    "alignment_matrix": {
        "Disfavored": {
            "ruthless_merciful": -1,
            "lawful_chaotic": -1,
            "honor_pragmatic": -1,
            "deferential_defiant": -1,
        },
        "None": {
            "ruthless_merciful": 0,
            "lawful_chaotic": 0,
            "honor_pragmatic": 0,
            "deferential_defiant": 0,
        },
    },
    "options": {
        "sample:4": {
            "text_sha256": "abc123",
            "tags": {
                "ruthless_merciful": -2,
                "lawful_chaotic": -1,
                "honor_pragmatic": -1,
                "deferential_defiant": -1,
                "faction_signal": "Disfavored",
                "confidence": 0.9,
            },
            "variants": ["Give them no quarter.", "Spare none of them."],
        }
    },
}


def _write_fixture(tmp_path: Path) -> Path:
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(_FIXTURE_CORPUS), encoding="utf-8")
    return p


def test_corpus_load_and_get(tmp_path):
    corpus = Corpus.load(_write_fixture(tmp_path))
    assert corpus.version == "test_v1"
    assert len(corpus) == 1
    assert "sample:4" in corpus

    got = corpus.get("sample", 4)
    assert got is not None
    assert got["tags"]["faction_signal"] == "Disfavored"
    assert got["variants"] == ["Give them no quarter.", "Spare none of them."]
    # Never exposes the original text -- only tags + variants.
    assert "text" not in got

    assert corpus.get("sample", 999) is None
    assert corpus.get("missing", 4) is None


def test_corpus_metadata(tmp_path):
    corpus = Corpus.load(_write_fixture(tmp_path))
    assert corpus.axes[0] == "ruthless_merciful"
    assert corpus.alignment_matrix["Disfavored"]["lawful_chaotic"] == -1


def test_corpus_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        Corpus.load(tmp_path / "nope.json")


def test_corpus_rejects_malformed():
    with pytest.raises(ValueError):
        Corpus({"version": "x"})  # missing axes/alignment_matrix/options

    bad_align = json.loads(json.dumps(_FIXTURE_CORPUS))
    del bad_align["alignment_matrix"]["Disfavored"]["lawful_chaotic"]
    with pytest.raises(ValueError):
        Corpus(bad_align)
