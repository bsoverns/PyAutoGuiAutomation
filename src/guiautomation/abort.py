"""Abort hotkey (Ctrl+Alt+Shift+Q; Ctrl+Alt+Q alone is AltGr+Q), polled with GetAsyncKeyState in a daemon thread."""

from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from types import TracebackType
from typing import Self

_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_VK_Q = 0x51
_KEY_DOWN = 0x8000


def _hotkey_down() -> bool:
    state = ctypes.windll.user32.GetAsyncKeyState
    return all(state(key) & _KEY_DOWN for key in (_VK_SHIFT, _VK_CONTROL, _VK_MENU, _VK_Q))


class AbortHotkey:
    """Watches the abort hotkey. Does nothing on non-Windows unless given a key checker."""

    def __init__(
        self, is_pressed: Callable[[], bool] | None = None, poll_interval: float = 0.05
    ) -> None:
        self._is_pressed = is_pressed
        self._poll_interval = poll_interval
        self._triggered = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def is_set(self) -> bool:
        """Return True once the hotkey has been pressed."""
        return self._triggered.is_set()

    def trigger(self) -> None:
        """Set the flag as if the hotkey had been pressed."""
        self._triggered.set()

    def start(self) -> None:
        if self._is_pressed is None:
            if sys.platform != "win32":
                return
            self._is_pressed = _hotkey_down
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True, name="abort-hotkey")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _pressed(self) -> bool:
        try:
            return self._is_pressed()
        except Exception:  # noqa: BLE001 - one bad poll must not end abort detection
            return False

    def _poll(self) -> None:
        while not self._stop.wait(self._poll_interval):
            if self._pressed():
                self._triggered.set()
                return

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()
