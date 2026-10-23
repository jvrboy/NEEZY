"""Installed NEEZY launcher: portable terminal by default, Tk on request."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def _run_desktop() -> int:
    """Start the desktop and explain missing platform GUI requirements clearly."""
    try:
        import tkinter  # noqa: F401
    except ModuleNotFoundError as error:
        raise SystemExit(
            "NEEZY desktop needs Tkinter. Install the operating-system Tk package "
            "(for example, python3-tk), then run 'neezy --desktop' again. "
            "The terminal workspace remains available as 'neezy'."
        ) from error
    from .enterprise import main as run_app

    run_app()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the terminal workspace, or the desktop only with ``--desktop``."""
    parser = argparse.ArgumentParser(
        prog="neezy",
        description="NEEZY intelligent market workspace (terminal by default).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--desktop",
        action="store_true",
        help="launch the Tk desktop app instead of the portable terminal workspace",
    )
    mode.add_argument(
        "--plain",
        action="store_true",
        help="disable colour in the terminal workspace (also: NO_COLOR=1)",
    )
    arguments = parser.parse_args(argv)
    if arguments.desktop:
        return _run_desktop()

    # Keep Tk and desktop-only dependencies out of the default CLI path.
    from neezy_backend.menu import run_menu

    if arguments.plain:
        return run_menu(sys.stdout, color=False)
    return run_menu(sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
