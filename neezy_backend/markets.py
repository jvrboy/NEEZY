"""Market catalog, timeframes, and price formatting shared by the UI and CLI."""

from __future__ import annotations

APP_ID = 1089
WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"

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
