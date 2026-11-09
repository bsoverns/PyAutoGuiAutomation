"""Test model: step types, strict validation, and JSON save and load."""

from __future__ import annotations

import filecmp
import json
import math
import os
import re
import shutil
from dataclasses import dataclass, field, fields
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Any

FORMAT_VERSION = 1
DEFAULT_CONFIDENCE = 0.9
DEFAULT_TIMEOUT = 10.0
DEFAULT_DRAG_DURATION = 0.2


class ValidationError(ValueError):
    """A test file or step is invalid. The message says where and why."""


class StepType(StrEnum):
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    MOVE = "move"
    DRAG = "drag"
    TYPE_TEXT = "type_text"
    PRESS_KEY = "press_key"
    HOTKEY = "hotkey"
    SCROLL = "scroll"
    WAIT_SECONDS = "wait_seconds"
    WAIT_FOR_IMAGE = "wait_for_image"
    ASSERT_IMAGE_VISIBLE = "assert_image_visible"


@dataclass(frozen=True)
class Step:
    type: StepType
    description: str | None = None
    x: int | None = None
    y: int | None = None
    image: str | None = None
    confidence: float | None = None
    timeout: float | None = None
    to_x: int | None = None
    to_y: int | None = None
    duration: float | None = None
    text: str | None = None
    env_var: str | None = None
    secret: bool = False
    key: str | None = None
    keys: tuple[str, ...] | None = None
    clicks: int | None = None
    seconds: float | None = None


_TARGET = {"x", "y", "image", "confidence", "timeout"}
_IMAGE = {"image", "confidence", "timeout"}
_ALLOWED_FIELDS: dict[StepType, set[str]] = {
    StepType.CLICK: _TARGET,
    StepType.DOUBLE_CLICK: _TARGET,
    StepType.RIGHT_CLICK: _TARGET,
    StepType.MOVE: _TARGET,
    StepType.DRAG: _TARGET | {"to_x", "to_y", "duration"},
    StepType.TYPE_TEXT: _TARGET | {"text", "env_var", "secret"},
    StepType.PRESS_KEY: {"key"},
    StepType.HOTKEY: {"keys"},
    StepType.SCROLL: _TARGET | {"clicks"},
    StepType.WAIT_SECONDS: {"seconds"},
    StepType.WAIT_FOR_IMAGE: _IMAGE,
    StepType.ASSERT_IMAGE_VISIBLE: _IMAGE,
}
_COMMON_FIELDS = {"type", "description"}
_TARGET_REQUIRED = {
    StepType.CLICK,
    StepType.DOUBLE_CLICK,
    StepType.RIGHT_CLICK,
    StepType.MOVE,
    StepType.DRAG,
}
_IMAGE_REQUIRED = {StepType.WAIT_FOR_IMAGE, StepType.ASSERT_IMAGE_VISIBLE}

_ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_LITERAL = re.compile(
    r"(?i)(?<![a-z0-9])(?:password|passwd|pwd|passphrase|secret|api[_-]?key"
    r"|access[_-]?token|auth[_-]?token|token)\s*[:=]\s*\S"
    r"|\b(?:ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,})\b"
)


def _fail(where: str, message: str) -> None:
    raise ValidationError(f"{where}: {message}")


def _check_int(value: Any, where: str, name: str) -> None:
    if type(value) is not int:
        _fail(where, f"{name} must be an integer")


def _check_number(value: Any, where: str, name: str, *, minimum: float = 0.0) -> None:
    if type(value) not in (int, float) or not math.isfinite(value):
        _fail(where, f"{name} must be a finite number")
    if value < minimum:
        _fail(where, f"{name} must be at least {minimum:g}")


