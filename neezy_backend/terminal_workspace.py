"""Dependency-free tab state and renderers for the NEEZY terminal workspace."""

from __future__ import annotations

import math
import textwrap
from dataclasses import dataclass
from functools import lru_cache

from .catalog import instrument
from .cli_chat import extract_symbol
from .markets import DEFAULT_WATCHLIST, SYMBOLS, TIMEFRAMES
from .microkernels import kernel_status
from .ui_style import Style, panel

TABS = ("CHAT", "SYMBOLS", "CHART", "SIGNALS", "HISTORY", "BOT", "SETTINGS")
SETTINGS_TABS = ("GENERAL", "APPEARANCE", "DATA", "AI", "PERFORMANCE", "SAFETY")
_TAB_ALIASES = {name.lower(): name for name in TABS}
_TAB_ALIASES.update({"home": "CHAT", "markets": "SYMBOLS", "config": "SETTINGS"})
_SETTINGS_ALIASES = {name.lower(): name for name in SETTINGS_TABS}
_SETTINGS_ALIASES.update({"ui": "APPEARANCE", "kernels": "PERFORMANCE"})
_AI_PROVIDERS = ("openrouter", "gemini", "grok", "ollama")


@dataclass(slots=True)
class WorkspaceState:
    tab: str = "CHAT"
    symbol: str = "frxEURUSD"
    timeframe: str = "5m"
    symbol_filter: str = ""
    settings_tab: str = "GENERAL"
    width_limit: int | None = None
    hints: bool = True
    chart_count: int = 120
    chart_height: int = 14
    history_limit: int = 12
    scan_count: int | None = None
    ai_provider: str = "default"
    ai_temperature: float | None = None
    ai_max_tokens: int | None = None
    bot_timeout: float | None = None

    def select_tab(self, name: str) -> bool:
        selected = _TAB_ALIASES.get(name.strip().lower())
        if selected is None:
            return False
        self.tab = selected
        return True

    def cycle_tab(self, step: int) -> None:
        index = TABS.index(self.tab)
        self.tab = TABS[(index + step) % len(TABS)]

    def select_settings_tab(self, name: str) -> bool:
        selected = _SETTINGS_ALIASES.get(name.strip().lower())
        if selected is None:
            return False
        self.settings_tab = selected
        return True

    def cycle_settings_tab(self, step: int) -> None:
        index = SETTINGS_TABS.index(self.settings_tab)
        self.settings_tab = SETTINGS_TABS[(index + step) % len(SETTINGS_TABS)]

    def select_symbol(self, text: str) -> bool:
        symbol = extract_symbol(text)
        if symbol is None:
            return False
        self.symbol = symbol
        self.symbol_filter = ""
        return True

    def select_timeframe(self, text: str) -> bool:
        timeframe = text.strip().lower()
        if timeframe not in TIMEFRAMES:
            return False
        self.timeframe = timeframe
        return True

    def view_width(self, available: int) -> int:
        """Keep output inside the real terminal and an optional lower user cap."""
        return max(28, min(available, self.width_limit or available))

    def reset_preferences(self) -> None:
        self.symbol = "frxEURUSD"
        self.timeframe = "5m"
        self.symbol_filter = ""
        self.settings_tab = "GENERAL"
        self.width_limit = None
        self.hints = True
        self.chart_count = 120
        self.chart_height = 14
        self.history_limit = 12
        self.scan_count = None
        self.ai_provider = "default"
        self.ai_temperature = None
        self.ai_max_tokens = None
        self.bot_timeout = None

    @staticmethod
    def _boolean(value: str) -> bool:
        lowered = value.strip().lower()
        if lowered in {"on", "true", "yes", "1"}:
            return True
        if lowered in {"off", "false", "no", "0"}:
            return False
        raise ValueError("expected on or off")

    @staticmethod
    def _integer(value: str, name: str, low: int, high: int) -> int:
        try:
            parsed = int(value)
        except ValueError as error:
            raise ValueError(f"{name} must be an integer") from error
        if not low <= parsed <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        return parsed

    @staticmethod
    def _number(value: str, name: str, low: float, high: float) -> float:
        try:
            parsed = float(value)
        except ValueError as error:
            raise ValueError(f"{name} must be a number") from error
        if not math.isfinite(parsed) or not low <= parsed <= high:
            raise ValueError(f"{name} must be between {low:g} and {high:g}")
        return parsed

    def set_option(self, name: str, value: str) -> None:
        """Set one validated session option; never changes trading safeguards."""
        key = name.strip().lower().replace("_", "-")
        value = value.strip()
        if not value:
            raise ValueError(f"{key} needs a value")
        if key == "symbol":
            if not self.select_symbol(value):
                raise ValueError(f"unknown market {value!r}")
            return
        if key in {"timeframe", "tf"}:
            if not self.select_timeframe(value):
                raise ValueError(f"unsupported timeframe {value!r}")
            return
        if key in {"width", "width-limit"}:
            self.width_limit = (
                None
                if value.lower() in {"auto", "default"}
                else self._integer(value, "width", 28, 84)
            )
            return
        if key == "hints":
            self.hints = self._boolean(value)
            return
        if key in {"chart-count", "candles"}:
            self.chart_count = self._integer(value, "chart-count", 20, 2_000)
            return
        if key == "chart-height":
            self.chart_height = self._integer(value, "chart-height", 6, 30)
            return
        if key == "history-limit":
            self.history_limit = self._integer(value, "history-limit", 1, 100)
            return
        if key == "scan-count":
            self.scan_count = (
                None
                if value.lower() in {"auto", "default"}
                else self._integer(value, "scan-count", 60, 5_000)
            )
            return
        if key in {"provider", "ai-provider"}:
            provider = value.lower()
            if provider != "default" and provider not in _AI_PROVIDERS:
                raise ValueError(
                    "provider must be default, openrouter, gemini, grok, or ollama"
                )
            self.ai_provider = provider
            return
        if key in {"temperature", "ai-temperature"}:
            self.ai_temperature = (
                None
                if value.lower() == "default"
                else self._number(value, "temperature", 0.0, 2.0)
            )
            return
        if key in {"max-tokens", "ai-max-tokens"}:
            self.ai_max_tokens = (
                None
                if value.lower() == "default"
                else self._integer(value, "max-tokens", 32, 4_000)
            )
            return
        if key == "bot-timeout":
            self.bot_timeout = (
                None
                if value.lower() == "default"
                else self._number(value, "bot-timeout", 0.1, 5.0)
            )
            return
        raise ValueError(f"unknown setting {name!r}")

    def apply_ai_preferences(self, argv: list[str]) -> list[str]:
        """Apply session overrides without overriding an explicit chat request."""
        if argv[:2] != ["ai", "chat"]:
            return argv
        result = list(argv)
        if self.ai_provider != "default" and "--provider" not in result:
            result.extend(["--provider", self.ai_provider])
        if self.ai_temperature is not None and "--temperature" not in result:
            result.extend(["--temperature", f"{self.ai_temperature:g}"])
        if self.ai_max_tokens is not None and "--max-tokens" not in result:
            result.extend(["--max-tokens", str(self.ai_max_tokens)])
        return result


