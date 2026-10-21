"""Terminal styling for the NEEZY CLI menu.

Stdlib only. Output is ASCII (no box-drawing glyphs) so it renders the same in
cmd.exe on a legacy code page, PowerShell, and any Unix terminal.

Colour is decided in one place, `color_enabled`:
- `--plain` or `NO_COLOR` (any non-empty value) turns colour off.
- `FORCE_COLOR` (any non-empty value) turns it on, even when piped.
- `TERM=dumb` turns it off.
- Otherwise colour is on only when the stream is a TTY.

Styling never changes the text content, only wraps it in ANSI codes, so the
same screen can be read with or without colour.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from typing import TextIO

RESET = "\x1b[0m"

# Role name -> SGR parameters. Restrained palette: one accent, one warning
# colour, one success colour. Everything else is bold, dim, or default.
ROLES: dict[str, str] = {
    "title": "1;36",  # bold cyan
    "accent": "36",  # cyan: keys and active items
    "bold": "1",
    "muted": "2",  # dim: hints, separators, command echo
    "ok": "32",  # green
    "warn": "33",  # yellow: anything that can move money
    "bad": "31",  # red: failures
    "border": "2",
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_WIDTH = 60


def color_enabled(
    stream: TextIO,
    *,
    plain: bool = False,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return True when `stream` should receive ANSI colour codes."""
    if plain:
        return False
    env = os.environ if env is None else env
    if env.get("NO_COLOR", ""):
        return False
    if env.get("FORCE_COLOR", ""):
        enable_windows_vt()
        return True
    if env.get("TERM", "") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty) or not isatty():
        return False
    enable_windows_vt()
    return True


def enable_windows_vt() -> None:
    """Turn on ANSI escape handling in the Windows console. No-op elsewhere.

    Windows 10+ supports VT sequences but only after the console mode is set.
    Failure is silent: the caller then just gets escape codes shown as text,
    so colour should be turned off by passing plain=True.
    """
    if os.name != "nt":
        return
    try:  # pragma: no cover - Windows only
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except (AttributeError, OSError):  # pragma: no cover - Windows only
        return


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def visible_width(text: str) -> int:
    return len(strip_ansi(text))


class Style:
    """Wraps text in ANSI codes when enabled, and returns it unchanged when not."""

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, text: str, role: str = "bold") -> str:
        if not self.enabled or not text:
            return text
        return f"\x1b[{ROLES[role]}m{text}{RESET}"

    def badge(self, text: str, role: str) -> str:
        return self(f"[{text}]", role)

    def rule(self, width: int = _WIDTH) -> str:
        return self("-" * width, "border")


def panel(style: Style, title: str, lines: Sequence[str], width: int = _WIDTH) -> str:
    """Bordered block. Lines may contain ANSI; padding uses visible width."""
    inner = width - 4
    top = style("+" + "-" * (width - 2) + "+", "border")
    divider = style("+" + "-" * (width - 2) + "+", "border")
    edge = style("|", "border")

    def row(content: str) -> str:
        pad = max(0, inner - visible_width(content))
        return f"{edge} {content}{' ' * pad} {edge}"

    out = [top, row(style(title, "title")), divider]
    out.extend(row(line) for line in lines)
    out.append(top)
    return "\n".join(out)


def status_bar(style: Style, items: Sequence[tuple[str, str, str]]) -> str:
    """One line of `label value` pairs, each value with a role colour."""
    parts = []
    for label, value, role in items:
        parts.append(f"{style(label, 'muted')} {style(value, role)}")
    return style("  |  ", "border").join(parts)


def key_line(style: Style, key: str, label: str, role: str = "bold") -> str:
    return f"  {style(key.rjust(2), 'accent')}  {style(label, role)}"
