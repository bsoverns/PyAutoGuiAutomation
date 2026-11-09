"""GUI behavior as plain code, so it can be tested without a display."""

from __future__ import annotations

import queue
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

from guiautomation.keys import canonical_key
from guiautomation.model import (
    DEFAULT_CONFIDENCE,
    KEEP_LOOKING,
    REPEAT_FOREVER,
    Step,
    StepType,
    ValidationError,
    validate_step,
)
from guiautomation.runner import Confirmation, RunResult, StepResult
from guiautomation.screen import Monitor

MIN_REGION_SIZE = 5
IMAGE_FOLDER = "images"
CLIP_DELAYS: tuple[tuple[str, int], ...] = (  # (label, seconds); the first is the default
    ("No delay", 0),
    ("3 seconds", 3),
    ("5 seconds", 5),
    ("10 seconds", 10),
)
COUNTDOWN_TICK_MS = 1000


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str  # "int", "float", "text", "key", "keys", "image", or "choice"
    choices: tuple[tuple[str, str | None], ...] = ()  # (label, stored value); the first is default


_X = FieldSpec("x", "X (screen)", "int")
_Y = FieldSpec("y", "Y (screen)", "int")
_IMAGE = FieldSpec("image", "Image", "image")
_CONFIDENCE = FieldSpec(
    "confidence", f"Confidence (1 = exact, lower = looser, blank = {DEFAULT_CONFIDENCE:g})", "float"
)
_TIMEOUT = FieldSpec("timeout", "Timeout (s)", "float")
_NOT_FOUND = FieldSpec(
    "if_not_found",
    "If the image is not found",
    "choice",
    (("Stop the run as failed", None), ("Keep looking until found", KEEP_LOOKING)),
)
_TARGET = [_X, _Y, _IMAGE, _CONFIDENCE, _TIMEOUT, _NOT_FOUND]
_IMAGE_ONLY = [_IMAGE, _CONFIDENCE, _TIMEOUT, _NOT_FOUND]
_DESCRIPTION = FieldSpec("description", "Step name", "text")

_FIELDS: dict[StepType, list[FieldSpec]] = {
    StepType.CLICK: _TARGET,
    StepType.DOUBLE_CLICK: _TARGET,
    StepType.RIGHT_CLICK: _TARGET,
    StepType.MOVE: _TARGET,
    StepType.DRAG: [
        *_TARGET,
        FieldSpec("to_x", "To X", "int"),
        FieldSpec("to_y", "To Y", "int"),
        FieldSpec("duration", "Duration (s)", "float"),
    ],
    StepType.TYPE_TEXT: [
        FieldSpec("text", "Text (not for secrets)", "text"),
        FieldSpec("env_var", "Or environment variable", "text"),
        *_TARGET,
    ],
    StepType.PRESS_KEY: [FieldSpec("key", "Key (pick one or type it)", "key")],
    StepType.HOTKEY: [FieldSpec("keys", "Keys (e.g. win+d, ctrl+c)", "keys")],
    StepType.SCROLL: [FieldSpec("clicks", "Clicks (+ up, - down)", "int"), *_TARGET],
    StepType.WAIT_SECONDS: [FieldSpec("seconds", "Seconds", "float")],
    StepType.WAIT_FOR_IMAGE: _IMAGE_ONLY,
    StepType.ASSERT_IMAGE_VISIBLE: _IMAGE_ONLY,
}


def fields_for(step_type: StepType) -> list[FieldSpec]:
    """Return the form fields for a step type."""
    return [_DESCRIPTION, *_FIELDS[step_type]]


def _parse(spec: FieldSpec, raw: str) -> Any:
    if spec.kind == "choice":
        return dict(spec.choices).get(raw)
    if spec.kind == "text" and spec.name == "text":
        return raw if raw else None
    text = raw.strip()
    if not text:
        return None
    if spec.kind == "int":
        try:
            return int(text)
        except ValueError:
            raise ValidationError(f"{spec.label}: must be a whole number") from None
    if spec.kind == "float":
        try:
            return float(text)
        except ValueError:
            raise ValidationError(f"{spec.label}: must be a number") from None
    if spec.kind == "key":
        return canonical_key(text)
    if spec.kind == "keys":
        parts = (part.strip() for part in text.replace(",", "+").split("+"))
        return tuple(canonical_key(part) for part in parts if part)
    return text


