"""Natural-language routing for the interactive NEEZY terminal workspace.

The router only creates existing CLI argv. It deliberately has no order route:
trade intent returns guidance to use the explicit, confirmation-gated palette.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .markets import SYMBOLS, TIMEFRAMES


@dataclass(frozen=True, slots=True)
class ChatRoute:
    """Either an existing CLI command or a local message for the workspace."""

    argv: tuple[str, ...] = ()
    message: str = ""


_HELP = """Ask in plain language, for example:
  scan the market on 15m
  analyse EURUSD on 5m
  show the MT5 account
  backtest GBPUSD on 1h
  chart EURUSD on 15m
  check numerical kernel status
General questions go to your configured AI provider. Type / for hidden tools.
Tabs: :next / :prev, or :chat :symbols :chart :signals :history :bot :settings.
Use :refresh to load the active tab. Settings has six sub-tabs: use
:settings next, :set width 44, :set provider gemini, or :set name value."""

_TRADE_GUIDANCE = (
    "Order actions are not available through natural language. Type / and choose "
    "DRY RUN or LIVE explicitly; LIVE still requires the typed SEND confirmation."
)

_ALIASES = {
    "gold": "frxXAUUSD",
    "silver": "frxXAGUSD",
    "bitcoin": "cryBTCUSD",
    "ethereum": "cryETHUSD",
    "volatility 100": "R_100",
    "volatility 75": "R_75",
    "volatility 50": "R_50",
    "volatility 25": "R_25",
    "volatility 10": "R_10",
    "nasdaq": "OTC_NDX",
    "us 100": "OTC_NDX",
    "us 500": "OTC_SPC",
    "us 30": "OTC_DJI",
    "dow jones": "OTC_DJI",
}

_SYMBOL_KEYS = {key.upper(): key for key in SYMBOLS}
_TIMEFRAME_WORDS = {
    "minute": "1m",
    "hourly": "1h",
    "hour": "1h",
    "daily": "1d",
    "day": "1d",
}
_TRADE_INTENT = re.compile(
    r"^(?:please\s+)?(?:buy|sell|place|open|close|execute|send)\b|"
    r"\b(?:place|send|execute)\s+(?:a\s+)?(?:live\s+)?(?:order|trade)\b",
    re.IGNORECASE,
)
_EDUCATIONAL_QUESTION = re.compile(
    r"^(?:please\s+)?(?:what(?:\s+is|\s+are|'s)|why|how|explain|define|"
    r"tell\s+me\s+about)\b",
    re.IGNORECASE,
)


def extract_symbol(text: str) -> str | None:
    """Resolve a catalog symbol, forex pair, or small set of friendly aliases."""
    lowered = text.lower()
    for alias, symbol in _ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            return symbol
    for token in re.findall(r"[A-Za-z0-9_]+", text):
        candidate = _SYMBOL_KEYS.get(token.upper())
        if candidate:
            return candidate
    for first, second in re.findall(r"\b([A-Za-z]{3})/?([A-Za-z]{3})\b", text):
        candidate = _SYMBOL_KEYS.get(f"FRX{first}{second}".upper())
        if candidate:
            return candidate
    return None


def extract_timeframe(text: str) -> str | None:
    lowered = text.lower()
    for timeframe in TIMEFRAMES:
        if re.search(rf"\b{re.escape(timeframe)}\b", lowered):
            return timeframe
    for word, timeframe in _TIMEFRAME_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            return timeframe
    match = re.search(r"\b(1|5|15|30)\s*(?:minute|min|minutes)\b", lowered)
    if match:
        return f"{match.group(1)}m"
    match = re.search(r"\b(1|4)\s*(?:hour|hours|hr|hrs)\b", lowered)
    if match:
        return f"{match.group(1)}h"
    return None


def _with_timeframe(argv: list[str], timeframe: str | None) -> tuple[str, ...]:
    if timeframe:
        argv.extend(["-t", timeframe])
    return tuple(argv)


def _ai_route(prompt: str) -> ChatRoute:
    lowered = prompt.lower()
    provider = next(
        (
            name
            for name in ("gemini", "grok", "openrouter", "ollama")
            if re.search(rf"\b{name}\b", lowered)
        ),
        None,
    )
    argv = ["ai", "chat", prompt]
    if provider:
        argv.extend(["--provider", provider])
    return ChatRoute(argv=tuple(argv))


def _need_symbol(action: str) -> ChatRoute:
    examples = {
        "analyse": "analyse EURUSD on 15m",
        "backtest": "backtest EURUSD on 1h",
        "chart": "chart EURUSD on 15m",
        "classify": "show the regime for EURUSD",
        "quote": "show the MT5 quote for EURUSD",
        "read": "show MT5 candles for EURUSD on 5m",
    }
    example = examples.get(action, f"{action} EURUSD on 15m")
    return ChatRoute(message=f"Which market should I {action}? For example: {example}.")


def natural_language(text: str) -> ChatRoute:
    """Translate one human request to existing CLI argv or local guidance."""
    prompt = text.strip()
    lowered = " ".join(prompt.lower().split())
    if not lowered:
        return ChatRoute(message="Type a question or request, or / for hidden tools.")
    if lowered in {"help", "what can you do", "what can you do?"}:
        return ChatRoute(message=_HELP)
    mt5_data_question = "mt5" in lowered and any(
        word in lowered
        for word in ("status", "account", "balance", "equity", "quote", "candle")
    )
    if _EDUCATIONAL_QUESTION.match(prompt) and not mt5_data_question:
        return _ai_route(prompt)
    if _TRADE_INTENT.search(prompt):
        return ChatRoute(message=_TRADE_GUIDANCE)

    symbol = extract_symbol(prompt)
    timeframe = extract_timeframe(prompt)
    if any(word in lowered for word in ("connectivity", "connection", "doctor")):
        return ChatRoute(argv=("doctor",))
    if "preflight" in lowered:
        return ChatRoute(argv=("mt5", "preflight"))
    if "mt5" in lowered and any(
        word in lowered for word in ("status", "bridge", "terminal")
    ):
        return ChatRoute(argv=("mt5", "status"))
    if "mt5" in lowered and any(
        word in lowered for word in ("account", "balance", "equity")
    ):
        return ChatRoute(argv=("mt5", "account"))
    if "mt5" in lowered and "quote" in lowered:
        if not symbol:
            return _need_symbol("quote")
        return ChatRoute(argv=("mt5", "quote", symbol))
    if "mt5" in lowered and "candle" in lowered:
        if not symbol:
            return _need_symbol("read")
        return ChatRoute(argv=_with_timeframe(["mt5", "candles", symbol], timeframe))
    if "status" in lowered and ("executor" in lowered or "bot" in lowered):
        return ChatRoute(argv=("bot", "status"))
    if "kernel" in lowered:
        if any(word in lowered for word in ("benchmark", "speed test", "time them")):
            return ChatRoute(argv=("kernels", "benchmark"))
        return ChatRoute(argv=("kernels", "status"))

    if any(
        phrase in lowered
        for phrase in ("supported markets", "market catalogue", "market catalog")
    ) or re.match(r"^(?:list|show)(?: me)?(?: the)? markets\b", lowered):
        return ChatRoute(argv=("markets",))
    if "provider" in lowered and "ai" in lowered:
        return ChatRoute(argv=("ai", "providers"))
    if "database" in lowered and any(
        word in lowered for word in ("stat", "size", "summary")
    ):
        return ChatRoute(argv=("db", "stats"))
    if "knowledge" in lowered:
        return ChatRoute(argv=("knowledge",))
    if "dataset" in lowered:
        return ChatRoute(argv=("datasets",))
    if "history" in lowered or "recent signals" in lowered:
        return ChatRoute(argv=("history",))

    if "chart" in lowered:
        if not symbol:
            return _need_symbol("chart")
        return ChatRoute(argv=_with_timeframe(["chart", symbol], timeframe))
    if any(word in lowered for word in ("backtest", "back-test")):
        if not symbol:
            return _need_symbol("backtest")
        return ChatRoute(argv=_with_timeframe(["backtest", symbol], timeframe))
    if any(word in lowered for word in ("analyse", "analyze", "analysis")):
        if not symbol:
            return _need_symbol("analyse")
        return ChatRoute(argv=_with_timeframe(["analyze", symbol], timeframe))
    if "regime" in lowered:
        if not symbol:
            return _need_symbol("classify")
        return ChatRoute(argv=_with_timeframe(["regime", symbol], timeframe))
    if "strateg" in lowered:
        argv = ["strategies"] + ([symbol] if symbol else [])
        return ChatRoute(argv=_with_timeframe(argv, timeframe))
    if any(word in lowered for word in ("scan", "opportunities", "rank the market")):
        argv = ["scan"] + ([symbol] if symbol else [])
        return ChatRoute(argv=_with_timeframe(argv, timeframe))

    return _ai_route(prompt)
