"""Trend and channel indicators beyond the core EMA/RSI/ATR/MACD set.

Everything here is vector-free (pure Python), aligned bar-for-bar with the
input candles, and uses ``None`` during warm-up so callers never read a
half-formed value. Educational indicator maths, not investment advice.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Candle = Sequence[float]


def _check_series(*series: Sequence[float]) -> int:
    lengths = {len(item) for item in series}
    if len(lengths) != 1:
        raise ValueError("price series must all have the same length")
    return lengths.pop()


def true_range_series(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    """Wilder's true range for every bar (first bar uses high-low only)."""
    _check_series(highs, lows, closes)
    if not closes:
        return []
    ranges = [float(highs[0] - lows[0])]
    ranges.extend(
        max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        for i in range(1, len(closes))
    )
    return ranges


def atr_series(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float | None]:
    """Wilder ATR aligned with the bars (None until ``period`` bars exist)."""
    if period < 1:
        raise ValueError("period must be positive")
    ranges = true_range_series(highs, lows, closes)
    result: list[float | None] = [None] * len(ranges)
    if len(ranges) < period:
        return result
    average = sum(ranges[:period]) / period
    result[period - 1] = average
    for index in range(period, len(ranges)):
        average = (average * (period - 1) + ranges[index]) / period
        result[index] = average
    return result


def supertrend(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 10,
    multiplier: float = 3.0,
) -> list[dict[str, float | int | None]]:
    """Supertrend bands and direction for every bar.

    Each entry is ``{"supertrend", "direction", "upper", "lower", "atr"}`` where
    ``direction`` is 1 (uptrend), -1 (downtrend) or 0 during warm-up. The line
    flips when a close crosses the active band, which is the classic Supertrend
    rule and the basis of the ``SUPERTREND`` strategy.
    """
    if period < 1:
        raise ValueError("period must be positive")
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    _check_series(highs, lows, closes)
    atr_values = atr_series(highs, lows, closes, period)
    entries: list[dict[str, float | int | None]] = [
        {"supertrend": None, "direction": 0, "upper": None, "lower": None, "atr": None}
        for _ in closes
    ]
    final_upper = final_lower = None
    direction = 0
    for index, close in enumerate(closes):
        average = atr_values[index]
        if average is None:
            continue
        midpoint = (highs[index] + lows[index]) / 2.0
        basic_upper = midpoint + multiplier * average
        basic_lower = midpoint - multiplier * average
        if final_upper is None or final_lower is None:
            final_upper, final_lower = basic_upper, basic_lower
            direction = 1 if close >= basic_lower else -1
        else:
            previous_close = closes[index - 1]
            final_upper = (
                basic_upper
                if basic_upper < final_upper or previous_close > final_upper
                else final_upper
            )
            final_lower = (
                basic_lower
                if basic_lower > final_lower or previous_close < final_lower
                else final_lower
            )
            if direction > 0 and close < final_lower:
                direction = -1
            elif direction < 0 and close > final_upper:
                direction = 1
        entries[index] = {
            "supertrend": final_lower if direction > 0 else final_upper,
            "direction": direction,
            "upper": final_upper,
            "lower": final_lower,
            "atr": average,
        }
    return entries


def donchian(
    highs: Sequence[float], lows: Sequence[float], period: int = 20
) -> list[dict[str, float | None]]:
    """Donchian channel from the previous ``period`` bars (breakout levels)."""
    if period < 2:
        raise ValueError("period must be at least 2")
    _check_series(highs, lows)
    result: list[dict[str, float | None]] = []
    for index in range(len(highs)):
        if index < period:
            result.append({"upper": None, "lower": None, "mid": None})
            continue
        window_high = max(highs[index - period : index])
        window_low = min(lows[index - period : index])
        result.append(
            {
                "upper": window_high,
                "lower": window_low,
                "mid": (window_high + window_low) / 2.0,
            }
        )
    return result


def keltner(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 20,
    multiplier: float = 2.0,
) -> list[dict[str, float | None]]:
    """Keltner channel: EMA of close ± ``multiplier`` x ATR."""
    if period < 1:
        raise ValueError("period must be positive")
    if multiplier <= 0:
        raise ValueError("multiplier must be positive")
    _check_series(highs, lows, closes)
    from .indicators import ema

    middles = ema(closes, period)
    averages = atr_series(highs, lows, closes, period)
    result: list[dict[str, float | None]] = []
    for index, middle in enumerate(middles):
        average = averages[index]
        if average is None:
            result.append({"upper": None, "lower": None, "mid": middle})
            continue
        result.append(
            {
                "upper": middle + multiplier * average,
                "lower": middle - multiplier * average,
                "mid": middle,
            }
        )
    return result


def williams_r(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float | None]:
    """Williams %R in the -100..0 range (oversold below -80)."""
    if period < 1:
        raise ValueError("period must be positive")
    _check_series(highs, lows, closes)
    result: list[float | None] = []
    for index in range(len(closes)):
        if index + 1 < period:
            result.append(None)
            continue
        highest = max(highs[index - period + 1 : index + 1])
        lowest = min(lows[index - period + 1 : index + 1])
        span = highest - lowest
        result.append(
            -100.0 if span == 0 else (highest - closes[index]) / span * -100.0
        )
    return result


