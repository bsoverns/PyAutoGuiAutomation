"""Full virtual-desktop overlay for dragging out a capture region."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from guiautomation.gui.logic import Region, drag_to_region, overlay_geometry, to_canvas
from guiautomation.screen import Monitor


class RegionOverlay:
    """A translucent window spanning all monitors. Reports a Region, or None if cancelled."""

    def __init__(
        self, root: tk.Misc, desktop: Monitor, on_done: Callable[[Region | None], None]
    ) -> None:
        self._desktop = desktop
        self._on_done = on_done
        self._start: tuple[int, int] | None = None
        self._rect: int | None = None

        self._window = tk.Toplevel(root)
        try:
            self._build(desktop)
        except Exception:
            self._window.destroy()
            raise

    def _build(self, desktop: Monitor) -> None:
        self._window.overrideredirect(True)
        self._window.geometry(overlay_geometry(desktop))
        self._window.attributes("-topmost", True, "-alpha", 0.3)
        self._canvas = tk.Canvas(self._window, bg="black", highlightthickness=0, cursor="crosshair")
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<ButtonPress-1>", self._press)
        self._canvas.bind("<B1-Motion>", self._drag)
        self._canvas.bind("<ButtonRelease-1>", self._release)
        self._window.bind("<Escape>", lambda _event: self._finish(None))
        self._window.focus_force()

    def _press(self, event: tk.Event) -> None:
        self._start = (event.x_root, event.y_root)
        x, y = to_canvas(event.x_root, event.y_root, self._desktop)
        self._rect = self._canvas.create_rectangle(x, y, x, y, outline="red", width=2)

    def _drag(self, event: tk.Event) -> None:
        if self._start is None or self._rect is None:
            return
        x0, y0 = to_canvas(*self._start, self._desktop)
        x1, y1 = to_canvas(event.x_root, event.y_root, self._desktop)
        self._canvas.coords(self._rect, x0, y0, x1, y1)

    def _release(self, event: tk.Event) -> None:
        if self._start is None:
            return
        x0, y0 = self._start
        self._finish(drag_to_region(x0, y0, event.x_root, event.y_root, self._desktop))

    def _finish(self, region: Region | None) -> None:
        self._window.destroy()
        self._on_done(region)
