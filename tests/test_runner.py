"""AC2, AC5, AC7, AC9: step execution, guided runs, delays, abort and failsafe."""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fakes import FakeClock, FakeDriver, FakeScreen, failsafe_driver, match_at

from guiautomation import abort as abort_module
from guiautomation.abort import AbortHotkey
from guiautomation.driver import (
    AbortRequested,
    DriverError,
    FailSafeAbort,
    PyAutoGuiDriver,
    _Input,
)
from guiautomation.model import Automation, Step, StepType, ValidationError, save_automation
from guiautomation.runner import (
    EXIT_ABORTED,
    EXIT_FAILED,
    EXIT_PASSED,
    Confirmation,
    Runner,
    Status,
    exit_code_for,
    run_automation,
)


def make_runner(steps, tmp_path, *, driver=None, screen=None, clock=None, **kwargs):
    for step in steps:
        if step.image:
            (tmp_path / step.image).write_bytes(b"png")
    clock = clock or FakeClock()
    return Runner(
        Automation(steps=list(steps), base_dir=tmp_path),
        driver if driver is not None else FakeDriver(),
        screen if screen is not None else FakeScreen(),
        sleep=clock.sleep,
        clock=clock.clock,
        **kwargs,
    )


def run_steps(steps, tmp_path, **kwargs):
    driver = kwargs.setdefault("driver", FakeDriver())
    result = make_runner(steps, tmp_path, **kwargs).run()
    return result, driver.calls


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (Step(StepType.CLICK, x=1, y=2), ("click", 1, 2, "left", 1)),
        (Step(StepType.DOUBLE_CLICK, x=1, y=2), ("click", 1, 2, "left", 2)),
        (Step(StepType.RIGHT_CLICK, x=1, y=2), ("click", 1, 2, "right", 1)),
        (Step(StepType.MOVE, x=-1, y=-2), ("move", -1, -2)),
        (
            Step(StepType.DRAG, x=1, y=2, to_x=-3, to_y=4, duration=1.0),
            ("drag", 1, 2, -3, 4, 1.0),
        ),
        (Step(StepType.TYPE_TEXT, text="hi"), ("type_text", "hi")),
        (Step(StepType.PRESS_KEY, key="enter"), ("press_key", "enter")),
        (Step(StepType.HOTKEY, keys=("ctrl", "s")), ("hotkey", ("ctrl", "s"))),
        (Step(StepType.SCROLL, clicks=-3), ("scroll", -3, None, None)),
        (Step(StepType.SCROLL, clicks=3, x=-5, y=6), ("scroll", 3, -5, 6)),
    ],
)
def test_steps_call_the_driver(step: Step, expected: tuple, tmp_path: Path) -> None:
    result, calls = run_steps([step], tmp_path)
    assert result.passed
    assert calls == [expected]


def test_image_target_clicks_the_match_in_negative_coordinates(tmp_path: Path) -> None:
    screen = FakeScreen({"a.png": match_at(-1500, -40)})
    result, calls = run_steps([Step(StepType.CLICK, image="a.png")], tmp_path, screen=screen)
    assert result.passed
    assert calls == [("click", -1500, -40, "left", 1)]
    assert screen.searches[0][1] == 0.9


def test_per_step_confidence_reaches_the_screen(tmp_path: Path) -> None:
    screen = FakeScreen({"a.png": match_at(1, 1)})
    run_steps([Step(StepType.CLICK, image="a.png", confidence=0.55)], tmp_path, screen=screen)
    assert screen.searches[0][1] == 0.55


def test_type_clicks_the_target_first(tmp_path: Path) -> None:
    _, calls = run_steps([Step(StepType.TYPE_TEXT, text="hi", x=5, y=6)], tmp_path)
    assert calls == [("click", 5, 6, "left", 1), ("type_text", "hi")]


def test_type_with_image_target_clicks_the_match(tmp_path: Path) -> None:
    screen = FakeScreen({"a.png": match_at(50, 60)})
    _, calls = run_steps(
        [Step(StepType.TYPE_TEXT, text="hi", image="a.png")], tmp_path, screen=screen
    )
    assert calls == [("click", 50, 60, "left", 1), ("type_text", "hi")]