def _check_text(value: Any, where: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _fail(where, f"{name} must be a non-empty string")


def validate_image_path(image: Any, where: str = "image") -> None:
    """Reject image paths that are not plain relative paths inside the test folder."""
    _check_text(image, where, "image")
    if "\0" in image or ":" in image:
        _fail(where, "image path contains invalid characters")
    windows_path = PureWindowsPath(image)
    if windows_path.is_absolute() or windows_path.root or image.startswith(("/", "\\")):
        _fail(where, "image path must be relative to the test file")
    if ".." in windows_path.parts:
        _fail(where, "image path must stay inside the test file's folder")


def _validate_target(step: Step, where: str) -> None:
    for name in ("to_x", "to_y"):
        value = getattr(step, name)
        if value is not None:
            _check_int(value, where, name)
    has_coordinates = step.x is not None or step.y is not None
    if has_coordinates:
        if step.x is None or step.y is None:
            _fail(where, "x and y must be given together")
        _check_int(step.x, where, "x")
        _check_int(step.y, where, "y")
    if step.image is not None:
        validate_image_path(step.image, where)
        if has_coordinates:
            _fail(where, "use either coordinates or an image, not both")
    elif step.type in _TARGET_REQUIRED and not has_coordinates:
        _fail(where, "needs a target: x and y, or an image")
    elif step.type in _IMAGE_REQUIRED:
        _fail(where, "needs an image")
    if step.confidence is not None:
        _check_number(step.confidence, where, "confidence")
        if not 0 < step.confidence <= 1:
            _fail(where, "confidence must be greater than 0 and at most 1")
    if step.timeout is not None:
        _check_number(step.timeout, where, "timeout")


def _validate_type_text(step: Step, where: str) -> None:
    if (step.text is None) == (step.env_var is None):
        _fail(where, "type_text needs exactly one of text or env_var")
    if type(step.secret) is not bool:
        _fail(where, "secret must be true or false")
    if step.env_var is not None:
        if not isinstance(step.env_var, str) or not _ENV_VAR_NAME.match(step.env_var):
            _fail(where, "env_var must be a valid environment variable name")
        return
    if not isinstance(step.text, str):
        _fail(where, "text must be a string")
    if step.secret:
        _fail(where, "a secret must come from env_var; literal text cannot be saved")
    if _SECRET_LITERAL.search(step.text):
        _fail(where, "text looks like a secret; use env_var instead")


def validate_step(step: Step, where: str = "step") -> None:
    """Raise ValidationError if the step is not valid for its type."""
    if not isinstance(step.type, StepType):
        _fail(where, f"unknown step type {step.type!r}")
    allowed = _ALLOWED_FIELDS[step.type] | _COMMON_FIELDS
    for spec in fields(step):
        value = getattr(step, spec.name)
        if spec.name not in allowed and value is not None and value is not False:
            _fail(where, f"field {spec.name!r} is not valid for {step.type.value}")
    if step.description is not None and not isinstance(step.description, str):
        _fail(where, "description must be a string")
    _validate_target(step, where)
    if step.type is StepType.TYPE_TEXT:
        _validate_type_text(step, where)
    elif step.type is StepType.DRAG:
        if step.to_x is None or step.to_y is None:
            _fail(where, "drag needs to_x and to_y")
        if step.duration is not None:
            _check_number(step.duration, where, "duration")
    elif step.type is StepType.PRESS_KEY:
        _check_text(step.key, where, "key")
    elif step.type is StepType.HOTKEY:
        if not isinstance(step.keys, (list, tuple)) or not step.keys:
            _fail(where, "keys must be a non-empty list")
        for key in step.keys:
            _check_text(key, where, "keys entry")
    elif step.type is StepType.SCROLL:
        _check_int(step.clicks, where, "clicks")
    elif step.type is StepType.WAIT_SECONDS:
        _check_number(step.seconds, where, "seconds")


def step_from_dict(raw: Any, where: str = "step") -> Step:
    """Build a validated Step from parsed JSON."""
    if not isinstance(raw, dict):
        _fail(where, "must be an object")
    if "type" not in raw:
        _fail(where, "missing field 'type'")
    try:
        step_type = StepType(raw["type"])
    except ValueError:
        _fail(where, f"unknown step type {raw['type']!r}")
    allowed = _ALLOWED_FIELDS[step_type] | _COMMON_FIELDS
    unknown = sorted(set(raw) - allowed)
    if unknown:
        _fail(where, f"unknown field(s) for {step_type.value}: {', '.join(unknown)}")
    values = {name: value for name, value in raw.items() if name != "type"}
    if "keys" in values:
        if not isinstance(values["keys"], list):
            _fail(where, "keys must be a non-empty list")
        values["keys"] = tuple(values["keys"])
    step = Step(type=step_type, **values)
    validate_step(step, where)
    return step


def step_to_dict(step: Step) -> dict[str, Any]:
    """Return the JSON form of a step; unset fields are left out."""
    data: dict[str, Any] = {"type": step.type.value}
    for spec in fields(step):
        if spec.name == "type":
            continue
        value = getattr(step, spec.name)
        if value is None or value is False:
            continue
        data[spec.name] = list(value) if spec.name == "keys" else value
    return data


REPEAT_FOREVER = 0  # A repeat count that means "until stopped".


def validate_repeat(value: Any) -> None:
    """Raise ValidationError unless value is a loop count or REPEAT_FOREVER."""
    if type(value) is not int or value < 0:
        _fail("repeat", "must be a whole number, 1 or more, or 0 to repeat forever")


@dataclass
class Automation:
    name: str = ""
    steps: list[Step] = field(default_factory=list)
    base_dir: Path | None = None
    version: int = FORMAT_VERSION
    repeat: int = 1

    def validate(self) -> None:
        """Raise ValidationError if the automation or any step is invalid."""
        if not isinstance(self.name, str):
            _fail("name", "must be a string")
        if type(self.version) is not int or self.version != FORMAT_VERSION:
            _fail("version", f"unsupported version {self.version!r}; expected {FORMAT_VERSION}")
        validate_repeat(self.repeat)
        for index, step in enumerate(self.steps):
            validate_step(step, f"steps[{index}]")

    def resolve_image(self, image: str) -> Path:
        """Return the absolute path of an image, refusing paths outside the test folder."""
        validate_image_path(image)
        if self.base_dir is None:
            raise ValidationError(f"image {image!r} has no folder; save the test first")
        base = self.base_dir.resolve()
        resolved = (base / image).resolve()
        if not resolved.is_relative_to(base):
            raise ValidationError(f"image {image!r} is outside the test folder")
        return resolved

    def image_paths(self) -> list[str]:
        """Return the distinct image paths the steps refer to."""
        return list(dict.fromkeys(step.image for step in self.steps if step.image is not None))

    def check_runnable(self) -> None:
        """Raise ValidationError if the automation cannot be run as it stands."""
        self.validate()
        if not self.steps:
            raise ValidationError("the test has no steps")
        for image in self.image_paths():
            if not self.resolve_image(image).is_file():
                raise ValidationError(f"image file not found: {image}")


def automation_from_dict(data: Any, base_dir: Path | None = None) -> Automation:
    """Build a validated Automation from parsed JSON."""
    if not isinstance(data, dict):
        raise ValidationError("top level must be an object")
    unknown = sorted(set(data) - {"version", "name", "steps", "repeat"})
    if unknown:
        raise ValidationError(f"unknown top-level field(s): {', '.join(unknown)}")
    if "version" not in data:
        raise ValidationError("missing field 'version'")
    if "steps" not in data:
        raise ValidationError("missing field 'steps'")
    if not isinstance(data["steps"], list):
        raise ValidationError("steps must be a list")
    steps = [step_from_dict(raw, f"steps[{i}]") for i, raw in enumerate(data["steps"])]
    automation = Automation(
        name=data.get("name", ""),
        steps=steps,
        base_dir=base_dir,
        version=data["version"],
        repeat=data.get("repeat", 1),
    )
    automation.validate()
    return automation


def automation_to_dict(automation: Automation) -> dict[str, Any]:
    """Return the JSON form of an automation, validating it first."""
    automation.validate()
    data: dict[str, Any] = {"version": automation.version, "name": automation.name}
    if automation.repeat != 1:
        data["repeat"] = automation.repeat
    data["steps"] = [step_to_dict(step) for step in automation.steps]
    return data


def _reject_constant(name: str) -> None:
    raise ValidationError(f"invalid JSON: {name} is not allowed")


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"invalid JSON: duplicate key {key!r}")
        result[key] = value
    return result


