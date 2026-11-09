# GuiAutomation

A Windows desktop tool for building and running step-by-step GUI tests of your own programs with PyAutoGUI. Tests are saved as JSON and can be exported to a runnable Python script.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

## Build a test

```bash
guiautomation gui [file.json]
```

`python -m guiautomation` works the same as `guiautomation`.

The builder adds, edits, deletes and reorders steps. Step types: click, double click, right click, move, drag, type text, press key, hotkey, scroll, wait seconds, wait for image, and assert image visible. Mouse and typing steps target screen coordinates or a captured image.

**New, Open, Save, Save as and Export script** are the buttons along the top of the builder, and also in the File menu. Ctrl+S saves and Ctrl+O opens. Open a saved test to keep editing it.

**Step name** is the first field of every step, and **Clip a click** asks for one. The name leads the step list, shows in the Run status window while the step runs, prints as each step starts on the command line, and appears in the results. It is optional; a step with no name shows its type.

**Clip from screen** in the step editor hides the builder and shows an overlay over all monitors; drag a box around the target, or press Esc to cancel. You clip while you build, with no file to choose and no need to save first. **Clip a click** in the main window does the same and adds a click on the clip in one go. Clips are kept in a temporary folder until the first save, then in an `images/` folder next to the test, and paths in the JSON stay relative to it.

**Confidence** is how closely the screen must match a clip. It uses the same scale as PyAutoGUI's `confidence=`: `1` is pixel-identical, around `0.8` tolerates small rendering differences, and values near `0.4` are very loose. Below about `0.5`, parts of the screen that merely resemble the clip can qualify. `0` means no resemblance at all, so it is not accepted. If you leave it blank, `0.8` is used. When several places qualify, the best match is chosen.

**If the image is not found** is set per step. **Stop the run as failed** is the default: the step searches until its timeout (10 seconds if blank), then fails and ends the run. **Keep looking until found** ignores the timeout and searches for as long as it takes, until the image appears or you stop the run.

Clicks glide to the target over 0.5 seconds before clicking, so the program sees the mouse arrive.

**Replacing steps:** select a step and use **Edit / replace** (or double-click it) to change anything about it in place, including its type, text or clip. **Replace clip** clips a new target for the selected step and keeps its other settings.

**Run** starts the test unattended after 5 seconds. Set **Repeat (times)** or tick **Forever** beside it; the setting is saved with the test and can be changed at any time. A small status window at the bottom right of the primary monitor shows the current loop and has a **Stop** button.

**Guided run** runs one step at a time and asks you to answer Pass, Fail or Stop for each step, then shows the results.

## Run a test unattended

```bash
guiautomation run file.json              # waits 5 seconds, then runs
guiautomation run file.json --no-delay   # starts immediately
guiautomation run file.json --delay 2    # waits 2 seconds
guiautomation run file.json --repeat 10  # runs the test 10 times
guiautomation run file.json --forever    # repeats until stopped
```

Without `--repeat` or `--forever`, the count saved in the test is used. The start delay happens once. Looping ends at the first loop that fails or is aborted, and the result shows how many loops completed and the steps of the last loop. A `--forever` run that you stop ends with exit code 3.

| Exit code | Meaning |
|---|---|
| 0 | Test passed |
| 1 | A step failed (the output names the step and the reason) |
| 2 | Bad input or usage |
| 3 | Aborted |
| 4 | Internal error |

## Python API

```python
from guiautomation import run_automation

result = run_automation("file.json")  # no delay by default
print(result.passed, result.summary())
```

An exported script takes the same `--no-delay`, `--delay N`, `--repeat N` and `--forever` options and uses exit codes 0 to 3.

`run_automation(path_or_automation, delay=0.0, repeat=None, ...)` returns a `RunResult`. `repeat` overrides the saved count, and `REPEAT_FOREVER` (0) loops until stopped. It raises `ValidationError` for bad input such as an invalid file or a missing image.

## Stopping a run

- Press **Ctrl+Alt+Shift+Q**. It is checked between steps, during waits and the start delay, and while typing.
- Move the mouse to a corner of the **primary** monitor to trigger the PyAutoGUI failsafe. It is checked at the same points and while a guided run waits for your answer. Steps aimed exactly at those corners also trigger it.

Both end the run with an aborted result.

## Secrets

Saved tests never hold secrets. A type step uses `text` or `env_var`; `env_var` reads an environment variable at run time, and a missing variable fails the step. Typed values are never logged and never placed on the clipboard; non-ASCII text is sent as Unicode key events. Literal text that is flagged `secret` or looks like a credential is rejected.

## Multiple monitors

Coordinates are virtual-desktop coordinates, so monitors left of or above the primary one have negative values. Capture and image search cover the whole virtual desktop.

## Build, test, lint

Run these in Git Bash with the virtual environment active:

```bash
python -m compileall -q src tests
python -m pytest
ruff check . && ruff format --check .
```
