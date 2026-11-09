"""Guided run window: steps run off the UI thread, the user judges each one."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from guiautomation.abort import AbortHotkey
from guiautomation.driver import PyAutoGuiDriver
from guiautomation.gui.logic import GuidedBridge, describe_step
from guiautomation.model import Automation
from guiautomation.runner import Confirmation, RunResult, failsafe_triggered, run_automation

_START_DELAY = 1.0  # Lets the builder window disappear before the first step.
_POLL_MS = 100
_SETTLE_MS = 200  # Lets the confirm window disappear before the next step runs.


class GuidedRun:
    """Runs a test on a worker thread. The window shows only while waiting for an answer."""

    def __init__(
        self, root: tk.Tk, automation: Automation, on_finished: Callable[[str], None]
    ) -> None:
        self._root = root
        self._automation = automation
        self._on_finished = on_finished
        self._hotkey = AbortHotkey()
        self._driver = PyAutoGuiDriver(abort=self._hotkey.is_set)
        self._bridge = GuidedBridge(abort=self._should_stop)

        self._window = tk.Toplevel(root)
        self._window.title("Guided run")
        self._window.attributes("-topmost", True)
        self._window.protocol("WM_DELETE_WINDOW", lambda: self._answer(Confirmation.STOP))
        self._label = ttk.Label(self._window, wraplength=420, justify="left")
        self._label.pack(padx=12, pady=12)
        buttons = ttk.Frame(self._window)
        buttons.pack(padx=12, pady=(0, 12))
        for text, choice in (
            ("Pass", Confirmation.PASS),
            ("Fail", Confirmation.FAIL),
            ("Stop", Confirmation.STOP),
        ):
            ttk.Button(buttons, text=text, command=lambda c=choice: self._answer(c)).pack(
                side="left", padx=4
            )
        self._window.withdraw()

    def _should_stop(self) -> bool:
        return self._hotkey.is_set() or failsafe_triggered(self._driver)

    def start(self) -> None:
        try:
            self._hotkey.start()
            threading.Thread(target=self._work, daemon=True, name="guided-run").start()
            self._root.after(_POLL_MS, self._poll)
        except Exception as exc:  # noqa: BLE001 - the builder must always come back
            self._finish(f"Error: {exc}")

    def _work(self) -> None:
        try:
            result = run_automation(
                self._automation,
                delay=_START_DELAY,
                driver=self._driver,
                abort=self._hotkey.is_set,
                confirm=self._bridge.confirm,
                repeat=1,  # Each step is judged once; looping is for the unattended Run.
            )
        except Exception as exc:  # noqa: BLE001 - shown to the user instead of crashing the GUI
            self._bridge.fail(str(exc))
        else:
            self._bridge.finish(result)

    def _answer(self, choice: Confirmation) -> None:
        self._window.withdraw()
        self._root.after(_SETTLE_MS, lambda: self._bridge.answer(choice))

    def _poll(self) -> None:
        try:
            self._handle_next_event()
        except Exception as exc:  # noqa: BLE001 - the builder must always come back
            self._finish(f"Error: {exc}")

    def _handle_next_event(self) -> None:
        try:
            kind, payload = self._bridge.events.get_nowait()
        except queue.Empty:
            self._root.after(_POLL_MS, self._poll)
            return
        if kind == "confirm":
            step, result = payload
            self._label.configure(
                text=f"Step {result.index}: {describe_step(step)}\n"
                f"Result: {result.message}\n\n"
                "Did this step do what you expected?\n"
                "Ctrl+Alt+Shift+Q aborts the run at any time."
            )
            self._window.deiconify()
            self._window.lift()
            self._root.after(_POLL_MS, self._poll)
            return
        self._finish(payload.summary() if isinstance(payload, RunResult) else f"Error: {payload}")

    def _finish(self, report: str) -> None:
        self._hotkey.trigger()  # Stops a worker that is still running after an error.
        self._hotkey.stop()
        try:
            self._window.destroy()
        except tk.TclError:
            pass
        self._on_finished(report)
