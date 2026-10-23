"""Terminal styling for the NEEZY CLI menu.

Stdlib only. Output is ASCII (no box-drawing glyphs) so it renders the same in
cmd.exe on a legacy code page, PowerShell, and any Unix terminal.

Colour is decided in one place, `color_enabled`:
- `--plain` or `NO_COLOR` (any non-empty value) turns colour off.
- `FORCE_COLOR` (any non-empty value) turns it on, even when piped.
- `TERM=dumb` turns it off.
- Otherwise colour is on only when the stream is a TTY and Windows VT setup,
  where needed, succeeds; legacy Windows consoles fall back to plain text.

Styling never changes the text content, only wraps it in ANSI codes, so the
same screen can be read with or without colour.
"""

from __future__ import annotations

import math
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
    return enable_windows_vt()


def enable_windows_vt() -> bool:
    """Enable ANSI in a Windows console and report whether colour is safe.

    Non-Windows terminals need no setup. On legacy Windows consoles, failure
    returns False so a TTY automatically falls back to plain text instead of
    displaying raw escape codes. Explicit FORCE_COLOR still wins for redirects.
    """
    if os.name != "nt":
        return True
    try:  # pragma: no cover - Windows only
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & 0x0004:  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):  # pragma: no cover - Windows only
        return False


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


# ---------------------------------------------------------------------------
# Themes (roadmap: advanced UI). Every theme maps the same role names, so
# components render identically no matter which palette is active.
# ---------------------------------------------------------------------------

#: Role palette per theme. "dark" preserves the original restrained palette.
THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "title": "1;36",
        "accent": "36",
        "bold": "1",
        "muted": "2",
        "ok": "32",
        "warn": "33",
        "bad": "31",
        "border": "2",
    },
    "light": {
        "title": "1;34",  # bold blue
        "accent": "34",
        "bold": "1",
        "muted": "2",
        "ok": "32",
        "warn": "33",
        "bad": "31",
        "border": "2",
    },
    "mono": {
        "title": "1",
        "accent": "1",
        "bold": "1",
        "muted": "2",
        "ok": "1",
        "warn": "1",
        "bad": "7",
        "border": "2",
    },
    "contrast": {
        "title": "1;37;44",  # bold white on blue
        "accent": "1;37",
        "bold": "1;37",
        "muted": "37",
        "ok": "1;32",
        "warn": "1;33",
        "bad": "1;31",
        "border": "1;37",
    },
    "ocean": {
        "title": "1;38;5;39",  # bold bright blue
        "accent": "38;5;81",
        "bold": "1",
        "muted": "38;5;245",
        "ok": "38;5;80",
        "warn": "38;5;214",
        "bad": "38;5;203",
        "border": "38;5;245",
    },
    "sunset": {
        "title": "1;38;5;209",  # bold orange
        "accent": "38;5;179",
        "bold": "1",
        "muted": "38;5;245",
        "ok": "38;5;114",
        "warn": "38;5;222",
        "bad": "38;5;160",
        "border": "38;5;245",
    },
    "grayscale": {
        "title": "1;37",
        "accent": "37",
        "bold": "1",
        "muted": "90",
        "ok": "1;37",
        "warn": "37",
        "bad": "7;90",
        "border": "90",
    },
}

THEME_NAMES: tuple[str, ...] = tuple(THEMES)

THEME_DESCRIPTIONS: dict[str, str] = {
    "dark": "default cyan-on-black terminal palette",
    "light": "blue accents for pale terminal backgrounds",
    "mono": "bold/dim only: safe for monochrome displays",
    "contrast": "high-contrast white-on-blue for low vision",
    "ocean": "256-color blue spectrum for modern terminals",
    "sunset": "256-color warm spectrum for modern terminals",
    "grayscale": "no colour, brightness levels only",
}

DEFAULT_THEME = "dark"


def resolve_theme(name: str | None = None, env: Mapping[str, str] | None = None) -> str:
    """Theme name from argument, then ``NEEZY_THEME``, then default.

    Unknown names fall back to the default instead of raising so a typo can
    never blank the interface.
    """
    import os

    values = os.environ if env is None else env
    candidate = (name or values.get("NEEZY_THEME", "")).strip().lower()
    return candidate if candidate in THEMES else DEFAULT_THEME


class ThemedStyle(Style):
    """Style bound to one theme palette; drops unknown roles to plain."""

    def __init__(self, enabled: bool, theme: str = DEFAULT_THEME) -> None:
        super().__init__(enabled)
        self.theme_name = resolve_theme(theme)
        self._roles = THEMES[self.theme_name]

    def __call__(self, text: str, role: str = "bold") -> str:
        if not self.enabled or not text:
            return text
        parameters = self._roles.get(role)
        if parameters is None:
            return text
        return f"\x1b[{parameters}m{text}{RESET}"