def _wrapped(text: str, width: int, indent: str = "") -> list[str]:
    return textwrap.wrap(
        text,
        width=max(12, width),
        initial_indent=indent,
        subsequent_indent=indent,
        break_long_words=True,
        break_on_hyphens=False,
    ) or [indent.rstrip()]


def _styled_lines(text: str, width: int, style: Style, role: str) -> list[str]:
    return [style(line, role) for line in _wrapped(text, width)]


def _tab_lines(
    names: tuple[str, ...], active_name: str, style: Style, width: int
) -> list[str]:
    inner = width - 4
    rows: list[list[tuple[str, bool]]] = []
    current: list[tuple[str, bool]] = []
    current_width = 0
    for name in names:
        active = name == active_name
        text = f"[{name}]" if active else name
        extra = len(text) + (2 if current else 0)
        if current and current_width + extra > inner:
            rows.append(current)
            current = []
            current_width = 0
            extra = len(text)
        current.append((text, active))
        current_width += extra
    if current:
        rows.append(current)
    return [
        "  ".join(style(text, "accent" if active else "muted") for text, active in row)
        for row in rows
    ]


def render_tabs(style: Style, state: WorkspaceState, width: int) -> str:
    """Render a wrapping tab bar; brackets identify the active tab."""
    return panel(
        style,
        "TABS / :next :prev",
        _tab_lines(TABS, state.tab, style, width),
        width=width,
    )


