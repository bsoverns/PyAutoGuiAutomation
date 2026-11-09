"""Looping a test, clipping on an unsaved test, and replacing steps and clips."""

from __future__ import annotations

import functools
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fakes import FakeClock, FakeDriver, FakeScreen
from PIL import Image

from guiautomation import cli
from guiautomation.abort import AbortHotkey
from guiautomation.export import render_script
from guiautomation.gui.logic import (
    Region,
    StepList,
    describe_loops,
    loop_status,
    parse_repeat,
    takes_image,
    with_clip,
)
from guiautomation.model import (
    REPEAT_FOREVER,
    Automation,
    Step,
    StepType,
    ValidationError,
    automation_to_dict,
    load_automation,
    parse_automation,
    save_automation,
)
from guiautomation.runner import Confirmation, Runner, Status, run_automation
from guiautomation.screen import Monitor

KEY = Step(StepType.PRESS_KEY, key="a")
DESKTOP = Monitor(index=0, left=0, top=0, width=100, height=100)


def make_runner(clock: FakeClock | None = None, **kwargs) -> tuple[Runner, FakeDriver]:
    clock = clock or FakeClock()
    driver = FakeDriver()
    runner = Runner(
        Automation(steps=[KEY]),
        driver,
        FakeScreen(),
        sleep=clock.sleep,
        clock=clock.clock,
        **kwargs,
    )
    return runner, driver


# -- saved repeat setting -----------------------------------------------------


def test_repeat_defaults_to_one_and_stays_out_of_the_file() -> None:
    automation = parse_automation('{"version": 1, "steps": []}')
    assert automation.repeat == 1
    assert "repeat" not in automation_to_dict(automation)


@pytest.mark.parametrize("repeat", [REPEAT_FOREVER, 7])
def test_repeat_survives_save_and_load(tmp_path: Path, repeat: int) -> None:
    path = tmp_path / "t.json"
    save_automation(Automation(steps=[KEY], repeat=repeat), path)
    assert load_automation(path).repeat == repeat


@pytest.mark.parametrize("value", ["-1", '"2"', "true", "1.5", "null"])
def test_bad_repeat_is_rejected(value: str) -> None:
    with pytest.raises(ValidationError, match="repeat"):
        parse_automation(f'{{"version": 1, "steps": [], "repeat": {value}}}')


# -- runner -------------------------------------------------------------------


def test_runs_the_requested_number_of_loops() -> None:
    runner, driver = make_runner()
    seen: list[int] = []
    result = runner.run(repeat=3, on_iteration=seen.append)
    assert result.passed
    assert seen == [1, 2, 3]
    assert len(driver.calls) == 3
    assert result.iterations == 3
    assert result.loops_completed == 3
    assert "Loops completed: 3" in result.summary()


def test_only_the_last_loop_is_kept_in_the_result() -> None:
    runner, _ = make_runner()
    assert len(runner.run(repeat=50).steps) == 1


def test_a_single_run_reports_no_loops() -> None:
    runner, _ = make_runner()
    result = runner.run()
    assert result.iterations == 1
    assert "Loops" not in result.summary()


def test_forever_runs_until_aborted() -> None:
    stop = {"now": False}
    runner, driver = make_runner(abort=lambda: stop["now"])

    def on_iteration(number: int) -> None:
        stop["now"] = number == 25

    result = runner.run(repeat=REPEAT_FOREVER, on_iteration=on_iteration)
    assert result.status is Status.ABORTED
    assert result.iterations == 25
    assert result.loops_completed == 24
    assert len(driver.calls) == 24


def test_a_failed_loop_ends_the_looping() -> None:
    answers = iter([Confirmation.PASS, Confirmation.FAIL])
    runner, driver = make_runner()
    result = runner.run(repeat=REPEAT_FOREVER, confirm=lambda _step, _res: next(answers))
    assert result.status is Status.FAILED
    assert result.iterations == 2
    assert result.loops_completed == 1
    assert len(driver.calls) == 2


