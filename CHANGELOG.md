# Changelog

## Unreleased

- Clip targets from the screen while building, with no file dialog on an unsaved test, and see a preview in the step editor. The image field no longer takes a typed path.
- **Clip a click** adds a click on a new clip in one action.
- Replace steps in place with **Edit / replace**, and swap a step's target with **Replace clip**.
- Loop a test a set number of times or forever: saved in the test, set in the builder, or with `--repeat N` and `--forever`.
- **Run** button in the builder for unattended runs, with a loop status window and a Stop button.

## 0.1.0

- tkinter test builder with add, edit, delete and reorder, and region capture across all monitors.
- Twelve step types, targeting screen coordinates or a captured image.
- Guided run with a pass, fail or stop answer for each step.
- `guiautomation run` with a default 5-second delay, `--no-delay`, `--delay N`, and exit codes 0, 1, 2, 3 and 4.
- `run_automation()` Python API and `python -m guiautomation`.
- JSON save and load with strict validation, and export to a runnable Python script.
- Multi-monitor support, including negative virtual-desktop coordinates.
- Stopping through the PyAutoGUI failsafe and the Ctrl+Alt+Shift+Q abort hotkey.
- Secrets typed from environment variables and never stored in saved tests.