def step_from_form(step_type: StepType, form: dict[str, str], previous: Step | None = None) -> Step:
    """Build a validated Step from form strings. Blank fields are unset."""
    values = {spec.name: _parse(spec, form.get(spec.name, "")) for spec in fields_for(step_type)}
    keep_secret = (
        previous is not None
        and previous.type is step_type
        and previous.secret
        and values.get("env_var") is not None
    )
    step = Step(type=step_type, secret=keep_secret, **values)
    validate_step(step, step_type.value)
    return step


def step_to_form(step: Step) -> dict[str, str]:
    """Return form strings for a step."""
    form: dict[str, str] = {}
    for spec in fields_for(step.type):
        value = getattr(step, spec.name)
        if spec.kind == "choice":
            form[spec.name] = next(label for label, kept in spec.choices if kept == value)
        elif value is None:
            form[spec.name] = ""
        elif spec.kind == "keys":
            form[spec.name] = "+".join(value)
        else:
            form[spec.name] = str(value)
    return form


def takes_image(step_type: StepType) -> bool:
    """Return True if steps of this type can target a clipped image."""
    return any(spec.kind == "image" for spec in fields_for(step_type))


def with_clip(step: Step, relative: str) -> Step:
    """Return the step aimed at a new clip, keeping everything else about it."""
    updated = replace(step, image=relative, x=None, y=None)
    validate_step(updated, step.type.value)
    return updated


def parse_repeat(count: str, forever: bool) -> int:
    """Turn the builder's loop controls into a repeat value."""
    if forever:
        return REPEAT_FOREVER
    try:
        value = int(count.strip())
    except ValueError:
        value = 0
    if value < 1:
        raise ValidationError("Repeat: must be a whole number, 1 or more")
    return value


def describe_loops(repeat: int) -> str:
    """Return a short description of a repeat value for the run status window."""
    if repeat == REPEAT_FOREVER:
        return "forever"
    return f"{repeat} time{'' if repeat == 1 else 's'}"


def loop_status(iteration: int, repeat: int) -> str:
    """Return the progress line shown while a run loops."""
    if repeat == REPEAT_FOREVER:
        return f"Loop {iteration} (repeating forever)"
    return f"Loop {iteration} of {repeat}"


def step_status(index: int, total: int, step: Step) -> str:
    """Return the line naming the step that is running. Never shows typed values."""
    return f"Step {index} of {total}: {step.label}"


def _describe_target(step: Step) -> str:
    if step.image is not None:
        until = ", until found" if step.if_not_found == KEEP_LOOKING else ""
        return f"image {step.image}{until}"
    if step.x is not None:
        return f"({step.x}, {step.y})"
    return ""


def describe_step(step: Step) -> str:
    """Return a one-line summary for the step list. Never shows an environment value."""
    kind = step.type.value.replace("_", " ")
    if step.type is StepType.TYPE_TEXT:
        what = f"${step.env_var}" if step.env_var else repr(step.text)
        detail = f"{what} {_describe_target(step)}".strip()
    elif step.type is StepType.DRAG:
        detail = f"{_describe_target(step)} to ({step.to_x}, {step.to_y})"
    elif step.type is StepType.PRESS_KEY:
        detail = str(step.key)
    elif step.type is StepType.HOTKEY:
        detail = "+".join(step.keys or ())
    elif step.type is StepType.SCROLL:
        detail = f"{step.clicks} {_describe_target(step)}".strip()
    elif step.type is StepType.WAIT_SECONDS:
        detail = f"{step.seconds:g} s"
    else:
        detail = _describe_target(step)
    summary = f"{kind}: {detail}"
    return f"{step.description}  ({summary})" if step.description else summary


class StepList:
    """Editing operations on a list of steps. Methods return the new selection."""

    def __init__(self, steps: list[Step] | None = None) -> None:
        self.steps: list[Step] = steps if steps is not None else []

    def add(self, step: Step, after: int | None = None) -> int:
        index = len(self.steps) if after is None else after + 1
        self.steps.insert(index, step)
        return index

    def replace(self, index: int, step: Step) -> int:
        self.steps[index] = step
        return index

    def delete(self, index: int) -> int | None:
        del self.steps[index]
        return min(index, len(self.steps) - 1) if self.steps else None

    def move_up(self, index: int) -> int:
        if index <= 0:
            return index
        self.steps[index - 1], self.steps[index] = self.steps[index], self.steps[index - 1]
        return index - 1

    def move_down(self, index: int) -> int:
        if index >= len(self.steps) - 1:
            return index
        self.steps[index + 1], self.steps[index] = self.steps[index], self.steps[index + 1]
        return index + 1


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int