@lru_cache(maxsize=128)
def _symbol_rows_cached(needle: str) -> tuple[tuple[str, str, str], ...]:
    symbols = DEFAULT_WATCHLIST if not needle else tuple(SYMBOLS)
    rows = []
    for symbol in symbols:
        info = instrument(symbol)
        haystack = f"{symbol} {info.name} {info.market} {info.submarket}".lower()
        if needle and not all(term in haystack for term in needle.split()):
            continue
        rows.append((symbol, info.name, info.market))
    return tuple(rows[:18])


def symbol_rows(query: str = "") -> list[tuple[str, str, str]]:
    """Return real catalog rows, defaulting to the existing watchlist."""
    return list(_symbol_rows_cached(query.strip().lower()))


def _context(state: WorkspaceState) -> str:
    return f"context | {SYMBOLS[state.symbol]} / {state.timeframe}"


def _chat_tab(style: Style, state: WorkspaceState, width: int) -> list[str]:
    inner = width - 4
    lines = _styled_lines(
        "Ready. Write naturally and press Enter.", inner, style, "bold"
    )
    if state.hints:
        lines.extend(
            _styled_lines(
                "/ opens hidden commands. ? shows examples.", inner, style, "muted"
            )
        )
    lines.extend(_styled_lines(_context(state), inner, style, "muted"))
    return lines


def _symbols_tab(style: Style, state: WorkspaceState, width: int) -> list[str]:
    inner = width - 4
    lines = _styled_lines(_context(state), inner, style, "bold")
    if state.symbol_filter:
        lines.extend(
            _styled_lines(f"filter | {state.symbol_filter}", inner, style, "muted")
        )
    rows = symbol_rows(state.symbol_filter)
    if not rows:
        lines.extend(
            _styled_lines("No matching catalog symbols.", inner, style, "warn")
        )
    for symbol, name, market in rows:
        marker = "*" if symbol == state.symbol else " "
        text = f"{marker} {symbol} | {name} | {market}"
        role = "accent" if symbol == state.symbol else "muted"
        lines.extend(_styled_lines(text, inner, style, role))
    if state.hints:
        lines.append("")
        lines.extend(
            _styled_lines(
                "Type a symbol or name to select/search. "
                ":refresh restores the watchlist.",
                inner,
                style,
                "muted",
            )
        )
    return lines


def _settings_lines(
    style: Style, state: WorkspaceState, width: int, runtime: str, color: bool
) -> list[str]:
    inner = width - 4
    lines = _tab_lines(SETTINGS_TABS, state.settings_tab, style, width)
    lines.append("")
    values: list[str] = []
    commands = ""
    if state.settings_tab == "GENERAL":
        values = [
            "session | changes last for this CLI session",
            f"symbol | {state.symbol}",
            f"timeframe | {state.timeframe}",
            f"hints | {'on' if state.hints else 'off'}",
            f"runtime | {runtime}",
        ]
        commands = ":settings next | :set name value | :reset"
    elif state.settings_tab == "APPEARANCE":
        values = [
            f"colour | {'enabled' if color else 'plain'}",
            f"actual panel width | {width}",
            f"width limit | {state.width_limit or 'auto'}",
            f"hints | {'on' if state.hints else 'off'}",
            "layout | responsive ASCII panels",
        ]
        commands = ":set width auto|44 | :set hints off | :color on/off"
    elif state.settings_tab == "DATA":
        values = [
            f"chart candles | {state.chart_count}",
            f"chart height | {state.chart_height}",
            f"scan candles | {state.scan_count or 'CLI default'}",
            f"history limit | {state.history_limit}",
            "closed candles | enforced",
        ]
        commands = ":set chart-count 240 | :set chart-height 18 | :set scan-count 500"
    elif state.settings_tab == "AI":
        temperature = (
            "default" if state.ai_temperature is None else f"{state.ai_temperature:g}"
        )
        values = [
            f"provider | {state.ai_provider}",
            f"temperature | {temperature}",
            f"max tokens | {state.ai_max_tokens or 'default'}",
            "keys | protected existing key store; never displayed here",
            "explicit provider in a chat request wins",
        ]
        commands = ":set provider gemini | :set temperature 0.7 | :set max-tokens 900"
    elif state.settings_tab == "PERFORMANCE":
        status = kernel_status()
        cache = _symbol_rows_cached.cache_info()
        values = [
            f"kernel backend | {status['backend']}",
            "fused kernels | " + ", ".join(status["kernels"]),
            "native dependency | none",
            f"symbol cache | {cache.hits} hits / {cache.misses} misses; max 128",
            f"bot timeout | {state.bot_timeout or 'default'}",
        ]
        commands = (
            ":refresh checks kernels | CLI: kernels benchmark | :set bot-timeout 1.5"
        )
    elif state.settings_tab == "SAFETY":
        values = [
            "natural-language orders | blocked",
            "live orders | explicit palette + typed SEND",
            "agent / MCP | no live orders",
            "BOT controls | read-only",
            "closed candles | enforced",
        ]
        commands = "These protections cannot be changed in SETTINGS."
    for value in values:
        role = "warn" if state.settings_tab == "SAFETY" else "muted"
        lines.extend(_styled_lines(value, inner, style, role))
    if commands:
        lines.append("")
        lines.extend(
            _styled_lines(
                commands,
                inner,
                style,
                "warn" if state.settings_tab == "SAFETY" else "accent",
            )
        )
    return lines


