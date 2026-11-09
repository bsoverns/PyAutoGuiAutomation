"""AC1, AC2, AC4, AC9: step validation, JSON save and load, and secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from guiautomation.model import (
    Automation,
    Step,
    StepType,
    ValidationError,
    load_automation,
    parse_automation,
    save_automation,
    step_from_dict,
    step_to_dict,
    validate_step,
)

VALID_STEPS = [
    {"type": "click", "x": 10, "y": 20},
    {"type": "click", "image": "images/a.png", "confidence": 0.8, "timeout": 2},
    {"type": "double_click", "x": -1500, "y": -20},
    {"type": "right_click", "x": 0, "y": 0},
    {"type": "move", "x": 1, "y": 2},
    {"type": "drag", "x": 1, "y": 2, "to_x": -3, "to_y": 4, "duration": 0.5},
    {"type": "type_text", "text": "hello"},
    {"type": "type_text", "env_var": "APP_PASSWORD", "secret": True, "x": 5, "y": 6},
    {"type": "press_key", "key": "enter"},
    {"type": "hotkey", "keys": ["ctrl", "s"]},
    {"type": "scroll", "clicks": -3},
    {"type": "scroll", "clicks": 3, "x": 9, "y": 9},
    {"type": "wait_seconds", "seconds": 1.5},
    {"type": "wait_for_image", "image": "a.png"},
    {"type": "assert_image_visible", "image": "sub/a.png", "timeout": 0},
]


def document(steps: list) -> str:
    return json.dumps({"version": 1, "name": "t", "steps": steps})


@pytest.mark.parametrize("raw", VALID_STEPS, ids=lambda r: r["type"])
def test_every_step_type_round_trips(raw: dict) -> None:
    assert step_to_dict(step_from_dict(raw)) == raw


def test_all_step_types_are_covered_by_samples() -> None:
    assert {raw["type"] for raw in VALID_STEPS} == {kind.value for kind in StepType}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{not json", "invalid JSON at line 1"),
        ("[]", "top level must be an object"),
        ('{"steps": []}', "missing field 'version'"),
        ('{"version": 1}', "missing field 'steps'"),
        ('{"version": 2, "steps": []}', "unsupported version"),
        ('{"version": true, "steps": []}', "unsupported version"),
        ('{"version": "1", "steps": []}', "unsupported version"),
        ('{"version": 1, "steps": {}}', "steps must be a list"),
        ('{"version": 1, "steps": [], "extra": 1}', "unknown top-level"),
        ('{"version": 1, "name": 5, "steps": []}', "name: must be a string"),
        ('{"version": 1, "version": 1, "steps": []}', "duplicate key"),
        ('{"version": 1, "steps": [{"type":"wait_seconds","seconds":NaN}]}', "NaN"),
    ],
)
def test_invalid_documents_have_clear_errors(text: str, expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        parse_automation(text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("nope", "must be an object"),
        ({"x": 1}, "missing field 'type'"),
        ({"type": "explode"}, "unknown step type"),
        ({"type": ["click"]}, "unknown step type"),
        ({"type": "click", "x": 1, "y": 2, "color": "red"}, "unknown field"),
        ({"type": "press_key", "key": "a", "x": 1}, "unknown field"),
        ({"type": "click"}, "needs a target"),
        ({"type": "click", "x": 1}, "together"),
        ({"type": "click", "x": 1.5, "y": 2}, "x must be an integer"),
        ({"type": "click", "x": True, "y": 2}, "x must be an integer"),
        ({"type": "click", "x": 1, "y": 2, "image": "a.png"}, "not both"),
        ({"type": "click", "image": "a.png", "confidence": 0}, "confidence"),
        ({"type": "click", "image": "a.png", "confidence": 1.5}, "confidence"),
        ({"type": "click", "image": "a.png", "timeout": -1}, "timeout"),
        ({"type": "drag", "x": 1, "y": 2}, "to_x and to_y"),
        ({"type": "type_text"}, "exactly one"),
        ({"type": "type_text", "text": "a", "env_var": "B"}, "exactly one"),
        ({"type": "type_text", "env_var": "1 BAD"}, "env_var"),
        ({"type": "type_text", "text": 5}, "text must be a string"),
        ({"type": "press_key", "key": " "}, "key"),
        ({"type": "hotkey", "keys": []}, "keys"),
        ({"type": "hotkey", "keys": "ctrl"}, "keys"),
        ({"type": "scroll"}, "clicks"),
        ({"type": "wait_seconds", "seconds": -1}, "seconds"),
        ({"type": "wait_for_image"}, "needs an image"),
    ],
)
def test_invalid_steps_are_rejected(raw: object, expected: str) -> None:
    with pytest.raises(ValidationError, match=expected):
        step_from_dict(raw)


def test_error_names_the_step_index() -> None:
    with pytest.raises(ValidationError, match=r"steps\[1\]"):
        parse_automation(document([VALID_STEPS[0], {"type": "explode"}]))


@pytest.mark.parametrize(
    "image",
    [
        "../a.png",
        "a/../../b.png",
        "a\\..\\..\\b.png",
        "C:\\a.png",
        "C:a.png",
        "/etc/a.png",
        "\\a.png",
        "\\\\server\\share\\a.png",
        "a.png:stream",
        "",
    ],
)
def test_unsafe_image_paths_are_rejected(image: str) -> None:
    with pytest.raises(ValidationError):
        parse_automation(document([{"type": "wait_for_image", "image": image}]))


def test_symlink_escaping_the_folder_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    base = tmp_path / "test"
    base.mkdir()
    try:
        os.symlink(outside, base / "link.png")
    except OSError:
        pytest.skip("symlinks are not permitted here")
    with pytest.raises(ValidationError, match="outside"):
        Automation(base_dir=base).resolve_image("link.png")


def test_resolve_image_needs_a_saved_test() -> None:
    with pytest.raises(ValidationError, match="save the test"):
        Automation().resolve_image("a.png")


def test_save_and_load_round_trip_with_non_ascii(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "test.json"
    automation = Automation("naïve", [Step(StepType.TYPE_TEXT, text="日本語 Ünï")])
    save_automation(automation, path)
    loaded = load_automation(path)
    assert loaded.steps == automation.steps
    assert loaded.name == "naïve"
    assert loaded.base_dir == path.resolve().parent
    assert not list(path.parent.glob("*.tmp"))


def test_load_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "t.json"
    path.write_bytes(b"\xef\xbb\xbf" + document([]).encode())
    assert load_automation(path).steps == []


def test_load_missing_file_is_a_validation_error(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="cannot read"):
        load_automation(tmp_path / "missing.json")


def test_load_reports_the_file_name(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValidationError, match="bad.json"):
        load_automation(path)


def test_save_to_another_folder_copies_images(tmp_path: Path) -> None:
    old = tmp_path / "old"
    (old / "images").mkdir(parents=True)
    (old / "images" / "a.png").write_bytes(b"png")
    automation = Automation(
        steps=[Step(StepType.WAIT_FOR_IMAGE, image="images/a.png")], base_dir=old
    )
    new = tmp_path / "new" / "t.json"
    save_automation(automation, new)
    assert (new.parent / "images" / "a.png").read_bytes() == b"png"
    assert automation.base_dir == new.resolve().parent


def test_literal_secret_flag_is_rejected_on_load_and_save(tmp_path: Path) -> None:
    raw = {"type": "type_text", "text": "hunter2", "secret": True}
    with pytest.raises(ValidationError, match="env_var"):
        parse_automation(document([raw]))
    automation = Automation(steps=[Step(StepType.TYPE_TEXT, text="hunter2", secret=True)])
    target = tmp_path / "t.json"
    with pytest.raises(ValidationError, match="env_var"):
        save_automation(automation, target)
    assert not target.exists()


@pytest.mark.parametrize(
    "text",
    [
        "password=hunter2",
        "API_KEY: abc",
        "my_password = x",
        "token=abc",
        "ghp_abcdefghijklmnopqrstuvwxyz",
        "AKIAABCDEFGHIJKLMNOP",
    ],
)
def test_secret_looking_literals_are_rejected(text: str) -> None:
    with pytest.raises(ValidationError, match="looks like a secret"):
        validate_step(Step(StepType.TYPE_TEXT, text=text))


@pytest.mark.parametrize("text", ["hello", "password", "the token was", "user@example.com"])
def test_ordinary_text_is_accepted(text: str) -> None:
    validate_step(Step(StepType.TYPE_TEXT, text=text))


def test_env_var_step_stores_only_the_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", "s3cret-value")
    automation = Automation(steps=[Step(StepType.TYPE_TEXT, env_var="APP_PASSWORD", secret=True)])
    path = tmp_path / "t.json"
    save_automation(automation, path)
    content = path.read_text(encoding="utf-8")
    assert "APP_PASSWORD" in content
    assert "s3cret-value" not in content


def test_check_runnable_rejects_empty_and_missing_images(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="no steps"):
        Automation(base_dir=tmp_path).check_runnable()
    automation = Automation(steps=[Step(StepType.WAIT_FOR_IMAGE, image="a.png")], base_dir=tmp_path)
    with pytest.raises(ValidationError, match="image file not found"):
        automation.check_runnable()
    (tmp_path / "a.png").write_bytes(b"x")
    automation.check_runnable()


def test_field_set_on_wrong_step_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="not valid"):
        validate_step(Step(StepType.PRESS_KEY, key="a", x=0, y=0))


def image_automation(old: Path) -> Automation:
    (old / "images").mkdir(parents=True)
    (old / "images" / "a.png").write_bytes(b"source")
    return Automation(steps=[Step(StepType.WAIT_FOR_IMAGE, image="images/a.png")], base_dir=old)


def test_save_as_skips_an_identical_image(tmp_path: Path) -> None:
    automation = image_automation(tmp_path / "old")
    existing = tmp_path / "new" / "images" / "a.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"source")
    before = existing.stat().st_mtime_ns
    save_automation(automation, tmp_path / "new" / "t.json")
    assert existing.stat().st_mtime_ns == before
    assert (tmp_path / "new" / "t.json").exists()


def test_save_as_refuses_to_replace_a_different_image(tmp_path: Path) -> None:
    automation = image_automation(tmp_path / "old")
    existing = tmp_path / "new" / "images" / "a.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"different")
    with pytest.raises(ValidationError, match="different content"):
        save_automation(automation, tmp_path / "new" / "t.json")
    assert existing.read_bytes() == b"different"
    assert not (tmp_path / "new" / "t.json").exists()
    assert automation.base_dir == tmp_path / "old"


def test_failed_replace_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args):
        raise OSError("locked")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="locked"):
        save_automation(Automation(), tmp_path / "t.json")
    assert list(tmp_path.iterdir()) == []
