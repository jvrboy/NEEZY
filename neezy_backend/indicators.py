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


def _rsi_value(average_gain: float, average_loss: float) -> float:
    if average_gain == 0 and average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    if average_gain == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + average_gain / average_loss)


def rsi_series(closes: Sequence[float], period: int = 14) -> list[float | None]:
    """Wilder RSI for every bar; ``None`` until the first value is formed."""
    if period < 1:
        raise ValueError("period must be positive")
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result
    gains = losses = 0.0
    for before, after in pairwise(closes[: period + 1]):
        delta = after - before
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    average_gain, average_loss = gains / period, losses / period
    result[period] = _rsi_value(average_gain, average_loss)
    for index in range(period + 1, len(closes)):
        delta = closes[index] - closes[index - 1]
        average_gain = (average_gain * (period - 1) + max(delta, 0.0)) / period
        average_loss = (average_loss * (period - 1) + max(-delta, 0.0)) / period
        result[index] = _rsi_value(average_gain, average_loss)
    return result


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    """Current Wilder RSI, or ``None`` while the series is still too short."""
    series = rsi_series(closes, period)
    return series[-1] if series else None


def macd_histogram_series(
    closes: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> list[float]:
    """MACD histogram aligned with ``closes`` (line minus signal line)."""
    if fast < 1 or slow < 1 or signal < 1:
        raise ValueError("MACD periods must be positive")
    if fast >= slow:
        raise ValueError("fast period must be shorter than slow period")
    if not closes:
        return []
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line = [a - b for a, b in zip(fast_ema, slow_ema, strict=True)]
    signal_line = ema(line, signal)
    return [a - b for a, b in zip(line, signal_line, strict=True)]


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


def sma(values: Sequence[float], period: int) -> list[float | None]:
    """Simple moving average aligned with ``values`` (None until warmed up)."""
    if period < 1:
        raise ValueError("period must be positive")
    result: list[float | None] = []
    window_sum = 0.0
    for index, value in enumerate(values):
        window_sum += float(value)
        if index >= period:
            window_sum -= float(values[index - period])
        result.append(window_sum / period if index >= period - 1 else None)
    return result


def bollinger(
    closes: Sequence[float], period: int = 20, deviations: float = 2.0
) -> dict[str, float] | None:
    """Latest Bollinger Bands with %B and bandwidth, using population deviation."""
    if period < 2:
        raise ValueError("period must be at least 2")
    if deviations <= 0:
        raise ValueError("deviations must be positive")
    if len(closes) < period:
        return None
    window = [float(value) for value in closes[-period:]]
    middle = sum(window) / period
    deviation = math.sqrt(sum((value - middle) ** 2 for value in window) / period)
    upper, lower = middle + deviations * deviation, middle - deviations * deviation
    width = upper - lower
    return {
        "upper": upper,
        "middle": middle,
        "lower": lower,
        "percent_b": (window[-1] - lower) / width if width else 0.5,
        "bandwidth": width / middle if middle else 0.0,
    }


def stochastic(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
    smooth: int = 3,
) -> dict[str, float] | None:
    """Latest stochastic oscillator %K and its ``smooth``-period %D."""
    if period < 1 or smooth < 1:
        raise ValueError("period and smooth must be positive")
    if len(highs) != len(lows) or len(lows) != len(closes):
        return None
    if len(closes) < period + smooth - 1:
        return None
    k_values = []
    for end in range(len(closes) - smooth + 1, len(closes) + 1):
        high = max(highs[end - period : end])
        low = min(lows[end - period : end])
        span = high - low
        k_values.append((closes[end - 1] - low) / span * 100.0 if span else 50.0)
    return {"k": k_values[-1], "d": sum(k_values) / len(k_values)}


def adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> dict[str, float] | None:
    """Wilder's Average Directional Index with +DI and -DI."""
    if period < 1:
        raise ValueError("period must be positive")
    if len(highs) != len(lows) or len(lows) != len(closes):
        return None
    if len(closes) < 2 * period + 1:
        return None
    true_ranges, plus_dm, minus_dm = [], [], []
    for i in range(1, len(closes)):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        true_ranges.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    smoothed_tr = sum(true_ranges[:period])
    smoothed_plus = sum(plus_dm[:period])
    smoothed_minus = sum(minus_dm[:period])

    def directional() -> tuple[float, float, float]:
        if not smoothed_tr:
            return 0.0, 0.0, 0.0
        plus_di = 100.0 * smoothed_plus / smoothed_tr
        minus_di = 100.0 * smoothed_minus / smoothed_tr
        total = plus_di + minus_di
        return (
            plus_di,
            minus_di,
            100.0 * abs(plus_di - minus_di) / total if total else 0.0,
        )

    plus_di, minus_di, dx = directional()
    dx_values = [dx]
    for i in range(period, len(true_ranges)):
        smoothed_tr = smoothed_tr - smoothed_tr / period + true_ranges[i]
        smoothed_plus = smoothed_plus - smoothed_plus / period + plus_dm[i]
        smoothed_minus = smoothed_minus - smoothed_minus / period + minus_dm[i]
        plus_di, minus_di, dx = directional()
        dx_values.append(dx)
    average = sum(dx_values[:period]) / period
    for value in dx_values[period:]:
        average = (average * (period - 1) + value) / period
    return {"adx": average, "plus_di": plus_di, "minus_di": minus_di}


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
    bands = bollinger(closes)
    stoch = stochastic(highs, lows, closes)
    directional = adx(highs, lows, closes)
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
        "bollinger": bands,
        "stochastic": stoch,
        "adx": directional,
        "regime": _regime(directional, bands),
        "closes": closes,
        "closed_candles": len(closed),
    }


def _regime(
    directional: dict[str, float] | None, bands: dict[str, float] | None
) -> str:
    """Describe market conditions; informational only, it does not affect score."""
    if directional is None:
        return "Unknown"
    if directional["adx"] >= 25:
        return "Trending"
    if bands is not None and bands["bandwidth"] < 0.002:
        return "Squeeze"
    return "Ranging"
