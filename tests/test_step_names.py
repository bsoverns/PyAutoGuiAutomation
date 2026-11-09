"""Step names, so the builder and every run say what a step is doing."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fakes import FakeClock, FakeDriver, FakeScreen

from guiautomation import cli
from guiautomation.gui.logic import describe_step, fields_for, step_status
from guiautomation.model import Automation, Step, StepType, ValidationError, validate_step
from guiautomation.runner import Confirmation, Runner, run_automation

NAMED = Step(StepType.PRESS_KEY, key="enter", description="Submit the form")
PLAIN = Step(StepType.PRESS_KEY, key="a")


def make_runner(*steps: Step, **kwargs) -> Runner:
    clock = FakeClock()
    return Runner(
        Automation(steps=list(steps)),
        kwargs.pop("driver", FakeDriver()),
        FakeScreen(),
        sleep=clock.sleep,
        clock=clock.clock,
        **kwargs,
    )


def test_label_is_the_name_or_the_type() -> None:
    assert NAMED.label == "Submit the form"
    assert PLAIN.label == "press key"


def test_the_name_comes_first_in_the_step_window() -> None:
    first = fields_for(StepType.CLICK)[0]
    assert (first.name, first.label) == ("description", "Step name")


def test_the_step_list_leads_with_the_name() -> None:
    assert describe_step(NAMED) == "Submit the form  (press key: enter)"
    assert describe_step(PLAIN) == "press key: a"


def test_each_step_is_announced_before_it_runs() -> None:
    driver = FakeDriver()
    seen: list[tuple] = []

    def on_start(index: int, step: Step) -> None:
        seen.append((index, step.label, len(driver.calls)))

    make_runner(NAMED, PLAIN, driver=driver).run(on_step_start=on_start)
    assert seen == [(1, "Submit the form", 0), (2, "press key", 1)]


def test_the_report_names_each_step() -> None:
    summary = make_runner(NAMED, PLAIN).run().summary()
    assert "1. Submit the form (press_key): passed" in summary
    assert "2. press_key: passed" in summary


def test_a_failure_names_the_step() -> None:
    result = make_runner(NAMED).run(confirm=lambda _s, _r: Confirmation.FAIL)
    assert "Failed at step 1 (Submit the form):" in result.summary()


def test_status_line() -> None:
    assert step_status(2, 5, NAMED) == "Step 2 of 5: Submit the form"


def test_typed_text_is_never_the_label() -> None:
    step = Step(StepType.TYPE_TEXT, text="private words")
    assert "private words" not in step_status(1, 1, step)


def test_a_secret_in_a_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="secret"):
        validate_step(Step(StepType.PRESS_KEY, key="a", description="password=hunter2"))


def test_run_automation_passes_the_callback() -> None:
    clock = FakeClock()
    seen: list[int] = []
    run_automation(
        Automation(steps=[NAMED]),
        driver=FakeDriver(),
        screen=FakeScreen(),
        sleep=clock.sleep,
        clock=clock.clock,
        abort=lambda: False,
        on_step_start=lambda index, _step: seen.append(index),
    )
    assert seen == [1]


def test_the_command_line_prints_each_step(tmp_path: Path, monkeypatch, capsys) -> None:
    path = tmp_path / "t.json"
    data = {
        "version": 1,
        "steps": [{"type": "press_key", "key": "a", "description": "Open the menu"}],
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    clock = FakeClock()

    def fake_run(*args, **kwargs):
        return run_automation(
            *args,
            driver=FakeDriver(),
            screen=FakeScreen(),
            sleep=clock.sleep,
            clock=clock.clock,
            abort=lambda: False,
            **kwargs,
        )

    monkeypatch.setattr(cli, "run_automation", fake_run)
    assert cli.main(["run", str(path), "--no-delay"]) == 0
    assert "Step 1: Open the menu" in capsys.readouterr().out


def test_clip_a_click_asks_for_a_name(monkeypatch) -> None:
    pytest.importorskip("tkinter")
    from guiautomation.gui import app
    from guiautomation.gui.logic import StepList

    monkeypatch.setattr(app.simpledialog, "askstring", lambda *_a, **_k: "  Open settings ")
    builder = app.BuilderApp.__new__(app.BuilderApp)
    builder.root = MagicMock()
    builder._steps = StepList([])
    builder._selected = lambda: None
    builder._changed = MagicMock()
    builder.capture = lambda _dialog, on_saved, _restore: on_saved("images/a.capture.png")
    builder._clip_click()
    assert builder._steps.steps[0].description == "Open settings"


@pytest.mark.parametrize("answer", [None, "", "   "])
def test_the_name_is_optional(monkeypatch, answer) -> None:
    pytest.importorskip("tkinter")
    from guiautomation.gui import app
    from guiautomation.gui.logic import StepList

    monkeypatch.setattr(app.simpledialog, "askstring", lambda *_a, **_k: answer)
    builder = app.BuilderApp.__new__(app.BuilderApp)
    builder.root = MagicMock()
    builder._steps = StepList([])
    builder._selected = lambda: None
    builder._changed = MagicMock()
    builder.capture = lambda _dialog, on_saved, _restore: on_saved("images/a.capture.png")
    builder._clip_click()
    assert builder._steps.steps[0].description is None
