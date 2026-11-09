"""The tkinter test builder."""

from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from guiautomation import screen
from guiautomation.export import export_script
from guiautomation.gui.capture import RegionOverlay
from guiautomation.gui.guided import GuidedRun
from guiautomation.gui.logic import (
    Region,
    StepList,
    capture_filename,
    describe_step,
    fields_for,
    step_from_form,
    step_to_form,
)
from guiautomation.model import (
    Automation,
    Step,
    StepType,
    ValidationError,
    load_automation,
    save_automation,
)

_JSON_TYPES = [("Test files", "*.json"), ("All files", "*.*")]
_HIDE_DELAY_MS = 250  # Time for windows to disappear before the screen is used.
_GRAB_RETRY_MS = 25
_GRAB_RETRIES = 40


def grab_when_viewable(window: tk.Misc, retries: int = _GRAB_RETRIES) -> None:
    """Take the input grab, retrying while the window is not yet viewable.

    Polls instead of using ``wait_visibility``, which never returns for a window already shown.
    """
    try:
        if window.winfo_exists():
            window.grab_set()
    except tk.TclError:
        if retries > 0:
            window.after(_GRAB_RETRY_MS, grab_when_viewable, window, retries - 1)


class StepEditor:
    """Dialog for adding or editing one step."""

    def __init__(self, app: BuilderApp, step: Step | None, on_ok: Callable[[Step], None]) -> None:
        self._app = app
        self._previous = step
        self._on_ok = on_ok
        self._entries: dict[str, tk.StringVar] = {}

        self.window = tk.Toplevel(app.root)
        self.window.title("Edit step" if step else "Add step")
        self._type = tk.StringVar(value=(step.type if step else StepType.CLICK).value)
        selector = ttk.Combobox(
            self.window,
            textvariable=self._type,
            values=[kind.value for kind in StepType],
            state="readonly",
        )
        selector.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=8)
        selector.bind("<<ComboboxSelected>>", lambda _event: self._build_form({}))
        self._form = ttk.Frame(self.window)
        self._form.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=8)
        ttk.Button(self.window, text="OK", command=self._ok).grid(row=2, column=1, pady=8)
        ttk.Button(self.window, text="Cancel", command=self.window.destroy).grid(row=2, column=2)
        self._build_form(step_to_form(step) if step else {})
        grab_when_viewable(self.window)

    def _build_form(self, values: dict[str, str]) -> None:
        for child in self._form.winfo_children():
            child.destroy()
        self._entries = {}
        for row, spec in enumerate(fields_for(StepType(self._type.get()))):
            ttk.Label(self._form, text=spec.label).grid(row=row, column=0, sticky="w", pady=2)
            variable = tk.StringVar(value=values.get(spec.name, ""))
            ttk.Entry(self._form, textvariable=variable, width=44).grid(row=row, column=1, padx=4)
            self._entries[spec.name] = variable
            if spec.kind == "image":
                ttk.Button(
                    self._form,
                    text="Capture...",
                    command=lambda v=variable: self._capture(v),
                ).grid(row=row, column=2)

    def _capture(self, variable: tk.StringVar) -> None:
        self.window.grab_release()

        def restore() -> None:
            self.window.deiconify()
            grab_when_viewable(self.window)

        self._app.capture(self.window, variable.set, restore)

    def _ok(self) -> None:
        form = {name: variable.get() for name, variable in self._entries.items()}
        try:
            step = step_from_form(StepType(self._type.get()), form, self._previous)
        except ValidationError as exc:
            messagebox.showerror("Invalid step", str(exc), parent=self.window)
            return
        self.window.destroy()
        self._on_ok(step)


