"""AC1, AC3: GUI behavior that does not need a display."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fakes import FakeDriver

from guiautomation.abort import AbortHotkey
from guiautomation.gui.logic import (
    GuidedBridge,
    Region,
    StepList,
    capture_filename,
    describe_step,
    drag_to_region,
    fields_for,
    overlay_geometry,
    step_from_form,
    step_to_form,
    to_canvas,
)
from guiautomation.model import Automation, Step, StepType, ValidationError, validate_image_path
from guiautomation.runner import Confirmation, Status, StepResult
from guiautomation.screen import Monitor

DESKTOP = Monitor(0, -1920, -200, 3840, 1280)


def key(name: str) -> Step:
    return Step(StepType.PRESS_KEY, key=name)


def names(steps: StepList) -> list[str]:
    return [step.key for step in steps.steps]


def test_add_appends_or_inserts_after_selection() -> None:
    steps = StepList()
    assert steps.add(key("a")) == 0
    assert steps.add(key("c")) == 1
    assert steps.add(key("b"), after=0) == 1
    assert names(steps) == ["a", "b", "c"]


def test_replace_changes_the_step_in_place() -> None:
    steps = StepList([key("a"), key("b")])
    assert steps.replace(1, key("z")) == 1
    assert names(steps) == ["a", "z"]


def test_delete_keeps_a_sensible_selection() -> None:
    steps = StepList([key("a"), key("b")])
    assert steps.delete(1) == 0
    assert steps.delete(0) is None
    assert steps.steps == []


def test_move_up_and_down_stop_at_the_edges() -> None:
    steps = StepList([key("a"), key("b"), key("c")])
    assert steps.move_up(0) == 0
    assert steps.move_down(2) == 2
    assert steps.move_up(2) == 1
    assert names(steps) == ["a", "c", "b"]
    assert steps.move_down(0) == 1
    assert names(steps) == ["c", "a", "b"]


def test_step_list_edits_the_shared_list() -> None:
    backing: list[Step] = []
    StepList(backing).add(key("a"))
    assert backing == [key("a")]


@pytest.mark.parametrize("kind", list(StepType))
def test_every_step_type_has_form_fields(kind: StepType) -> None:
    assert any(spec.name == "description" for spec in fields_for(kind))


@pytest.mark.parametrize(
    "step",
    [
        Step(StepType.CLICK, x=-10, y=20),
        Step(StepType.CLICK, image="images/a.png", confidence=0.8, timeout=3.0),
        Step(StepType.DRAG, x=1, y=2, to_x=3, to_y=4, duration=0.5),
        Step(StepType.TYPE_TEXT, text=" spaced ", x=1, y=2),
        Step(StepType.TYPE_TEXT, env_var="APP_SECRET"),
        Step(StepType.HOTKEY, keys=("ctrl", "shift", "s")),
        Step(StepType.SCROLL, clicks=-2),
        Step(StepType.WAIT_SECONDS, seconds=1.5),
        Step(StepType.ASSERT_IMAGE_VISIBLE, image="a.png"),
    ],
    ids=lambda s: s.type.value,
)
def test_form_round_trip(step: Step) -> None:
    assert step_from_form(step.type, step_to_form(step)) == step


def test_blank_form_fields_are_unset() -> None:
    step = step_from_form(StepType.CLICK, {"x": " 5 ", "y": "6", "image": "", "timeout": ""})
    assert step == Step(StepType.CLICK, x=5, y=6)


@pytest.mark.parametrize(
    ("kind", "form", "expected"),
    [
        (StepType.CLICK, {"x": "abc", "y": "1"}, "whole number"),
        (StepType.WAIT_SECONDS, {"seconds": "soon"}, "must be a number"),
        (StepType.CLICK, {}, "needs a target"),
        (StepType.TYPE_TEXT, {"text": "password=abc"}, "looks like a secret"),
        (StepType.WAIT_FOR_IMAGE, {"image": "../a.png"}, "inside"),
    ],
)
def test_form_errors_are_clear(kind: StepType, form: dict, expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        step_from_form(kind, form)


def test_hotkey_form_accepts_plus_or_comma() -> None:
    step = step_from_form(StepType.HOTKEY, {"keys": "ctrl, alt+del"})
    assert step.keys == ("ctrl", "alt", "del")


def test_editing_a_secret_step_keeps_its_flag() -> None:
    previous = Step(StepType.TYPE_TEXT, env_var="A", secret=True)
    assert step_from_form(StepType.TYPE_TEXT, {"env_var": "B"}, previous).secret is True


def test_switching_a_secret_step_to_text_drops_its_flag() -> None:
    previous = Step(StepType.TYPE_TEXT, env_var="A", secret=True)
    assert step_from_form(StepType.TYPE_TEXT, {"text": "hi"}, previous).secret is False


def test_describe_shows_env_var_name_only() -> None:
    assert "$APP_SECRET" in describe_step(Step(StepType.TYPE_TEXT, env_var="APP_SECRET"))


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (Step(StepType.CLICK, x=-1, y=2), "(-1, 2)"),
        (Step(StepType.CLICK, image="a.png"), "image a.png"),
        (Step(StepType.DRAG, x=1, y=2, to_x=3, to_y=4), "to (3, 4)"),
        (Step(StepType.HOTKEY, keys=("ctrl", "c")), "ctrl+c"),
        (Step(StepType.WAIT_SECONDS, seconds=2), "2 s"),
        (Step(StepType.PRESS_KEY, key="a", description="why"), "why  (press key: a)"),
    ],
)
def test_describe_step(step: Step, expected: str) -> None:
    assert expected in describe_step(step)


def test_overlay_geometry_uses_tk_offset_form_for_negatives() -> None:
    # "-1920" alone would mean "from the right edge" to Tk; "+-1920" is the left offset.
    assert overlay_geometry(DESKTOP) == "3840x1280+-1920+-200"


def test_to_canvas_converts_negative_coordinates() -> None:
    assert to_canvas(-1920, -200, DESKTOP) == (0, 0)
    assert to_canvas(0, 0, DESKTOP) == (1920, 200)


def test_drag_to_region_normalizes_direction() -> None:
    assert drag_to_region(-100, -50, -200, -150, DESKTOP) == Region(-200, -150, 100, 100)


def test_drag_to_region_spans_monitors() -> None:
    assert drag_to_region(-100, 10, 100, 60, DESKTOP) == Region(-100, 10, 200, 50)


def test_drag_to_region_clamps_to_the_desktop() -> None:
    assert drag_to_region(-3000, -500, -1900, -180, DESKTOP) == Region(-1920, -200, 20, 20)


def test_tiny_drag_is_ignored() -> None:
    assert drag_to_region(10, 10, 12, 12, DESKTOP) is None


def test_capture_filename_is_a_safe_ignored_path() -> None:
    name = capture_filename(datetime(2026, 1, 2, 3, 4, 5, 6))
    assert name == "images/20260102-030405-000006.capture.png"
    validate_image_path(name)


def test_bridge_delivers_the_answer_to_the_worker() -> None:
    bridge = GuidedBridge()
    answers: list[Confirmation] = []
    result = StepResult(1, StepType.CLICK, Status.PASSED)
    worker = threading.Thread(
        target=lambda: answers.append(bridge.confirm(key("a"), result)), daemon=True
    )
    worker.start()
    kind, payload = bridge.events.get(timeout=2)
    assert kind == "confirm"
    assert payload[1] is result
    bridge.answer(Confirmation.FAIL)
    worker.join(timeout=2)
    assert answers == [Confirmation.FAIL]


def test_bridge_stops_waiting_when_aborted() -> None:
    bridge = GuidedBridge(abort=lambda: True, poll=0.001)
    result = StepResult(1, StepType.CLICK, Status.PASSED)
    assert bridge.confirm(key("a"), result) is Confirmation.STOP


class FakeRoot:
    """Records after() callbacks; no Tk window exists."""

    def __init__(self) -> None:
        self.visible = True
        self.pending: list[tuple[int, object]] = []

    def withdraw(self) -> None:
        self.visible = False

    def deiconify(self) -> None:
        self.visible = True

    def after(self, delay, callback) -> None:
        self.pending.append((delay, callback))

    def run_pending(self) -> None:
        pending, self.pending = self.pending, []
        for _, callback in pending:
            callback()


@pytest.fixture
def gui(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The tkinter-using modules, with dialogs replaced. No window is ever created."""
    pytest.importorskip("tkinter")
    from guiautomation.gui import app, capture, guided

    errors: list[str] = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda _t, text: errors.append(text))
    return SimpleNamespace(app=app, capture=capture, guided=guided, errors=errors)


