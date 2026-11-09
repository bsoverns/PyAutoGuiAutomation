# Assumptions and decisions

Request #26. Decisions marked (owner) were chosen by the project owner; the rest were made during the run.

## Decisions

- (owner) Build in the existing repo; ignore `TestPrograms/`; push directly to `main`.
- (owner) CI runs on `windows-latest` only.
- (owner) tkinter GUI; `mss` capture with a DPI-aware process for one or more monitors.
- (owner) Steps saved as JSON, with export to a runnable `.py` file.
- (owner) Command-line runner: 5-second default wait, `--no-delay` when called, exit code 0 for pass and non-zero for fail, plus a small Python function.
- (owner) Secrets come from environment variables. Captured screenshots are gitignored.
- (owner) PyAutoGUI failsafe stays on, plus an abort hotkey.
- (owner) QA uses mocked tests plus a manual checklist; it never takes over the real desktop.
- Image matching uses OpenCV template matching on an `mss` capture of the virtual desktop, because PyAutoGUI's own search is oriented to the primary monitor.
- Saved automations live in an ignored `automations/` folder, so they do not reach GitHub by default.

## Acceptance criteria

Derived from "What needs to happen" in the request.

- AC1: The GUI builds a test step by step, with steps added, edited, deleted and reordered.
- AC2: Step types cover click, double and right click, typing, hotkey, key press, scroll, wait, and wait-for-image.
- AC3: The GUI captures screenshots of a chosen screen region, for use as click and typing targets.
- AC4: Tests save and load as JSON and export to a runnable Python script.
- AC5: A guided run executes one step at a time and records the user's pass or fail confirmation for each step.
- AC6: Run by itself, a test waits a default delay (5 seconds) before starting.
- AC7: Called from another program, a test runs with limited or no delay, through a command-line option and a Python function, and reports pass or fail by exit code or return value.
- AC8: Capture and image targets work on one or several monitors, including negative virtual-desktop coordinates.
- AC9: Runs can be stopped by the failsafe and an abort hotkey, and saved tests never store secrets.
