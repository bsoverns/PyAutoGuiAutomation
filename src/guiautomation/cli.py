"""Command-line interface: ``guiautomation run`` and ``guiautomation gui``."""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence

from guiautomation import screen
from guiautomation.model import ValidationError, load_automation
from guiautomation.runner import (
    EXIT_ABORTED,
    EXIT_BAD_INPUT,
    EXIT_INTERNAL_ERROR,
    exit_code_for,
    run_automation,
)

DEFAULT_DELAY = 5.0


def make_output_safe() -> None:
    """Keep text the console encoding cannot represent from raising an error."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def _delay_value(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text}") from None
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("delay must be a finite number, zero or more")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guiautomation", description="Build and run step-by-step GUI tests."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="run a saved test unattended")
    run.add_argument("file", help="path to the test JSON file")
    delay = run.add_mutually_exclusive_group()
    delay.add_argument("--no-delay", action="store_true", help="start immediately")
    delay.add_argument(
        "--delay",
        type=_delay_value,
        metavar="N",
        help=f"seconds to wait before starting (default {DEFAULT_DELAY:g})",
    )

    gui = commands.add_parser("gui", help="open the test builder")
    gui.add_argument("file", nargs="?", help="test JSON file to open")
    return parser


def _run_command(args: argparse.Namespace) -> int:
    delay = 0.0 if args.no_delay else DEFAULT_DELAY if args.delay is None else args.delay
    if delay > 0:
        print(f"Starting in {delay:g} s. Press Ctrl+Alt+Shift+Q to abort.", flush=True)
    try:
        result = run_automation(args.file, delay=delay)
        print(result.summary())
    except ValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except KeyboardInterrupt:
        print("Aborted.", file=sys.stderr)
        return EXIT_ABORTED
    except Exception as exc:  # noqa: BLE001 - reported as its own exit code, not a test failure
        print(f"error: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_INTERNAL_ERROR
    return exit_code_for(result)


def _gui_command(args: argparse.Namespace) -> int:
    automation = None
    if args.file is not None:
        try:
            automation = load_automation(args.file)
        except ValidationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_BAD_INPUT
    try:
        from guiautomation.gui.app import run_gui
    except ImportError as exc:
        if exc.name not in ("tkinter", "_tkinter"):
            raise
        print(f"error: tkinter is not available: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    run_gui(automation, args.file)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns the process exit code."""
    make_output_safe()
    args = _build_parser().parse_args(argv)
    screen.enable_dpi_awareness()
    if args.command == "run":
        return _run_command(args)
    return _gui_command(args)
