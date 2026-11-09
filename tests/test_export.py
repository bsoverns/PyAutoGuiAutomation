"""AC4: exported scripts are valid, safely escaped, and hold no secrets."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeClock, FakeDriver, FakeScreen

from guiautomation.export import export_script, render_script
from guiautomation.model import Automation, Step, StepType, ValidationError
from guiautomation.runner import run_automation

NASTY_TEXT = 'quote" single\' triple""" back\\slash\nnew line\ttab {braces} {{x}} %s 日本語'


def exec_script(source: str, script_path: Path, fake_run=None) -> dict:
    namespace = {"__name__": "exported", "__file__": str(script_path)}
    exec(compile(source, str(script_path), "exec"), namespace)
    if fake_run is not None:
        namespace["run_automation"] = fake_run
    return namespace


def automation_with(text: str, base_dir: Path | None = None) -> Automation:
    return Automation(
        name='odd "name"\nline', steps=[Step(StepType.TYPE_TEXT, text=text)], base_dir=base_dir
    )


def test_quotes_and_newlines_compile_and_execute(tmp_path: Path) -> None:
    source = render_script(automation_with(NASTY_TEXT))
    driver = FakeDriver()
    clock = FakeClock()

    def fake_run(automation, delay):
        assert delay == 5.0
        return run_automation(
            automation,
            delay=0,
            driver=driver,
            screen=FakeScreen(),
            sleep=clock.sleep,
            clock=clock.clock,
            abort=lambda: False,
        )

    namespace = exec_script(source, tmp_path / "x.py", fake_run)
    assert namespace["main"]([]) == 0
    assert driver.calls == [("type_text", NASTY_TEXT)]


def test_export_writes_a_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    assert export_script(automation_with(NASTY_TEXT), path) == path
    compile(path.read_text(encoding="utf-8"), str(path), "exec")


def test_env_var_value_is_never_embedded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_SECRET", "s3cret-value")
    automation = Automation(steps=[Step(StepType.TYPE_TEXT, env_var="APP_SECRET", secret=True)])
    source = render_script(automation)
    assert "s3cret-value" not in source
    assert "APP_SECRET" in source


def test_literal_secret_cannot_be_exported() -> None:
    automation = Automation(steps=[Step(StepType.TYPE_TEXT, text="x", secret=True)])
    with pytest.raises(ValidationError):
        render_script(automation)


def test_exported_script_finds_images_relative_to_the_test(tmp_path: Path) -> None:
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "a.png").write_bytes(b"png")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    automation = Automation(steps=[Step(StepType.WAIT_FOR_IMAGE, image="a.png")], base_dir=test_dir)
    script = scripts / "x.py"
    seen = {}

    def fake_run(loaded, delay):
        seen["base"] = loaded.base_dir
        raise ValidationError("stop here")

    namespace = exec_script(render_script(automation, script), script, fake_run)
    assert namespace["main"]([]) == 2
    assert seen["base"] == test_dir.resolve()


def test_exit_code_maps_a_failed_run(tmp_path: Path) -> None:
    source = render_script(automation_with("hi"))

    def fake_run(automation, delay):
        return run_automation(
            automation,
            driver=FakeDriver(fail_on="type_text"),
            screen=FakeScreen(),
            abort=lambda: False,
        )

    assert exec_script(source, tmp_path / "x.py", fake_run)["main"]([]) == 1


def delay_used(tmp_path: Path, argv: list[str]) -> float:
    seen = {}

    def fake_run(automation, delay):
        seen["delay"] = delay
        raise ValidationError("stop here")

    exec_script(render_script(automation_with("hi")), tmp_path / "x.py", fake_run)["main"](argv)
    return seen["delay"]


def test_exported_script_delay_options(tmp_path: Path) -> None:
    assert delay_used(tmp_path, []) == 5.0
    assert delay_used(tmp_path, ["--no-delay"]) == 0.0
    assert delay_used(tmp_path, ["--delay", "1.5"]) == 1.5


def test_exported_script_rejects_conflicting_delay_options(tmp_path: Path) -> None:
    namespace = exec_script(render_script(automation_with("hi")), tmp_path / "x.py")
    with pytest.raises(SystemExit) as exit_info:
        namespace["main"](["--no-delay", "--delay", "1"])
    assert exit_info.value.code == 2


def test_exported_script_maps_ctrl_c_to_aborted(tmp_path: Path) -> None:
    def fake_run(automation, delay):
        raise KeyboardInterrupt

    namespace = exec_script(render_script(automation_with("hi")), tmp_path / "x.py", fake_run)
    assert namespace["main"]([]) == 3


def test_exported_script_notes_where_images_live(tmp_path: Path) -> None:
    automation = automation_with("hi", tmp_path / "tests")
    source = render_script(automation, tmp_path / "scripts" / "x.py")
    assert "relative to this folder" in source
    assert "tests" in source.split("import argparse")[0]
