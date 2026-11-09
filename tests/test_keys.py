"""Named keys: the picker list, friendly spellings, and their use in forms and the driver."""

from __future__ import annotations

import pytest

from guiautomation.driver import DriverError, PyAutoGuiDriver
from guiautomation.gui.logic import fields_for, step_from_form, step_to_form
from guiautomation.keys import COMMON_KEYS, canonical_key, key_choices
from guiautomation.model import StepType


class RecordingGui:
    """Stands in for pyautogui: records key calls and knows a few key names."""

    FailSafeException = RuntimeError

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def isValidKey(self, key: str) -> bool:
        return key in ("win", "apps", "ctrl", "d", "pageup")

    def press(self, *keys: str) -> None:
        self.calls.append(("press", keys))

    def hotkey(self, *keys: str) -> None:
        self.calls.append(("hotkey", keys))


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("win", "win"),
        ("Win", "win"),
        ("Windows", "win"),
        ("windows key", "win"),
        ("Windows button", "win"),
        ("Windows key (win)", "win"),
        ("super", "win"),
        ("Menu", "apps"),
        ("Control", "ctrl"),
        ("Page Up", "pageup"),
        ("page-up", "pageup"),
        ("Print Screen", "printscreen"),
        ("  Enter  ", "enter"),
        ("F5", "f5"),
        ("up arrow", "up"),
        ("Mute", "volumemute"),
    ],
)
def test_friendly_spellings_map_to_key_names(typed: str, expected: str) -> None:
    assert canonical_key(typed) == expected


@pytest.mark.parametrize("key", ["a", "A", "+", " ", "日"])
def test_a_single_character_is_kept_as_typed(key: str) -> None:
    assert canonical_key(key) == key


def test_unrecognized_names_pass_through_for_the_driver_to_judge() -> None:
    assert canonical_key("BrowserBack") == "browserback"
    assert canonical_key("No Such Key") == "nosuchkey"


def test_picker_lists_the_windows_key_first_and_every_entry_resolves() -> None:
    choices = key_choices()
    assert choices[0] == "Windows key (win)"
    assert len(choices) == len(set(choices)) == len(COMMON_KEYS)
    assert [canonical_key(choice) for choice in choices] == [name for _, name in COMMON_KEYS]
    for label, name in COMMON_KEYS:
        assert canonical_key(label) == name
        assert canonical_key(name) == name


def test_every_listed_key_is_a_real_pyautogui_key() -> None:
    pyautogui = pytest.importorskip("pyautogui")  # Reads the key table; sends no input.
    listed = {name for _, name in COMMON_KEYS}
    assert listed <= set(pyautogui.KEYBOARD_KEYS)


def test_press_key_form_offers_the_picker_and_accepts_its_entries() -> None:
    spec = next(spec for spec in fields_for(StepType.PRESS_KEY) if spec.name == "key")
    assert spec.kind == "key"
    assert step_from_form(StepType.PRESS_KEY, {"key": "Windows key (win)"}).key == "win"
    assert step_from_form(StepType.PRESS_KEY, {"key": "Windows"}).key == "win"
    assert step_from_form(StepType.PRESS_KEY, {"key": "A"}).key == "A"


def test_hotkey_form_accepts_friendly_names() -> None:
    step = step_from_form(StepType.HOTKEY, {"keys": "Windows + d"})
    assert step.keys == ("win", "d")
    assert step_to_form(step)["keys"] == "win+d"
    assert step_from_form(StepType.HOTKEY, {"keys": "control, Page Up"}).keys == ("ctrl", "pageup")


def test_driver_accepts_friendly_names_from_hand_written_tests() -> None:
    gui = RecordingGui()
    driver = PyAutoGuiDriver(module=gui)
    driver.press_key("Windows")
    driver.hotkey(["Windows", "d"])
    assert gui.calls == [("press", ("win",)), ("hotkey", ("win", "d"))]


def test_driver_still_rejects_unknown_keys_and_names_what_was_typed() -> None:
    with pytest.raises(DriverError, match="No Such Key"):
        PyAutoGuiDriver(module=RecordingGui()).press_key("No Such Key")
