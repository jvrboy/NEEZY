"""Candlestick pattern detection and support/resistance levels.

Candles are five-tuples of (epoch, open, high, low, close). Patterns are
educational descriptions of recent price action, not trade recommendations.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

Candle = Sequence[float]


def _body(candle: Candle) -> float:
    return abs(candle[4] - candle[1])


def _range(candle: Candle) -> float:
    return candle[2] - candle[3]


def detect_patterns(candles: Sequence[Candle]) -> list[dict[str, str]]:
    """Return patterns formed by the most recent one or two candles."""
    patterns: list[dict[str, str]] = []
    if not candles:
        return patterns
    last = candles[-1]
    _epoch, open_, high, low, close = (float(value) for value in last[:5])
    span = high - low
    if span <= 0:
        return patterns
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    if body <= span * 0.1:
        patterns.append({"name": "Doji", "bias": "Neutral"})
    elif lower_wick >= body * 2 and upper_wick <= body:
        patterns.append({"name": "Hammer", "bias": "Bullish"})
    elif upper_wick >= body * 2 and lower_wick <= body:
        patterns.append({"name": "Shooting star", "bias": "Bearish"})
    if body >= span * 0.9:
        patterns.append(
            {
                "name": "Bullish marubozu" if close > open_ else "Bearish marubozu",
                "bias": "Bullish" if close > open_ else "Bearish",
            }
        )
    if len(candles) >= 2:
        prior = candles[-2]
        prior_open, prior_close = float(prior[1]), float(prior[4])
        if (
            prior_close < prior_open
            and close > open_
            and open_ <= prior_close
            and close >= prior_open
            and body > _body(prior)
        ):
            patterns.append({"name": "Bullish engulfing", "bias": "Bullish"})
        elif (
            prior_close > prior_open
            and close < open_
            and open_ >= prior_close
            and close <= prior_open
            and body > _body(prior)
        ):
            patterns.append({"name": "Bearish engulfing", "bias": "Bearish"})
        if high <= float(prior[2]) and low >= float(prior[3]) and _range(prior) > 0:
            patterns.append({"name": "Inside bar", "bias": "Neutral"})
    return patterns


def pivot_points(candle: Candle) -> dict[str, float]:
    """Classic floor-trader pivots computed from one completed candle."""
    high, low, close = float(candle[2]), float(candle[3]), float(candle[4])
    pivot = (high + low + close) / 3.0
    return {
        "r2": pivot + (high - low),
        "r1": 2 * pivot - low,
        "pivot": pivot,
        "s1": 2 * pivot - high,
        "s2": pivot - (high - low),
    }


def swing_levels(
    candles: Sequence[Candle], window: int = 3, max_levels: int = 3
) -> dict[str, list[float]]:
    """Nearest swing-high resistance and swing-low support around the last close.

    A swing high is a candle whose high is the maximum of ``window`` candles on
    each side (fractal definition); swing lows are defined symmetrically.
    """
    if window < 1 or max_levels < 1:
        raise ValueError("window and max_levels must be positive")
    result: dict[str, list[float]] = {"support": [], "resistance": []}
    if len(candles) < window * 2 + 1:
        return result
    last_close = float(candles[-1][4])
    highs = [float(candle[2]) for candle in candles]
    lows = [float(candle[3]) for candle in candles]
    resistance, support = set(), set()
    for i in range(window, len(candles) - window):
        neighbourhood = slice(i - window, i + window + 1)
        if highs[i] == max(highs[neighbourhood]) and highs[i] > last_close:
            resistance.add(highs[i])
        if lows[i] == min(lows[neighbourhood]) and lows[i] < last_close:
            support.add(lows[i])
    result["resistance"] = sorted(resistance)[:max_levels]
    result["support"] = sorted(support, reverse=True)[:max_levels]
    return result


def price_action_summary(candles: Sequence[Candle]) -> dict[str, Any]:
    """Patterns, pivots, and swing levels for the latest *closed* candle set."""
    if len(candles) < 2:
        return {"patterns": [], "pivots": None, "levels": swing_levels(candles)}
    return {
        "patterns": detect_patterns(candles),
        "pivots": pivot_points(candles[-1]),
        "levels": swing_levels(candles),
    }