def test_wait_seconds_uses_the_injected_sleep(tmp_path: Path) -> None:
    clock = FakeClock()
    result, _ = run_steps([Step(StepType.WAIT_SECONDS, seconds=1.0)], tmp_path, clock=clock)
    assert result.passed
    assert clock.slept == pytest.approx(1.0)


def test_wait_for_image_retries_until_found(tmp_path: Path) -> None:
    screen = FakeScreen({"a.png": match_at(1, 1)}, found_after=2)
    result, _ = run_steps([Step(StepType.WAIT_FOR_IMAGE, image="a.png")], tmp_path, screen=screen)
    assert result.passed
    assert len(screen.searches) == 3


def test_wait_for_image_timeout_fails(tmp_path: Path) -> None:
    result, _ = run_steps([Step(StepType.WAIT_FOR_IMAGE, image="a.png", timeout=1.0)], tmp_path)
    assert result.status is Status.FAILED
    assert "not found within 1 s" in result.first_failure.message


def test_assert_image_checks_once_by_default(tmp_path: Path) -> None:
    screen = FakeScreen()
    clock = FakeClock()
    result, _ = run_steps(
        [Step(StepType.ASSERT_IMAGE_VISIBLE, image="a.png")], tmp_path, screen=screen, clock=clock
    )
    assert result.status is Status.FAILED
    assert len(screen.searches) == 1
    assert clock.slept == 0


def test_image_file_missing_at_run_time_fails_the_step(tmp_path: Path) -> None:
    clock = FakeClock()
    automation = Automation(steps=[Step(StepType.CLICK, image="gone.png")], base_dir=tmp_path)
    runner = Runner(automation, FakeDriver(), FakeScreen(), sleep=clock.sleep, clock=clock.clock)
    result = runner.run()
    assert result.status is Status.FAILED
    assert "image file not found" in result.first_failure.message


def test_failure_stops_the_run_and_records_step_and_reason(tmp_path: Path) -> None:
    steps = [
        Step(StepType.PRESS_KEY, key="a"),
        Step(StepType.ASSERT_IMAGE_VISIBLE, image="a.png"),
        Step(StepType.PRESS_KEY, key="b"),
    ]
    result, calls = run_steps(steps, tmp_path)
    assert result.status is Status.FAILED
    assert result.first_failure.index == 2
    assert calls == [("press_key", "a")]
    assert "Failed at step 2" in result.summary()
    assert exit_code_for(result) == EXIT_FAILED


def test_stop_on_failure_can_be_turned_off(tmp_path: Path) -> None:
    steps = [Step(StepType.ASSERT_IMAGE_VISIBLE, image="a.png"), Step(StepType.PRESS_KEY, key="b")]
    result, calls = run_steps(steps, tmp_path, stop_on_failure=False)
    assert result.status is Status.FAILED
    assert calls == [("press_key", "b")]
    assert len(result.steps) == 2


def test_driver_exception_is_a_step_failure(tmp_path: Path) -> None:
    driver = FakeDriver(fail_on="press_key")
    result, _ = run_steps([Step(StepType.PRESS_KEY, key="a")], tmp_path, driver=driver)
    assert result.status is Status.FAILED
    assert "driver broke" in result.first_failure.message


def test_missing_env_var_fails_without_a_value(tmp_path: Path) -> None:
    step = Step(StepType.TYPE_TEXT, env_var="NOT_SET", x=1, y=2)
    result, calls = run_steps([step], tmp_path, env={})
    assert result.status is Status.FAILED
    assert "NOT_SET is not set" in result.first_failure.message
    assert calls == []  # Failing before the click leaves the target untouched.


def test_env_var_value_is_typed_but_never_reported(tmp_path: Path) -> None:
    step = Step(StepType.TYPE_TEXT, env_var="APP_SECRET")
    result, calls = run_steps([step], tmp_path, env={"APP_SECRET": "s3cret-value"})
    assert result.passed
    assert calls == [("type_text", "s3cret-value")]
    assert "s3cret-value" not in result.summary()
    assert "APP_SECRET" in result.summary()


