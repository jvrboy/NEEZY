"""``neezy-cli ui``: theme, component, and device-capability preview."""

from __future__ import annotations

import sys
from typing import TextIO

from ..capabilities import BACKEND_FEATURES
from ..ui_style import (
    THEME_DESCRIPTIONS,
    THEME_NAMES,
    banner,
    fit_table,
    gauge,
    heatmap,
    histogram,
    kv_grid,
    progress_bar,
    sparkline,
    state_dot,
    themed_style,
    tree,
)
from .common import _emit

_DEMO_SERIES = [float((index * 37) % 91) for index in range(30)]


def cmd_ui(args, fetch, out: TextIO) -> int:
    del fetch
    action = getattr(args, "action", "demo")
    if action == "theme":
        return _theme(out, args)
    if action == "demo":
        return _demo(out, args)
    if action == "capabilities":
        return _capabilities(out, args.json)
    raise ValueError(f"unknown ui action {action!r}")


def _theme(out: TextIO, args) -> int:
    verb = getattr(args, "verb", "list")
    if verb == "list":
        if args.json:
            _emit(
                out,
                [
                    {"name": name, "description": THEME_DESCRIPTIONS[name]}
                    for name in THEME_NAMES
                ],
            )
            return 0
        rows = [(name, THEME_DESCRIPTIONS[name]) for name in THEME_NAMES]
        out.write("Available themes (NEEZY_THEME=name or --theme name):\n")
        for line in fit_table(("theme", "description"), rows, width=78):
            out.write("  " + line + "\n")
        return 0
    if verb == "show":
        name = args.theme_name
        style = themed_style(out, theme=name, plain=False)
        out.write(f"Theme preview: {style.theme_name}\n")
        out.write(style("title  - panel titles", "title") + "\n")
        out.write(style("accent - keys and active items", "accent") + "\n")
        out.write(style("ok     - success states", "ok") + "\n")
        out.write(style("warn   - anything that can move money", "warn") + "\n")
        out.write(style("bad    - failures", "bad") + "\n")
        out.write(style("muted  - hints and separators", "muted") + "\n")
        out.write("\nColours appear only on a TTY; redirected output stays plain.\n")
        return 0
    raise ValueError(f"unknown theme verb {verb!r}")


def _demo(out: TextIO, args) -> int:
    del args
    style = themed_style(out)
    width = 72
    out.write("\n" + banner("NEEZY UI COMPONENT TOUR", width=width) + "\n\n")

    out.write(style("progress bars", "title") + "\n")
    for label, value in (("boot", 1.0), ("scan", 0.62), ("warmup", 0.08)):
        out.write("  " + progress_bar(value, width=28, label=label) + "\n")
    out.write("\n")

    out.write(style("sparkline (30-bar close series)", "title") + "\n")
    out.write("  " + sparkline(_DEMO_SERIES, width=40) + "\n")
    out.write("\n")

    out.write(style("gauges (RSI-style 0-100)", "title") + "\n")
    out.write(f"  RSI 28 {gauge(28, 100, width=24)}\n")
    out.write(f"  RSI 72 {gauge(72, 100, width=24)}\n")
    out.write("\n")

    out.write(style("histogram (return distribution)", "title") + "\n")
    for line in histogram(_DEMO_SERIES, bins=6, width=46):
        out.write("  " + line + "\n")
    out.write("\n")

    out.write(style("heatmap (correlation-style matrix)", "title") + "\n")
    matrix = [
        [1.0, 0.3, 0.1],
        [0.3, 1.0, 0.6],
        [0.1, 0.6, 1.0],
    ]
    for line in heatmap(("EURUSD", "GBPUSD", "XAUUSD"), ("EUR", "GBP", "XAU"), matrix):
        out.write("  " + line + "\n")
    out.write("\n")

    out.write(style("tree (bot roster view)", "title") + "\n")
    for line in tree(
        (
            ("scanner", ["watchlist scan", "consensus ranking"]),
            ("risk_guard", ["ATR stop advice"]),
            ("scribe", ["heartbeat"]),
        )
    ):
        out.write("  " + line + "\n")
    out.write("\n")

    out.write(style("key-value grid (status panel)", "title") + "\n")
    for line in kv_grid(
        (
            ("state", state_dot("running") + " running"),
            ("session", state_dot("open") + " London/NY overlap"),
            ("connectivity", state_dot("ok") + " loopback"),
        )
    ):
        out.write("  " + line + "\n")
    out.write("\n")

    out.write(style("responsive table (fit to 46 columns)", "title") + "\n")
    rows = [
        ("frxEURUSD", "BUY", "72", "strong"),
        ("frxGBPUSD", "NEUTRAL", "41", "mixed"),
        ("frxXAUUSD", "SELL", "64", "clean"),
    ]
    for line in fit_table(("market", "signal", "confidence", "note"), rows, width=46):
        out.write("  " + line + "\n")
    out.write("\n" + banner("END OF TOUR", width=width) + "\n")
    return 0


def _capabilities(out: TextIO, as_json: bool) -> int:
    from ..btoken import btoken_enabled, describe_mode
    from ..menu import runtime_label
    from ..ui_style import output_width

    color = out.isatty() if hasattr(out, "isatty") else False
    report = {
        "runtime": runtime_label(),
        "python": sys.version.split()[0],
        "terminal_width": output_width(out),
        "color_tty": color,
        "no_color_env_set": bool(__import__("os").environ.get("NO_COLOR")),
        "btoken_mode": btoken_enabled(),
        "btoken_description": describe_mode(),
        "backend_features": dict(BACKEND_FEATURES),
    }
    if as_json:
        _emit(out, report)
        return 0
    out.write("Device and runtime capabilities:\n")
    for line in kv_grid(tuple(report.items())):
        out.write("  " + line + "\n")
    out.write("\nBackend features (true = available locally):\n")
    for feature, available in report["backend_features"].items():
        out.write(f"  {state_dot('ok' if available else 'stopped')} {feature}\n")
    return 0
