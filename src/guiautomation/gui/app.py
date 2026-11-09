"""The tkinter test builder."""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

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
    parse_repeat,
    step_from_form,
    step_to_form,
    takes_image,
    with_clip,
)
from guiautomation.gui.running import LoopRun
from guiautomation.keys import canonical_key, key_choices
from guiautomation.model import (
    REPEAT_FOREVER,
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
_PREVIEW_SIZE = 200  # Largest width or height of an image preview, in pixels.


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
        selector.bind("<<ComboboxSelected>>", lambda _event: self._build_form(self._form_values()))
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
            self._entries[spec.name] = variable
            if spec.kind == "image":
                self._build_image_row(row, variable)
            elif spec.kind == "choice":
                labels = [label for label, _ in spec.choices]
                variable.set(variable.get() or labels[0])
                box = ttk.Combobox(
                    self._form, textvariable=variable, values=labels, state="readonly", width=42
                )
                box.grid(row=row, column=1, padx=4, sticky="w")
            elif spec.kind == "key":
                self._build_key_row(row, variable)
            elif spec.kind == "keys":
                self._build_hotkey_row(row, variable)
            else:
                entry = ttk.Entry(self._form, textvariable=variable, width=44)
                entry.grid(row=row, column=1, padx=4)

    def _build_key_row(self, row: int, variable: tk.StringVar) -> None:
        """A key field that lists the named keys and still accepts a typed one."""
        box = ttk.Combobox(self._form, textvariable=variable, values=key_choices(), width=42)
        box.grid(row=row, column=1, padx=4, sticky="w")
        box.bind("<<ComboboxSelected>>", lambda _event: variable.set(canonical_key(box.get())))

    def _build_hotkey_row(self, row: int, variable: tk.StringVar) -> None:
        """A typed key combination with a picker that appends a named key to it."""
        frame = ttk.Frame(self._form)
        frame.grid(row=row, column=1, padx=4, sticky="w")
        ttk.Entry(frame, textvariable=variable, width=24).pack(side="left")
        prompt = "Add a key"
        picked = tk.StringVar(value=prompt)
        box = ttk.Combobox(
            frame, textvariable=picked, values=key_choices(), state="readonly", width=16
        )
        box.pack(side="left", padx=4)

        def add(_event: object) -> None:
            keys = variable.get().strip().rstrip("+,").strip()
            name = canonical_key(picked.get())
            variable.set(f"{keys}+{name}" if keys else name)
            picked.set(prompt)

        box.bind("<<ComboboxSelected>>", add)

    def _form_values(self) -> dict[str, str]:
        return {name: variable.get() for name, variable in self._entries.items()}

    def _build_image_row(self, row: int, variable: tk.StringVar) -> None:
        frame = ttk.Frame(self._form)
        frame.grid(row=row, column=1, sticky="w", padx=4)
        clip = ttk.Button(frame, command=lambda: self._capture(variable))
        clip.pack(side="left")
        ttk.Button(frame, text="Clear", command=lambda: variable.set("")).pack(side="left", padx=4)
        preview = ttk.Label(frame)
        preview.pack(side="left", padx=4)

        def refresh(*_args: object) -> None:
            clip.configure(text="Replace clip" if variable.get() else "Clip from screen")
            self._show_preview(preview, variable.get())

        variable.trace_add("write", refresh)
        refresh()

    def _show_preview(self, label: ttk.Label, relative: str) -> None:
        self._preview = None  # Tk drops an image once nothing references it, so keep one.
        if not relative:
            label.configure(image="", text="No image clipped yet")
            return
        try:
            picture = tk.PhotoImage(file=self._app.image_file(relative))
        except (tk.TclError, ValidationError):
            label.configure(image="", text=relative)
            return
        factor = math.ceil(max(picture.width(), picture.height()) / _PREVIEW_SIZE)
        self._preview = picture.subsample(max(factor, 1))
        label.configure(image=self._preview, text="")

    def _capture(self, variable: tk.StringVar) -> None:
        self.window.grab_release()

        def restore() -> None:
            self.window.deiconify()
            grab_when_viewable(self.window)

        def on_saved(relative: str) -> None:
            variable.set(relative)
            for name in ("x", "y"):  # A step targets an image or coordinates, never both.
                if name in self._entries:
                    self._entries[name].set("")

        self._app.capture(self.window, on_saved, restore)

    def _ok(self) -> None:
        form = self._form_values()
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
        self._scratch: Path | None = None  # Holds clips until the test is first saved.
        self._set_automation(automation or Automation(), self._path)

        root.geometry("760x560")
        root.protocol("WM_DELETE_WINDOW", self._quit)
        root.bind("<Control-s>", lambda _event: self._save())
        root.bind("<Control-o>", lambda _event: self._open())
        self._build_menu()
        self._build_file_bar()
        toolbar = ttk.Frame(root)
        toolbar.pack(side="right", fill="y", padx=8, pady=8)
        for text, command in (
            ("Add", self._add),
            ("Clip a click", self._clip_click),
            ("Edit / replace", self._edit),
            ("Replace clip", self._replace_clip),
            ("Delete", self._delete),
            ("Move up", self._move_up),
            ("Move down", self._move_down),
            ("Guided run", self._guided_run),
            ("Run", self._run),
        ):
            ttk.Button(toolbar, text=text, command=command).pack(fill="x", pady=2)
        self._build_repeat_controls(toolbar)
        self._listbox = tk.Listbox(root, activestyle="dotbox", exportselection=False)
        self._listbox.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        self._listbox.bind("<Double-Button-1>", lambda _event: self._edit())
        self._show_repeat()
        self._refresh()

    def _build_repeat_controls(self, toolbar: ttk.Frame) -> None:
        self._syncing_repeat = False
        self._repeat_count = tk.StringVar(value="1")
        self._forever = tk.BooleanVar(value=False)
        ttk.Label(toolbar, text="Repeat (times):").pack(anchor="w", pady=(12, 0))
        self._repeat_box = ttk.Spinbox(
            toolbar, from_=1, to=1_000_000, textvariable=self._repeat_count, width=10
        )
        self._repeat_box.pack(fill="x", pady=2)
        ttk.Checkbutton(toolbar, text="Forever", variable=self._forever).pack(anchor="w")
        self._repeat_count.trace_add("write", self._repeat_edited)
        self._forever.trace_add("write", self._repeat_edited)

    def _show_repeat(self) -> None:
        """Make the loop controls match the current test."""
        self._syncing_repeat = True
        forever = self._automation.repeat == REPEAT_FOREVER
        self._forever.set(forever)
        self._repeat_count.set("1" if forever else str(self._automation.repeat))
        self._syncing_repeat = False
        self._repeat_box.configure(state="disabled" if forever else "normal")

    def _repeat_edited(self, *_args: object) -> None:
        if self._syncing_repeat:
            return
        self._repeat_box.configure(state="disabled" if self._forever.get() else "normal")
        try:
            value = parse_repeat(self._repeat_count.get(), self._forever.get())
        except ValidationError:
            return  # Possibly half typed; saving or running reports it.
        if value != self._automation.repeat:
            self._automation.repeat = value
            self._changed(self._selected())

    def _apply_repeat(self) -> bool:
        try:
            self._automation.repeat = parse_repeat(self._repeat_count.get(), self._forever.get())
        except ValidationError as exc:
            messagebox.showerror("Invalid repeat", str(exc))
            return False
        return True

    def _file_commands(self) -> tuple[tuple[str, Callable[[], object]], ...]:
        return (
            ("New", self._new),
            ("Open...", self._open),
            ("Save", self._save),
            ("Save as...", self._save_as),
            ("Export script...", self._export),
        )

    def _build_file_bar(self) -> None:
        bar = ttk.Frame(self.root)
        bar.pack(side="top", fill="x", padx=8, pady=(8, 0))
        for text, command in self._file_commands():
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=(0, 4))

    def _dialog_folder(self) -> str:
        """Return where file dialogs start: the open test's folder, or ./automations."""
        if self._path is not None:
            return str(self._path.parent)
        folder = Path.cwd() / "automations"
        try:
            folder.mkdir(exist_ok=True)
        except OSError:
            return str(Path.cwd())
        return str(folder)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        for label, command in self._file_commands():
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

    def _clip_click(self) -> None:
        """Clip a target from the screen, name the step, and add a click on it."""
        after = self._selected()

        def on_saved(relative: str) -> None:
            name = simpledialog.askstring(
                "Step name", "What does this click do? (optional)", parent=self.root
            )
            step = Step(
                type=StepType.CLICK, image=relative, description=(name or "").strip() or None
            )
            self._changed(self._steps.add(step, after))

        self.capture(None, on_saved, lambda: None)

    def _replace_clip(self) -> None:
        """Clip a new target for the selected step, keeping its other settings."""
        index = self._selected()
        if index is None:
            messagebox.showerror("Replace clip", "Select a step in the list first.")
            return
        step = self._steps.steps[index]
        if not takes_image(step.type):
            messagebox.showerror("Replace clip", "This type of step does not use a clip.")
            return

        def on_saved(relative: str) -> None:
            self._changed(self._steps.replace(index, with_clip(step, relative)))

        self.capture(None, on_saved, lambda: None)

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
            self._show_repeat()
            self._refresh()

    def _open(self) -> None:
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(filetypes=_JSON_TYPES, initialdir=self._dialog_folder())
        if not path:
            return
        try:
            self._set_automation(load_automation(path), Path(path))
        except ValidationError as exc:
            messagebox.showerror("Cannot open test", str(exc))
            return
        self._show_repeat()
        self._refresh()

    def _save(self) -> bool:
        if self._path is None:
            return self._save_as()
        return self._apply_repeat() and self._write(self._path)

    def _save_as(self) -> bool:
        if not self._apply_repeat():
            return False
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=_JSON_TYPES, initialdir=self._dialog_folder()
        )
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
        # Clips in the temporary folder would vanish, so they must be saved with the test first.
        if self._path is None and self._automation.image_paths() and not self._save():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".py", filetypes=[("Python files", "*.py")]
        )
        if not path:
            return
        try:
            export_script(self._automation, path)
        except (ValidationError, OSError) as exc:
            messagebox.showerror("Cannot export test", str(exc))

    def image_file(self, relative: str) -> Path:
        """Return the absolute path of one of this test's images."""
        return self._automation.resolve_image(relative)

    def _ensure_image_folder(self) -> None:
        """Give an unsaved test a temporary folder; the first save copies its clips across."""
        if self._automation.base_dir is None:
            if self._scratch is None:
                self._scratch = Path(tempfile.mkdtemp(prefix="guiautomation-"))
            self._automation.base_dir = self._scratch

    def capture(
        self,
        dialog: tk.Toplevel | None,
        on_saved: Callable[[str], None],
        restore: Callable[[], None],
    ) -> None:
        """Hide all windows, let the user drag a region, and save it with the test's images."""
        try:
            self._ensure_image_folder()
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

        if dialog is not None:
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
        self._start_run(GuidedRun)

    def _run(self) -> None:
        if self._apply_repeat():
            self._start_run(LoopRun)

    def _start_run(self, kind: Callable[..., GuidedRun | LoopRun]) -> None:
        try:
            self._automation.check_runnable()
        except ValidationError as exc:
            messagebox.showerror("Cannot run test", str(exc))
            return
        self.root.withdraw()
        try:
            run = kind(self.root, self._automation, self._show_report)
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
            if self._scratch is not None:
                shutil.rmtree(self._scratch, ignore_errors=True)
            self.root.destroy()


def run_gui(
    automation: Automation | None = None, path: str | os.PathLike[str] | None = None
) -> None:
    """Open the builder and block until it closes."""
    screen.enable_dpi_awareness()
    root = tk.Tk()
    BuilderApp(root, automation, path)
    root.mainloop()
