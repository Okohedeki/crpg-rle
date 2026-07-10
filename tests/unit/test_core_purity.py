"""The generic core must contain zero game-specific (Tyranny) logic (brief §2)."""
import pathlib

import pytest

CORE_DIR = pathlib.Path(__file__).resolve().parents[2] / "crpg_rle" / "core"


def test_core_has_no_tyranny_references():
    offenders = []
    for py in CORE_DIR.rglob("*.py"):
        text = py.read_text(encoding="utf-8").lower()
        if "tyranny" in text or "adapters.tyranny" in text:
            offenders.append(py.name)
    assert not offenders, f"core modules reference Tyranny: {offenders}"


def test_core_imports_without_adapter():
    import importlib
    import sys

    for mod in list(sys.modules):
        if mod.startswith("crpg_rle.adapters"):
            del sys.modules[mod]
    # Importing core must not pull in any adapter.
    importlib.import_module("crpg_rle.core.env")
    importlib.import_module("crpg_rle.core.modes")
    importlib.import_module("crpg_rle.core.spaces")
    assert not any(m.startswith("crpg_rle.adapters.tyranny") for m in sys.modules), \
        "importing core pulled in the Tyranny adapter"
