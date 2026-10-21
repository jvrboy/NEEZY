"""Market regime: trend, range, or squeeze, from completed candles.

Pure functions, no I/O. Like `analyze`, the final candle is treated as
in-progress and dropped, so the read never uses a bar that is still forming.

Classification, in order:
1. ADX >= 25 means a trend. +DI above -DI is ``trend_up``, the reverse is
   ``trend_down``.
2. Otherwise, if the current Bollinger bandwidth sits in the bottom 20% of its
   recent history, the market is ``squeeze``: volatility is coiled, but a
   breakout is not confirmed. The percentile is measured against the last
   ``BANDWIDTH_HISTORY`` (100) bars, so a squeeze that has lasted most of that
   window is no longer the bottom 20% and reads as ``range``.
3. Otherwise it is ``range``.

ATR(14) divided by ATR(50) gives a separate volatility label, ``expanding``,
``contracting``, or ``normal``. It does not change the regime.

This is a description of conditions, not a trade signal. The thresholds are
fixed and named so they are easy to review.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from .indicators import adx, atr, bollinger

MIN_CLOSED_CANDLES = 60
ADX_PERIOD = 14
ATR_SHORT = 14
ATR_LONG = 50
BOLLINGER_PERIOD = 20
BANDWIDTH_HISTORY = 100
TREND_ADX = 25.0
SQUEEZE_PERCENTILE = 20.0
EXPANDING_ATR_RATIO = 1.3
CONTRACTING_ATR_RATIO = 0.8

Candle = Sequence[float]


def _closed_ohlc(
    candles: Sequence[Candle],
) -> tuple[list[float], list[float], list[float]]:
    rows = list(candles)[:-1]
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for row in rows:
        if len(row) < 5:
            raise ValueError(
                "each candle must contain timestamp, open, high, low, close"
            )
        high, low, close = float(row[2]), float(row[3]), float(row[4])
        if not all(math.isfinite(value) for value in (high, low, close)):
            raise ValueError("candle values must be finite numbers")
        highs.append(high)
        lows.append(low)
        closes.append(close)
    return highs, lows, closes


def _bandwidth_series(closes: Sequence[float]) -> list[float]:
    widths: list[float] = []
    for end in range(BOLLINGER_PERIOD, len(closes) + 1):
        band = bollinger(closes[:end], BOLLINGER_PERIOD)
        if band is not None:
            widths.append(band["bandwidth"])
    return widths[-BANDWIDTH_HISTORY:]


def _volatility(ratio: float | None) -> str:
    if ratio is None:
        return "unknown"
    if ratio >= EXPANDING_ATR_RATIO:
        return "expanding"
    if ratio <= CONTRACTING_ATR_RATIO:
        return "contracting"
    return "normal"


def _summary(regime: str, adx_value: float, percentile: float) -> str:
    if regime.startswith("trend"):
        direction = "up" if regime == "trend_up" else "down"
        return (
            f"Trend {direction}: ADX {adx_value:.1f}, {direction} directional movement."
        )
    if regime == "squeeze":
        return (
            f"Squeeze: bandwidth is in the bottom {percentile:.0f}% of recent "
            "history. A breakout is possible but not confirmed."
        )
    return f"Range: ADX {adx_value:.1f} and no strong directional movement."


def market_regime(candles: Sequence[Candle]) -> dict[str, Any]:
    """Describe trend, range, or squeeze from (ts, o, h, l, c) rows, oldest first."""
    highs, lows, closes = _closed_ohlc(candles)
    if len(closes) < MIN_CLOSED_CANDLES:
        return {
            "regime": "unknown",
            "summary": (
                f"Need {MIN_CLOSED_CANDLES} closed candles; have {len(closes)}."
            ),
            "candles_used": len(closes),
        }

    directional = adx(highs, lows, closes, ADX_PERIOD)
    widths = _bandwidth_series(closes)
    if directional is None or not widths:
        return {
            "regime": "unknown",
            "summary": "Not enough history for ADX or Bollinger bandwidth.",
            "candles_used": len(closes),
        }

    adx_value = directional["adx"]
    plus_di, minus_di = directional["plus_di"], directional["minus_di"]
    current_width = widths[-1]
    at_or_below = sum(1 for width in widths if width <= current_width)
    percentile = 100.0 * at_or_below / len(widths)

    if adx_value >= TREND_ADX:
        if plus_di > minus_di:
            regime = "trend_up"
        elif minus_di > plus_di:
            regime = "trend_down"
        else:
            regime = "range"
    elif percentile <= SQUEEZE_PERCENTILE:
        regime = "squeeze"
    else:
        regime = "range"

    short_atr = atr(highs, lows, closes, ATR_SHORT)
    long_atr = atr(highs, lows, closes, ATR_LONG)
    ratio = short_atr / long_atr if short_atr is not None and long_atr else None

    return {
        "regime": regime,
        "summary": _summary(regime, adx_value, percentile),
        "adx": round(adx_value, 2),
        "plus_di": round(plus_di, 2),
        "minus_di": round(minus_di, 2),
        "bandwidth": round(current_width, 5),
        "bandwidth_percentile": round(percentile, 1),
        "atr_ratio": None if ratio is None else round(ratio, 3),
        "volatility": _volatility(ratio),
        "candles_used": len(closes),
    }
