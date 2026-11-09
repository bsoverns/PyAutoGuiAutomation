"""Shared safety net: no test may reach the real desktop."""

from __future__ import annotations

import pytest

from guiautomation import driver, screen


def _no_real_pyautogui():
    raise AssertionError("a test tried to reach the real desktop")


@pytest.fixture(autouse=True)
def _protect_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(driver, "_load_pyautogui", _no_real_pyautogui)
    monkeypatch.setattr(driver, "_load_user32", _no_real_pyautogui)
    monkeypatch.setattr(screen, "_dpi_done", True)
