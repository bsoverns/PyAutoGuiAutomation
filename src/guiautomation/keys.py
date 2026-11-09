"""Named keys for press key and hotkey steps: the picker list and friendly spellings.

Plain data, so the builder can offer keys without importing PyAutoGUI. Every name here is
a PyAutoGUI 0.9.54 key name.
"""

from __future__ import annotations

# (label shown in the builder, key name stored in the test)
COMMON_KEYS: tuple[tuple[str, str], ...] = (
    ("Windows key", "win"),
    ("Menu key", "apps"),
    ("Ctrl", "ctrl"),
    ("Alt", "alt"),
    ("Shift", "shift"),
    ("Enter", "enter"),
    ("Tab", "tab"),
    ("Esc", "esc"),
    ("Space", "space"),
    ("Backspace", "backspace"),
    ("Delete", "delete"),
    ("Insert", "insert"),
    ("Home", "home"),
    ("End", "end"),
    ("Page Up", "pageup"),
    ("Page Down", "pagedown"),
    ("Up arrow", "up"),
    ("Down arrow", "down"),
    ("Left arrow", "left"),
    ("Right arrow", "right"),
    ("Print Screen", "printscreen"),
    ("Pause", "pause"),
    ("Caps Lock", "capslock"),
    ("Num Lock", "numlock"),
    ("Scroll Lock", "scrolllock"),
    *((f"F{number}", f"f{number}") for number in range(1, 13)),
    ("Volume up", "volumeup"),
    ("Volume down", "volumedown"),
    ("Mute", "volumemute"),
    ("Play/Pause", "playpause"),
    ("Next track", "nexttrack"),
    ("Previous track", "prevtrack"),
)

# Other spellings people type, mapped to the key name. Spaces, hyphens and underscores
# are ignored when matching, so "Page Up" and "page-up" both work.
_ALIASES: dict[str, str] = {
    "windows": "win",
    "windowskey": "win",
    "winkey": "win",
    "windowsbutton": "win",
    "start": "win",
    "super": "win",
    "meta": "win",
    "menu": "apps",
    "menukey": "apps",
    "contextmenu": "apps",
    "control": "ctrl",
    "spacebar": "space",
    "uparrow": "up",
    "downarrow": "down",
    "leftarrow": "left",
    "rightarrow": "right",
    "ins": "insert",
    "break": "pause",
    "mute": "volumemute",
    "previoustrack": "prevtrack",
}


def _squash(text: str) -> str:
    return "".join(char for char in text.lower() if char not in " -_")


_BY_SPELLING: dict[str, str] = {
    **_ALIASES,
    **{_squash(label): name for label, name in COMMON_KEYS},
    **{_squash(f"{label} ({name})"): name for label, name in COMMON_KEYS},
}


def key_choices() -> list[str]:
    """Return the picker entries, such as ``Windows key (win)``."""
    return [f"{label} ({name})" for label, name in COMMON_KEYS]


def canonical_key(key: str) -> str:
    """Return the key name for a picker entry or friendly spelling.

    A single character is a literal key and is returned unchanged. Names that are not
    recognized are returned lowercased without spaces, hyphens or underscores, for the
    driver to accept or reject.
    """
    if len(key) <= 1:
        return key
    text = key.strip()
    if len(text) <= 1:
        return text or key
    squashed = _squash(text)
    return _BY_SPELLING.get(squashed, squashed)