def themed_style(
    stream: TextIO,
    *,
    theme: str | None = None,
    plain: bool = False,
    env: Mapping[str, str] | None = None,
) -> ThemedStyle:
    """Build a themed Style with the same colour detection as always."""
    import os

    values = os.environ if env is None else env
    enabled = color_enabled(stream, plain=plain, env=values)
    return ThemedStyle(enabled, resolve_theme(theme, values))


# ---------------------------------------------------------------------------
# Device-aware output width. Phones and termux consoles get compact layouts;
# wide desktops are capped so panels stay readable.
# ---------------------------------------------------------------------------


def output_width(
    stream: TextIO | None = None,
    *,
    minimum: int = 40,
    maximum: int = 100,
    env: Mapping[str, str] | None = None,
) -> int:
    """Bounded terminal width for responsive ASCII layouts."""
    import os
    import shutil

    values = os.environ if env is None else env
    if values.get("COLUMNS", "").isdigit():
        columns = int(values["COLUMNS"])
    else:
        try:
            columns = shutil.get_terminal_size(fallback=(80, 24)).columns
            if stream is not None and getattr(stream, "isatty", lambda: False)():
                columns = shutil.get_terminal_size((columns, 24)).columns
        except (OSError, ValueError):
            columns = 80
    return max(minimum, min(maximum, columns))


# ---------------------------------------------------------------------------
# Advanced ASCII components. Every function returns plain-printable lines
# (no ANSI) so they compose inside panels and degrade on any device.
# ---------------------------------------------------------------------------

_SPARK_RAMP = " .:-=+*#%"


