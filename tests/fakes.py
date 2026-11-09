"""Fakes that stand in for the real mouse, keyboard, screen and clock."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from guiautomation.driver import FailSafeAbort
from guiautomation.screen import Match


class FakeDriver:
    """Records every call instead of touching the desktop."""

    def __init__(self, fail_on: str | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self.fail_on = fail_on
        self.error = error or RuntimeError("driver broke")
        self.in_corner = lambda: False

    def _record(self, *call) -> None:
        self.calls.append(call)
        if call[0] == self.fail_on:
            raise self.error

    def move(self, x, y):
        self._record("move", x, y)

    def click(self, x, y, button="left", clicks=1):
        self._record("click", x, y, button, clicks)

    def drag(self, x, y, to_x, to_y, duration):
        self._record("drag", x, y, to_x, to_y, duration)

    def type_text(self, text):
        self._record("type_text", text)

    def press_key(self, key):
        self._record("press_key", key)

    def hotkey(self, keys):
        self._record("hotkey", tuple(keys))

    def scroll(self, clicks, x=None, y=None):
        self._record("scroll", clicks, x, y)

    def failsafe_triggered(self):
        return self.in_corner()


def failsafe_driver() -> FakeDriver:
    return FakeDriver(fail_on="click", error=FailSafeAbort("corner"))


class FakeScreen:
    """Returns a match for image names in ``matches``; others are never found."""

    def __init__(self, matches: dict[str, Match] | None = None, found_after: int = 0) -> None:
        self.matches = matches or {}
        self.found_after = found_after
        self.searches: list[tuple[Path, float]] = []

    def find_image(self, image_path, confidence):
        self.searches.append((image_path, confidence))
        if len(self.searches) <= self.found_after:
            return None
        return self.matches.get(Path(image_path).name)


class FakeClock:
    """A clock that only advances when sleep is called."""

    def __init__(self) -> None:
        self.now = 100.0
        self.slept = 0.0
        self.sleeps = 0

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        self.slept += seconds
        self.sleeps += 1


def match_at(x: int, y: int) -> Match:
    return Match(x, y, x - 5, y - 5, 10, 10, 1.0)


class FakeSct:
    """Mimics mss over a painted BGRA canvas of a whole virtual desktop."""

    def __init__(self, monitors: list[dict], canvas: np.ndarray) -> None:
        self.monitors = monitors
        self.canvas = canvas
        self.grabs: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def grab(self, region: dict) -> np.ndarray:
        self.grabs.append(region)
        desk = self.monitors[0]
        x = region["left"] - desk["left"]
        y = region["top"] - desk["top"]
        return self.canvas[y : y + region["height"], x : x + region["width"]]


class FakeScheduler:
    """Stands in for tkinter's ``after`` and ``after_cancel``. Time moves only in ``advance``."""

    def __init__(self) -> None:
        self.now = 0
        self.cancelled: list[int] = []
        self._next = 0
        self._due: dict[int, tuple[int, object]] = {}

    def schedule(self, milliseconds, callback) -> int:
        self._next += 1
        self._due[self._next] = (self.now + milliseconds, callback)
        return self._next

    def cancel(self, handle) -> None:
        self.cancelled.append(handle)
        self._due.pop(handle, None)

    @property
    def waiting(self) -> int:
        return len(self._due)

    def advance(self, milliseconds: int) -> None:
        """Move time on, running each callback that falls due, in order."""
        end = self.now + milliseconds
        while True:
            ready = [(when, handle) for handle, (when, _) in self._due.items() if when <= end]
            if not ready:
                break
            when, handle = min(ready)
            self.now = when
            self._due.pop(handle)[1]()
        self.now = end