def test_typing_error_does_not_leak_the_value(tmp_path: Path) -> None:
    driver = FakeDriver(fail_on="type_text", error=RuntimeError("cannot type s3cret-value"))
    step = Step(StepType.TYPE_TEXT, env_var="APP_SECRET")
    result, _ = run_steps([step], tmp_path, driver=driver, env={"APP_SECRET": "s3cret-value"})
    assert result.status is Status.FAILED
    assert "s3cret-value" not in result.summary()


def test_abort_mid_wait(tmp_path: Path) -> None:
    clock = FakeClock()
    step = Step(StepType.WAIT_SECONDS, seconds=60.0)
    runner = make_runner([step], tmp_path, clock=clock, abort=lambda: clock.sleeps >= 3)
    result = runner.run()
    assert result.status is Status.ABORTED
    assert clock.slept < 1.0
    assert exit_code_for(result) == EXIT_ABORTED


def test_abort_while_waiting_for_image(tmp_path: Path) -> None:
    clock = FakeClock()
    step = Step(StepType.WAIT_FOR_IMAGE, image="a.png", timeout=60.0)
    runner = make_runner([step], tmp_path, clock=clock, abort=lambda: clock.sleeps >= 2)
    assert runner.run().status is Status.ABORTED


def test_abort_between_steps(tmp_path: Path) -> None:
    driver = FakeDriver()
    steps = [Step(StepType.PRESS_KEY, key="a"), Step(StepType.PRESS_KEY, key="b")]
    runner = make_runner(steps, tmp_path, driver=driver, abort=lambda: len(driver.calls) >= 1)
    result = runner.run()
    assert result.status is Status.ABORTED
    assert driver.calls == [("press_key", "a")]


def test_abort_during_start_delay_runs_nothing(tmp_path: Path) -> None:
    clock = FakeClock()
    driver = FakeDriver()
    steps = [Step(StepType.PRESS_KEY, key="a")]
    runner = make_runner(
        steps, tmp_path, clock=clock, driver=driver, abort=lambda: clock.sleeps >= 2
    )
    result = runner.run(delay=5.0)
    assert result.status is Status.ABORTED
    assert driver.calls == []


def test_failsafe_becomes_an_aborted_result(tmp_path: Path) -> None:
    result, _ = run_steps([Step(StepType.CLICK, x=1, y=2)], tmp_path, driver=failsafe_driver())
    assert result.status is Status.ABORTED
    assert "failsafe" in result.reason


def test_delay_is_waited_before_the_first_step(tmp_path: Path) -> None:
    clock = FakeClock()
    runner = make_runner([Step(StepType.PRESS_KEY, key="a")], tmp_path, clock=clock)
    assert runner.run(delay=5.0).passed
    assert clock.slept == pytest.approx(5.0)


def test_zero_delay_never_sleeps(tmp_path: Path) -> None:
    clock = FakeClock()
    runner = make_runner([Step(StepType.PRESS_KEY, key="a")], tmp_path, clock=clock)
    runner.run()
    assert clock.sleeps == 0


def test_guided_records_pass_and_fail_and_stops_on_fail(tmp_path: Path) -> None:
    steps = [
        Step(StepType.PRESS_KEY, key="a"),
        Step(StepType.PRESS_KEY, key="b"),
        Step(StepType.PRESS_KEY, key="c"),
    ]
    answers = iter([Confirmation.PASS, Confirmation.FAIL])
    seen = []
    driver = FakeDriver()
    result = make_runner(steps, tmp_path, driver=driver).run(
        confirm=lambda step, res: next(answers), on_step=seen.append
    )
    assert result.status is Status.FAILED
    assert [s.confirmed for s in result.steps] == [True, False]
    assert len(driver.calls) == 2
    assert seen == result.steps


def test_guided_all_passed(tmp_path: Path) -> None:
    steps = [Step(StepType.PRESS_KEY, key="a")]
    result = make_runner(steps, tmp_path).run(confirm=lambda s, r: Confirmation.PASS)
    assert result.passed


