"""Saving a test from the builder and opening it again to edit."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from guiautomation.gui.logic import StepList
from guiautomation.model import Automation, Step, StepType, load_automation

KEY = Step(StepType.PRESS_KEY, key="a")


class Text:
    def __init__(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    pytest.importorskip("tkinter")
    from guiautomation.gui import app as module

    errors: list[str] = []
    monkeypatch.setattr(module.messagebox, "showerror", lambda _t, text: errors.append(text))
    return SimpleNamespace(module=module, errors=errors)


def make_builder(app: SimpleNamespace, steps: list[Step], repeat: str = "1"):
    builder = app.module.BuilderApp.__new__(app.module.BuilderApp)
    builder._path = None
    builder._dirty = True
    builder._automation = Automation(steps=steps)
    builder._steps = StepList(builder._automation.steps)
    builder._repeat_count = Text(repeat)
    builder._forever = Text(False)
    builder._selected = lambda: None
    builder._refresh = MagicMock()
    builder._show_repeat = MagicMock()
    return builder


def test_save_writes_a_file_that_opens_again(app, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "mine.json"
    seen: dict = {}

    def save_dialog(**kwargs):
        seen.update(kwargs)
        return str(target)

    monkeypatch.setattr(app.module.filedialog, "asksaveasfilename", save_dialog)
    monkeypatch.chdir(tmp_path)
    builder = make_builder(app, [KEY], repeat="3")
    assert builder._save() is True
    assert seen["initialdir"] == str(tmp_path / "automations")
    assert builder._dirty is False

    loaded = load_automation(target)
    assert loaded.steps == [KEY]
    assert loaded.repeat == 3
    assert app.errors == []


def test_save_goes_straight_to_the_open_file(app, tmp_path: Path, monkeypatch) -> None:
    def no_dialog(**_kwargs):
        raise AssertionError("a saved test needs no dialog")

    monkeypatch.setattr(app.module.filedialog, "asksaveasfilename", no_dialog)
    builder = make_builder(app, [KEY])
    builder._path = tmp_path / "mine.json"
    assert builder._save() is True
    assert builder._path.is_file()


def test_cancelling_the_dialog_saves_nothing(app, monkeypatch) -> None:
    monkeypatch.setattr(app.module.filedialog, "asksaveasfilename", lambda **_k: "")
    builder = make_builder(app, [KEY])
    assert builder._save() is False
    assert builder._dirty is True


def test_open_loads_a_test_for_editing(app, tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "mine.json"
    make_builder(app, [KEY, KEY], repeat="5")._write(target)
    monkeypatch.setattr(app.module.filedialog, "askopenfilename", lambda **_k: str(target))
    builder = make_builder(app, [])
    builder._dirty = False
    builder._open()
    assert builder._path == target
    assert builder._steps.steps == [KEY, KEY]
    builder._show_repeat.assert_called_once()
    builder._refresh.assert_called()


def test_open_reports_a_bad_file(app, tmp_path: Path, monkeypatch) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    monkeypatch.setattr(app.module.filedialog, "askopenfilename", lambda **_k: str(bad))
    builder = make_builder(app, [KEY])
    builder._dirty = False
    builder._open()
    assert builder._path is None
    assert "invalid JSON" in app.errors[0]


def test_dialogs_start_in_the_open_tests_folder(app, tmp_path: Path) -> None:
    builder = make_builder(app, [])
    builder._path = tmp_path / "deep" / "mine.json"
    assert builder._dialog_folder() == str(tmp_path / "deep")