def cci(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 20,
) -> list[float | None]:
    """Commodity Channel Index using mean absolute deviation."""
    if period < 1:
        raise ValueError("period must be positive")
    _check_series(highs, lows, closes)
    typical = [
        (high + low + close) / 3.0
        for high, low, close in zip(highs, lows, closes, strict=True)
    ]
    result: list[float | None] = []
    for index in range(len(typical)):
        if index + 1 < period:
            result.append(None)
            continue
        window = typical[index - period + 1 : index + 1]
        mean = sum(window) / period
        deviation = sum(abs(value - mean) for value in window) / period
        if deviation == 0:
            result.append(0.0)
        else:
            result.append((typical[index] - mean) / (0.015 * deviation))
    return result


def rate_of_change(values: Sequence[float], period: int = 10) -> list[float | None]:
    """Percentage change over ``period`` bars."""
    if period < 1:
        raise ValueError("period must be positive")
    result: list[float | None] = []
    for index in range(len(values)):
        if index < period or values[index - period] == 0:
            result.append(None)
            continue
        previous = values[index - period]
        result.append((values[index] - previous) / previous * 100.0)
    return result


def linear_regression_slope(
    values: Sequence[float], period: int = 20
) -> list[float | None]:
    """Least-squares slope of the last ``period`` values, in price per bar."""
    if period < 2:
        raise ValueError("period must be at least 2")
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < period:
            result.append(None)
            continue
        window = list(values[index - period + 1 : index + 1])
        mean_x = (period - 1) / 2.0
        mean_y = sum(window) / period
        denominator = sum((x - mean_x) ** 2 for x in range(period))
        numerator = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(window))
        result.append(numerator / denominator)
    return result


def stoch_rsi(
    closes: Sequence[float], period: int = 14, smooth: int = 3
) -> list[float | None]:
    """Stochastic RSI (0..100), smoothed with an SMA of ``smooth``."""
    from .indicators import rsi_series

    series = rsi_series(closes, period)
    raw: list[float | None] = []
    for index, value in enumerate(series):
        window = series[max(0, index - period + 1) : index + 1]
        known = [item for item in window if item is not None]
        if value is None or len(known) < period:
            raw.append(None)
            continue
        lowest, highest = min(known), max(known)
        raw.append(
            50.0 if highest == lowest else (value - lowest) / (highest - lowest) * 100.0
        )
    result: list[float | None] = []
    for index, value in enumerate(raw):
        window = raw[max(0, index - smooth + 1) : index + 1]
        known = [item for item in window if item is not None]
        result.append(
            None if value is None or len(known) < smooth else sum(known) / smooth
        )
    return result


def trend_summary(
    candles: Sequence[Candle], period: int = 10, multiplier: float = 3.0
) -> dict:
    """Compact Supertrend read for the UI, CLI, and AI context."""
    if not candles:
        return {"direction": 0, "label": "unknown", "line": None, "bars_since_flip": 0}
    highs = [row[2] for row in candles]
    lows = [row[3] for row in candles]
    closes = [row[4] for row in candles]
    entries = supertrend(highs, lows, closes, period, multiplier)
    known = [entry for entry in entries if entry["direction"]]
    if not known:
        return {"direction": 0, "label": "unknown", "line": None, "bars_since_flip": 0}
    direction = int(known[-1]["direction"])
    flips = 0
    for entry in reversed(known):
        if int(entry["direction"]) != direction:
            break
        flips += 1
    last = closes[-1]
    line = known[-1]["supertrend"]
    distance = None
    if isinstance(line, (int, float)) and last:
        distance = (last - line) / last * 100.0
    return {
        "direction": direction,
        "label": "uptrend" if direction > 0 else "downtrend",
        "line": line,
        "distance_pct": round(distance, 4) if distance is not None else None,
        "bars_since_flip": flips,
        "atr": known[-1]["atr"],
        "period": period,
        "multiplier": multiplier,
    }


def channel_breakout(candles: Sequence[Candle], period: int = 20) -> str | None:
    """``"breakout"`` / ``"breakdown"`` when the last close clears the channel."""
    if len(candles) < period + 1:
        return None
    highs = [row[2] for row in candles]
    lows = [row[3] for row in candles]
    channels = donchian(highs, lows, period)
    latest = channels[-1]
    close = candles[-1][4]
    if latest["upper"] is not None and close > float(latest["upper"]):
        return "breakout"
    if latest["lower"] is not None and close < float(latest["lower"]):
        return "breakdown"
    return None


def band_squeeze(
    candles: Sequence[Candle], period: int = 20
) -> dict[str, float | bool]:
    """Bollinger bandwidth percentile: low readings precede expansion."""
    if len(candles) < period + 5:
        return {"squeeze": False, "percentile": 1.0, "bandwidth": 0.0}
    closes = [row[4] for row in candles]
    widths: list[float] = []
    for end in range(period, len(closes) + 1):
        window = closes[end - period : end]
        mean = sum(window) / period
        deviation = math.sqrt(sum((value - mean) ** 2 for value in window) / period)
        widths.append(4.0 * deviation / mean if mean else 0.0)
    widths = widths[-120:]
    if len(widths) < 5:
        return {"squeeze": False, "percentile": 1.0, "bandwidth": 0.0}
    latest = widths[-1]
    rank = sum(1 for width in widths if width <= latest) / len(widths)
    return {
        "squeeze": rank <= 0.2,
        "percentile": round(rank, 3),
        "bandwidth": latest,
    }


def finite(value: float | None) -> bool:
    """True only for a real, finite number (guards UI and JSON output)."""
    return isinstance(value, (int, float)) and math.isfinite(float(value))


__all__ = [
    "atr_series",
    "band_squeeze",
    "cci",
    "channel_breakout",
    "donchian",
    "finite",
    "keltner",
    "linear_regression_slope",
    "rate_of_change",
    "stoch_rsi",
    "supertrend",
    "trend_summary",
    "true_range_series",
    "williams_r",
]
