"""Compatibility entry point; `python -m app` runs the same command."""

from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