def test_guided_stop_aborts(tmp_path: Path) -> None:
    driver = FakeDriver()
    steps = [Step(StepType.PRESS_KEY, key="a"), Step(StepType.PRESS_KEY, key="b")]
    result = make_runner(steps, tmp_path, driver=driver).run(confirm=lambda s, r: Confirmation.STOP)
    assert result.status is Status.ABORTED
    assert result.reason == "stopped by the user"
    assert len(driver.calls) == 1


def test_guided_does_not_ask_about_a_step_that_failed(tmp_path: Path) -> None:
    def never(step, result):
        raise AssertionError("confirm must not be called")

    result = make_runner([Step(StepType.ASSERT_IMAGE_VISIBLE, image="a.png")], tmp_path).run(
        confirm=never
    )
    assert result.status is Status.FAILED


def fake_run_kwargs(clock: FakeClock, driver: FakeDriver | None = None) -> dict:
    return {
        "driver": driver or FakeDriver(),
        "screen": FakeScreen(),
        "sleep": clock.sleep,
        "clock": clock.clock,
        "abort": lambda: False,
    }


def test_run_automation_defaults_to_no_delay_and_loads_files(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    save_automation(Automation(steps=[Step(StepType.PRESS_KEY, key="a")]), path)
    clock = FakeClock()
    for target in (path, str(path)):
        result = run_automation(target, **fake_run_kwargs(clock))
        assert result.passed
        assert exit_code_for(result) == EXIT_PASSED
    assert clock.sleeps == 0


def test_run_automation_accepts_an_automation_with_delay() -> None:
    clock = FakeClock()
    automation = Automation(steps=[Step(StepType.PRESS_KEY, key="a")])
    assert run_automation(automation, delay=2, **fake_run_kwargs(clock)).passed
    assert clock.slept == pytest.approx(2.0)


@pytest.mark.parametrize("delay", [-1, float("nan"), float("inf"), True, "5"])
def test_run_automation_rejects_bad_delay(delay: object) -> None:
    automation = Automation(steps=[Step(StepType.PRESS_KEY, key="a")])
    with pytest.raises(ValidationError, match="delay"):
        run_automation(automation, delay=delay, **fake_run_kwargs(FakeClock()))


def test_run_automation_rejects_missing_images(tmp_path: Path) -> None:
    automation = Automation(steps=[Step(StepType.CLICK, image="a.png")], base_dir=tmp_path)
    with pytest.raises(ValidationError, match="image file not found"):
        run_automation(automation, **fake_run_kwargs(FakeClock()))


def test_run_automation_rejects_invalid_steps() -> None:
    automation = Automation(steps=[Step(StepType.TYPE_TEXT, text="x", secret=True)])
    with pytest.raises(ValidationError):
        run_automation(automation, **fake_run_kwargs(FakeClock()))


def wait_until(condition, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_abort_hotkey_sets_flag_from_the_polling_thread() -> None:
    pressed = {"down": False}
    with AbortHotkey(is_pressed=lambda: pressed["down"], poll_interval=0.005) as hotkey:
        assert not hotkey.is_set()
        pressed["down"] = True
        assert wait_until(hotkey.is_set)


def test_abort_hotkey_is_a_no_op_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    hotkey = AbortHotkey()
    hotkey.start()
    assert hotkey._thread is None
    assert not hotkey.is_set()
    hotkey.stop()


def test_abort_hotkey_needs_all_four_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    down: set[int] = set()
    user32 = SimpleNamespace(GetAsyncKeyState=lambda vk: 0x8000 if vk in down else 0)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    down.update({0x11, 0x12, 0x51})  # Ctrl+Alt+Q is also AltGr+Q and must not abort.
    assert not abort_module._hotkey_down()
    down.add(0x10)
    assert abort_module._hotkey_down()


class FakePyAutoGui:
    """Stands in for the pyautogui module."""

    class FailSafeException(Exception):
        pass

    def __init__(self, failsafe_on: str | None = None) -> None:
        self.FAILSAFE = False
        self.calls: list[tuple] = []
        self.failsafe_on = failsafe_on
        self.cursor = (500, 500)
        self.FAILSAFE_POINTS = [(0, 0)]

    def position(self) -> tuple[int, int]:
        return self.cursor

    def mouseUp(self, **kwargs) -> None:
        # The real mouseUp runs the failsafe check before it releases the button.
        if self.FAILSAFE and self.cursor in self.FAILSAFE_POINTS:
            raise self.FailSafeException("corner")
        self.calls.append(("mouseUp", (), kwargs))

    def isValidKey(self, key: str) -> bool:
        return key.isascii() and key != "nosuchkey"

    def __getattr__(self, name: str):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == self.failsafe_on:
                raise self.FailSafeException("corner")

        return record


def test_driver_passes_negative_coordinates_through() -> None:
    gui = FakePyAutoGui()
    PyAutoGuiDriver(module=gui).click(-1500, -20, button="right")
    assert gui.calls == [
        ("click", (), {"x": -1500, "y": -20, "clicks": 1, "interval": 0.0, "button": "right"})
    ]


def test_driver_keeps_failsafe_on() -> None:
    gui = FakePyAutoGui()
    PyAutoGuiDriver(module=gui).move(1, 2)
    assert gui.FAILSAFE is True


def test_driver_converts_failsafe() -> None:
    driver = PyAutoGuiDriver(module=FakePyAutoGui(failsafe_on="moveTo"))
    with pytest.raises(FailSafeAbort):
        driver.move(0, 0)


def test_failsafe_from_pyautogui_aborts_the_run(tmp_path: Path) -> None:
    driver = PyAutoGuiDriver(module=FakePyAutoGui(failsafe_on="click"))
    result = make_runner([Step(StepType.CLICK, x=1, y=2)], tmp_path, driver=driver).run()
    assert result.status is Status.ABORTED


def test_driver_moves_the_cursor_before_scrolling() -> None:
    gui = FakePyAutoGui()
    PyAutoGuiDriver(module=gui).scroll(-3, -100, 50)
    assert [call[0] for call in gui.calls] == ["moveTo", "scroll"]
    assert gui.calls[0][1] == (-100, 50)
    assert gui.calls[1][1] == (-3,)


def test_driver_drag_moves_then_drags() -> None:
    gui = FakePyAutoGui()
    PyAutoGuiDriver(module=gui).drag(-10, 1, 20, 2, 0.5)
    assert [(c[0], c[1]) for c in gui.calls] == [("moveTo", (-10, 1)), ("dragTo", (20, 2))]


def test_driver_rejects_unknown_keys() -> None:
    driver = PyAutoGuiDriver(module=FakePyAutoGui())
    with pytest.raises(DriverError):
        driver.press_key("NoSuchKey")
    with pytest.raises(DriverError):
        driver.hotkey(["ctrl", "nosuchkey"])


def test_driver_lowercases_key_names() -> None:
    gui = FakePyAutoGui()
    PyAutoGuiDriver(module=gui).press_key("Enter")
    assert gui.calls[0][1] == ("enter",)


def test_only_the_driver_module_imports_pyautogui() -> None:
    package = Path(__file__).parent.parent / "src" / "guiautomation"
    importers = [
        path.relative_to(package).as_posix()
        for path in package.rglob("*.py")
        if "import pyautogui" in path.read_text(encoding="utf-8")
    ]
    assert importers == ["driver.py"]


def test_importing_the_package_does_not_load_pyautogui() -> None:
    code = "import sys, guiautomation, guiautomation.cli; sys.exit('pyautogui' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False, timeout=60).returncode == 0


def corner_driver(after_sleeps: int, clock: FakeClock) -> FakeDriver:
    driver = FakeDriver()
    driver.in_corner = lambda: clock.sleeps >= after_sleeps
    return driver


def test_failsafe_is_honored_during_a_wait(tmp_path: Path) -> None:
    clock = FakeClock()
    step = Step(StepType.WAIT_SECONDS, seconds=60.0)
    runner = make_runner([step], tmp_path, clock=clock, driver=corner_driver(3, clock))
    result = runner.run()
    assert result.status is Status.ABORTED
    assert "failsafe" in result.reason
    assert clock.slept < 1.0


def test_failsafe_is_honored_during_the_start_delay(tmp_path: Path) -> None:
    clock = FakeClock()
    driver = corner_driver(2, clock)
    runner = make_runner([Step(StepType.PRESS_KEY, key="a")], tmp_path, clock=clock, driver=driver)
    result = runner.run(delay=5.0)
    assert result.status is Status.ABORTED
    assert "failsafe" in result.reason
    assert driver.calls == []


def test_failsafe_is_honored_during_image_polling(tmp_path: Path) -> None:
    clock = FakeClock()
    step = Step(StepType.WAIT_FOR_IMAGE, image="a.png", timeout=60.0)
    runner = make_runner([step], tmp_path, clock=clock, driver=corner_driver(2, clock))
    assert runner.run().status is Status.ABORTED


def test_a_broken_failsafe_probe_does_not_fail_the_run(tmp_path: Path) -> None:
    def broken():
        raise OSError("no cursor")

    driver = FakeDriver()
    driver.in_corner = broken
    result, _ = run_steps([Step(StepType.PRESS_KEY, key="a")], tmp_path, driver=driver)
    assert result.passed


def test_guided_stop_from_the_failsafe_reports_the_failsafe(tmp_path: Path) -> None:
    driver = FakeDriver()
    answered = []

    def confirm(step, result):
        driver.in_corner = lambda: True
        answered.append(step)
        return Confirmation.STOP

    result = make_runner([Step(StepType.PRESS_KEY, key="a")], tmp_path, driver=driver).run(
        confirm=confirm
    )
    assert result.status is Status.ABORTED
    assert "failsafe" in result.reason
    assert len(answered) == 1


def test_abort_requested_by_the_driver_aborts_the_run(tmp_path: Path) -> None:
    driver = FakeDriver(fail_on="type_text", error=AbortRequested("hotkey"))
    result, _ = run_steps([Step(StepType.TYPE_TEXT, text="hi")], tmp_path, driver=driver)
    assert result.status is Status.ABORTED
    assert result.reason == "abort hotkey pressed"


def test_abort_hotkey_survives_a_failing_poll() -> None:
    results = iter([OSError("flaky"), False, True])

    def is_pressed() -> bool:
        value = next(results, True)
        if isinstance(value, Exception):
            raise value
        return value

    with AbortHotkey(is_pressed=is_pressed, poll_interval=0.001) as hotkey:
        assert wait_until(hotkey.is_set)


def test_abort_hotkey_can_be_triggered_directly() -> None:
    hotkey = AbortHotkey(is_pressed=lambda: False)
    hotkey.trigger()
    assert hotkey.is_set()


def test_failsafe_probe_reads_the_cursor_position() -> None:
    gui = FakePyAutoGui()
    driver = PyAutoGuiDriver(module=gui)
    assert driver.failsafe_triggered() is False
    gui.cursor = (0, 0)
    assert driver.failsafe_triggered() is True


def test_failsafe_mid_drag_releases_the_button_and_restores_the_failsafe() -> None:
    gui = FakePyAutoGui(failsafe_on="dragTo")
    gui.cursor = (0, 0)  # The real mouseUp would refuse to run here with the failsafe on.
    driver = PyAutoGuiDriver(module=gui)
    with pytest.raises(FailSafeAbort):
        driver.drag(10, 10, 20, 20, 0.0)
    assert gui.calls[-1][0] == "mouseUp"
    assert gui.calls[-1][2]["button"] == "left"
    assert gui.FAILSAFE is True


def test_a_normal_drag_does_not_release_again() -> None:
    gui = FakePyAutoGui()
    PyAutoGuiDriver(module=gui).drag(10, 10, 20, 20, 0.0)
    assert "mouseUp" not in [call[0] for call in gui.calls]


def test_ascii_text_is_written_in_chunks_without_pausing() -> None:
    gui = FakePyAutoGui()
    PyAutoGuiDriver(module=gui).type_text("x" * 40)
    writes = [call for call in gui.calls if call[0] == "write"]
    assert "".join(call[1][0] for call in writes) == "x" * 40
    assert len(writes) == 3
    assert all(call[2]["_pause"] is False for call in writes)


def test_abort_stops_long_ascii_typing_between_chunks() -> None:
    gui = FakePyAutoGui()
    writes = lambda: [call for call in gui.calls if call[0] == "write"]
    driver = PyAutoGuiDriver(module=gui, abort=lambda: len(writes()) >= 1)
    with pytest.raises(AbortRequested):
        driver.type_text("x" * 40)
    assert len(writes()) == 1


class FakeUser32:
    """Records SendInput calls; no input ever reaches Windows."""

    def __init__(self, drop: int = 0) -> None:
        self.events: list[tuple[int, int, int, int]] = []
        self.sizes: list[int] = []
        self.drop = drop

    def SendInput(self, count, events, size):
        self.sizes.append(size)
        for index in range(count):
            event = events[index]
            ki = event.union.ki
            self.events.append((event.type, ki.wVk, ki.wScan, ki.dwFlags))
        return count - self.drop


def typed_text(user32: FakeUser32) -> str:
    units = [scan for _, _, scan, flags in user32.events if not flags & 0x2]
    return b"".join(unit.to_bytes(2, "little") for unit in units).decode("utf-16-le")


def unicode_driver(user32: FakeUser32, **kwargs) -> PyAutoGuiDriver:
    return PyAutoGuiDriver(
        module=kwargs.pop("module", FakePyAutoGui()),
        user32=user32,
        sleep=lambda _s: None,
        **kwargs,
    )


def test_non_ascii_text_uses_unicode_key_events() -> None:
    user32 = FakeUser32()
    unicode_driver(user32).type_text("日本語 ñ")
    assert typed_text(user32) == "日本語 ñ"
    first_down, first_up = user32.events[:2]
    assert first_down == (1, 0, ord("日"), 0x4)
    assert first_up == (1, 0, ord("日"), 0x6)
    assert set(user32.sizes) == {ctypes.sizeof(_Input)}


def test_characters_outside_the_bmp_are_sent_as_surrogates() -> None:
    user32 = FakeUser32()
    unicode_driver(user32).type_text("a😀b")
    assert typed_text(user32) == "a😀b"
    assert len(user32.events) == 8


def test_long_non_ascii_text_keeps_its_order_across_chunks() -> None:
    user32 = FakeUser32()
    text = "日本語😀" * 20
    unicode_driver(user32).type_text(text)
    assert typed_text(user32) == text
    assert len(user32.sizes) > 1


def test_newlines_in_unicode_text_become_enter() -> None:
    user32 = FakeUser32()
    unicode_driver(user32).type_text("é\r\nè\n")
    assert typed_text(user32) == "é\rè\r"


def test_input_struct_matches_the_size_windows_expects() -> None:
    assert ctypes.sizeof(_Input) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


def test_unicode_typing_stops_on_abort_between_chunks() -> None:
    user32 = FakeUser32()
    driver = unicode_driver(user32, abort=lambda: len(user32.sizes) >= 1)
    with pytest.raises(AbortRequested):
        driver.type_text("日" * 40)
    assert len(user32.sizes) == 1


def test_unicode_typing_stops_on_failsafe_between_chunks() -> None:
    gui = FakePyAutoGui()
    user32 = FakeUser32()

    class CornerAfterFirstChunk(PyAutoGuiDriver):
        def _check_stop(self) -> None:
            gui.cursor = (0, 0) if user32.sizes else (500, 500)
            super()._check_stop()

    driver = CornerAfterFirstChunk(module=gui, user32=user32, sleep=lambda _s: None)
    with pytest.raises(FailSafeAbort):
        driver.type_text("日" * 40)
    assert len(user32.sizes) == 1


def test_blocked_input_is_an_error_that_does_not_quote_the_text() -> None:
    with pytest.raises(DriverError) as error:
        unicode_driver(FakeUser32(drop=1)).type_text("秘密")
    assert "秘密" not in str(error.value)


def test_the_clipboard_is_never_used_for_typing() -> None:
    source = Path(__file__).parent.parent / "src" / "guiautomation" / "driver.py"
    assert "pyperclip" not in source.read_text(encoding="utf-8")
