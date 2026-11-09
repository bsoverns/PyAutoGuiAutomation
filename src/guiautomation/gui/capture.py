"""Full virtual-desktop overlay for dragging out a capture region, and the clip countdown."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from PIL import Image

from guiautomation.gui.logic import (
    ClipCountdown,
    Region,
    countdown_text,
    drag_to_region,
    overlay_geometry,
    to_canvas,
)
from guiautomation.screen import Monitor

_FROZEN_BRIGHTNESS = 0.7  # A frozen screen is dimmed about as much as the live one.
_COUNTDOWN_MARGIN = 24  # Gap between the countdown and the top of the primary monitor.


class RegionOverlay:
    """A window spanning all monitors. Reports a Region, or None if cancelled.

    Without ``frozen`` it is translucent over the live screen. With ``frozen``, an image of the
    whole virtual desktop, it shows that image instead, so menus and hover states that close when
    the overlay takes the focus can still be clipped.
    """

    def __init__(
        self,
        root: tk.Misc,
        desktop: Monitor,
        on_done: Callable[[Region | None], None],
        frozen: Image.Image | None = None,
    ) -> None:
        self._desktop = desktop
        self._on_done = on_done
        self._start: tuple[int, int] | None = None
        self._rect: int | None = None
        self._photo: object = None  # Tk drops an image once nothing references it.

        self._window = tk.Toplevel(root)
        try:
            self._build(desktop, frozen)
        except Exception:
            self._window.destroy()
            raise

    def _build(self, desktop: Monitor, frozen: Image.Image | None) -> None:
        self._window.overrideredirect(True)
        self._window.geometry(overlay_geometry(desktop))
        self._window.attributes("-topmost", True, "-alpha", 0.3 if frozen is None else 1.0)
        self._canvas = tk.Canvas(self._window, bg="black", highlightthickness=0, cursor="crosshair")
        self._canvas.pack(fill="both", expand=True)
        if frozen is not None:
            from PIL import ImageEnhance, ImageTk

            dimmed = ImageEnhance.Brightness(frozen).enhance(_FROZEN_BRIGHTNESS)
            self._photo = ImageTk.PhotoImage(dimmed, master=self._window)
            self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._canvas.create_text(
            *to_canvas(24, 24, desktop),
            anchor="nw",
            fill="white",
            font=("Segoe UI", 20, "bold"),
            text="Drag a box around the target. Esc cancels.",
        )
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


class CountdownWindow:
    """A small always-on-top note that counts down to a delayed clip.

    It closes itself before calling ``on_done`` or ``on_cancel``. Clicking it cancels; so does Esc
    while it has the keyboard focus, which it loses once the user clicks another program.
    """

    def __init__(
        self,
        root: tk.Misc,
        seconds: int,
        on_done: Callable[[], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._on_done = on_done
        self._on_cancel = on_cancel
        self._window = tk.Toplevel(root)
        try:
            self._window.overrideredirect(True)
            self._window.attributes("-topmost", True)
            self._label = tk.Label(
                self._window,
                bg="black",
                fg="white",
                font=("Segoe UI", 14, "bold"),
                padx=16,
                pady=10,
                cursor="hand2",
                text=countdown_text(seconds),
            )
            self._label.pack()
            self._window.update_idletasks()
            left = (self._window.winfo_screenwidth() - self._window.winfo_reqwidth()) // 2
            self._window.geometry(f"+{left}+{_COUNTDOWN_MARGIN}")
            self._label.bind("<Button-1>", lambda _event: self._cancel())
            self._window.bind("<Escape>", lambda _event: self._cancel())
            self._window.focus_force()
            self._countdown = ClipCountdown(
                seconds, root.after, root.after_cancel, self._tick, self._elapsed
            )
        except Exception:
            self._window.destroy()
            raise
        self._countdown.start()

    def _tick(self, remaining: int) -> None:
        self._label.configure(text=countdown_text(remaining))

    def _elapsed(self) -> None:
        self._window.destroy()
        self._on_done()

    def _cancel(self) -> None:
        if self._countdown.cancel():
            self._window.destroy()
            self._on_cancel()
