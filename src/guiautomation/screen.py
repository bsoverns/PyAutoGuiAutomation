"""Screen capture and image search over the whole virtual desktop."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

_DPI_AWARE_PER_MONITOR_V2 = -4
_dpi_done = False

SctFactory = Callable[[], Any]


@dataclass(frozen=True)
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True)
class Match:
    """An image match. x and y are the center, in virtual-desktop coordinates."""

    x: int
    y: int
    left: int
    top: int
    width: int
    height: int
    score: float


class Screen(Protocol):
    def find_image(self, image_path: Path, confidence: float) -> Match | None: ...


def enable_dpi_awareness() -> None:
    """Make the process DPI aware, once. Must run before any coordinates are read."""
    global _dpi_done
    if _dpi_done or sys.platform != "win32":
        return
    _dpi_done = True
    try:
        context = ctypes.c_void_p(_DPI_AWARE_PER_MONITOR_V2)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(context):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()


def _open_mss() -> Any:
    import mss

    return mss.MSS()


def list_monitors(sct_factory: SctFactory = _open_mss) -> list[Monitor]:
    """Return mss monitors; index 0 is the whole virtual desktop."""
    with sct_factory() as sct:
        return [
            Monitor(index, mon["left"], mon["top"], mon["width"], mon["height"])
            for index, mon in enumerate(sct.monitors)
        ]


def virtual_desktop(sct_factory: SctFactory = _open_mss) -> Monitor:
    """Return the rectangle that spans all monitors."""
    return list_monitors(sct_factory)[0]


def _bgr_array(shot: Any) -> np.ndarray:
    return np.asarray(shot)[:, :, :3].astype(np.uint8)


def grab_region(
    left: int, top: int, width: int, height: int, sct_factory: SctFactory = _open_mss
) -> Image.Image:
    """Capture a rectangle given in virtual-desktop coordinates."""
    region = {"left": left, "top": top, "width": width, "height": height}
    with sct_factory() as sct:
        bgr = _bgr_array(sct.grab(region))
    return Image.fromarray(bgr[:, :, ::-1].copy())


def match_template(
    desktop: np.ndarray, template: np.ndarray, origin: tuple[int, int], confidence: float
) -> Match | None:
    """Find a BGR template in a BGR desktop image whose top-left is at ``origin``."""
    import cv2

    desk_height, desk_width = desktop.shape[:2]
    height, width = template.shape[:2]
    if width == 0 or height == 0 or width > desk_width or height > desk_height:
        return None
    if np.ptp(template, axis=(0, 1)).max() == 0:
        # Correlation is undefined for a flat template, so compare pixel values instead.
        result = cv2.matchTemplate(desktop, template, cv2.TM_SQDIFF)
        minimum, _, min_loc, _ = cv2.minMaxLoc(result)
        score = 1.0 - float(np.sqrt(minimum / (width * height * 3))) / 255.0
        location = min_loc
    else:
        result = cv2.matchTemplate(desktop, template, cv2.TM_CCOEFF_NORMED)
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
        _, score, _, location = cv2.minMaxLoc(result)
    if score < confidence:
        return None
    left = origin[0] + int(location[0])
    top = origin[1] + int(location[1])
    return Match(left + width // 2, top + height // 2, left, top, width, height, float(score))


def _load_template(image_path: Path) -> np.ndarray:
    with Image.open(image_path) as image:
        rgb = np.array(image.convert("RGB"))
    return rgb[:, :, ::-1].copy()


def find_image(
    image_path: Path, confidence: float, sct_factory: SctFactory = _open_mss
) -> Match | None:
    """Search the whole virtual desktop for an image file."""
    template = _load_template(image_path)
    with sct_factory() as sct:
        desk = sct.monitors[0]
        shot = sct.grab(
            {
                "left": desk["left"],
                "top": desk["top"],
                "width": desk["width"],
                "height": desk["height"],
            }
        )
        desktop = _bgr_array(shot)
    return match_template(desktop, template, (desk["left"], desk["top"]), confidence)


class MssScreen:
    """Screen implementation backed by mss and OpenCV."""

    def __init__(self, sct_factory: SctFactory = _open_mss) -> None:
        self._sct_factory = sct_factory

    def find_image(self, image_path: Path, confidence: float) -> Match | None:
        return find_image(image_path, confidence, self._sct_factory)
