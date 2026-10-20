"""Validated technical indicators and closed-candle signal analysis.

These calculations are educational summaries, not investment recommendations.
Candles are five-tuples of (epoch, open, high, low, close).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise
from typing import Any

Candle = Sequence[float]


def ema(values: Sequence[float], period: int) -> list[float]:
    if period < 1:
        raise ValueError("period must be positive")
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(float(value) * alpha + result[-1] * (1.0 - alpha))
    return result


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    if period < 1:
        raise ValueError("period must be positive")
    if len(closes) <= period:
        return None
    gains = losses = 0.0
    for before, after in pairwise(closes[: period + 1]):
        delta = after - before
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    average_gain, average_loss = gains / period, losses / period
    for before, after in pairwise(closes[period:]):
        delta = after - before
        average_gain = (average_gain * (period - 1) + max(delta, 0.0)) / period
        average_loss = (average_loss * (period - 1) + max(-delta, 0.0)) / period
    if average_gain == 0 and average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    if average_gain == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + average_gain / average_loss)


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    if period < 1:
        raise ValueError("period must be positive")
    if not closes or len(highs) != len(lows) or len(lows) != len(closes):
        return None
    ranges = [highs[0] - lows[0]]
    ranges.extend(
        max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        for i in range(1, len(closes))
    )
    initial = ranges[:period]
    average = sum(initial) / len(initial)
    for current in ranges[period:]:
        average = (average * (period - 1) + current) / period
    return average


def _validated_candles(
    candles: Sequence[Candle],
) -> list[tuple[float, float, float, float, float]]:
    clean: list[tuple[float, float, float, float, float]] = []
    for row in candles:
        if len(row) < 5:
            raise ValueError(
                "each candle must contain timestamp, open, high, low, close"
            )
        values = tuple(float(value) for value in row[:5])
        if not all(math.isfinite(value) for value in values):
            raise ValueError("candle values must be finite numbers")
        _timestamp, open_, high, low, close = values
        if (
            min(open_, high, low, close) <= 0
            or high < max(open_, close)
            or low > min(open_, close)
            or high < low
        ):
            raise ValueError("candle OHLC values are inconsistent")
        clean.append(values)
    return clean


def analyze(candles: Sequence[Candle]) -> dict[str, Any] | None:
    """Analyze only completed candles; the final row is treated as in-progress."""
    validated = _validated_candles(candles)
    closed = validated[:-1]
    if len(closed) < 60:
        return None
    highs = [row[2] for row in closed]
    lows = [row[3] for row in closed]
    closes = [row[4] for row in closed]
    ema9, ema21, ema50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    macd_line = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26), strict=True)]
    macd_hist = [
        line - signal for line, signal in zip(macd_line, ema(macd_line, 9), strict=True)
    ]
    current_rsi = rsi(closes)
    current_atr = atr(highs, lows, closes)
    last = closes[-1]

    score = 0
    reasons: list[str] = []
    ema_direction = 1 if ema9[-1] > ema21[-1] else -1 if ema9[-1] < ema21[-1] else 0
    score += ema_direction
    reasons.append(
        "EMA 9 above EMA 21"
        if ema_direction > 0
        else "EMA 9 below EMA 21"
        if ema_direction < 0
        else "EMA 9 aligned with EMA 21"
    )
    price_direction = 1 if last > ema50[-1] else -1 if last < ema50[-1] else 0
    score += price_direction
    reasons.append(
        "Price above EMA 50"
        if price_direction > 0
        else "Price below EMA 50"
        if price_direction < 0
        else "Price aligned with EMA 50"
    )
    ema_bullish = ema_direction > 0
    above_ema50 = price_direction > 0
    if current_rsi is not None:
        if current_rsi < 35:
            score += 1
            reasons.append(f"RSI {current_rsi:.1f} oversold")
        elif current_rsi > 65:
            score -= 1
            reasons.append(f"RSI {current_rsi:.1f} overbought")
        else:
            reasons.append(f"RSI {current_rsi:.1f} neutral")
    macd_direction = 1 if macd_hist[-1] > 0 else -1 if macd_hist[-1] < 0 else 0
    score += macd_direction
    reasons.append(
        "MACD momentum positive"
        if macd_direction > 0
        else "MACD momentum negative"
        if macd_direction < 0
        else "MACD momentum flat"
    )
    signal = (
        "STRONG BUY"
        if score >= 4
        else "BUY"
        if score >= 2
        else "STRONG SELL"
        if score <= -4
        else "SELL"
        if score <= -2
        else "NEUTRAL"
    )
    return {
        "signal": signal,
        "score": score,
        "rsi": current_rsi,
        "atr": current_atr,
        "atr_pct": (current_atr / last * 100.0)
        if current_atr is not None and last
        else None,
        "macd_histogram": macd_hist[-1],
        "trend": "Bullish"
        if ema_bullish and above_ema50
        else "Bearish"
        if not ema_bullish and not above_ema50
        else "Mixed",
        "why": reasons,
        "ema9": ema9[-1],
        "ema21": ema21[-1],
        "ema50": ema50[-1],
        "closes": closes,
        "closed_candles": len(closed),
    }