def sparkline(values: Sequence[float], width: int = 24) -> str:
    """Compact ASCII trend line. Flat series renders as a low line."""
    if width < 4:
        width = 4
    if not values:
        return " " * width
    numbers = [float(value) for value in values]
    low, high = min(numbers), max(numbers)
    span = high - low
    steps = len(_SPARK_RAMP) - 1
    if span == 0:
        return _SPARK_RAMP[steps // 2] * width
    chars = []
    for value in numbers:
        scaled = (value - low) / span
        chars.append(_SPARK_RAMP[min(steps, int(scaled * steps + 0.5))])
    # Resample to the requested width without inventing data points.
    if len(chars) == width:
        return "".join(chars)
    if len(chars) > width:
        keep = len(chars) / width
        picked = [chars[int(index * keep)] for index in range(width)]
        return "".join(picked)
    pad = width - len(chars)
    left = pad // 2
    return " " * left + "".join(chars) + " " * (pad - left)


def progress_bar(value: float, width: int = 20, *, label: str = "") -> str:
    """``[####----] 40%`` bar for 0.0-1.0 (or percent) values."""
    width = max(6, width)
    if not math.isfinite(value):
        value = 0.0
    fraction = max(0.0, min(1.0, value))
    filled = round(fraction * (width - 2))
    bar = "#" * filled + "-" * (width - 2 - filled)
    percent = f"{int(fraction * 100):3d}%"
    if label:
        return f"{label} [{bar}] {percent}"
    return f"[{bar}] {percent}"


_SPINNER_FRAMES = ("|", "/", "-", "\\")


def spinner_frame(step: int) -> str:
    """Rotating ASCII spinner frame; any int step is accepted."""
    return _SPINNER_FRAMES[step % len(_SPINNER_FRAMES)]


def gauge(value: float, maximum: float = 100.0, width: int = 20) -> str:
    """Needle gauge ``<-----|---->`` pinned into ``width`` characters."""
    width = max(8, width)
    if maximum <= 0 or not math.isfinite(value):
        return "<" + "-" * (width - 2) + ">"
    fraction = max(0.0, min(1.0, value / maximum))
    slot = max(0, min(width - 3, round(fraction * (width - 3))))
    body = "-" * slot + "|" + "-" * (width - 3 - slot)
    return f"<{body}>"


def histogram(values: Sequence[float], bins: int = 8, width: int = 30) -> list[str]:
    """Horizontal bar histogram; one ASCII row per bin, bin label first."""
    bins = max(1, min(12, bins))
    width = max(10, width)
    numbers = [float(value) for value in values]
    if not numbers:
        return ["(no data)"]
    low, high = min(numbers), max(numbers)
    if low == high:
        high = low + 1.0
    counts = [0] * bins
    for number in numbers:
        index = int((number - low) / (high - low) * bins)
        counts[min(bins - 1, index)] += 1
    peak = max(counts) or 1
    lines = []
    for index, count in enumerate(counts):
        start = low + (high - low) * index / bins
        end = low + (high - low) * (index + 1) / bins
        bar = "#" * max(0, int(count / peak * (width - 14)))
        lines.append(f"{start:>7.3g} {bar} {count}")
        del end
    return lines


def heatmap(
    rows: Sequence[str],
    columns: Sequence[str],
    matrix: Sequence[Sequence[float]],
    *,
    low: float = 0.0,
    high: float = 1.0,
) -> list[str]:
    """Character-density grid with row and column labels."""
    if not rows or not columns:
        return ["(no data)"]
    span = (high - low) or 1.0
    label_width = max((len(name) for name in rows), default=0)
    head = " " * (label_width + 1) + " ".join(name[:3].rjust(3) for name in columns)
    lines = [head]
    for name, row in zip(rows, matrix, strict=False):
        cells = []
        for value in row:
            fraction = max(0.0, min(1.0, (float(value) - low) / span))
            cells.append(_SPARK_RAMP[min(8, int(fraction * 8 + 0.5))])
        lines.append(
            name.ljust(label_width) + " " + " ".join(cell.rjust(3) for cell in cells)
        )
    return lines


def tree(entries: Sequence[tuple[str, Sequence[str]]]) -> list[str]:
    """ASCII tree: top-level names with nested leaf lines."""
    lines: list[str] = []
    for index, (root, leaves) in enumerate(entries):
        marker = "`--" if index == len(entries) - 1 else "|--"
        lines.append(f"{marker} {root}")
        for leaf_index, leaf in enumerate(leaves):
            last = leaf_index == len(leaves) - 1
            branch = "    " if index == len(entries) - 1 else "|   "
            twig = "`-- " if last else "|-- "
            lines.append(f"{branch}{twig}{leaf}")
    return lines


def kv_grid(pairs: Sequence[tuple[str, object]]) -> list[str]:
    """Aligned ``key .... value`` lines for report panels."""
    if not pairs:
        return ["(empty)"]
    width = max(len(str(key)) for key, _ in pairs)
    return [f"{str(key).ljust(width)}  {value}" for key, value in pairs]


def state_dot(status: str) -> str:
    """``[ok]`` / ``[!!]`` / ``[..]`` / ``[--]`` marker for a status word."""
    lowered = status.strip().lower()
    good = {"ok", "open", "running", "active", "pass", "enabled", "up", "true"}
    bad_exact = {
        "bad",
        "fail",
        "error",
        "down",
        "closed",
        "stopped",
        "false",
        "offline",
    }
    bad_prefixes = ("fail", "error", "down", "stopped", "offline")
    if lowered in good or lowered.startswith("ok"):
        return "[ok]"
    if lowered in bad_exact or lowered.startswith(bad_prefixes):
        return "[!!]"
    if lowered in {"pending", "paused", "idle", "warn", "warning"}:
        return "[..]"
    return "[--]"


def banner(title: str, width: int = 60, char: str = "=") -> str:
    """Centered title banner with rules: ``=== TITLE ===``."""
    width = max(20, width)
    if len(char) != 1:
        char = "="
    text = f" {title.strip()} "
    if len(text) >= width:
        return text.strip()
    pad = width - len(text)
    left = pad // 2
    return char * left + text + char * (pad - left)


def fit_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    width: int = 80,
) -> list[str]:
    """Responsive table: shrinks columns and truncates cells to fit ``width``.

    Unlike the CLI's fixed ``_table`` helper, this drops whole columns from
    the right (keeping the first ones) when a phone-sized terminal would
    otherwise wrap every row.
    """
    columns = len(headers)
    if columns == 0:
        return []
    cells = [[str(cell) for cell in row] for row in rows]
    while True:
        widths = [
            max(
                len(str(headers[i])),
                *(len(row[i]) for row in cells),
            )
            if cells
            else len(str(headers[i]))
            for i in range(columns)
        ]
        total = sum(widths) + 2 * (columns - 1)
        if total <= width or columns <= 1:
            break
        columns -= 1  # drop the right-most column and retry
        cells = [row[:columns] for row in cells]
    kept = list(headers[:columns])
    lines = ["  ".join(str(h).ljust(w) for h, w in zip(kept, widths, strict=True))]
    lines.append("  ".join("-" * w for w in widths))
    for row in cells:
        lines.append(
            "  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True))
        )
    return lines


def flatten_panel(title: str, lines: Sequence[str]) -> list[str]:
    """Screen-reader layout: panel as ``title: line`` sentences, no borders.

    Screen readers read box borders as noise; this keeps every piece of
    information but flattens the geometry.
    """
    flat = [f"{title}:"]
    for line in lines:
        cleaned = strip_ansi(line).strip()
        if cleaned:
            flat.append(f"  {cleaned}")
    return flat
