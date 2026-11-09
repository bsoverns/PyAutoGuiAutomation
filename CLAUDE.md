# GuiAutomation

Windows desktop app (tkinter) for building and running step-by-step PyAutoGUI tests.

## Commands

Run in Git Bash with `.venv` active.

- Build: `python -m compileall -q src tests`
- Test: `python -m pytest`
- Lint: `ruff check . && ruff format --check .`

## Conventions

- Type hints on public functions.
- Use the virtual environment; pin exact versions in `pyproject.toml`.
- Tests never control the real mouse, keyboard or screen. Use the injected fakes.
- `import pyautogui` only inside the driver module, and lazily, so other modules import without a display.
- Never read or depend on `TestPrograms/`; it is local and gitignored.
- Never store passwords in saved tests. Typed secrets come from environment variables.
- Commit messages use Conventional Commits, for example `feat: <summary>`.
