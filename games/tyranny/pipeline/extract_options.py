"""Extract Act 1 player dialogue options from Tyranny conversation data (NO API).

Walks every ``*.conversation`` file in a game conversation directory, finds each
``<FlowChartNode xsi:type="PlayerResponseNode">`` and resolves its display text
from the sibling stringtable (the ``<Entry>`` whose ``<ID>`` equals the node's
``<NodeID>``). Empty / whitespace options are skipped.

Output: ``games/tyranny/pipeline/out/options.jsonl`` -- one JSON object per line::

    {"key": {"conv": "<basename>", "node": <int>},
     "text": "<option text>", "text_sha256": "<hex>"}

Example usage::

    C:\\Python311\\python.exe H:\\RL\\games\\tyranny\\pipeline\\extract_options.py
    C:\\Python311\\python.exe H:\\RL\\games\\tyranny\\pipeline\\extract_options.py --game-dir "D:\\other\\08_vendrienswell"

This script requires NO API key and produces real output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

DEFAULT_GAME_DIR = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\Tyranny"
    r"\Data\data\design\conversations\08_vendrienswell"
)


def _derive_text_dir(game_dir: Path) -> Path:
    """Map a design-conversations dir to its exported-localized-text dir.

    Tyranny stores flow-chart nodes under ``.../data/design/conversations/<leaf>``
    and the localized strings under
    ``.../data/exported/localized/en/text/conversations/<leaf>``. Some installs
    nest ``data`` under an ``assets`` folder; the substring swap below is agnostic
    to that prefix because it only rewrites the ``design/conversations`` segment.
    """
    parts = list(game_dir.parts)
    # Find the 'design' -> 'conversations' pair and swap the design subtree.
    for i in range(len(parts) - 1):
        if parts[i].lower() == "design" and parts[i + 1].lower() == "conversations":
            new = (
                parts[:i]
                + ["exported", "localized", "en", "text", "conversations"]
                + parts[i + 2 :]
            )
            return Path(*new)
    # Fallback: assume caller passes a design-style path; try naive replace.
    swapped = str(game_dir).replace(
        r"design\conversations", r"exported\localized\en\text\conversations"
    ).replace(
        "design/conversations", "exported/localized/en/text/conversations"
    )
    return Path(swapped)


def _read_xml(path: Path) -> ET.Element:
    """Parse XML tolerating a UTF-8 BOM."""
    text = path.read_text(encoding="utf-8-sig")
    return ET.fromstring(text)


def _load_stringtable(path: Path) -> dict[int, str]:
    """Return {EntryID: DefaultText} for a .stringtable file."""
    if not path.exists():
        return {}
    root = _read_xml(path)
    table: dict[int, str] = {}
    for entry in root.iter("Entry"):
        eid_el = entry.find("ID")
        txt_el = entry.find("DefaultText")
        if eid_el is None or eid_el.text is None:
            continue
        try:
            eid = int(eid_el.text.strip())
        except ValueError:
            continue
        table[eid] = txt_el.text if (txt_el is not None and txt_el.text) else ""
    return table


def _player_nodes(root: ET.Element) -> list[int]:
    """Return NodeIDs of every PlayerResponseNode in a conversation."""
    node_ids: list[int] = []
    for node in root.iter("FlowChartNode"):
        if node.get(XSI_TYPE) != "PlayerResponseNode":
            continue
        nid_el = node.find("NodeID")
        if nid_el is None or nid_el.text is None:
            continue
        try:
            node_ids.append(int(nid_el.text.strip()))
        except ValueError:
            continue
    return node_ids


def extract(game_dir: Path, text_dir: Path) -> list[dict]:
    """Extract all player options across every conversation in game_dir."""
    records: list[dict] = []
    conv_files = sorted(game_dir.glob("*.conversation"))
    for conv_path in conv_files:
        basename = conv_path.stem
        try:
            root = _read_xml(conv_path)
        except ET.ParseError:
            continue
        node_ids = _player_nodes(root)
        if not node_ids:
            continue
        table = _load_stringtable(text_dir / f"{basename}.stringtable")
        for nid in node_ids:
            text = (table.get(nid) or "").strip()
            if not text:
                continue
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            records.append(
                {
                    "key": {"conv": basename, "node": nid},
                    "text": text,
                    "text_sha256": sha,
                }
            )
    return records


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--game-dir",
        type=Path,
        default=DEFAULT_GAME_DIR,
        help="Directory of .conversation files (default: Tyranny 08_vendrienswell).",
    )
    ap.add_argument(
        "--text-dir",
        type=Path,
        default=None,
        help="Directory of .stringtable files (default: derived from --game-dir).",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "out" / "options.jsonl",
        help="Output JSONL path.",
    )
    args = ap.parse_args(argv)

    game_dir: Path = args.game_dir
    text_dir: Path = args.text_dir or _derive_text_dir(game_dir)

    if not game_dir.is_dir():
        print(f"ERROR: game-dir not found: {game_dir}", file=sys.stderr)
        return 1

    records = extract(game_dir, text_dir)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"game-dir : {game_dir}")
    print(f"text-dir : {text_dir}")
    print(f"options  : {len(records)} written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
