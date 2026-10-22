"""Design tokens for the desktop shell (roadmap update #8).

The three shipped themes live here as palettes of shared color tokens.
`App._apply_theme` consumes them; nothing in this module touches Tkinter,
so palettes can be validated and diffed in headless tests.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

Theme = Mapping[str, str]

THEME_PALETTES: dict[str, dict[str, str]] = {
    "Liquid dark": {
        "BG": "#08111f",
        "PANEL": "#101d30",
        "PANEL2": "#14253b",
        "TEXT": "#e6f0ff",
        "MUTED": "#8ea4bd",
        "CYAN": "#55d6ff",
        "GREEN": "#48e6a1",
        "RED": "#ff718c",
        "BORDER": "#203754",
    },
    "Midnight blue": {
        "BG": "#071522",
        "PANEL": "#10263a",
        "PANEL2": "#17354e",
        "TEXT": "#e7f5ff",
        "MUTED": "#9bb8ca",
        "CYAN": "#64e1ff",
        "GREEN": "#5ce8b2",
        "RED": "#ff8299",
        "BORDER": "#29506b",
    },
    "High contrast": {
        "BG": "#000000",
        "PANEL": "#111111",
        "PANEL2": "#222222",
        "TEXT": "#ffffff",
        "MUTED": "#d2d2d2",
        "CYAN": "#00e5ff",
        "GREEN": "#00ff76",
        "RED": "#ff647c",
        "BORDER": "#777777",
    },
}

#: Chart canvas background per theme (kept beside the palettes it depends on).
THEME_CANVAS_BG = {
    "Liquid dark": "#0c192b",
    "Midnight blue": "#0c192b",
    "High contrast": "#050505",
}

DEFAULT_THEME = "Liquid dark"


def palette_for(theme_name: str | None) -> dict[str, str]:
    """Return the palette for ``theme_name``, or the default theme's."""
    name = theme_name if theme_name in THEME_PALETTES else DEFAULT_THEME
    return dict(THEME_PALETTES[name])


def validate_palette(palette: Mapping[str, Any]) -> list[str]:
    """Return a list of token problems (empty when the palette is well formed)."""
    problems: list[str] = []
    expected = set(THEME_PALETTES[DEFAULT_THEME])
    missing = expected - set(palette)
    if missing:
        problems.append(f"missing tokens: {sorted(missing)}")
    for key, value in palette.items():
        if not isinstance(value, str) or not value.startswith("#") or len(value) != 7:
            problems.append(f"token {key!r} is not a #rrggbb color: {value!r}")
    return problems
