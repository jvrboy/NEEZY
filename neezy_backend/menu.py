"""Plain-text terminal menu for NEEZY.

Stdlib only, no curses, so it runs in cmd.exe, PowerShell, and any ANSI-less
terminal. Each choice runs the same command the CLI exposes, so the menu adds
no new behaviour and no new trading paths.

Layout: a header panel with a status bar, a grouped command palette, and a
prompt. Type a key to run it, `/text` to filter the palette, `?` for help, and
`q` to quit. Colour follows `ui_style.color_enabled`; the text content is the
same with or without it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TextIO

from .mcp_catalog import MCP_SERVERS
from .ui_style import Style, color_enabled, key_line, panel

LIVE_CONFIRM_PHRASE = "SEND"

# (key, group, label, tone). Tone is a ui_style role; "warn" marks anything
# that can move money so it stands out in the palette.
MenuItem = tuple[str, str, str, str]

MENU: tuple[MenuItem, ...] = (
    ("1", "System", "Market data connectivity check", "bold"),
    ("2", "MT5 read-only", "MT5 bridge status", "bold"),
    ("3", "MT5 read-only", "MT5 account info", "bold"),
    ("4", "MT5 read-only", "MT5 quote", "bold"),
    ("5", "MT5 read-only", "MT5 candles", "bold"),
    ("p", "MT5 read-only", "MT5 preflight checklist", "bold"),
    ("6", "MT5 orders", "Order: DRY RUN (never sent)", "ok"),
    ("7", "MT5 orders", "Order: LIVE (type SEND to confirm)", "warn"),
    ("r", "Market", "Market regime for one symbol", "bold"),
    ("8", "MCP", "MCP server catalog", "bold"),
    ("9", "MCP", "MCP client config for one server", "bold"),
    ("0", "Exit", "Quit", "muted"),
)

_QUIT_WORDS = ("0", "q", "quit", "exit")


def _ask(prompt: str, input_fn: Callable[[str], str]) -> str:
    return input_fn(prompt).strip()


def _order_args(input_fn: Callable[[str], str]) -> list[str]:
    symbol = _ask("Symbol (e.g. frxEURUSD): ", input_fn)
    side = _ask("Side BUY or SELL: ", input_fn).upper()
    volume = _ask("Volume (lots): ", input_fn)
    if not symbol or side not in ("BUY", "SELL") or not volume:
        raise ValueError("symbol, BUY/SELL, and volume are all required")
    return ["mt5", "order", symbol, "--type", side, "--volume", volume]


def filter_menu(query: str) -> tuple[MenuItem, ...]:
    """Palette entries whose key, group, or label contain `query` (case-insensitive)."""
    needle = query.strip().lower()
    if not needle:
        return MENU
    return tuple(item for item in MENU if needle in " ".join(item[:3]).lower())


def _render_header(out: TextIO, style: Style) -> None:
    status = (
        f"{style('mode', 'muted')} {style('local', 'bold')}   "
        f"{style('live orders', 'muted')} {style('locked until SEND', 'ok')}"
    )
    body = [
        style("local trading terminal", "muted"),
        status,
    ]
    out.write("\n" + panel(style, "NEEZY", body) + "\n")


def _render_palette(
    out: TextIO,
    style: Style,
    items: Sequence[MenuItem],
    *,
    empty_note: str = "No matches. Type / alone to see everything.",
) -> None:
    if not items:
        out.write(style(empty_note, "warn") + "\n")
        return
    group = None
    for key, item_group, label, tone in items:
        if item_group != group:
            group = item_group
            out.write("\n" + style(group, "bold") + "\n")
        out.write(key_line(style, key, label, tone) + "\n")


def _render_footer(out: TextIO, style: Style) -> None:
    out.write(
        "\n"
        + style(
            "number runs it  /text filters  ?  help  q  quit",
            "muted",
        )
        + "\n"
    )


def _argv_for(
    choice: str,
    input_fn: Callable[[str], str],
    out: TextIO,
    style: Style,
) -> list[str] | None:
    """argv for one palette key. None means the action was cancelled."""
    if choice == "1":
        return ["doctor"]
    if choice == "p":
        return ["mt5", "preflight"]
    if choice == "2":
        return ["mt5", "status"]
    if choice == "3":
        return ["mt5", "account"]
    if choice == "4":
        return ["mt5", "quote", _ask("Symbol: ", input_fn)]
    if choice == "5":
        return ["mt5", "candles", _ask("Symbol: ", input_fn)]
    if choice == "6":
        return [*_order_args(input_fn), "--dry-run"]
    if choice == "7":
        argv = _order_args(input_fn)
        prompt = f"Type {LIVE_CONFIRM_PHRASE} to send a live order: "
        if _ask(prompt, input_fn) != LIVE_CONFIRM_PHRASE:
            out.write(style("Cancelled. No order sent.", "warn") + "\n")
            return None
        argv.append("--confirm")
        return argv
    if choice == "r":
        return ["regime", _ask("Symbol (e.g. frxEURUSD): ", input_fn)]
    if choice == "8":
        return ["mcp", "list"]
    if choice == "9":
        ids = ", ".join(server.id for server in MCP_SERVERS)
        out.write(style(f"Servers: {ids}", "muted") + "\n")
        return ["mcp", "config", _ask("Server id: ", input_fn)]
    raise ValueError(f"unknown choice {choice!r}. Type / to search, ? for help.")


def _result_line(style: Style, code: int) -> str:
    role = "ok" if code == 0 else "bad"
    return style.badge(f"exit {code}", role) + "\n"


def run_menu(
    out: TextIO,
    *,
    input_fn: Callable[[str], str] | None = None,
    run: Callable[[list[str]], int] | None = None,
    color: bool | None = None,
) -> int:
    """Loop over the menu until the user quits. `run` executes one CLI argv.

    `input_fn` defaults to the builtin ``input`` resolved at call time (not
    import time), so ``mock.patch("builtins.input")`` works in tests and no
    default-argument capture holds a stale reference. `color` forces colour on
    or off. Left as None, it follows the stream: a terminal gets colour, a
    pipe or StringIO does not.
    """
    if input_fn is None:
        input_fn = input
    style = Style(color_enabled(out) if color is None else color)
    if run is None:
        from .cli import main as cli_main

        def run(argv: list[str]) -> int:
            return cli_main(argv, out=out)

    _render_header(out, style)
    _render_palette(out, style, MENU)
    _render_footer(out, style)

    while True:
        prompt = style("neezy", "accent") + style("> ", "muted")
        try:
            choice = _ask(prompt, input_fn)
        except (EOFError, KeyboardInterrupt):
            out.write("\n" + style("bye", "muted") + "\n")
            return 0

        lowered = choice.lower()
        if lowered in _QUIT_WORDS:
            out.write(style("bye", "muted") + "\n")
            return 0
        if choice in ("", "?"):
            _render_palette(out, style, MENU)
            _render_footer(out, style)
            continue
        if choice.startswith("/"):
            _render_palette(out, style, filter_menu(choice[1:]))
            continue

        try:
            argv = _argv_for(choice, input_fn, out, style)
            if argv is None:
                continue
            out.write(style("$ neezy-cli " + " ".join(argv), "muted") + "\n")
            code = run(argv)
            out.write(_result_line(style, code))
        except (EOFError, KeyboardInterrupt):
            out.write("\n" + style("bye", "muted") + "\n")
            return 0
        except (OSError, RuntimeError, ValueError) as error:
            out.write(style(f"neezy: {error}", "bad") + "\n")
