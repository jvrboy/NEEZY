"""Market catalog, timeframes, and price formatting shared by the UI and CLI."""

from __future__ import annotations

import os
from collections.abc import Iterable

from .catalog import instrument, instruments

APP_ID = 1089

# Deriv's current public market-data endpoint. It needs no app id or login and
# answers the same v3 request format (ticks_history, ticks, active_symbols) as
# the legacy hosts, which sit behind Cloudflare and answer HTTP 520 (origin
# error) from many networks. It is tried first; the legacy hosts remain as
# fallbacks. Set NEEZY_WS_URL to pin one endpoint (a proxy, or a host we do not
# list).
PUBLIC_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
_LEGACY_HOSTS: tuple[str, ...] = (
    "wss://ws.derivws.com/websockets/v3",
    "wss://ws.binaryws.com/websockets/v3",
    "wss://frontend.binaryws.com/websockets/v3",
)


def app_id() -> str:
    """Deriv app id, overridable with NEEZY_APP_ID for a registered app."""
    return os.environ.get("NEEZY_APP_ID", "").strip() or str(APP_ID)


def ws_urls(custom: str = "") -> tuple[str, ...]:
    """Candidate market-data endpoints in preference order.

    NEEZY_WS_URL or the ``custom`` endpoint (from settings) pins a single URL.
    The environment variable wins when both are set.
    """
    override = os.environ.get("NEEZY_WS_URL", "").strip() or custom.strip()
    if override:
        return (override,)
    query = f"?app_id={app_id()}"
    return (PUBLIC_WS_URL, *(host + query for host in _LEGACY_HOSTS))


WS_URL = ws_urls()[0]

# Every instrument Deriv's public endpoint lists (see catalog.py). Lookups,
# validation and the CLI use this full set.
SYMBOLS: dict[str, str] = {item.symbol: item.name for item in instruments().values()}

# Markets streamed live by default. Adding every instrument at once would open
# one subscription per symbol, so the rest are opt-in via settings.
DEFAULT_WATCHLIST: tuple[str, ...] = (
    "frxEURUSD",
    "frxGBPUSD",
    "frxUSDJPY",
    "frxAUDUSD",
    "frxUSDCAD",
    "frxUSDCHF",
    "frxNZDUSD",
    "frxEURGBP",
    "frxEURJPY",
    "frxGBPJPY",
    "R_100",
)


def watchlist(extra: str | Iterable[str] = "") -> dict[str, str]:
    """Default markets plus any extra symbols, in display order.

    ``extra`` is a comma-separated string or an iterable of Deriv symbols. An
    unknown symbol raises ValueError rather than being dropped silently.
    """
    if isinstance(extra, str):
        extra = [part.strip() for part in extra.split(",")]
    symbols = list(DEFAULT_WATCHLIST)
    for symbol in extra:
        if not symbol:
            continue
        if symbol not in SYMBOLS:
            raise ValueError(f"unknown market {symbol!r}")
        if symbol not in symbols:
            symbols.append(symbol)
    return {symbol: SYMBOLS[symbol] for symbol in symbols}


TIMEFRAMES: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def display_name(symbol: str) -> str:
    return SYMBOLS.get(symbol, symbol)


def price_decimals(symbol: str) -> int:
    """Quote precision from the catalogue tick size.

    Unknown symbols fall back to the forex/JPY/synthetic defaults.
    """
    item = instrument(symbol)
    if item is not None:
        return item.decimals
    if "JPY" in symbol:
        return 3
    if symbol.startswith("R_"):
        return 2
    return 5


def pip_size(symbol: str) -> float:
    """Size of one pip, used for stop distances in pips.

    Forex pairs keep the conventional pip (0.0001, or 0.01 for JPY crosses).
    Every other market uses its catalogue tick size, so indices, metals,
    crypto and synthetics are no longer forced into a forex-shaped pip.
    """
    item = instrument(symbol)
    if item is not None and not item.is_forex:
        return item.tick_size
    if "JPY" in symbol or symbol.startswith("R_"):
        return 0.01
    return 0.0001


def format_price(symbol: str, price: float | None) -> str:
    if price is None:
        return "—"
    return f"{price:.{price_decimals(symbol)}f}"


def granularity(timeframe: str) -> int:
    try:
        return TIMEFRAMES[timeframe]
    except KeyError:
        raise ValueError(
            f"Unknown timeframe {timeframe!r}; choose from {', '.join(TIMEFRAMES)}"
        ) from None
