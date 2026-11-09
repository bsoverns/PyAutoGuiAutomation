# Architecture

```
GUI builder (tkinter) --> Automation (model) --> JSON file + images
                                  |
CLI / run_automation() --> Runner --> Driver (pyautogui) + Screen (mss + OpenCV)
                                  |
                              export --> standalone .py
```

| Module (`src/guiautomation/`) | Responsibility |
|---|---|
| `model.py` | `StepType`, `Step`, `Automation`; validation; JSON save and load; rejects secret-looking literal text |
| `screen.py` | `enable_dpi_awareness`, `Monitor`, `list_monitors`, `grab_region`, `find_image` over the virtual desktop |
| `driver.py` | `Driver` protocol and `PyAutoGuiDriver`, the only module that imports `pyautogui` (lazily) |
| `abort.py` | Abort hotkey polling (`GetAsyncKeyState` on Windows); no extra dependency |
| `runner.py` | `Runner`: executes steps, one at a time or all, with a confirm callback; `StepResult`, `RunResult`; `run_automation()` |
| `export.py` | Generates a runnable `.py` that calls `run_automation` on its embedded steps |
| `cli.py` | `guiautomation run` and `guiautomation gui`; delay handling; exit codes |
| `gui/` | tkinter builder, region-capture overlay, guided run window |

Dependencies are pinned in `pyproject.toml`: PyAutoGUI, mss, numpy, opencv-python-headless, pillow; pytest and ruff for development.

## Acceptance criteria map

Criteria are defined in `ASSUMPTIONS.md`.

| AC | Implemented in | Tested in |
|---|---|---|
| AC1 step editing | `model.py`, `gui/` | `test_model.py`, `test_gui_logic.py` |
| AC2 step types | `model.py`, `runner.py` | `test_runner.py` |
| AC3 screenshots | `screen.py`, `gui/` | `test_screen.py`, `test_gui_logic.py` |
| AC4 save, load, export | `model.py`, `export.py` | `test_model.py`, `test_export.py` |
| AC5 guided run | `runner.py`, `gui/` | `test_runner.py` |
| AC6 default delay | `cli.py`, `runner.py` | `test_cli.py` |
| AC7 called from a program | `cli.py`, `runner.py` | `test_cli.py`, `test_runner.py` |
| AC8 multiple monitors | `screen.py` | `test_screen.py` |
| AC9 stop and secrets | `abort.py`, `runner.py`, `model.py` | `test_runner.py`, `test_model.py` |
