"""Allow ``python -m guiautomation``."""

from guiautomation.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
