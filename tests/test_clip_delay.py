"""The clip delay: its choices, the countdown, and cutting a clip from a frozen screen."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fakes import FakeScheduler

from guiautomation.gui.logic import (
    CLIP_DELAYS,
    ClipCountdown,
    Region,
    clip_delay_seconds,
    countdown_text,
    crop_box,
)
from guiautomation.screen import Monitor


def make_countdown(seconds: int) -> tuple[ClipCountdown, FakeScheduler, list]:
    scheduler = FakeScheduler()
    events: list = []
    countdown = ClipCountdown(
        seconds, scheduler.schedule, scheduler.cancel, events.append, lambda: events.append("done")
    )
    return countdown, scheduler, events


def test_the_default_clip_delay_is_none() -> None:
    label, seconds = CLIP_DELAYS[0]
    assert seconds == 0
    assert clip_delay_seconds(label) == 0


def test_clip_delay_choices_are_none_3_5_and_10_seconds() -> None:
    assert [seconds for _, seconds in CLIP_DELAYS] == [0, 3, 5, 10]
    assert clip_delay_seconds("5 seconds") == 5


def test_an_unknown_clip_delay_label_means_no_delay() -> None:
    assert clip_delay_seconds("") == 0
    assert clip_delay_seconds("a while") == 0


def test_countdown_text_shows_the_time_left_and_how_to_cancel() -> None:
    text = countdown_text(3)
    assert "3 s" in text
    assert "Esc" in text


def test_countdown_ticks_once_a_second_then_finishes() -> None:
    countdown, scheduler, events = make_countdown(3)
    countdown.start()
    assert events == [3]
    scheduler.advance(999)
    assert events == [3]
    scheduler.advance(1)
    assert events == [3, 2]
    scheduler.advance(1000)
    assert events == [3, 2, 1]
    scheduler.advance(1000)
    assert events == [3, 2, 1, "done"]
    assert scheduler.waiting == 0


@pytest.mark.parametrize("seconds", [0, -2])
def test_countdown_with_nothing_to_count_finishes_at_once(seconds: int) -> None:
    countdown, scheduler, events = make_countdown(seconds)
    countdown.start()
    assert events == ["done"]
    assert scheduler.waiting == 0


def test_cancelling_a_countdown_stops_it_for_good() -> None:
    countdown, scheduler, events = make_countdown(5)
    countdown.start()
    scheduler.advance(2000)
    assert countdown.cancel() is True
    assert scheduler.cancelled and scheduler.waiting == 0
    scheduler.advance(10_000)
    assert events == [5, 4, 3]


def test_cancelling_twice_or_after_the_end_reports_nothing_to_cancel() -> None:
    countdown, scheduler, _events = make_countdown(1)
    countdown.start()
    assert countdown.cancel() is True
    assert countdown.cancel() is False

    finished, scheduler, events = make_countdown(1)
    finished.start()
    scheduler.advance(1000)
    assert events == [1, "done"]
    assert finished.cancel() is False


def test_starting_a_countdown_twice_counts_once() -> None:
    countdown, scheduler, events = make_countdown(2)
    countdown.start()
    countdown.start()
    scheduler.advance(2000)
    assert events == [2, 1, "done"]


def test_crop_box_allows_for_monitors_left_of_and_above_the_primary() -> None:
    desktop = Monitor(0, -1920, -200, 3840, 1280)
    assert crop_box(Region(-1920, -200, 10, 20), desktop) == (0, 0, 10, 20)
    assert crop_box(Region(100, 50, 30, 40), desktop) == (2020, 250, 2050, 290)


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch):
    """The capture module with every tkinter widget replaced. No window is ever created."""
    pytest.importorskip("tkinter")
    from guiautomation.gui import capture

    monkeypatch.setattr(capture.tk, "Toplevel", MagicMock())
    monkeypatch.setattr(capture.tk, "Label", MagicMock())
    return capture


def open_countdown(capture, seconds: int) -> tuple[SimpleNamespace, FakeScheduler, list[str]]:
    scheduler = FakeScheduler()
    root = SimpleNamespace(after=scheduler.schedule, after_cancel=scheduler.cancel)
    ended: list[str] = []
    window = capture.CountdownWindow(
        root, seconds, lambda: ended.append("done"), lambda: ended.append("cancelled")
    )
    return window, scheduler, ended


def test_countdown_window_shows_the_time_left_then_closes_before_the_clip(capture) -> None:
    window, scheduler, ended = open_countdown(capture, 3)
    scheduler.advance(2000)
    window._label.configure.assert_called_with(text=countdown_text(1))
    window._window.destroy.assert_not_called()
    scheduler.advance(1000)
    window._window.destroy.assert_called_once()
    assert ended == ["done"]


def test_countdown_window_cancels_once_on_esc_or_a_click(capture) -> None:
    window, scheduler, ended = open_countdown(capture, 3)
    escape = dict(call.args for call in window._window.bind.call_args_list)["<Escape>"]
    click = dict(call.args for call in window._label.bind.call_args_list)["<Button-1>"]
    escape(None)
    click(None)
    scheduler.advance(10_000)
    window._window.destroy.assert_called_once()
    assert ended == ["cancelled"]


def test_countdown_window_destroys_a_half_built_window(capture) -> None:
    capture.tk.Label.side_effect = capture.tk.TclError("no label")
    with pytest.raises(capture.tk.TclError):
        open_countdown(capture, 3)
    capture.tk.Toplevel.return_value.destroy.assert_called_once()
