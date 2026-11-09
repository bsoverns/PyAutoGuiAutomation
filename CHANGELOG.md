# Changelog

## Unreleased

- **Run GuiAutomation.bat** sets itself up on a fresh clone: it creates `.venv`, installs the pinned packages, and reinstalls when `pyproject.toml` changes.
- Step names: shown first in the step editor and list, live during a run, and in the results.
- Each image step can stop the run as failed when its image is missing, or keep looking until it is found.
- New, Open, Save, Save as and Export script buttons along the top of the builder, with Ctrl+S and Ctrl+O. The file dialogs start in the `automations` folder.
- Clicks glide to their target over 0.5 seconds before clicking.
- The default image confidence is now 0.8, and the step editor explains the scale.
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
