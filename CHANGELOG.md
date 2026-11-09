# Changelog

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