def parse_automation(text: str, base_dir: Path | None = None) -> Automation:
    """Parse JSON text into a validated Automation."""
    try:
        data = json.loads(
            text, parse_constant=_reject_constant, object_pairs_hook=_reject_duplicates
        )
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except RecursionError as exc:
        raise ValidationError("invalid JSON: nested too deeply") from exc
    return automation_from_dict(data, base_dir)


def load_automation(path: str | os.PathLike[str]) -> Automation:
    """Load and validate a test file. Images are relative to its folder."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(f"cannot read {file_path}: {exc}") from exc
    try:
        return parse_automation(text, file_path.resolve().parent)
    except ValidationError as exc:
        raise ValidationError(f"{file_path}: {exc}") from exc


def _copy_images(automation: Automation, new_base: Path) -> None:
    """Copy images to a new folder, refusing to replace different files already there."""
    copies: list[tuple[Path, Path]] = []
    for image in automation.image_paths():
        source = automation.resolve_image(image)
        destination = new_base / image
        if not source.is_file():
            continue
        if not destination.exists():
            copies.append((source, destination))
        elif not filecmp.cmp(source, destination, shallow=False):
            raise ValidationError(f"{destination} already exists with different content")
    for source, destination in copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def save_automation(automation: Automation, path: str | os.PathLike[str]) -> None:
    """Validate and write a test file, copying its images when the folder changes."""
    data = automation_to_dict(automation)
    target = Path(path)
    new_base = target.resolve().parent
    new_base.mkdir(parents=True, exist_ok=True)
    if automation.base_dir is not None and automation.base_dir.resolve() != new_base:
        _copy_images(automation, new_base)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    automation.base_dir = new_base
