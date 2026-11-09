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

**Capture** in the step editor hides the builder and shows an overlay over all monitors; drag a region, or press Esc to cancel. Images are saved in an `images/` folder next to the test, and paths in the JSON stay relative to it.

**Guided run** runs one step at a time and asks you to answer Pass, Fail or Stop for each step, then shows the results.

## Run a test unattended

```bash
guiautomation run file.json              # waits 5 seconds, then runs
guiautomation run file.json --no-delay   # starts immediately
guiautomation run file.json --delay 2    # waits 2 seconds
```

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

An exported script takes the same `--no-delay` and `--delay N` options and uses exit codes 0 to 3.

`run_automation(path_or_automation, delay=0.0, ...)` returns a `RunResult`, and raises `ValidationError` for bad input such as an invalid file or a missing image.

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
