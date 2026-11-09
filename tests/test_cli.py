"""AC6, AC7: delays, exit codes and the module entry point."""

from __future__ import annotations

import functools
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fakes import FakeClock, FakeDriver, FakeScreen, failsafe_driver

from guiautomation import cli
from guiautomation.runner import run_automation


def write_test(tmp_path: Path, steps: list | None = None) -> Path:
    path = tmp_path / "t.json"
    steps = steps if steps is not None else [{"type": "press_key", "key": "a"}]
    path.write_text(json.dumps({"version": 1, "name": "t", "steps": steps}), encoding="utf-8")
    return path


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Runs the real run_automation against fakes, with a fake clock."""
    fake = FakeClock()
    monkeypatch.setattr(
        cli,
        "run_automation",
        functools.partial(
            run_automation,
            driver=FakeDriver(),
            screen=FakeScreen(),
            sleep=fake.sleep,
            clock=fake.clock,
            abort=lambda: False,
        ),
    )
    return fake


def test_pass_exits_zero_after_the_default_delay(clock: FakeClock, tmp_path: Path) -> None:
    assert cli.main(["run", str(write_test(tmp_path))]) == 0
    assert clock.slept == pytest.approx(5.0)


def test_no_delay(clock: FakeClock, tmp_path: Path) -> None:
    assert cli.main(["run", str(write_test(tmp_path)), "--no-delay"]) == 0
    assert clock.sleeps == 0


def test_delay_override(clock: FakeClock, tmp_path: Path) -> None:
    assert cli.main(["run", str(write_test(tmp_path)), "--delay", "1.5"]) == 0
    assert clock.slept == pytest.approx(1.5)


def test_delay_zero(clock: FakeClock, tmp_path: Path) -> None:
    assert cli.main(["run", str(write_test(tmp_path)), "--delay", "0"]) == 0
    assert clock.sleeps == 0


def test_failed_run_exits_one_and_names_the_step(
    clock: FakeClock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "a.png").write_bytes(b"png")
    path = write_test(tmp_path, [{"type": "assert_image_visible", "image": "a.png"}])
    assert cli.main(["run", str(path), "--no-delay"]) == 1
    assert "Failed at step 1" in capsys.readouterr().out


def test_failsafe_exits_three(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        cli,
        "run_automation",
        functools.partial(
            run_automation, driver=failsafe_driver(), screen=FakeScreen(), abort=lambda: False
        ),
    )
    path = write_test(tmp_path, [{"type": "click", "x": 1, "y": 2}])
    assert cli.main(["run", str(path), "--no-delay"]) == 3


def test_abort_during_delay_exits_three(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeClock()
    monkeypatch.setattr(
        cli,
        "run_automation",
        functools.partial(
            run_automation,
            driver=FakeDriver(),
            screen=FakeScreen(),
            sleep=fake.sleep,
            clock=fake.clock,
            abort=lambda: fake.sleeps > 1,
        ),
    )
    assert cli.main(["run", str(write_test(tmp_path))]) == 3


def test_ctrl_c_exits_three(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_automation", interrupted)
    assert cli.main(["run", str(write_test(tmp_path))]) == 3


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        '{"steps": []}',
        '{"version": 1, "steps": []}',
        '{"version": 1, "steps": [{"type": "explode"}]}',
        '{"version": 1, "steps": [{"type": "wait_for_image", "image": "../a.png"}]}',
        '{"version": 1, "steps": [{"type": "wait_for_image", "image": "missing.png"}]}',
    ],
)
def test_bad_input_exits_two(
    clock: FakeClock, tmp_path: Path, content: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "t.json"
    path.write_text(content, encoding="utf-8")
    assert cli.main(["run", str(path), "--no-delay"]) == 2
    assert "error:" in capsys.readouterr().err


def test_missing_file_exits_two(clock: FakeClock, tmp_path: Path) -> None:
    assert cli.main(["run", str(tmp_path / "gone.json")]) == 2


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bogus"],
        ["run"],
        ["run", "x.json", "--delay", "abc"],
        ["run", "x.json", "--delay", "-1"],
        ["run", "x.json", "--delay", "inf"],
        ["run", "x.json", "--delay", "nan"],
        ["run", "x.json", "--no-delay", "--delay", "1"],
    ],
)
def test_usage_errors_exit_two(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    assert exit_info.value.code == 2


def test_missing_env_var_is_a_failure_that_names_only_the_variable(
    clock: FakeClock, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch
) -> None:
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    path = write_test(tmp_path, [{"type": "type_text", "env_var": "NOT_SET_ANYWHERE"}])
    assert cli.main(["run", str(path), "--no-delay"]) == 1
    assert "NOT_SET_ANYWHERE is not set" in capsys.readouterr().out


def test_gui_with_invalid_file_exits_two(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_text("{", encoding="utf-8")
    assert cli.main(["gui", str(path)]) == 2


def test_module_help_smoke() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "guiautomation", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0
    assert "guiautomation" in completed.stdout


def test_run_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["run", "--help"])
    assert exit_info.value.code == 0


def test_unencodable_output_does_not_fail_a_passing_run(
    clock: FakeClock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)
    path = write_test(tmp_path, [{"type": "press_key", "key": "日"}])
    assert cli.main(["run", str(path), "--no-delay"]) == 0
    stream.flush()
    assert b"pressed ?" in raw.getvalue()


def test_unexpected_exception_exits_four(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "run_automation", broken)
    assert cli.main(["run", str(write_test(tmp_path)), "--no-delay"]) == 4
    assert "internal error" in capsys.readouterr().err


def test_gui_without_tkinter_exits_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delitem(sys.modules, "guiautomation.gui.app", raising=False)
    monkeypatch.setitem(sys.modules, "tkinter", None)
    assert cli.main(["gui"]) == 2
    assert "tkinter is not available" in capsys.readouterr().err


def test_gui_reraises_other_import_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "guiautomation.gui.app", None)
    with pytest.raises(ImportError):
        cli.main(["gui"])