def overlay_geometry(desktop: Monitor) -> str:
    """Return a Tk geometry string; Tk reads "+-1920" as an offset left of the origin."""
    return f"{desktop.width}x{desktop.height}+{desktop.left}+{desktop.top}"


def to_canvas(x_root: int, y_root: int, desktop: Monitor) -> tuple[int, int]:
    """Convert virtual-desktop coordinates to overlay canvas coordinates."""
    return x_root - desktop.left, y_root - desktop.top


def drag_to_region(x0: int, y0: int, x1: int, y1: int, desktop: Monitor) -> Region | None:
    """Turn a drag, in virtual-desktop coordinates, into a region clamped to the desktop."""
    left = max(min(x0, x1), desktop.left)
    top = max(min(y0, y1), desktop.top)
    right = min(max(x0, x1), desktop.right)
    bottom = min(max(y0, y1), desktop.bottom)
    if right - left < MIN_REGION_SIZE or bottom - top < MIN_REGION_SIZE:
        return None
    return Region(left, top, right - left, bottom - top)


def crop_box(region: Region, desktop: Monitor) -> tuple[int, int, int, int]:
    """Return the box that cuts a region out of an image of the whole virtual desktop."""
    left, top = to_canvas(region.left, region.top, desktop)
    return left, top, left + region.width, top + region.height


def clip_delay_seconds(label: str) -> int:
    """Return the seconds for a clip delay label. An unknown label means no delay."""
    return dict(CLIP_DELAYS).get(label, 0)


def countdown_text(remaining: int) -> str:
    """Return the line shown while a delayed clip is pending."""
    return f"Clip in {remaining} s. Click here or press Esc to cancel."


class ClipCountdown:
    """Counts down whole seconds before a clip, on an injected scheduler.

    ``schedule(milliseconds, callback)`` returns a handle that ``cancel_scheduled`` accepts, as
    tkinter's ``after`` and ``after_cancel`` do. ``on_tick`` gets the seconds left, once a second.
    """

    def __init__(
        self,
        seconds: int,
        schedule: Callable[[int, Callable[[], None]], Any],
        cancel_scheduled: Callable[[Any], None],
        on_tick: Callable[[int], None],
        on_done: Callable[[], None],
    ) -> None:
        self.remaining = max(seconds, 0)
        self._schedule = schedule
        self._cancel_scheduled = cancel_scheduled
        self._on_tick = on_tick
        self._on_done = on_done
        self._handle: Any = None
        self._started = False
        self._over = False

    def start(self) -> None:
        """Begin counting. With nothing to count, ``on_done`` runs at once."""
        if self._started:
            return
        self._started = True
        self._show()

    def _show(self) -> None:
        if self.remaining <= 0:
            self._over = True
            self._on_done()
            return
        self._on_tick(self.remaining)
        self._handle = self._schedule(COUNTDOWN_TICK_MS, self._second_passed)

    def _second_passed(self) -> None:
        self._handle = None
        if self._over:
            return
        self.remaining -= 1
        self._show()

    def cancel(self) -> bool:
        """Stop counting. Returns False if the countdown had already finished or been stopped."""
        if self._over:
            return False
        self._over = True
        if self._handle is not None:
            self._cancel_scheduled(self._handle)
            self._handle = None
        return True


def capture_filename(now: datetime) -> str:
    """Return a relative path for a new capture. The suffix is gitignored."""
    name = f"{now:%Y%m%d-%H%M%S-%f}.capture.png"
    return str(PurePosixPath(IMAGE_FOLDER) / name)


class GuidedBridge:
    """Passes confirm requests from the worker thread to the UI thread and back."""

    def __init__(self, abort: Callable[[], bool] = lambda: False, poll: float = 0.05) -> None:
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._answers: queue.Queue[Confirmation] = queue.Queue()
        self._abort = abort
        self._poll = poll

    def confirm(self, step: Step, result: StepResult) -> Confirmation:
        """Called on the worker thread: ask the user, and wait for the answer or an abort."""
        self.events.put(("confirm", (step, result)))
        while True:
            try:
                return self._answers.get(timeout=self._poll)
            except queue.Empty:
                if self._abort():
                    return Confirmation.STOP

    def answer(self, confirmation: Confirmation) -> None:
        """Called on the UI thread with the user's choice."""
        self._answers.put(confirmation)

    def finish(self, result: RunResult) -> None:
        self.events.put(("done", result))

    def fail(self, message: str) -> None:
        self.events.put(("error", message))