def make_builder(gui: SimpleNamespace, tmp_path: Path):
    builder = gui.app.BuilderApp.__new__(gui.app.BuilderApp)
    builder.root = FakeRoot()
    builder._path = tmp_path / "t.json"
    builder._automation = Automation(steps=[key("a")], base_dir=tmp_path)
    builder._clip_delay = SimpleNamespace(get=lambda: "No delay")
    return builder


def fail(*args, **kwargs):
    raise RuntimeError("cannot build")


def test_overlay_failure_restores_the_builder(gui, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gui.app.screen, "virtual_desktop", lambda: DESKTOP)
    monkeypatch.setattr(gui.app, "RegionOverlay", fail)
    builder = make_builder(gui, tmp_path)
    dialog = MagicMock()
    restored: list[bool] = []
    builder.capture(dialog, lambda _p: None, lambda: restored.append(True))
    assert builder.root.visible is False
    builder.root.run_pending()
    assert builder.root.visible is True
    assert restored == [True]
    assert gui.errors == ["cannot build"]


def test_overlay_destroys_a_half_built_window(gui, monkeypatch) -> None:
    window = MagicMock()
    window.attributes.side_effect = gui.capture.tk.TclError("no alpha")
    monkeypatch.setattr(gui.capture.tk, "Toplevel", lambda _root: window)
    with pytest.raises(gui.capture.tk.TclError):
        gui.capture.RegionOverlay(MagicMock(), DESKTOP, lambda _r: None)
    window.destroy.assert_called_once()