def test_the_start_delay_happens_once() -> None:
    clock = FakeClock()
    runner, _ = make_runner(clock)
    runner.run(delay=2.0, repeat=4)
    assert clock.slept == pytest.approx(2.0)


def fake_kwargs(clock: FakeClock) -> dict:
    return {
        "driver": FakeDriver(),
        "screen": FakeScreen(),
        "sleep": clock.sleep,
        "clock": clock.clock,
        "abort": lambda: False,
    }


def test_run_automation_uses_the_saved_repeat() -> None:
    automation = Automation(steps=[KEY], repeat=2)
    assert run_automation(automation, **fake_kwargs(FakeClock())).iterations == 2


def test_run_automation_repeat_overrides_the_saved_one() -> None:
    automation = Automation(steps=[KEY], repeat=2)
    assert run_automation(automation, repeat=5, **fake_kwargs(FakeClock())).iterations == 5


@pytest.mark.parametrize("repeat", [-1, 1.5, "2", True])
def test_run_automation_rejects_a_bad_repeat(repeat: object) -> None:
    with pytest.raises(ValidationError, match="repeat"):
        run_automation(Automation(steps=[KEY]), repeat=repeat, **fake_kwargs(FakeClock()))


# -- command line and exported scripts ----------------------------------------


@pytest.fixture
def driver(monkeypatch: pytest.MonkeyPatch) -> FakeDriver:
    fake = FakeDriver()
    clock = FakeClock()
    monkeypatch.setattr(
        cli,
        "run_automation",
        functools.partial(
            run_automation,
            driver=fake,
            screen=FakeScreen(),
            sleep=clock.sleep,
            clock=clock.clock,
            abort=lambda: False,
        ),
    )
    return fake


def write_test(tmp_path: Path, **extra: object) -> str:
    path = tmp_path / "t.json"
    data = {"version": 1, "steps": [{"type": "press_key", "key": "a"}], **extra}
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_cli_repeat(driver: FakeDriver, tmp_path: Path, capsys) -> None:
    assert cli.main(["run", write_test(tmp_path), "--no-delay", "--repeat", "3"]) == 0
    assert len(driver.calls) == 3
    output = capsys.readouterr().out
    assert "Starting loop 3" in output
    assert "Starting loop 4" not in output


def test_cli_uses_the_saved_repeat(driver: FakeDriver, tmp_path: Path) -> None:
    assert cli.main(["run", write_test(tmp_path, repeat=2), "--no-delay"]) == 0
    assert len(driver.calls) == 2


def test_cli_forever_passes_the_forever_value(tmp_path: Path, monkeypatch) -> None:
    seen: dict = {}

    def fake_run(_path, delay, repeat, on_iteration):
        seen["repeat"] = repeat
        return run_automation(Automation(steps=[KEY]), delay=delay, **fake_kwargs(FakeClock()))

    monkeypatch.setattr(cli, "run_automation", fake_run)
    assert cli.main(["run", write_test(tmp_path), "--no-delay", "--forever"]) == 0
    assert seen["repeat"] == REPEAT_FOREVER


