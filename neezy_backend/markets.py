"""Market catalog, timeframes, and price formatting shared by the UI and CLI."""

from __future__ import annotations

import os

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

SYMBOLS: dict[str, str] = {
    "frxEURUSD": "EUR/USD",
    "frxGBPUSD": "GBP/USD",
    "frxUSDJPY": "USD/JPY",
    "frxAUDUSD": "AUD/USD",
    "frxUSDCAD": "USD/CAD",
    "frxUSDCHF": "USD/CHF",
    "frxNZDUSD": "NZD/USD",
    "frxEURGBP": "EUR/GBP",
    "frxEURJPY": "EUR/JPY",
    "frxGBPJPY": "GBP/JPY",
    "R_100": "Volatility 100",
}

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
    """Quote precision: JPY crosses use 3 decimals, synthetic indices 2, else 5."""
    if "JPY" in symbol:
        return 3
    if symbol.startswith("R_"):
        return 2
    return 5


def pip_size(symbol: str) -> float:
    """Size of one pip (JPY crosses 0.01, synthetic indices 0.01, else 0.0001)."""
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