def _information_tab(
    style: Style, state: WorkspaceState, width: int, runtime: str, color: bool
) -> tuple[str, list[str]]:
    inner = width - 4
    lines: list[str] = []
    if state.tab == "CHART":
        lines = _styled_lines("Closed-candle ASCII OHLC chart.", inner, style, "bold")
        lines.extend(_styled_lines(_context(state), inner, style, "muted"))
        if state.hints:
            lines.extend(
                _styled_lines(
                    ":refresh fetches real candles. Nothing is simulated.",
                    inner,
                    style,
                    "muted",
                )
            )
    elif state.tab == "SIGNALS":
        lines = _styled_lines(
            "Ranked signals from the existing analysis engine.", inner, style, "bold"
        )
        lines.extend(_styled_lines(_context(state), inner, style, "muted"))
        if state.hints:
            lines.extend(
                _styled_lines(
                    ":refresh scans this symbol. :scan all scans the watchlist.",
                    inner,
                    style,
                    "muted",
                )
            )
        lines.extend(
            _styled_lines(
                "Educational only; not financial advice.", inner, style, "warn"
            )
        )
    elif state.tab == "HISTORY":
        lines = _styled_lines("Local signal-transition history.", inner, style, "bold")
        lines.extend(
            _styled_lines(
                f":refresh loads the latest {state.history_limit} records. "
                "Empty history stays empty.",
                inner,
                style,
                "muted",
            )
        )
    elif state.tab == "BOT":
        lines = _styled_lines(
            "Read-only lightweight executor monitor.", inner, style, "bold"
        )
        if state.hints:
            lines.extend(
                _styled_lines(
                    ":refresh queries loopback status. No start, stop, promotion, "
                    "or order controls.",
                    inner,
                    style,
                    "muted",
                )
            )
    elif state.tab == "SETTINGS":
        lines = _settings_lines(style, state, width, runtime, color)
        return f"SETTINGS / {state.settings_tab}", lines
    return state.tab, lines


def render_tab(
    style: Style,
    state: WorkspaceState,
    width: int,
    *,
    runtime: str,
) -> str:
    if state.tab == "CHAT":
        title, lines = "CHAT BOX", _chat_tab(style, state, width)
    elif state.tab == "SYMBOLS":
        title, lines = "SYMBOLS", _symbols_tab(style, state, width)
    else:
        title, lines = _information_tab(style, state, width, runtime, style.enabled)
    return panel(style, title, lines, width=width)


def refresh_argv(state: WorkspaceState, width: int) -> tuple[list[str], str] | None:
    """Existing read-only CLI action for the active tab, if it has one."""
    if state.tab == "CHART":
        return (
            [
                "chart",
                state.symbol,
                "-t",
                state.timeframe,
                "-n",
                str(state.chart_count),
                "--width",
                str(width),
                "--height",
                str(state.chart_height),
            ],
            "Closed-candle chart",
        )
    if state.tab == "SIGNALS":
        argv = ["scan", state.symbol, "-t", state.timeframe]
        if state.scan_count is not None:
            argv.extend(["-n", str(state.scan_count)])
        return (argv, "Selected-symbol signal scan")
    if state.tab == "HISTORY":
        return (
            ["history", "--limit", str(state.history_limit)],
            "Local signal history",
        )
    if state.tab == "BOT":
        argv = ["bot", "status"]
        if state.bot_timeout is not None:
            argv.extend(["--timeout", f"{state.bot_timeout:g}"])
        return (argv, "Loopback executor status")
    if state.tab == "SETTINGS" and state.settings_tab == "PERFORMANCE":
        return (["kernels", "status"], "Numerical microkernel status")
    return None
