"""Unit tests for window capture. No running game required.

The PrintWindow path is exercised against a throwaway tkinter window filled
with a solid red canvas: we launch it from Python, capture it by handle, and
assert the red channel dominates. When tkinter is unavailable (e.g. a headless
CI runner without Tk), the live-capture test is skipped; the pure-numpy
``is_mostly_black`` tests always run.
"""

from __future__ import annotations

import numpy as np
import pytest

from crpg_rle.core.capture import capture_window, is_mostly_black

try:
    import tkinter

    _TK_AVAILABLE = True
except Exception:  # noqa: BLE001 - Tk missing or no display
    _TK_AVAILABLE = False


# --------------------------------------------------------------------------
# is_mostly_black
# --------------------------------------------------------------------------


def test_is_mostly_black_all_zero():
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    assert is_mostly_black(frame) is True


def test_is_mostly_black_all_white():
    frame = np.full((10, 10, 3), 255, dtype=np.uint8)
    assert is_mostly_black(frame) is False


def test_is_mostly_black_respects_threshold():
    frame = np.full((10, 10, 3), 5, dtype=np.uint8)
    assert is_mostly_black(frame, threshold=8) is True
    assert is_mostly_black(frame, threshold=4) is False


def test_is_mostly_black_empty_frame():
    assert is_mostly_black(np.empty((0, 0, 3), dtype=np.uint8)) is True


def test_capture_invalid_hwnd_raises():
    with pytest.raises(ValueError):
        capture_window(0)


# --------------------------------------------------------------------------
# Live capture against a tkinter window
# --------------------------------------------------------------------------


def _settle(root, canvas):
    """Pump the Tk event loop until the window has actually painted.

    A single ``update()`` often returns before the canvas fill has been drawn,
    yielding a blank (white) capture, so pump a few cycles with a short pause.
    """
    import time

    for _ in range(20):
        root.update_idletasks()
        root.update()
        time.sleep(0.02)

    hwnd = int(canvas.winfo_id())
    parent = _win32gui().GetParent(hwnd)
    return parent if parent else hwnd


def _win32gui():
    import win32gui

    return win32gui


@pytest.mark.skipif(not _TK_AVAILABLE, reason="tkinter not available")
def test_capture_red_tk_window():
    root = tkinter.Tk()
    try:
        root.title("crpg_rle capture test")
        root.geometry("200x150+100+100")
        canvas = tkinter.Canvas(
            root, width=200, height=150, highlightthickness=0, bg="#ff0000"
        )
        canvas.pack(fill="both", expand=True)
        # winfo_id is the canvas child HWND; walk up to the toplevel window.
        hwnd = _settle(root, canvas)
        frame = capture_window(hwnd)
    finally:
        root.destroy()

    assert frame.ndim == 3
    assert frame.shape[2] == 3
    assert frame.dtype == np.uint8
    assert frame.shape[0] > 0 and frame.shape[1] > 0

    # Red channel should dominate green and blue on a solid-red fill.
    r, g, b = frame[..., 0].mean(), frame[..., 1].mean(), frame[..., 2].mean()
    assert r > g + 40, f"red not dominant over green: r={r:.1f} g={g:.1f}"
    assert r > b + 40, f"red not dominant over blue: r={r:.1f} b={b:.1f}"


@pytest.mark.skipif(not _TK_AVAILABLE, reason="tkinter not available")
def test_capture_red_tk_window_resized():
    root = tkinter.Tk()
    try:
        root.geometry("200x150+120+120")
        canvas = tkinter.Canvas(
            root, width=200, height=150, highlightthickness=0, bg="#ff0000"
        )
        canvas.pack(fill="both", expand=True)
        hwnd = _settle(root, canvas)
        frame = capture_window(hwnd, out_size=(64, 48))
    finally:
        root.destroy()

    assert frame.shape == (48, 64, 3)
