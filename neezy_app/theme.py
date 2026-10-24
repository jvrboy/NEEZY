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

# Appearance density multipliers for spacing/typography
DENSITY_SCALE: dict[str, float] = {
    "comfortable": 1.2,
    "compact": 0.85,
    "spacious": 1.45,
}

# Supported wick styles for chart renderer
WICK_STYLES = frozenset({"thin", "bold", "dotted"})


def merged_palette(
    theme_name: str | None,
    *,
    custom_tokens: dict[str, str] | None = None,
    colorblind: bool = False,
) -> dict[str, str]:
    """Palette merged with user custom tokens (custom keys override)."""
    base = palette_for(theme_name, colorblind=colorblind)
    if not custom_tokens:
        return base
    merged = dict(base)
    for k, v in custom_tokens.items():
        if (
            isinstance(k, str)
            and isinstance(v, str)
            and v.startswith("#")
            and len(v) == 7
        ):
            merged[k] = v
    return merged


def density_scale(density: str) -> float:
    """Numeric scale factor for ``appearance_density``."""
    return DENSITY_SCALE.get(density, 1.0)


def validate_wick_style(style: str) -> list[str]:
    if style in WICK_STYLES:
        return []
    return [f"wick style {style!r} not in {sorted(WICK_STYLES)}"]


def palette_for(theme_name: str | None, *, colorblind: bool = False) -> dict[str, str]:
    """Return the palette for ``theme_name``, or the default theme's."""
    name = theme_name if theme_name in THEME_PALETTES else DEFAULT_THEME
    palette = dict(THEME_PALETTES[name])
    if colorblind:
        palette["GREEN"] = "#38bdf8"
        palette["RED"] = "#fb923c"
    return palette


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
