"""What a step does when its image is not on the screen."""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeClock, FakeDriver, FakeScreen, match_at

from guiautomation.gui.logic import describe_step, fields_for, step_from_form, step_to_form
from guiautomation.model import (
    KEEP_LOOKING,
    Automation,
    Step,
    StepType,
    ValidationError,
    automation_to_dict,
    parse_automation,
)
from guiautomation.runner import Runner, Status

STOP_LABEL = "Stop the run as failed"
LOOK_LABEL = "Keep looking until found"


def make_runner(
    step: Step, tmp_path: Path, screen: FakeScreen, **kwargs
) -> tuple[Runner, FakeDriver]:
    (tmp_path / "a.png").write_bytes(b"png")
    clock = FakeClock()
    driver = FakeDriver()
    runner = Runner(
        Automation(steps=[step], base_dir=tmp_path),
        driver,
        screen,
        sleep=clock.sleep,
        clock=clock.clock,
        **kwargs,
    )
    return runner, driver


def test_by_default_a_missing_image_stops_the_run_as_failed(tmp_path: Path) -> None:
    step = Step(StepType.CLICK, image="a.png", timeout=1.0)
    runner, driver = make_runner(step, tmp_path, FakeScreen())
    result = runner.run()
    assert result.status is Status.FAILED
    assert "not found within 1 s" in result.steps[0].message
    assert driver.calls == []


def test_keep_looking_outlasts_the_timeout_and_clicks_when_found(tmp_path: Path) -> None:
    step = Step(StepType.CLICK, image="a.png", timeout=1.0, if_not_found=KEEP_LOOKING)
    screen = FakeScreen({"a.png": match_at(7, 8)}, found_after=2000)  # About 500 s of searching.
    runner, driver = make_runner(step, tmp_path, screen)
    result = runner.run()
    assert result.passed
    assert len(screen.searches) == 2001
    assert driver.calls == [("click", 7, 8, "left", 1)]


def test_keep_looking_can_be_stopped(tmp_path: Path) -> None:
    step = Step(StepType.WAIT_FOR_IMAGE, image="a.png", if_not_found=KEEP_LOOKING)
    screen = FakeScreen()
    runner, _ = make_runner(step, tmp_path, screen, abort=lambda: len(screen.searches) >= 40)
    result = runner.run()
    assert result.status is Status.ABORTED
    assert len(screen.searches) == 40


def test_keep_looking_with_a_missing_file_fails_at_once(tmp_path: Path) -> None:
    step = Step(StepType.CLICK, image="gone.png", if_not_found=KEEP_LOOKING)
    screen = FakeScreen()
    runner, _ = make_runner(step, tmp_path, screen)
    result = runner.run()
    assert result.status is Status.FAILED
    assert screen.searches == []


def test_setting_is_saved_only_when_used() -> None:
    plain = Automation(steps=[Step(StepType.CLICK, image="a.png")])
    assert "if_not_found" not in automation_to_dict(plain)["steps"][0]
    text = (
        '{"version": 1, "steps": [{"type": "click", "image": "a.png", '
        '"if_not_found": "keep_looking"}]}'
    )
    assert parse_automation(text).steps[0].if_not_found == KEEP_LOOKING


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ('"image": "a.png", "if_not_found": "maybe"', "if_not_found must be"),
        ('"x": 1, "y": 2, "if_not_found": "keep_looking"', "needs an image"),
    ],
)
def test_bad_settings_are_rejected(extra: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        parse_automation(f'{{"version": 1, "steps": [{{"type": "click", {extra}}}]}}')


def test_only_steps_with_images_offer_the_choice() -> None:
    assert any(spec.name == "if_not_found" for spec in fields_for(StepType.WAIT_FOR_IMAGE))
    assert not any(spec.name == "if_not_found" for spec in fields_for(StepType.PRESS_KEY))


def test_form_round_trip_for_both_choices() -> None:
    looking = step_from_form(StepType.CLICK, {"image": "a.png", "if_not_found": LOOK_LABEL})
    assert looking.if_not_found == KEEP_LOOKING
    assert step_to_form(looking)["if_not_found"] == LOOK_LABEL

    stopping = step_from_form(StepType.CLICK, {"image": "a.png", "if_not_found": STOP_LABEL})
    assert stopping.if_not_found is None
    assert step_to_form(stopping)["if_not_found"] == STOP_LABEL


def test_the_step_list_shows_keep_looking() -> None:
    assert "until found" in describe_step(
        Step(StepType.CLICK, image="a.png", if_not_found=KEEP_LOOKING)
    )
    assert "until found" not in describe_step(Step(StepType.CLICK, image="a.png"))
