# GuiAutomation

A Windows desktop app for building and running step-by-step GUI tests of your own programs with PyAutoGUI.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

## Build, test, lint

Run these in Git Bash with the virtual environment active:

```bash
python -m compileall -q src tests
python -m pytest
ruff check . && ruff format --check .
```
