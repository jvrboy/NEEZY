"""Appearance helpers for the CLI (density, palette, wicks)."""

from __future__ import annotations

from typing import Any

try:
    from neezy_app.theme import DENSITY_SCALE, WICK_STYLES, palette_for
except ImportError:  # headless / test isolation fallback
    DENSITY_SCALE: dict[str, float] = {
        "comfortable": 1.2,
        "compact": 0.85,
        "spacious": 1.45,
    }
    WICK_STYLES = frozenset({"thin", "bold", "dotted"})  # type: ignore[assignment]

    def palette_for(  # type: ignore[no-redef]
        theme_name: str | None, *, colorblind: bool = False
    ) -> dict[str, str]:
        return {"BG": "#08111f", "PANEL": "#101d30"}


def cmd_appearance(args: Any) -> int:
    action = getattr(args, "action", "show")
    if action == "density":
        name = getattr(args, "name", None)
        if name:
            scale = DENSITY_SCALE.get(name)
            if scale is None:
                choices = ", ".join(sorted(DENSITY_SCALE))
                print(f"unknown density {name!r}; choices: {choices}")
                return 1
            print(f"{name} -> scale {scale}")
        else:
            for k, v in sorted(DENSITY_SCALE.items()):
                print(f"{k}: {v}")
        return 0
    if action == "palette":
        theme = getattr(args, "theme_name", None)
        pal = palette_for(theme)
        if getattr(args, "json", False):
            import json

            print(json.dumps(pal, indent=2))
        else:
            for k, v in sorted(pal.items()):
                print(f"{k}={v}")
        return 0
    if action == "wick-styles":
        print(", ".join(sorted(WICK_STYLES)))
        return 0
    # show
    theme = getattr(args, "theme_name", None)
    pal = palette_for(theme)
    if getattr(args, "json", False):
        import json

        print(
            json.dumps(
                {
                    "theme": theme or "default",
                    "palette": pal,
                    "densities": DENSITY_SCALE,
                    "wicks": sorted(WICK_STYLES),
                },
                indent=2,
            )
        )
    else:
        dens = ", ".join(sorted(DENSITY_SCALE))
        print(f"Theme {theme or 'default'}: {len(pal)} tokens; densities: {dens}")
    return 0
