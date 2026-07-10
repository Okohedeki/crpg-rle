"""Capture the client area of a game window as an RGB frame.

Uses the Win32 ``PrintWindow`` API with the ``PW_RENDERFULLCONTENT`` flag,
which renders DirectX 11 surfaces on Windows 10 (build 19045) even when the
window is occluded or off-screen. Frames come back as ``(H, W, 3)`` ``uint8``
RGB arrays.

GDI handles are a finite, process-wide resource: leaking a bitmap or device
context per frame crashes a long training run. Every allocation here is paired
with an unconditional release in a ``finally`` block.
"""

from __future__ import annotations

import ctypes
import logging

import numpy as np
import win32gui
import win32ui

logger = logging.getLogger(__name__)

# PrintWindow flag: render the full window contents including DX/child surfaces.
# Not exposed by win32con on all pywin32 builds, so define it explicitly.
_PW_RENDERFULLCONTENT = 2


def capture_window(
    hwnd: int, out_size: tuple[int, int] | None = None
) -> np.ndarray:
    """Capture the client area of ``hwnd`` as an ``(H, W, 3)`` uint8 RGB array.

    ``out_size`` is ``(width, height)``; when given the frame is resized to it.
    On PrintWindow failure a black frame of the correct size is returned (with a
    logged warning) rather than raising, so a transient capture glitch does not
    abort a run. Raises :class:`ValueError` if ``hwnd`` is not a valid window.
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        raise ValueError(f"invalid window handle: {hwnd!r}")

    # Client rect is DPI-correct and excludes borders/title bar.
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    width = right - left
    height = bottom - top

    def _black() -> np.ndarray:
        h, w = (out_size[1], out_size[0]) if out_size else (height, width)
        return np.zeros((max(h, 1), max(w, 1), 3), dtype=np.uint8)

    if width <= 0 or height <= 0:
        logger.warning(
            "window %d has non-positive client size %dx%d; returning black frame",
            hwnd,
            width,
            height,
        )
        return _resize(_black(), out_size)

    window_dc = None
    mem_dc = None
    src_dc = None
    bitmap = None
    try:
        window_dc = win32gui.GetDC(hwnd)
        src_dc = win32ui.CreateDCFromHandle(window_dc)
        mem_dc = src_dc.CreateCompatibleDC()

        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(src_dc, width, height)
        mem_dc.SelectObject(bitmap)

        result = ctypes.windll.user32.PrintWindow(
            hwnd, mem_dc.GetSafeHdc(), _PW_RENDERFULLCONTENT
        )
        if result != 1:
            logger.warning(
                "PrintWindow failed for window %d (returned %d); returning black frame",
                hwnd,
                result,
            )
            return _resize(_black(), out_size)

        bmp_info = bitmap.GetInfo()
        bmp_bits = bitmap.GetBitmapBits(True)
        # win32ui returns bottom-up BGRA rows; reshape then convert.
        arr = np.frombuffer(bmp_bits, dtype=np.uint8)
        arr = arr.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
        rgb = arr[:, :, 2::-1]  # BGRA -> RGB (drop alpha, reverse BGR)
        rgb = np.ascontiguousarray(rgb)
        return _resize(rgb, out_size)
    finally:
        # Release in reverse order of acquisition; guard each independently.
        if bitmap is not None:
            try:
                win32gui.DeleteObject(bitmap.GetHandle())
            except Exception:  # noqa: BLE001 - best-effort GDI cleanup
                pass
        if mem_dc is not None:
            try:
                mem_dc.DeleteDC()
            except Exception:  # noqa: BLE001
                pass
        if src_dc is not None:
            try:
                src_dc.DeleteDC()
            except Exception:  # noqa: BLE001
                pass
        if window_dc is not None:
            try:
                win32gui.ReleaseDC(hwnd, window_dc)
            except Exception:  # noqa: BLE001
                pass


def _resize(frame: np.ndarray, out_size: tuple[int, int] | None) -> np.ndarray:
    """Resize ``frame`` to ``out_size`` (width, height) if requested."""
    if out_size is None:
        return frame
    if (frame.shape[1], frame.shape[0]) == out_size:
        return frame
    import cv2

    return cv2.resize(frame, out_size, interpolation=cv2.INTER_AREA)


def is_mostly_black(frame: np.ndarray, threshold: float = 8) -> bool:
    """Return whether ``frame``'s mean brightness is at or below ``threshold``.

    Useful for detecting loading screens or a window that has not yet rendered.
    """
    if frame.size == 0:
        return True
    return bool(frame.mean() <= threshold)
