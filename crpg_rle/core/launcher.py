"""Launch and manage a game process instance for the RL environment.

Each :class:`GameProcess` owns one running copy of the game executable. The
launcher wires up the environment variables and Unity command-line arguments the
BepInEx bridge mod expects, then locates the game's top-level window so the rest
of the pipeline can capture frames from it.

Multiple instances can run side by side: each is keyed by ``instance_id`` and
listens on a distinct bridge port (``5555 + instance_id`` by default).
"""

from __future__ import annotations

import logging
import os
import subprocess
import time

import win32gui
import win32process

logger = logging.getLogger(__name__)

_DEFAULT_BASE_PORT = 5555


class GameProcess:
    """A single launched instance of the game executable.

    Wraps a :class:`subprocess.Popen`, tracks its bridge port and instance id,
    and provides window discovery plus lifecycle management (liveness, kill,
    context-manager cleanup).
    """

    def __init__(
        self,
        exe_path: str,
        instance_id: int = 0,
        port: int | None = None,
        window: tuple[int, int] = (1280, 720),
        extra_args: list[str] | None = None,
        log_dir: str | None = None,
    ) -> None:
        self.exe_path = os.path.abspath(exe_path)
        self.instance_id = instance_id
        self.port = port if port is not None else _DEFAULT_BASE_PORT + instance_id
        self.window = window
        self.extra_args = list(extra_args) if extra_args else []
        self.log_dir = log_dir

        self._proc: subprocess.Popen | None = None
        self._hwnd: int | None = None

    # -- launching ---------------------------------------------------------

    def launch(self) -> subprocess.Popen:
        """Start the executable and return the :class:`~subprocess.Popen`.

        Sets the ``CRPG_INSTANCE_ID`` / ``CRPG_BRIDGE_PORT`` environment
        variables the bridge mod reads, and passes Unity screen arguments plus
        an optional ``-logFile`` and any caller-supplied ``extra_args``.
        """
        if self._proc is not None:
            raise RuntimeError("process already launched")

        width, height = self.window
        args: list[str] = [
            self.exe_path,
            "-screen-width",
            str(width),
            "-screen-height",
            str(height),
            "-screen-fullscreen",
            "0",
        ]
        if self.log_dir is not None:
            log_path = os.path.join(self.log_dir, f"game_{self.instance_id}.log")
            args += ["-logFile", log_path]
        args += self.extra_args

        env = os.environ.copy()
        env["CRPG_INSTANCE_ID"] = str(self.instance_id)
        env["CRPG_BRIDGE_PORT"] = str(self.port)

        cwd = os.path.dirname(self.exe_path)
        logger.info(
            "launching instance %d: %s (port=%d, cwd=%s)",
            self.instance_id,
            self.exe_path,
            self.port,
            cwd,
        )
        self._proc = subprocess.Popen(args, cwd=cwd, env=env)
        return self._proc

    # -- window discovery --------------------------------------------------

    def find_window(self, timeout: float = 120) -> int:
        """Poll for this process's visible, titled top-level window.

        Returns the window handle (HWND). Raises :class:`RuntimeError` if a
        window titled ``Fatal error`` (a Unity crash dialog) appears, or
        :class:`TimeoutError` if no suitable window is found within ``timeout``.
        """
        if self._proc is None:
            raise RuntimeError("process not launched")
        target_pid = self._proc.pid
        deadline = time.monotonic() + timeout

        while True:
            found: list[int] = []
            fatal: list[str] = []

            def _callback(hwnd: int, _extra: object) -> bool:
                if not win32gui.IsWindowVisible(hwnd):
                    return True
                try:
                    _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
                except Exception:  # noqa: BLE001 - window may vanish mid-enum
                    return True
                if pid != target_pid:
                    return True
                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return True
                if "Fatal error" in title:
                    fatal.append(title)
                    return True
                # Require a real rendered client area — during boot the game
                # briefly owns a 0x0 splash window that captures as black.
                try:
                    left, top, right, bottom = win32gui.GetClientRect(hwnd)
                    if (right - left) <= 0 or (bottom - top) <= 0:
                        return True
                except Exception:  # noqa: BLE001
                    return True
                found.append(hwnd)
                return True

            win32gui.EnumWindows(_callback, None)

            if fatal:
                raise RuntimeError(
                    f"instance {self.instance_id} showed a fatal error dialog: "
                    f"{fatal[0]!r}"
                )
            if found:
                self._hwnd = found[0]
                logger.info(
                    "instance %d window found: hwnd=%d", self.instance_id, self._hwnd
                )
                return self._hwnd

            if not self.alive:
                raise RuntimeError(
                    f"instance {self.instance_id} exited before a window appeared"
                )
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"no window for instance {self.instance_id} within {timeout}s"
                )
            time.sleep(0.5)

    # -- state -------------------------------------------------------------

    @property
    def pid(self) -> int | None:
        """The OS process id, or ``None`` if not launched."""
        return self._proc.pid if self._proc is not None else None

    @property
    def hwnd(self) -> int | None:
        """The cached window handle from :meth:`find_window`, if discovered."""
        return self._hwnd

    @property
    def alive(self) -> bool:
        """Whether the process is currently running."""
        if self._proc is None:
            return False
        try:
            import psutil

            return psutil.pid_exists(self._proc.pid) and self._proc.poll() is None
        except Exception:  # noqa: BLE001 - fall back to Popen.poll
            return self._proc.poll() is None

    # -- teardown ----------------------------------------------------------

    def kill(self, grace: float = 5.0) -> None:
        """Terminate the process, escalating to a hard kill after ``grace``.

        Idempotent: safe to call when the process was never launched or has
        already exited.
        """
        if self._proc is None:
            return
        if self._proc.poll() is not None:
            return

        logger.info("terminating instance %d (pid=%s)", self.instance_id, self._proc.pid)
        try:
            self._proc.terminate()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            logger.warning(
                "instance %d did not exit in %.1fs; killing", self.instance_id, grace
            )
            try:
                self._proc.kill()
            except OSError:
                pass
            try:
                self._proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                logger.error("instance %d could not be killed", self.instance_id)

    def close(self) -> None:
        """Alias for :meth:`kill`."""
        self.kill()

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> GameProcess:
        if self._proc is None:
            self.launch()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
