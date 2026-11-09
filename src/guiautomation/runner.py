"""Runs automations through an injected Driver and Screen."""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from guiautomation import screen as screen_module
from guiautomation.abort import AbortHotkey
from guiautomation.driver import AbortRequested, Driver, FailSafeAbort, PyAutoGuiDriver
from guiautomation.model import (
    DEFAULT_CONFIDENCE,
    DEFAULT_DRAG_DURATION,
    DEFAULT_TIMEOUT,
    Automation,
    Step,
    StepType,
    ValidationError,
    load_automation,
)
from guiautomation.screen import Match, MssScreen, Screen

EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_BAD_INPUT = 2
EXIT_ABORTED = 3
EXIT_INTERNAL_ERROR = 4

_POLL_INTERVAL = 0.05
_IMAGE_POLL_INTERVAL = 0.25
_HOTKEY_REASON = "abort hotkey pressed"
_FAILSAFE_REASON = "PyAutoGUI failsafe triggered"
_CLICK_STYLES = {
    StepType.CLICK: ("left", 1),
    StepType.DOUBLE_CLICK: ("left", 2),
    StepType.RIGHT_CLICK: ("right", 1),
}


class Status(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ABORTED = "aborted"


class Confirmation(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    STOP = "stop"


@dataclass
class StepResult:
    index: int  # 1-based position in the test
    step_type: StepType
    status: Status
    message: str = ""
    confirmed: bool | None = None  # The user's answer in a guided run


@dataclass
class RunResult:
    status: Status
    steps: list[StepResult] = field(default_factory=list)
    reason: str = ""

    @property
    def passed(self) -> bool:
        return self.status is Status.PASSED

    @property
    def first_failure(self) -> StepResult | None:
        return next((s for s in self.steps if s.status is Status.FAILED), None)

    def summary(self) -> str:
        """Return a readable report. It never contains typed values."""
        lines = [f"Result: {self.status.value.upper()} ({len(self.steps)} step(s) run)"]
        lines += [
            f"  {s.index}. {s.step_type.value}: {s.status.value} - {s.message}" for s in self.steps
        ]
        failure = self.first_failure
        if failure is not None:
            lines.append(f"Failed at step {failure.index}: {failure.message}")
        elif self.reason:
            lines.append(f"Reason: {self.reason}")
        return "\n".join(lines)


def exit_code_for(result: RunResult) -> int:
    """Map a run result to the command-line exit code."""
    return {
        Status.PASSED: EXIT_PASSED,
        Status.FAILED: EXIT_FAILED,
        Status.ABORTED: EXIT_ABORTED,
    }[result.status]


def failsafe_triggered(driver: Driver) -> bool:
    """Return True if the cursor is on a failsafe point. A broken probe never fails a run."""
    try:
        return driver.failsafe_triggered()
    except Exception:  # noqa: BLE001 - the next real driver call reports the problem
        return False


class _Aborted(Exception):
    pass


class _StepFailed(Exception):
    pass


Confirm = Callable[[Step, StepResult], Confirmation]
OnStep = Callable[[StepResult], None]


class Runner:
    """Executes the steps of an automation, all at once or with user confirmation."""

    def __init__(
        self,
        automation: Automation,
        driver: Driver,
        screen: Screen,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        abort: Callable[[], bool] = lambda: False,
        env: Mapping[str, str] = os.environ,
        stop_on_failure: bool = True,
    ) -> None:
        self._automation = automation
        self._driver = driver
        self._screen = screen
        self._sleep = sleep
        self._clock = clock
        self._abort = abort
        self._env = env
        self._stop_on_failure = stop_on_failure

    def run(
        self, delay: float = 0.0, confirm: Confirm | None = None, on_step: OnStep | None = None
    ) -> RunResult:
        """Run every step. With ``confirm``, the user judges each step that succeeds."""
        results: list[StepResult] = []
        try:
            self._wait(delay)
        except _Aborted as exc:
            return RunResult(Status.ABORTED, results, str(exc))
        failed = False
        for index, step in enumerate(self._automation.steps, start=1):
            result = self._execute(index, step)
            if result.status is Status.PASSED and confirm is not None:
                self._apply_confirmation(result, confirm(step, result))
            results.append(result)
            if on_step is not None:
                on_step(result)
            if result.status is Status.ABORTED:
                return RunResult(Status.ABORTED, results, result.message)
            if result.status is Status.FAILED:
                failed = True
                if self._stop_on_failure:
                    break
        return RunResult(Status.FAILED if failed else Status.PASSED, results)

    def _apply_confirmation(self, result: StepResult, answer: Confirmation) -> None:
        if answer is Confirmation.STOP:
            result.status = Status.ABORTED
            result.message = self._abort_reason() or "stopped by the user"
        elif answer is Confirmation.FAIL:
            result.status = Status.FAILED
            result.confirmed = False
            result.message = "marked as failed by the user"
        else:
            result.confirmed = True

    def _execute(self, index: int, step: Step) -> StepResult:
        try:
            self._check_abort()
            message = self._perform(step)
        except _Aborted as exc:
            return StepResult(index, step.type, Status.ABORTED, str(exc))
        except FailSafeAbort:
            return StepResult(index, step.type, Status.ABORTED, _FAILSAFE_REASON)
        except AbortRequested:
            return StepResult(index, step.type, Status.ABORTED, _HOTKEY_REASON)
        except _StepFailed as exc:
            return StepResult(index, step.type, Status.FAILED, str(exc))
        except Exception as exc:  # noqa: BLE001 - a step failure must never crash the run
            if step.type is StepType.TYPE_TEXT:  # The message could quote the typed value.
                message = f"typing failed ({type(exc).__name__})"
            else:
                message = f"{type(exc).__name__}: {exc}"
            return StepResult(index, step.type, Status.FAILED, message)
        return StepResult(index, step.type, Status.PASSED, message)

    def _perform(self, step: Step) -> str:
        kind = step.type
        if kind in _CLICK_STYLES:
            button, clicks = _CLICK_STYLES[kind]
            x, y = self._required_target(step)
            self._driver.click(x, y, button=button, clicks=clicks)
            return f"clicked at ({x}, {y})"
        if kind is StepType.MOVE:
            x, y = self._required_target(step)
            self._driver.move(x, y)
            return f"moved to ({x}, {y})"
        if kind is StepType.DRAG:
            x, y = self._required_target(step)
            duration = DEFAULT_DRAG_DURATION if step.duration is None else step.duration
            self._driver.drag(x, y, step.to_x, step.to_y, duration)
            return f"dragged from ({x}, {y}) to ({step.to_x}, {step.to_y})"
        if kind is StepType.TYPE_TEXT:
            return self._type_text(step)
        if kind is StepType.PRESS_KEY:
            self._driver.press_key(step.key)
            return f"pressed {step.key}"
        if kind is StepType.HOTKEY:
            self._driver.hotkey(step.keys)
            return f"pressed {'+'.join(step.keys)}"
        if kind is StepType.SCROLL:
            target = self._target(step)
            if target is None:
                self._driver.scroll(step.clicks)
            else:
                self._driver.scroll(step.clicks, target[0], target[1])
            return f"scrolled {step.clicks}"
        if kind is StepType.WAIT_SECONDS:
            self._wait(step.seconds)
            return f"waited {step.seconds:g} s"
        match = self._wait_for_image(step)
        return f"found {step.image} at ({match.x}, {match.y})"

    def _type_text(self, step: Step) -> str:
        if step.env_var is not None:
            text = self._env.get(step.env_var)
            if text is None:
                raise _StepFailed(f"environment variable {step.env_var} is not set")
            done = f"typed the value of {step.env_var}"
        else:
            text = step.text
            done = "typed text"
        target = self._target(step)
        if target is not None:
            self._driver.click(target[0], target[1])
        self._driver.type_text(text)
        return done

    def _required_target(self, step: Step) -> tuple[int, int]:
        target = self._target(step)
        if target is None:
            raise _StepFailed("the step has no target")
        return target

    def _target(self, step: Step) -> tuple[int, int] | None:
        if step.image is not None:
            match = self._wait_for_image(step)
            return match.x, match.y
        if step.x is not None and step.y is not None:
            return step.x, step.y
        return None

    def _wait_for_image(self, step: Step) -> Match:
        timeout = step.timeout
        if timeout is None:
            timeout = 0.0 if step.type is StepType.ASSERT_IMAGE_VISIBLE else DEFAULT_TIMEOUT
        confidence = DEFAULT_CONFIDENCE if step.confidence is None else step.confidence
        try:
            path = self._automation.resolve_image(step.image)
        except ValidationError as exc:
            raise _StepFailed(str(exc)) from exc
        if not path.is_file():
            raise _StepFailed(f"image file not found: {step.image}")
        deadline = self._clock() + timeout
        while True:
            self._check_abort()
            match = self._screen.find_image(path, confidence)
            if match is not None:
                return match
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise _StepFailed(f"image {step.image} not found within {timeout:g} s")
            self._wait(min(remaining, _IMAGE_POLL_INTERVAL))

    def _abort_reason(self) -> str | None:
        if self._abort():
            return _HOTKEY_REASON
        if failsafe_triggered(self._driver):
            return _FAILSAFE_REASON
        return None

    def _check_abort(self) -> None:
        reason = self._abort_reason()
        if reason is not None:
            raise _Aborted(reason)

    def _wait(self, seconds: float) -> None:
        """Sleep in short slices so an abort or the failsafe is honored during waits."""
        deadline = self._clock() + seconds
        while True:
            self._check_abort()
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            self._sleep(min(remaining, _POLL_INTERVAL))


def run_automation(
    target: str | os.PathLike[str] | Automation,
    delay: float = 0.0,
    *,
    driver: Driver | None = None,
    screen: Screen | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    abort: Callable[[], bool] | None = None,
    env: Mapping[str, str] = os.environ,
    confirm: Confirm | None = None,
    on_step: OnStep | None = None,
    stop_on_failure: bool = True,
) -> RunResult:
    """Run a test file or Automation and return the result.

    Raises ValidationError for bad input (invalid file, missing image, bad delay).
    A failing step is reported in the result, not raised.
    """
    if type(delay) not in (int, float) or not math.isfinite(delay) or delay < 0:
        raise ValidationError("delay must be a finite number of seconds, zero or more")
    automation = load_automation(target) if isinstance(target, (str, os.PathLike)) else target
    automation.check_runnable()
    if driver is None or screen is None:
        screen_module.enable_dpi_awareness()

    def execute(abort_check: Callable[[], bool]) -> RunResult:
        runner = Runner(
            automation,
            driver if driver is not None else PyAutoGuiDriver(abort=abort_check),
            screen if screen is not None else MssScreen(),
            sleep=sleep,
            clock=clock,
            abort=abort_check,
            env=env,
            stop_on_failure=stop_on_failure,
        )
        return runner.run(delay=delay, confirm=confirm, on_step=on_step)

    if abort is not None:
        return execute(abort)
    with AbortHotkey() as hotkey:
        return execute(hotkey.is_set)
