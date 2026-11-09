"""Unattended run from the builder: loops off the UI thread with a small status window."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from guiautomation.abort import AbortHotkey
from guiautomation.gui.logic import describe_loops, loop_status
from guiautomation.model import Automation
from guiautomation.runner import run_automation

RUN_DELAY = 5.0  # Time to click into the program under test.
_POLL_MS = 100


class LoopRun:
    """Runs a test on a worker thread until its loops end or the user stops it."""

    def __init__(
        self, root: tk.Tk, automation: Automation, on_finished: Callable[[str], None]
    ) -> None:
        self._root = root
        self._automation = automation
        self._on_finished = on_finished
        self._hotkey = AbortHotkey()
        self._events: queue.Queue[tuple[str, Any]] = queue.Queue()

        self._window = tk.Toplevel(root)
        self._window.overrideredirect(True)
        self._window.attributes("-topmost", True)
        self._window.geometry("-20-60")  # Bottom right of the primary monitor.
        self._label = ttk.Label(
            self._window,
            text=f"Starts in {RUN_DELAY:g} s, running {describe_loops(automation.repeat)}.\n"
            "Click into your program now.\nCtrl+Alt+Shift+Q stops the run.",
        )
        self._label.pack(side="left", padx=8, pady=6)
        ttk.Button(self._window, text="Stop", command=self._hotkey.trigger).pack(
            side="left", padx=(0, 8)
        )

    def start(self) -> None:
        try:
            self._hotkey.start()
            threading.Thread(target=self._work, daemon=True, name="loop-run").start()
            self._root.after(_POLL_MS, self._poll)
        except Exception as exc:  # noqa: BLE001 - the builder must always come back
            self._finish(f"Error: {exc}")

    def _work(self) -> None:
        try:
            result = run_automation(
                self._automation,
                delay=RUN_DELAY,
                abort=self._hotkey.is_set,
                on_iteration=lambda number: self._events.put(("loop", number)),
            )
        except Exception as exc:  # noqa: BLE001 - shown to the user instead of crashing the GUI
            self._events.put(("done", f"Error: {exc}"))
        else:
            self._events.put(("done", result.summary()))

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "done":
                    self._finish(payload)
                    return
                self._label.configure(
                    text=f"{loop_status(payload, self._automation.repeat)}\n"
                    "Ctrl+Alt+Shift+Q stops the run."
                )
        except queue.Empty:
            self._root.after(_POLL_MS, self._poll)
        except Exception as exc:  # noqa: BLE001 - the builder must always come back
            self._finish(f"Error: {exc}")

    def _finish(self, report: str) -> None:
        self._hotkey.trigger()  # Stops a worker that is still running after an error.
        self._hotkey.stop()
        try:
            self._window.destroy()
        except tk.TclError:
            pass
        self._on_finished(report)
