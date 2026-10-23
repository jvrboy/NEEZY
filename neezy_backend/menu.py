"""Portable chat-style terminal workspace over the existing NEEZY CLI.

Stdlib only: no curses, mouse, cursor addressing, or screen clearing. The
initial view stays quiet; / reveals a grouped, filterable command palette.
Every action still becomes argv for cli.main and retains its safety gates.
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
from collections.abc import Callable, Sequence
from typing import NamedTuple, TextIO

from .cli_chat import natural_language
from .mcp_catalog import MCP_SERVERS
from .terminal_workspace import (
    WorkspaceState,
    refresh_argv,
    render_tab,
    render_tabs,
)
from .ui_style import Style, color_enabled, panel

LIVE_CONFIRM_PHRASE = "SEND"
InputFn = Callable[[str], str]

# BTOKEN accessibility: logical actions for users who cannot press special
# keys. Typed at the menu prompt, e.g. "bt:quit" instead of CTRL+C.
_BT_TOKEN_ACTIONS = {
    "bt:quit": "quit",
    "bt:ctrl-c": "quit",
    "bt:ctrl-d": "quit",
    "bt:esc": "palette-close",
    "bt:escape": "palette-close",
    "bt:space": "refresh",
    "bt:enter": "refresh",
    "bt:return": "refresh",
    "bt:tab": "next-tab",
    "bt:shift-tab": "prev-tab",
    "bt:del": "refresh",
    "bt:delete": "refresh",
    "bt:backspace": "refresh",
    "bt:pgup": "prev-tab",
    "bt:pgdn": "next-tab",
    "bt:up": "prev-history",
    "bt:down": "next-history",
}


class MenuItem(NamedTuple):
    key: str
    group: str
    label: str
    tone: str = "plain"


MENU: tuple[MenuItem, ...] = (
    MenuItem("1", "System", "Market data connectivity check", "bold"),
    MenuItem("m", "System", "Supported market catalogue", "bold"),
    MenuItem("i", "System", "AI provider and key status", "bold"),
    MenuItem("n", "System", "Numerical microkernel status", "bold"),
    MenuItem("j", "System", "Correctness-checked local kernel benchmark", "bold"),
    MenuItem("s", "Market research", "Scan the watchlist", "bold"),
    MenuItem("a", "Market research", "Analyse one market", "bold"),
    MenuItem("r", "Market research", "Market regime for one symbol", "bold"),
    MenuItem("b", "Market research", "Backtest one market", "bold"),
    MenuItem("c", "Market research", "Closed-candle ASCII chart", "bold"),
    MenuItem("t", "Market research", "Score strategies for one market", "bold"),
    MenuItem("z", "Market research", "Position size calculator (plan only)", "bold"),
    MenuItem("2", "MT5 read-only", "MT5 bridge status", "bold"),
    MenuItem("3", "MT5 read-only", "MT5 account info", "bold"),
    MenuItem("4", "MT5 read-only", "MT5 quote", "bold"),
    MenuItem("5", "MT5 read-only", "MT5 candles", "bold"),
    MenuItem("p", "MT5 read-only", "MT5 preflight checklist", "bold"),
    MenuItem("h", "Local data", "Signal history", "bold"),
    MenuItem("k", "Local data", "Learned knowledge", "bold"),
    MenuItem("d", "Local data", "Database statistics", "bold"),
    MenuItem("6", "MT5 orders", "Order: DRY RUN (never sent)", "ok"),
    MenuItem("7", "MT5 orders", "Order: LIVE (type SEND to confirm)", "warn"),
    MenuItem("o", "Automation", "Lightweight executor status (read-only)", "bold"),
    MenuItem("e", "Automation", "Advanced indicator suite for one market", "bold"),
    MenuItem("w", "Automation", "UTC trading-session clock (offline)", "bold"),
    MenuItem("g", "Automation", "Bot roster status (read-only)", "bold"),
    MenuItem("f", "Automation", "Agent team briefing (offline-friendly)", "bold"),
    MenuItem("v", "Automation", "UI themes and device capabilities", "bold"),
    MenuItem("8", "Automation", "MCP server catalog", "bold"),
    MenuItem("9", "Automation", "MCP client config for one server", "bold"),
    MenuItem("u", "Session", "Keyboard-accessibility (BTOKEN) help", "bold"),
    MenuItem("0", "Session", "Quit", "muted"),
)

_QUIT_WORDS = ("0", "q", "quit", "exit")
_SEARCH_TERMS = {
    "1": "doctor connectivity connection",
    "m": "markets catalog catalogue",
    "i": "ai providers models keys",
    "n": "kernels performance ema macd atr status",
    "j": "kernels benchmark speed performance correctness",
    "s": "scan opportunities",
    "a": "analyze analyse analysis",
    "r": "regime",
    "b": "backtest",
    "c": "chart ohlc candles",
    "t": "strategies",
    "z": "risk position size",
    "2": "mt5 status",
    "3": "mt5 account balance equity",
    "4": "mt5 quote",
    "5": "mt5 candles",
    "p": "mt5 preflight",
    "h": "history signals",
    "k": "knowledge",
    "d": "db database stats",
    "6": "mt5 order dry-run preview",
    "7": "mt5 order live",
    "o": "bot executor status",
    "e": "indicators advanced suite cci aroon ichimoku",
    "w": "sessions clock london tokyo sydney newyork overlap",
    "g": "bots roster scanner scribe guard heartbeat",
    "f": "agents team briefing scout analyst reporter",
    "v": "ui themes demo capabilities devices",
    "u": "btoken accessibility keyboard broken keys stuck",
    "8": "mcp list servers",
    "9": "mcp config",
    "0": "quit exit",
}
_COMMAND_NAMES = {
    "1": "doctor",
    "m": "markets",
    "i": "ai providers",
    "n": "kernels status",
    "j": "kernels benchmark",
    "s": "scan",
    "a": "analyze",
    "r": "regime",
    "b": "backtest",
    "c": "chart",
    "t": "strategies",
    "z": "risk",
    "2": "mt5 status",
    "3": "mt5 account",
    "4": "mt5 quote",
    "5": "mt5 candles",
    "p": "mt5 preflight",
    "h": "history",
    "k": "knowledge",
    "d": "db stats",
    "6": "mt5 order",
    "7": "mt5 order",
    "o": "bot status",
    "e": "indicators",
    "w": "sessions",
    "g": "bots status",
    "f": "agents list",
    "v": "ui capabilities",
    "u": "btoken list",
    "8": "mcp list",
    "9": "mcp config",
    "0": "quit",
}
_COMMAND_WIDTH = max(len(command) for command in _COMMAND_NAMES.values())
_BANNER = (
    "#   #  #####  #####  #####  #   #",
    "##  #  #      #          #   # # ",
    "# # #  ####   ####      #     #  ",
    "#  ##  #      #        #      #  ",
    "#   #  #####  #####  #####    #  ",
)


def _ask(prompt: str, input_fn: InputFn) -> str:
    return input_fn(prompt).strip()


def _ask_default(prompt: str, default: str, input_fn: InputFn) -> str:
    return _ask(prompt, input_fn) or default


def _order_args(input_fn: InputFn) -> list[str]:
    symbol = _ask("Symbol (e.g. frxEURUSD): ", input_fn)
    side = _ask("Side BUY or SELL: ", input_fn).upper()
    volume = _ask("Volume (lots): ", input_fn)
    if not symbol or side not in ("BUY", "SELL") or not volume:
        raise ValueError("symbol, BUY/SELL, and volume are all required")
    return ["mt5", "order", symbol, "--type", side, "--volume", volume]


def filter_menu(query: str, items: tuple[MenuItem, ...] = MENU) -> tuple[MenuItem, ...]:
    """Match all search terms against keys, labels, and command aliases."""
    needle = query.strip().lower()
    if not needle:
        return items
    terms = needle.split()
    return tuple(
        item
        for item in items
        if all(
            term in " ".join((*item[:3], _SEARCH_TERMS.get(item.key, ""))).lower()
            for term in terms
        )
    )


def terminal_width() -> int:
    """A bounded panel width that remains usable on phone-sized terminals."""
    try:
        columns = shutil.get_terminal_size(fallback=(72, 24)).columns
    except (OSError, ValueError):
        columns = 72
    return max(28, min(84, columns))


def runtime_label(
    env: dict[str, str] | None = None, platform: str | None = None
) -> str:
    """Describe common hosts without distro-specific or optional packages."""
    values = os.environ if env is None else env
    system = (sys.platform if platform is None else platform).lower()
    if values.get("TERMUX_VERSION") or "com.termux" in values.get("PREFIX", ""):
        return "Termux / Android"
    if values.get("CODESPACES", "").lower() == "true" or values.get("CODESPACE_NAME"):
        return "GitHub Codespaces"
    if values.get("ANDROID_ROOT") or values.get("ANDROID_DATA"):
        return "Android"
    if system.startswith("win"):
        return "Windows"
    if system == "darwin":
        return "macOS"
    if system.startswith("linux"):
        return "Linux"
    return system or "Terminal"


def _wrapped(
    text: str, width: int, initial: str = "", subsequent: str = ""
) -> list[str]:
    return textwrap.wrap(
        text,
        width=max(12, width),
        initial_indent=initial,
        subsequent_indent=subsequent,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [initial.rstrip()]


def _styled_wrapped(text: str, width: int, style: Style, role: str) -> list[str]:
    return [style(line, role) for line in _wrapped(text, width)]


def _ellipsize(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return text[: max(1, width - 3)] + "..."


def _render_header(out: TextIO, style: Style, width: int) -> None:
    inner = width - 4
    status = (
        ("INTELLIGENT MARKET WORKSPACE", "title"),
        ("LOCAL CLI / NATURAL LANGUAGE", "muted"),
        (f"runtime | {runtime_label()}", "bold"),
        ("orders  | LIVE needs SEND", "ok"),
        ("palette | hidden until /", "muted"),
    )
    body: list[str] = []
    if width >= 72:
        right_width = inner - len(_BANNER[0]) - 3
        for artwork, (text, role) in zip(_BANNER, status, strict=True):
            right = style(_ellipsize(text, right_width), role)
            body.append(style(artwork, "accent") + " " * 3 + right)
    else:
        if width >= 40:
            body.extend(style(line, "accent") for line in _BANNER)
            body.append("")
        for text, role in status:
            body.extend(_styled_wrapped(text, inner, style, role))
    out.write("\n" + panel(style, "NEEZY", body, width=width) + "\n")


def _render_workspace(
    out: TextIO, style: Style, state: WorkspaceState, width: int
) -> None:
    out.write(render_tabs(style, state, width) + "\n")
    out.write(render_tab(style, state, width, runtime=runtime_label()) + "\n")


def _palette_item_lines(item: MenuItem, style: Style, width: int) -> list[str]:
    key, _group, label, tone = item
    command = _COMMAND_NAMES.get(key, key)
    inner = width - 4
    prefix = f"[{key}] "
    if width >= 60:
        command_field = command.ljust(_COMMAND_WIDTH)
        lead = f"{prefix}{command_field} | "
        wrapped = _wrapped(
            label,
            inner,
            initial=lead,
            subsequent=" " * len(lead),
        )
        first = (
            style(prefix, "accent")
            + style(command_field, "bold")
            + style(" | ", "border")
            + style(wrapped[0][len(lead) :], tone)
        )
        return [first, *(style(line, tone) for line in wrapped[1:])]
    lines = [style(prefix, "accent") + style(command, "bold")]
    lines.extend(
        style(line, tone)
        for line in _wrapped(label, inner, initial="    ", subsequent="    ")
    )
    return lines


def _render_palette(
    out: TextIO,
    style: Style,
    items: Sequence[MenuItem],
    *,
    query: str = "",
    width: int = 60,
    empty_note: str = "No matches. Type / alone to see everything.",
) -> None:
    inner = width - 4
    if not items:
        body = _styled_wrapped(empty_note, inner, style, "warn")
        body.extend(
            _styled_wrapped("Use /close to return to chat.", inner, style, "muted")
        )
        out.write("\n" + panel(style, "COMMAND PALETTE", body, width=width) + "\n")
        return

    groups: dict[str, list[MenuItem]] = {}
    for item in items:
        groups.setdefault(item.group, []).append(item)
    lines: list[str] = []
    if query:
        summary = f"filter / {query} | {len(items)} matching tools"
        lines.extend(_styled_wrapped(summary, inner, style, "muted"))
    for group, group_items in groups.items():
        if lines:
            lines.append("")
        lines.append(style(f"{group.upper()} / {len(group_items)}", "title"))
        for item in group_items:
            lines.extend(_palette_item_lines(item, style, width))
    lines.append("")
    hint = "key + Enter selects | /text searches | /close hides"
    lines.extend(_styled_wrapped(hint, inner, style, "muted"))
    out.write("\n" + panel(style, "COMMAND PALETTE", lines, width=width) + "\n")


def _render_message(
    out: TextIO,
    style: Style,
    message: str,
    width: int,
    *,
    title: str = "NEEZY",
) -> None:
    lines: list[str] = []
    for source_line in message.splitlines():
        lines.extend(_wrapped(source_line, width - 4))
    out.write(panel(style, title, lines, width=width) + "\n")


def _render_help(out: TextIO, style: Style, width: int) -> None:
    _render_message(
        out, style, natural_language("help").message, width, title="HOW TO CHAT"
    )


def _result_line(style: Style, code: int) -> str:
    role = "ok" if code == 0 else "bad"
    return style.badge(f"exit {code}", role) + "\n"


def _write_error(out: TextIO, style: Style, error: object, width: int) -> None:
    for line in _styled_wrapped(f"neezy: {error}", width, style, "bad"):
        out.write(line + "\n")


def _mt5_confirm_send(input_fn: InputFn, out: TextIO, style: Style) -> list[str] | None:
    argv = _order_args(input_fn)
    prompt = f"Type {LIVE_CONFIRM_PHRASE} to send a live order: "
    if _ask(prompt, input_fn) != LIVE_CONFIRM_PHRASE:
        out.write(style("Cancelled. No order sent.", "warn") + "\n")
        return None
    argv.append("--confirm")
    return argv


def _mcp_config_argv(input_fn: InputFn, out: TextIO, style: Style) -> list[str] | None:
    ids = ", ".join(server.id for server in MCP_SERVERS)
    out.write(style(f"Servers: {ids}", "muted") + "\n")
    return ["mcp", "config", _ask("Server id: ", input_fn)]


def _analyze_args(input_fn: InputFn) -> list[str]:
    symbol = _ask("Symbol: ", input_fn)
    timeframe = _ask_default("Timeframe [5m]: ", "5m", input_fn)
    if not symbol:
        raise ValueError("symbol is required")
    return ["analyze", symbol, "-t", timeframe]


def _chart_args(input_fn: InputFn) -> list[str]:
    symbol = _ask("Symbol: ", input_fn)
    timeframe = _ask_default("Timeframe [5m]: ", "5m", input_fn)
    if not symbol:
        raise ValueError("symbol is required")
    return ["chart", symbol, "-t", timeframe]


def _strategy_args(input_fn: InputFn) -> list[str]:
    symbol = _ask("Symbol (blank for all): ", input_fn)
    return ["strategies"] + ([symbol] if symbol else [])


def _position_args(input_fn: InputFn) -> list[str]:
    symbol = _ask("Symbol: ", input_fn)
    balance = _ask("Account balance: ", input_fn)
    entry = _ask("Entry price: ", input_fn)
    stop = _ask("Stop price: ", input_fn)
    risk = _ask_default("Risk percent [1]: ", "1", input_fn)
    if not all((symbol, balance, entry, stop)):
        raise ValueError("symbol, balance, entry, and stop are all required")
    return [
        "risk",
        symbol,
        "--balance",
        balance,
        "--entry",
        entry,
        "--stop",
        stop,
        "--risk",
        risk,
    ]


# Palette key -> existing CLI argv. None means cancelled before command dispatch.
ARGV_BUILDERS: dict[str, Callable[[InputFn, TextIO, Style], list[str] | None]] = {
    "1": lambda input_fn, out, style: ["doctor"],
    "m": lambda input_fn, out, style: ["markets"],
    "i": lambda input_fn, out, style: ["ai", "providers"],
    "n": lambda input_fn, out, style: ["kernels", "status"],
    "j": lambda input_fn, out, style: ["kernels", "benchmark"],
    "s": lambda input_fn, out, style: ["scan"],
    "a": lambda input_fn, out, style: _analyze_args(input_fn),
    "r": lambda input_fn, out, style: [
        "regime",
        _ask("Symbol (e.g. frxEURUSD): ", input_fn),
    ],
    "b": lambda input_fn, out, style: [
        "backtest",
        _ask("Symbol (e.g. frxEURUSD): ", input_fn),
    ],
    "c": lambda input_fn, out, style: _chart_args(input_fn),
    "t": lambda input_fn, out, style: _strategy_args(input_fn),
    "z": lambda input_fn, out, style: _position_args(input_fn),
    "p": lambda input_fn, out, style: ["mt5", "preflight"],
    "2": lambda input_fn, out, style: ["mt5", "status"],
    "3": lambda input_fn, out, style: ["mt5", "account"],
    "4": lambda input_fn, out, style: [
        "mt5",
        "quote",
        _ask("Symbol: ", input_fn),
    ],
    "5": lambda input_fn, out, style: [
        "mt5",
        "candles",
        _ask("Symbol: ", input_fn),
    ],
    "6": lambda input_fn, out, style: [*_order_args(input_fn), "--dry-run"],
    "7": _mt5_confirm_send,
    "o": lambda input_fn, out, style: ["bot", "status"],
    "e": lambda input_fn, out, style: [
        "indicators",
        _ask("Symbol (e.g. frxEURUSD): ", input_fn),
    ],
    "w": lambda input_fn, out, style: ["sessions"],
    "g": lambda input_fn, out, style: ["bots", "status"],
    "f": lambda input_fn, out, style: [
        "agents",
        "run",
        _ask("Goal for the team (e.g. review EURUSD): ", input_fn),
    ],
    "v": lambda input_fn, out, style: ["ui", "capabilities"],
    "u": lambda input_fn, out, style: ["btoken", "list"],
    "h": lambda input_fn, out, style: ["history"],
    "k": lambda input_fn, out, style: ["knowledge"],
    "d": lambda input_fn, out, style: ["db", "stats"],
    "8": lambda input_fn, out, style: ["mcp", "list"],
    "9": _mcp_config_argv,
}


def _argv_for(
    choice: str, input_fn: InputFn, out: TextIO, style: Style
) -> list[str] | None:
    builder = ARGV_BUILDERS.get(choice)
    if builder is None:
        raise ValueError(f"unknown choice {choice!r}. Type / to search, ? for help.")
    return builder(input_fn, out, style)


def _label_for(choice: str) -> str:
    return next((item.label for item in MENU if item.key == choice), "Request")


def _natural_label(argv: list[str]) -> str:
    if argv[:2] == ["ai", "chat"]:
        return "AI assistant"
    if argv[:2] == ["ai", "providers"]:
        return "AI provider status"
    if argv[:2] == ["db", "stats"]:
        return "Local database statistics"
    if argv[:2] == ["kernels", "status"]:
        return "Numerical microkernel status"
    if argv[:2] == ["kernels", "benchmark"]:
        return "Correctness-checked local kernel benchmark"
    if argv and argv[0] == "mt5":
        return "MT5 read-only request"
    labels = {
        "analyze": "Market analysis",
        "scan": "Market scan",
        "backtest": "Backtest research",
        "chart": "Closed-candle chart",
        "bot": "Loopback executor status",
        "regime": "Market regime",
        "strategies": "Strategy scores",
        "markets": "Market catalogue",
        "doctor": "Connectivity check",
        "history": "Signal history",
        "knowledge": "Learned knowledge",
        "datasets": "Knowledge datasets",
    }
    return labels.get(argv[0] if argv else "", "Your request")


def _run_btoken(
    token: str,
    state: WorkspaceState,
    out: TextIO,
    style: Style,
    width: int,
) -> None:
    """Execute one ``bt:`` accessibility token inside the menu loop.

    Quitting is handled by the caller so the return path stays simple;
    every other logical key maps to an existing workspace action.
    """
    action = _BT_TOKEN_ACTIONS.get(token)
    if action is None:
        from .btoken import BTOKENS

        known = ", ".join(sorted(BTOKENS)[:8])
        _write_error(
            out,
            style,
            f"unknown btoken {token!r}; some tokens: {known}",
            width,
        )
        return
    if action == "palette-close":
        _render_workspace(out, style, state, width)
        return
    if action == "next-tab":
        state.cycle_tab(1)
        _render_workspace(out, style, state, width)
        return
    if action == "prev-tab":
        state.cycle_tab(-1)
        _render_workspace(out, style, state, width)
        return
    # refresh / clear-line / history lookups: re-show the current view.
    _render_workspace(out, style, state, width)


def run_menu(
    out: TextIO,
    *,
    input_fn: InputFn | None = None,
    run: Callable[[list[str]], int] | None = None,
    color: bool | None = None,
) -> int:
    """Run the tabbed chat workspace until quit, EOF, or Ctrl+C.

    ``run`` is the only execution seam. The real default is ``cli.main``;
    this module never sends an order or calls a broker itself.
    """
    interactive_input = False
    if input_fn is None:
        interactive_input = sys.stdin.isatty()
        input_fn = input
    style = Style(color_enabled(out) if color is None else color)
    if run is None:
        from .cli import main as cli_main

        def run(argv: list[str]) -> int:
            return cli_main(argv, out=out)

    def execute(argv: list[str], label: str) -> None:
        for line in _wrapped(f"[working] {label}", width):
            out.write(style(line, "muted") + "\n")
        code = run(argv)
        out.write(_result_line(style, code))

    state = WorkspaceState()
    width = state.view_width(terminal_width())
    _render_header(out, style, width)
    _render_workspace(out, style, state, width)

    while True:
        prompt = style(state.tab.lower(), "accent") + style(" you > ", "muted")
        try:
            choice = _ask(prompt, input_fn)
        except (EOFError, KeyboardInterrupt):
            out.write("\n" + style("bye", "muted") + "\n")
            return 0
        except OSError as error:
            _write_error(out, style, error, width)
            return 1

        # Piped stdin does not echo a newline after the prompt. Keep the next
        # panel off that prompt line; real TTY input already supplies one.
        if not interactive_input:
            out.write("\n")
        width = state.view_width(terminal_width())
        lowered = choice.lower()
        if lowered in _QUIT_WORDS:
            out.write(style("bye", "muted") + "\n")
            return 0
        if lowered.startswith("bt:"):
            if lowered in ("bt:quit", "bt:ctrl-c", "bt:ctrl-d"):
                out.write(style("bye", "muted") + "\n")
                return 0
            _run_btoken(lowered, state, out, style, width)
            continue
        if choice.startswith("/"):
            query = choice[1:].strip()
            if query.lower() in {"close", "hide"}:
                _render_workspace(out, style, state, width)
                continue
            if query.lower() in _QUIT_WORDS:
                out.write(style("bye", "muted") + "\n")
                return 0
            _render_palette(out, style, filter_menu(query), query=query, width=width)
            continue
        if not choice:
            _render_workspace(out, style, state, width)
            continue
        if choice == "?":
            _render_help(out, style, width)
            continue

        if choice.startswith(":"):
            try:
                command, _separator, argument = choice[1:].strip().partition(" ")
                command = command.lower()
                argument = argument.strip()
                if command == "tab" and argument:
                    command, argument = argument, ""
                if command in _QUIT_WORDS:
                    out.write(style("bye", "muted") + "\n")
                    return 0
                if command in {"next", "prev"}:
                    state.cycle_tab(1 if command == "next" else -1)
                    _render_workspace(out, style, state, width)
                    continue
                if command in {"settings", "subtab"} and argument:
                    state.tab = "SETTINGS"
                    if argument.lower() in {"next", "prev"}:
                        state.cycle_settings_tab(
                            1 if argument.lower() == "next" else -1
                        )
                    elif not state.select_settings_tab(argument):
                        raise ValueError(
                            "use :settings next, :settings prev, or a settings tab name"
                        )
                    _render_workspace(out, style, state, width)
                    continue
                if command == "set":
                    name, separator, value = argument.partition(" ")
                    if not separator or not name or not value.strip():
                        raise ValueError("use :set name value")
                    if name.lower() in {"color", "colour"}:
                        color_value = value.strip().lower()
                        if color_value not in {"on", "off"}:
                            raise ValueError("use :set color on or :set color off")
                        style.enabled = (
                            color_enabled(out) if color_value == "on" else False
                        )
                        state.settings_tab = "APPEARANCE"
                    else:
                        state.set_option(name, value)
                    state.tab = "SETTINGS"
                    width = state.view_width(terminal_width())
                    _render_workspace(out, style, state, width)
                    continue
                if command == "tabs" or (not argument and state.select_tab(command)):
                    _render_workspace(out, style, state, width)
                    continue
                if command == "symbol":
                    if not state.select_symbol(argument):
                        raise ValueError(f"unknown market {argument!r}")
                    _render_workspace(out, style, state, width)
                    continue
                if command in {"timeframe", "tf"}:
                    if not state.select_timeframe(argument):
                        raise ValueError(f"unsupported timeframe {argument!r}")
                    _render_workspace(out, style, state, width)
                    continue
                if command == "find":
                    state.tab = "SYMBOLS"
                    state.symbol_filter = argument
                    _render_workspace(out, style, state, width)
                    continue
                if command == "color":
                    if argument not in {"on", "off"}:
                        raise ValueError("use :color on or :color off")
                    style.enabled = color_enabled(out) if argument == "on" else False
                    state.tab = "SETTINGS"
                    state.settings_tab = "APPEARANCE"
                    _render_workspace(out, style, state, width)
                    continue
                if command == "reset":
                    state.reset_preferences()
                    if color is None:
                        style.enabled = color_enabled(out)
                    state.tab = "SETTINGS"
                    width = state.view_width(terminal_width())
                    _render_workspace(out, style, state, width)
                    continue
                if command == "scan" and argument.lower() == "all":
                    state.tab = "SIGNALS"
                    argv = ["scan", "-t", state.timeframe]
                    if state.scan_count is not None:
                        argv.extend(["-n", str(state.scan_count)])
                    execute(argv, "Watchlist signal scan")
                    continue
                if command == "refresh":
                    if state.tab == "SYMBOLS":
                        state.symbol_filter = ""
                    action = refresh_argv(state, width)
                    if action is None:
                        _render_workspace(out, style, state, width)
                        continue
                    argv, label = action
                    execute(argv, label)
                    continue
                raise ValueError(
                    f"unknown tab command {command!r}; use :next, :prev, or :tabs"
                )
            except (EOFError, KeyboardInterrupt):
                out.write("\n" + style("bye", "muted") + "\n")
                return 0
            except (OSError, RuntimeError, ValueError) as error:
                _write_error(out, style, error, width)
                continue

        try:
            if state.tab == "SYMBOLS" and choice not in ARGV_BUILDERS:
                if not state.select_symbol(choice):
                    state.symbol_filter = choice
                _render_workspace(out, style, state, width)
                continue
            if lowered in {"settings", "open settings", "show settings", "preferences"}:
                state.tab = "SETTINGS"
                state.settings_tab = "GENERAL"
                _render_workspace(out, style, state, width)
                continue
            if lowered.startswith(("open ", "show ")) and lowered.endswith(" settings"):
                candidate = lowered[5:-8].strip()
                if state.select_settings_tab(candidate):
                    state.tab = "SETTINGS"
                    _render_workspace(out, style, state, width)
                    continue
            label = _label_for(choice)
            if choice in ARGV_BUILDERS:
                argv = _argv_for(choice, input_fn, out, style)
            else:
                route = natural_language(choice)
                if route.message:
                    _render_message(out, style, route.message, width)
                    continue
                argv = state.apply_ai_preferences(list(route.argv))
                label = _natural_label(argv)
            if argv is None:
                continue
            execute(argv, label)
        except (EOFError, KeyboardInterrupt):
            out.write("\n" + style("bye", "muted") + "\n")
            return 0
        except (OSError, RuntimeError, ValueError) as error:
            _write_error(out, style, error, width)


__all__ = ["MENU", "MenuItem", "filter_menu", "run_menu", "runtime_label"]