@pytest.mark.parametrize(
    "options", [["--repeat", "0"], ["--repeat", "x"], ["--repeat", "2", "--forever"]]
)
def test_cli_rejects_bad_loop_options(tmp_path: Path, options: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", write_test(tmp_path), *options])
    assert exc.value.code == 2


def exported_options(tmp_path: Path) -> object:
    source = render_script(Automation(steps=[KEY]))
    namespace = {"__name__": "exported", "__file__": str(tmp_path / "x.py")}
    exec(compile(source, "x.py", "exec"), namespace)
    return namespace["parse_options"]


def test_exported_script_loop_options(tmp_path: Path) -> None:
    parse = exported_options(tmp_path)
    assert parse([]) == (5.0, None)
    assert parse(["--no-delay", "--repeat", "4"]) == (0.0, 4)
    assert parse(["--forever"]) == (5.0, REPEAT_FOREVER)
    with pytest.raises(SystemExit):
        parse(["--repeat", "0"])


# -- builder logic ------------------------------------------------------------


def test_parse_repeat() -> None:
    assert parse_repeat(" 12 ", False) == 12
    assert parse_repeat("not used", True) == REPEAT_FOREVER


@pytest.mark.parametrize("text", ["", "0", "-2", "abc", "1.5"])
def test_parse_repeat_rejects_bad_counts(text: str) -> None:
    with pytest.raises(ValidationError, match="Repeat"):
        parse_repeat(text, False)


def test_loop_descriptions() -> None:
    assert describe_loops(1) == "1 time"
    assert describe_loops(3) == "3 times"
    assert describe_loops(REPEAT_FOREVER) == "forever"
    assert loop_status(2, 5) == "Loop 2 of 5"
    assert "forever" in loop_status(2, REPEAT_FOREVER)


def test_with_clip_keeps_the_rest_of_the_step() -> None:
    step = Step(StepType.TYPE_TEXT, text="hello", x=1, y=2, description="note")
    updated = with_clip(step, "images/new.capture.png")
    assert (updated.image, updated.x, updated.y) == ("images/new.capture.png", None, None)
    assert (updated.text, updated.description) == ("hello", "note")


def test_takes_image() -> None:
    assert takes_image(StepType.CLICK)
    assert takes_image(StepType.WAIT_FOR_IMAGE)
    assert not takes_image(StepType.PRESS_KEY)
    assert not takes_image(StepType.WAIT_SECONDS)


# -- builder ------------------------------------------------------------------


class FakeRoot:
    def __init__(self) -> None:
        self.pending: list = []

    def withdraw(self) -> None:
        pass

    def deiconify(self) -> None:
        pass

    def after(self, _delay, callback) -> None:
        self.pending.append(callback)

    def run_pending(self) -> None:
        while self.pending:
            self.pending.pop(0)()


@pytest.fixture
def gui(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The tkinter-using modules, with dialogs replaced. No window is ever created."""
    pytest.importorskip("tkinter")
    from guiautomation.gui import app, running

    errors: list[str] = []
    monkeypatch.setattr(app.messagebox, "showerror", lambda _t, text: errors.append(text))
    return SimpleNamespace(app=app, running=running, errors=errors)


def make_builder(gui: SimpleNamespace, steps: list[Step] | None = None):
    builder = gui.app.BuilderApp.__new__(gui.app.BuilderApp)
    builder.root = FakeRoot()
    builder._path = None
    builder._scratch = None
    builder._automation = Automation(steps=steps if steps is not None else [])
    builder._steps = StepList(builder._automation.steps)
    builder._selected = lambda: None
    builder._changed = MagicMock()
    return builder


def patch_clipping(gui, monkeypatch, tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(gui.app.tempfile, "mkdtemp", lambda prefix: str(scratch))
    monkeypatch.setattr(gui.app.screen, "virtual_desktop", lambda: DESKTOP)
    monkeypatch.setattr(
        gui.app.screen, "grab_region", lambda *_a: Image.new("RGB", (10, 10), "white")
    )

    def overlay(_root, _desktop, on_done) -> None:
        on_done(Region(0, 0, 10, 10))

    monkeypatch.setattr(gui.app, "RegionOverlay", overlay)

    def no_dialog(**_kwargs):
        raise AssertionError("clipping must not open a file dialog")

    monkeypatch.setattr(gui.app.filedialog, "asksaveasfilename", no_dialog)
    monkeypatch.setattr(gui.app.filedialog, "askopenfilename", no_dialog)


def test_clipping_an_unsaved_test_asks_for_no_file(gui, monkeypatch, tmp_path) -> None:
    patch_clipping(gui, monkeypatch, tmp_path)
    builder = make_builder(gui)
    saved: list[str] = []
    builder.capture(None, saved.append, lambda: None)
    builder.root.run_pending()
    assert saved and saved[0].startswith("images/")
    assert builder.image_file(saved[0]).is_file()
    assert gui.errors == []


def test_saving_moves_unsaved_clips_next_to_the_test(gui, monkeypatch, tmp_path) -> None:
    patch_clipping(gui, monkeypatch, tmp_path)
    builder = make_builder(gui)
    saved: list[str] = []
    builder.capture(None, saved.append, lambda: None)
    builder.root.run_pending()
    builder._steps.add(Step(StepType.CLICK, image=saved[0]))
    target = tmp_path / "keep" / "t.json"
    save_automation(builder._automation, target)
    assert (target.parent / saved[0]).is_file()
    load_automation(target).check_runnable()


def test_clip_a_click_adds_a_step(gui, monkeypatch, tmp_path) -> None:
    patch_clipping(gui, monkeypatch, tmp_path)
    builder = make_builder(gui)
    builder._clip_click()
    builder.root.run_pending()
    assert [s.type for s in builder._steps.steps] == [StepType.CLICK]
    assert builder._steps.steps[0].image.startswith("images/")
    builder._changed.assert_called_once()
    builder._automation.check_runnable()


def test_replace_clip_swaps_the_target_in_place(gui, monkeypatch, tmp_path) -> None:
    patch_clipping(gui, monkeypatch, tmp_path)
    first = Step(StepType.TYPE_TEXT, text="hello", x=1, y=2)
    builder = make_builder(gui, [first, KEY])
    builder._selected = lambda: 0
    builder._replace_clip()
    builder.root.run_pending()
    assert len(builder._steps.steps) == 2
    assert builder._steps.steps[0].text == "hello"
    assert builder._steps.steps[0].image.startswith("images/")
    assert builder._steps.steps[0].x is None
    assert builder._steps.steps[1] == KEY


def test_replace_clip_needs_a_selection(gui) -> None:
    builder = make_builder(gui, [Step(StepType.CLICK, x=1, y=2)])
    builder.capture = MagicMock()
    builder._replace_clip()
    builder.capture.assert_not_called()
    assert gui.errors == ["Select a step in the list first."]


def test_replace_clip_refuses_a_step_without_a_clip(gui) -> None:
    builder = make_builder(gui, [KEY])
    builder._selected = lambda: 0
    builder.capture = MagicMock()
    builder._replace_clip()
    builder.capture.assert_not_called()
    assert gui.errors == ["This type of step does not use a clip."]


def make_loop_run(gui: SimpleNamespace, repeat: int):
    run = gui.running.LoopRun.__new__(gui.running.LoopRun)
    run._root = FakeRoot()
    run._window = MagicMock()
    run._label = MagicMock()
    run._automation = Automation(steps=[KEY], repeat=repeat)
    run._hotkey = AbortHotkey(is_pressed=lambda: False)
    run._events = gui.running.queue.Queue()
    run.reports = []
    run._on_finished = run.reports.append
    return run


def test_loop_run_shows_progress_and_reports_when_done(gui) -> None:
    run = make_loop_run(gui, 3)
    run._events.put(("loop", 2))
    run._poll()
    assert "Loop 2 of 3" in run._label.configure.call_args.kwargs["text"]
    assert run.reports == []
    run._events.put(("done", "all good"))
    run._poll()
    assert run.reports == ["all good"]
    run._window.destroy.assert_called_once()


def test_run_button_starts_a_loop_run(gui, monkeypatch) -> None:
    runs: list = []

    def fake_run(root, automation, on_finished):
        run = SimpleNamespace(start=lambda: runs.append(automation))
        return run

    monkeypatch.setattr(gui.app, "LoopRun", fake_run)
    builder = make_builder(gui, [KEY])
    builder._repeat_count = SimpleNamespace(get=lambda: "4")
    builder._forever = SimpleNamespace(get=lambda: False)
    builder._run()
    builder.root.run_pending()
    assert runs == [builder._automation]
    assert builder._automation.repeat == 4


def test_run_button_reports_a_bad_repeat(gui, monkeypatch) -> None:
    monkeypatch.setattr(gui.app, "LoopRun", MagicMock())
    builder = make_builder(gui, [KEY])
    builder._repeat_count = SimpleNamespace(get=lambda: "abc")
    builder._forever = SimpleNamespace(get=lambda: False)
    builder._run()
    gui.app.LoopRun.assert_not_called()
    assert "Repeat" in gui.errors[0]
