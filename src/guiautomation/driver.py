"""Mouse and keyboard driver. The only module that imports pyautogui, and only lazily.

Checked against PyAutoGUI 0.9.54 on Windows: ``moveTo`` and ``click`` position the cursor with
``SetCursorPos`` and do not clamp, so negative and secondary-monitor coordinates work. Button
events carry no move flag, so they land at the cursor. ``scroll`` never moves the cursor, so
this driver moves it first.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import time
from collections.abc import Callable, Sequence
from ctypes import wintypes
from typing import Any, Protocol

from guiautomation import screen

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x2
_KEYEVENTF_UNICODE = 0x4
_TYPE_CHUNK = 16  # Characters typed between checks of the abort hotkey and failsafe.
_UNICODE_CHUNK_PAUSE = 0.01


class FailSafeAbort(Exception):
    """The PyAutoGUI failsafe fired; the run must stop as aborted."""


class AbortRequested(Exception):
    """The abort hotkey was pressed during a driver action."""


class DriverError(Exception):
    """The driver could not perform an action."""


class Driver(Protocol):
    def move(self, x: int, y: int) -> None: ...

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None: ...

    def drag(self, x: int, y: int, to_x: int, to_y: int, duration: float) -> None: ...

    def type_text(self, text: str) -> None: ...

    def press_key(self, key: str) -> None: ...

    def hotkey(self, keys: Sequence[str]) -> None: ...

    def scroll(self, clicks: int, x: int | None = None, y: int | None = None) -> None: ...

    def failsafe_triggered(self) -> bool: ...


class _MouseInput(ctypes.Structure):
    # Unused, but the largest union member, so it sets the size Windows expects.
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _KeyboardInput(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _InputUnion(ctypes.Union):
    _fields_ = (("mi", _MouseInput), ("ki", _KeyboardInput))


class _Input(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("union", _InputUnion))


def _unicode_events(text: str) -> ctypes.Array[_Input]:
    """Build a key down and key up for each UTF-16 code unit of the text."""
    encoded = text.encode("utf-16-le", "surrogatepass")
    units = struct.unpack(f"<{len(encoded) // 2}H", encoded)
    events = (_Input * (len(units) * 2))()
    for index, unit in enumerate(units):
        for offset, flags in ((0, _KEYEVENTF_UNICODE), (1, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP)):
            event = events[index * 2 + offset]
            event.type = _INPUT_KEYBOARD
            event.union.ki.wScan = unit
            event.union.ki.dwFlags = flags
    return events


def _load_pyautogui() -> Any:
    # DPI awareness must come first: importing pyautogui sets a weaker awareness mode.
    screen.enable_dpi_awareness()
    import pyautogui

    return pyautogui


def _load_user32() -> Any:
    if sys.platform != "win32":
        raise DriverError("typing this text is only supported on Windows")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT
    return user32


class PyAutoGuiDriver:
    """Driver backed by PyAutoGUI, with its failsafe left on."""

    def __init__(
        self,
        module: Any = None,
        user32: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        abort: Callable[[], bool] = lambda: False,
    ) -> None:
        self._module = module
        self._user32 = user32
        self._sleep = sleep
        self._abort = abort

    def _gui(self) -> Any:
        if self._module is None:
            self._module = _load_pyautogui()
        self._module.FAILSAFE = True
        return self._module

    def _call(self, function: str, *args: Any, **kwargs: Any) -> Any:
        gui = self._gui()
        try:
            return getattr(gui, function)(*args, **kwargs)
        except gui.FailSafeException as exc:
            raise FailSafeAbort(str(exc)) from exc

    def failsafe_triggered(self) -> bool:
        """Return True if the cursor is on a failsafe point."""
        gui = self._gui()
        return bool(gui.FAILSAFE) and tuple(gui.position()) in gui.FAILSAFE_POINTS

    def _check_stop(self) -> None:
        if self._abort():
            raise AbortRequested("abort hotkey pressed")
        if self.failsafe_triggered():
            raise FailSafeAbort("cursor is on a failsafe point")

    def move(self, x: int, y: int) -> None:
        self._call("moveTo", x, y)

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> None:
        interval = 0.05 if clicks > 1 else 0.0
        self._call("click", x=x, y=y, clicks=clicks, interval=interval, button=button)

    def drag(self, x: int, y: int, to_x: int, to_y: int, duration: float) -> None:
        self._call("moveTo", x, y)
        try:
            self._call("dragTo", to_x, to_y, duration=duration, button="left")
        except FailSafeAbort:
            self._release_left_button()
            raise

    def _release_left_button(self) -> None:
        # mouseUp checks the failsafe before releasing, so with the cursor still in a corner
        # it would raise and leave the button held. The check is off only for this one call.
        gui = self._gui()
        gui.FAILSAFE = False
        try:
            gui.mouseUp(button="left", _pause=False)
        finally:
            gui.FAILSAFE = True

    def type_text(self, text: str) -> None:
        gui = self._gui()
        if text.isascii() and all(gui.isValidKey(char) for char in text):
            for start in range(0, len(text), _TYPE_CHUNK):
                self._check_stop()
                self._call("write", text[start : start + _TYPE_CHUNK], interval=0.01, _pause=False)
        else:
            self._type_unicode(text)

    def _type_unicode(self, text: str) -> None:
        """Send text PyAutoGUI cannot type as Unicode key events; the clipboard is not used."""
        user32 = self._user32 if self._user32 is not None else _load_user32()
        normalized = text.replace("\r\n", "\r").replace("\n", "\r")  # Enter produces "\r".
        for start in range(0, len(normalized), _TYPE_CHUNK):
            self._check_stop()
            events = _unicode_events(normalized[start : start + _TYPE_CHUNK])
            if user32.SendInput(len(events), events, ctypes.sizeof(_Input)) != len(events):
                raise DriverError("Windows blocked the keyboard input")
            self._sleep(_UNICODE_CHUNK_PAUSE)

    def _normalize_key(self, key: str) -> str:
        name = key.lower() if len(key) > 1 else key
        if not self._gui().isValidKey(name):
            raise DriverError(f"unknown key: {key}")
        return name

    def press_key(self, key: str) -> None:
        self._call("press", self._normalize_key(key))

    def hotkey(self, keys: Sequence[str]) -> None:
        self._call("hotkey", *[self._normalize_key(key) for key in keys])

    def scroll(self, clicks: int, x: int | None = None, y: int | None = None) -> None:
        if x is not None and y is not None:
            self._call("moveTo", x, y)
        self._call("scroll", clicks)