class BuilderApp:
    """Main window: edit the step list, save, export, capture, and start guided runs."""

    def __init__(
        self,
        root: tk.Tk,
        automation: Automation | None = None,
        path: str | os.PathLike[str] | None = None,
    ) -> None:
        self.root = root
        self._path: Path | None = Path(path) if path else None
        self._dirty = False
        self._set_automation(automation or Automation(), self._path)

        root.geometry("640x420")
        root.protocol("WM_DELETE_WINDOW", self._quit)
        self._build_menu()
        toolbar = ttk.Frame(root)
        toolbar.pack(side="right", fill="y", padx=8, pady=8)
        for text, command in (
            ("Add", self._add),
            ("Edit", self._edit),
            ("Delete", self._delete),
            ("Move up", self._move_up),
            ("Move down", self._move_down),
            ("Guided run", self._guided_run),
        ):
            ttk.Button(toolbar, text=text, command=command).pack(fill="x", pady=2)
        self._listbox = tk.Listbox(root, activestyle="dotbox", exportselection=False)
        self._listbox.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self._listbox.bind("<Double-Button-1>", lambda _event: self._edit())
        self._refresh()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        for label, command in (
            ("New", self._new),
            ("Open...", self._open),
            ("Save", self._save),
            ("Save as...", self._save_as),
            ("Export script...", self._export),
        ):
            file_menu.add_command(label=label, command=command)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.configure(menu=menubar)

    def _set_automation(self, automation: Automation, path: Path | None) -> None:
        self._automation = automation
        self._path = path
        self._steps = StepList(automation.steps)
        self._dirty = False

    def _refresh(self, select: int | None = None) -> None:
        self._listbox.delete(0, "end")
        for number, step in enumerate(self._steps.steps, start=1):
            self._listbox.insert("end", f"{number}. {describe_step(step)}")
        if select is not None:
            self._listbox.selection_set(select)
            self._listbox.see(select)
        marker = "*" if self._dirty else ""
        self.root.title(f"GuiAutomation - {self._path.name if self._path else 'untitled'}{marker}")

    def _selected(self) -> int | None:
        selection = self._listbox.curselection()
        return selection[0] if selection else None

    def _changed(self, select: int | None) -> None:
        self._dirty = True
        self._refresh(select)

    def _add(self) -> None:
        after = self._selected()
        StepEditor(self, None, lambda step: self._changed(self._steps.add(step, after)))

    def _edit(self) -> None:
        index = self._selected()
        if index is None:
            return
        StepEditor(
            self,
            self._steps.steps[index],
            lambda step: self._changed(self._steps.replace(index, step)),
        )

    def _delete(self) -> None:
        index = self._selected()
        if index is not None:
            self._changed(self._steps.delete(index))

    def _move_up(self) -> None:
        index = self._selected()
        if index is not None:
            self._changed(self._steps.move_up(index))

    def _move_down(self) -> None:
        index = self._selected()
        if index is not None:
            self._changed(self._steps.move_down(index))

    def _confirm_discard(self) -> bool:
        return not self._dirty or messagebox.askyesno("Unsaved changes", "Discard your changes?")

    def _new(self) -> None:
        if self._confirm_discard():
            self._set_automation(Automation(), None)
            self._refresh()

    def _open(self) -> None:
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(filetypes=_JSON_TYPES)
        if not path:
            return
        try:
            self._set_automation(load_automation(path), Path(path))
        except ValidationError as exc:
            messagebox.showerror("Cannot open test", str(exc))
            return
        self._refresh()

    def _save(self) -> bool:
        if self._path is None:
            return self._save_as()
        return self._write(self._path)

    def _save_as(self) -> bool:
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=_JSON_TYPES)
        return self._write(Path(path)) if path else False

    def _write(self, path: Path) -> bool:
        try:
            if not self._automation.name:
                self._automation.name = path.stem
            save_automation(self._automation, path)
        except (ValidationError, OSError) as exc:
            messagebox.showerror("Cannot save test", str(exc))
            return False
        self._path = path
        self._dirty = False
        self._refresh(self._selected())
        return True

    def _export(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".py", filetypes=[("Python files", "*.py")]
        )
        if not path:
            return
        try:
            export_script(self._automation, path)
        except (ValidationError, OSError) as exc:
            messagebox.showerror("Cannot export test", str(exc))

    def capture(
        self, dialog: tk.Toplevel, on_saved: Callable[[str], None], restore: Callable[[], None]
    ) -> None:
        """Hide all windows, let the user drag a region, and save it next to the test."""
        if (self._path is None and not self._save()) or self._automation.base_dir is None:
            restore()
            return
        try:
            desktop = screen.virtual_desktop()
        except Exception as exc:  # noqa: BLE001 - shown to the user instead of crashing the GUI
            messagebox.showerror("Capture failed", str(exc))
            restore()
            return

        def finish() -> None:
            self.root.deiconify()
            restore()

        def grab(region: Region) -> None:
            try:
                relative = self._save_capture(region)
            except Exception as exc:  # noqa: BLE001 - shown to the user instead of crashing the GUI
                finish()
                messagebox.showerror("Capture failed", str(exc))
                return
            finish()
            on_saved(relative)

        def on_region(region: Region | None) -> None:
            if region is None:
                finish()
            else:
                self.root.after(_HIDE_DELAY_MS, lambda: grab(region))

        def show_overlay() -> None:
            try:
                RegionOverlay(self.root, desktop, on_region)
            except Exception as exc:  # noqa: BLE001 - the builder must always come back
                finish()
                messagebox.showerror("Capture failed", str(exc))

        dialog.withdraw()
        self.root.withdraw()
        self.root.after(_HIDE_DELAY_MS, show_overlay)

    def _save_capture(self, region: Region) -> str:
        relative = capture_filename(datetime.now())
        target = self._automation.resolve_image(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        image = screen.grab_region(region.left, region.top, region.width, region.height)
        image.save(target, "PNG")
        return relative

    def _guided_run(self) -> None:
        try:
            self._automation.check_runnable()
        except ValidationError as exc:
            messagebox.showerror("Cannot run test", str(exc))
            return
        self.root.withdraw()
        try:
            run = GuidedRun(self.root, self._automation, self._show_report)
        except Exception as exc:  # noqa: BLE001 - the builder must always come back
            self._show_report(f"Error: {exc}")
            return
        self.root.after(_HIDE_DELAY_MS, run.start)

    def _show_report(self, report: str) -> None:
        self.root.deiconify()
        window = tk.Toplevel(self.root)
        window.title("Run results")
        text = tk.Text(window, width=80, height=20, wrap="word")
        text.insert("1.0", report)
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)

    def _quit(self) -> None:
        if self._confirm_discard():
            self.root.destroy()


def run_gui(
    automation: Automation | None = None, path: str | os.PathLike[str] | None = None
) -> None:
    """Open the builder and block until it closes."""
    screen.enable_dpi_awareness()
    root = tk.Tk()
    BuilderApp(root, automation, path)
    root.mainloop()
