"""Bridge from the CLI to the interactive terminal menu."""

from __future__ import annotations


def cmd_menu(args, fetch, out) -> int:
    """Interactive text menu that works in cmd.exe and PowerShell."""
    del fetch
    from ..menu import run_menu
    from ..ui_style import color_enabled

    return run_menu(out, color=color_enabled(out, plain=args.plain))
