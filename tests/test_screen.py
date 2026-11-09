"""AC3, AC8: capture and image search on a fake two-monitor layout."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fakes import FakeSct
from PIL import Image

from guiautomation import screen

# A secondary monitor to the left of and above the primary one.
MONITORS = [
    {"left": -1920, "top": -200, "width": 3840, "height": 1280},
    {"left": 0, "top": 0, "width": 1920, "height": 1080},
    {"left": -1920, "top": -200, "width": 1920, "height": 1080},
]


def noise_canvas() -> np.ndarray:
    rng = np.random.default_rng(7)
    desk = MONITORS[0]
    canvas = rng.integers(0, 40, (desk["height"], desk["width"], 4), dtype=np.uint8)
    canvas[:, :, 3] = 255
    return canvas


def patterned_template(size: int = 40) -> np.ndarray:
    """A BGRA block with enough structure to match in exactly one place."""
    rng = np.random.default_rng(11)
    block = rng.integers(100, 255, (size, size, 4), dtype=np.uint8)
    block[:, :, 3] = 255
    return block


def paint(canvas: np.ndarray, block: np.ndarray, left: int, top: int) -> None:
    x = left - MONITORS[0]["left"]
    y = top - MONITORS[0]["top"]
    canvas[y : y + block.shape[0], x : x + block.shape[1]] = block


def save_png(block: np.ndarray, path: Path) -> Path:
    Image.fromarray(block[:, :, 2::-1].copy()).save(path)
    return path


def factory_for(canvas: np.ndarray):
    sct = FakeSct(MONITORS, canvas)
    return (lambda: sct), sct


def test_list_monitors_keeps_negative_origins() -> None:
    factory, _ = factory_for(noise_canvas())
    monitors = screen.list_monitors(factory)
    assert monitors[0] == screen.Monitor(0, -1920, -200, 3840, 1280)
    assert monitors[2].left == -1920
    assert monitors[2].top == -200
    assert screen.virtual_desktop(factory).right == 1920
    assert screen.virtual_desktop(factory).bottom == 1080


@pytest.mark.parametrize(
    ("left", "top"), [(-1800, -150), (100, 200), (-20, -20)], ids=["secondary", "primary", "seam"]
)
def test_find_image_returns_virtual_desktop_coordinates(left, top, tmp_path: Path) -> None:
    canvas = noise_canvas()
    block = patterned_template()
    paint(canvas, block, left, top)
    factory, sct = factory_for(canvas)
    match = screen.find_image(save_png(block, tmp_path / "t.png"), 0.9, factory)
    assert match is not None
    assert (match.left, match.top) == (left, top)
    assert (match.x, match.y) == (left + 20, top + 20)
    assert sct.grabs[0]["left"] == -1920  # The search used monitor 0, the whole desktop.


def test_find_image_returns_none_when_absent(tmp_path: Path) -> None:
    factory, _ = factory_for(noise_canvas())
    path = save_png(patterned_template(), tmp_path / "t.png")
    assert screen.find_image(path, 0.9, factory) is None


def test_confidence_threshold_is_respected(tmp_path: Path) -> None:
    canvas = noise_canvas()
    block = patterned_template()
    noisy = block.copy()
    noisy[::2, :, :3] = 30  # Damage half the rows.
    paint(canvas, noisy, -500, 100)
    factory, _ = factory_for(canvas)
    path = save_png(block, tmp_path / "t.png")
    assert screen.find_image(path, 0.99, factory) is None
    assert screen.find_image(path, 0.2, factory) is not None


def test_missing_template_file_raises(tmp_path: Path) -> None:
    factory, _ = factory_for(noise_canvas())
    with pytest.raises(FileNotFoundError):
        screen.find_image(tmp_path / "gone.png", 0.9, factory)


def test_template_larger_than_desktop_is_not_found() -> None:
    desktop = np.zeros((10, 10, 3), np.uint8)
    template = np.zeros((20, 20, 3), np.uint8)
    assert screen.match_template(desktop, template, (0, 0), 0.5) is None


def test_flat_colored_template_matches_by_pixel_value() -> None:
    desktop = np.zeros((50, 50, 3), np.uint8)
    desktop[10:20, 30:40] = (200, 100, 50)
    template = np.zeros((10, 10, 3), np.uint8)
    template[:] = (200, 100, 50)
    match = screen.match_template(desktop, template, (-100, -100), 0.95)
    assert match is not None
    assert (match.left, match.top) == (-70, -90)


def test_flat_template_absent_is_not_found() -> None:
    desktop = np.zeros((50, 50, 3), np.uint8)
    template = np.full((10, 10, 3), 255, np.uint8)
    assert screen.match_template(desktop, template, (0, 0), 0.95) is None


def test_grab_region_reads_negative_coordinates_as_rgb() -> None:
    canvas = noise_canvas()
    block = np.zeros((20, 30, 4), np.uint8)
    block[:, :] = (10, 20, 30, 255)  # BGRA
    paint(canvas, block, -1000, -100)
    factory, sct = factory_for(canvas)
    image = screen.grab_region(-1000, -100, 30, 20, factory)
    assert image.size == (30, 20)
    assert image.getpixel((5, 5)) == (30, 20, 10)
    assert sct.grabs == [{"left": -1000, "top": -100, "width": 30, "height": 20}]


def test_mss_screen_delegates_to_the_factory(tmp_path: Path) -> None:
    canvas = noise_canvas()
    block = patterned_template()
    paint(canvas, block, -40, 300)
    factory, _ = factory_for(canvas)
    match = screen.MssScreen(factory).find_image(save_png(block, tmp_path / "t.png"), 0.9)
    assert match is not None
    assert match.left == -40


def test_dpi_awareness_is_called_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    user32 = SimpleNamespace(SetProcessDpiAwarenessContext=lambda ctx: calls.append(ctx) or 1)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32), raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(screen, "_dpi_done", False)
    screen.enable_dpi_awareness()
    screen.enable_dpi_awareness()
    assert len(calls) == 1


def test_dpi_awareness_falls_back_when_context_call_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    windll = SimpleNamespace(
        user32=SimpleNamespace(SetProcessDpiAwarenessContext=lambda ctx: 0),
        shcore=SimpleNamespace(SetProcessDpiAwareness=calls.append),
    )
    monkeypatch.setattr(ctypes, "windll", windll, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(screen, "_dpi_done", False)
    screen.enable_dpi_awareness()
    assert calls == [2]


def test_dpi_awareness_is_a_no_op_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(screen, "_dpi_done", False)
    screen.enable_dpi_awareness()
    assert screen._dpi_done is False


def test_open_mss_uses_the_non_deprecated_class(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = SimpleNamespace(MSS=lambda: "instance")  # No mss.mss attribute, so using it would fail.
    monkeypatch.setitem(sys.modules, "mss", fake)
    assert screen._open_mss() == "instance"
