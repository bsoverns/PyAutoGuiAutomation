"""How clicks reach their target and which match a confidence value selects."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import numpy as np
import pytest

from guiautomation.driver import CLICK_MOVE_DURATION, FailSafeAbort, PyAutoGuiDriver
from guiautomation.gui.logic import fields_for
from guiautomation.model import DEFAULT_CONFIDENCE, StepType
from guiautomation.screen import match_template


class _FailSafe(Exception):
    pass


def fake_gui() -> MagicMock:
    gui = MagicMock()
    gui.FailSafeException = _FailSafe
    return gui


def test_click_glides_to_the_target_first() -> None:
    gui = fake_gui()
    PyAutoGuiDriver(module=gui).click(-5, 6)
    assert CLICK_MOVE_DURATION == 0.5
    assert gui.mock_calls == [
        call.moveTo(-5, 6, duration=0.5),
        call.click(x=-5, y=6, clicks=1, interval=0.0, button="left"),
    ]


def test_failsafe_during_the_glide_stops_before_clicking() -> None:
    gui = fake_gui()
    gui.moveTo.side_effect = _FailSafe("corner")
    with pytest.raises(FailSafeAbort):
        PyAutoGuiDriver(module=gui).click(1, 2)
    gui.click.assert_not_called()


def noise(rng: np.random.Generator, height: int, width: int) -> np.ndarray:
    return rng.integers(0, 256, (height, width, 3), dtype=np.uint8)


def scene() -> tuple[np.ndarray, np.ndarray]:
    """A desktop with a degraded copy of the template above an exact copy."""
    rng = np.random.default_rng(7)
    desktop = noise(rng, 120, 120)
    template = noise(rng, 24, 24)
    degraded = ((template.astype(int) + noise(rng, 24, 24)) // 2).astype(np.uint8)
    desktop[5:29, 5:29] = degraded
    desktop[80:104, 70:94] = template
    return desktop, template


def test_a_loose_confidence_still_picks_the_best_match() -> None:
    desktop, template = scene()
    match = match_template(desktop, template, (0, 0), 0.4)
    assert (match.left, match.top) == (70, 80)
    assert match.score == pytest.approx(1.0)


def test_the_score_is_on_the_scale_the_user_sets() -> None:
    desktop, template = scene()
    desktop[80:104, 70:94] = 0  # Only the degraded copy is left.
    assert match_template(desktop, template, (0, 0), 0.95) is None
    loose = match_template(desktop, template, (0, 0), 0.4)
    assert (loose.left, loose.top) == (5, 5)
    assert 0.4 <= loose.score < 0.95


def test_the_form_explains_confidence() -> None:
    assert DEFAULT_CONFIDENCE == 0.8
    labels = [spec.label for spec in fields_for(StepType.CLICK) if spec.name == "confidence"]
    assert "1 = exact" in labels[0]
    assert "blank = 0.8" in labels[0]