def test_guided_build_failure_restores_the_builder(gui, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(gui.app, "GuidedRun", fail)
    monkeypatch.setattr(gui.app.tk, "Toplevel", MagicMock())
    monkeypatch.setattr(gui.app.tk, "Text", MagicMock())
    builder = make_builder(gui, tmp_path)
    builder._guided_run()
    assert builder.root.visible is True
    assert builder.root.pending == []


def make_guided(gui: SimpleNamespace):
    run = gui.guided.GuidedRun.__new__(gui.guided.GuidedRun)
    run._root = FakeRoot()
    run._window = MagicMock()
    run._label = MagicMock()
    run._automation = Automation(steps=[key("a")])
    run._hotkey = AbortHotkey(is_pressed=lambda: False)
    run._driver = FakeDriver()
    run._bridge = GuidedBridge()
    run.reports = []
    run._on_finished = run.reports.append
    return run


def test_error_while_polling_finishes_the_run(gui) -> None:
    run = make_guided(gui)
    run._label.configure.side_effect = RuntimeError("widget gone")
    run._bridge.events.put(
        ("confirm", (key("a"), StepResult(1, StepType.PRESS_KEY, Status.PASSED)))
    )
    run._poll()
    assert run.reports == ["Error: widget gone"]
    assert run._hotkey.is_set()  # A worker still running is told to stop.
    run._window.destroy.assert_called_once()


def test_finish_survives_a_window_that_is_already_gone(gui) -> None:
    run = make_guided(gui)
    run._window.destroy.side_effect = gui.guided.tk.TclError("gone")
    run._finish("report")
    assert run.reports == ["report"]


def test_failure_to_start_finishes_the_run(gui, monkeypatch) -> None:
    run = make_guided(gui)
    monkeypatch.setattr(gui.guided.threading, "Thread", fail)
    run.start()
    assert run.reports == ["Error: cannot build"]


def test_answer_waits_for_the_window_to_settle(gui) -> None:
    run = make_guided(gui)
    run._answer(Confirmation.PASS)
    run._window.withdraw.assert_called_once()
    assert run._bridge._answers.empty()
    assert run._root.pending[0][0] == gui.guided._SETTLE_MS
    run._root.run_pending()
    assert run._bridge._answers.get_nowait() is Confirmation.PASS


def test_guided_confirm_wait_notices_the_failsafe(gui) -> None:
    run = make_guided(gui)
    assert run._should_stop() is False
    run._driver.in_corner = lambda: True
    assert run._should_stop() is True


def test_grab_retries_until_the_window_is_viewable(gui) -> None:
    window = MagicMock()
    window.grab_set.side_effect = [gui.app.tk.TclError("not viewable"), None]
    gui.app.grab_when_viewable(window)
    delay, callback, *args = window.after.call_args.args
    assert delay == gui.app._GRAB_RETRY_MS
    callback(*args)
    assert window.grab_set.call_count == 2
    assert window.after.call_count == 1


def test_grab_gives_up_after_its_retries(gui) -> None:
    window = MagicMock()
    window.grab_set.side_effect = gui.app.tk.TclError("not viewable")
    gui.app.grab_when_viewable(window, retries=0)
    window.after.assert_not_called()
