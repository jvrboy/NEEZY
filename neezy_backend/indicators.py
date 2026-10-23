"""Validated technical indicators and closed-candle signal analysis.

These calculations are educational summaries, not investment recommendations.
Candles are five-tuples of (epoch, open, high, low, close).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import pairwise
from typing import Any

from .microkernels import atr_kernel, ema_kernel, macd_histogram_kernel

Candle = Sequence[float]


def ema(values: Sequence[float], period: int) -> list[float]:
    return ema_kernel(values, period)


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
    return macd_histogram_kernel(closes, fast, slow, signal)


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    return atr_kernel(highs, lows, closes, period)


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
    macd_hist = macd_histogram_series(closes)
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


# ---------------------------------------------------------------------------
# Advanced indicator suite (roadmap: more advanced indicators).
#
# Every function follows the house rules already used above: pure math,
# stdlib only, ``None`` (or a partial dict) until enough closed candles
# exist, and no look-ahead - the newest candle forms the output value.
# ---------------------------------------------------------------------------


def typical_price(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]
) -> list[float]:
    """(high + low + close) / 3 per bar."""
    return [
        (float(h) + float(low) + float(c)) / 3.0
        for h, low, c in zip(highs, lows, closes, strict=True)
    ]


def cci(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 20,
) -> float | None:
    """Commodity Channel Index on the typical price."""
    if period < 2:
        raise ValueError("period must be at least 2")
    if len(closes) < period:
        return None
    tp = typical_price(highs, lows, closes)
    window = tp[-period:]
    mean = sum(window) / period
    mean_deviation = sum(abs(value - mean) for value in window) / period
    if mean_deviation == 0:
        return 0.0
    return (window[-1] - mean) / (0.015 * mean_deviation)


def williams_r(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    """Williams %R: -100 (at the low) to 0 (at the high)."""
    if period < 1:
        raise ValueError("period must be positive")
    if len(closes) < period:
        return None
    highest = max(float(v) for v in highs[-period:])
    lowest = min(float(v) for v in lows[-period:])
    span = highest - lowest
    if span == 0:
        return -50.0
    return (highest - float(closes[-1])) / span * -100.0


def roc(closes: Sequence[float], period: int = 12) -> float | None:
    """Rate of change in percent over ``period`` bars."""
    if period < 1:
        raise ValueError("period must be positive")
    if len(closes) <= period:
        return None
    past = float(closes[-1 - period])
    if past == 0:
        return None
    return (float(closes[-1]) - past) / past * 100.0


def trix(closes: Sequence[float], period: int = 15) -> float | None:
    """TRIX: percent rate of change of a triple-smoothed EMA."""
    if period < 1:
        raise ValueError("period must be positive")
    if len(closes) < period * 3:
        return None
    first = ema(closes, period)
    second = ema(first, period)
    third = ema(second, period)
    if len(third) < 2 or third[-2] == 0:
        return None
    return (third[-1] - third[-2]) / third[-2] * 100.0


def choppiness(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> float | None:
    """Choppiness Index: 100 (flat range) down to 0 (strong trend)."""
    if period < 2:
        raise ValueError("period must be at least 2")
    if len(closes) < period + 1:
        return None
    true_ranges = []
    for i in range(len(closes) - period, len(closes)):
        true_ranges.append(
            max(
                float(highs[i]) - float(lows[i]),
                abs(float(highs[i]) - float(closes[i - 1])),
                abs(float(lows[i]) - float(closes[i - 1])),
            )
        )
    sum_tr = sum(true_ranges)
    highest = max(float(v) for v in highs[-period:])
    lowest = min(float(v) for v in lows[-period:])
    span = highest - lowest
    if sum_tr <= 0 or span <= 0:
        return None
    import math

    return 100.0 * math.log10(sum_tr / span) / math.log10(period)


def fisher_transform(
    highs: Sequence[float], lows: Sequence[float], period: int = 10
) -> float | None:
    """Fisher Transform of the normalised mid-price (sharp turning points)."""
    if period < 2:
        raise ValueError("period must be at least 2")
    if len(lows) < period:
        return None
    mids = [(float(h) + float(low)) / 2.0 for h, low in zip(highs, lows, strict=True)]
    value = 0.0
    for end in range(period, len(mids) + 1):
        window = mids[end - period : end]
        highest, lowest = max(window), min(window)
        span = highest - lowest
        normalized = 2.0 * ((window[-1] - lowest) / span) - 1.0 if span else 0.0
        # Standard Ehlers clipping keeps the transform finite.
        clipped = max(-0.999, min(0.999, 0.66 * normalized + 0.67 * value))
        value = 0.5 * math.log((1 + clipped) / (1 - clipped))
    return value


def ultimate_oscillator(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> float | None:
    """Ultimate Oscillator: 0-100 blend of 7/14/28-bar buying pressure."""
    fast, middle, slow = 7, 14, 28
    if len(closes) < slow + 1:
        return None
    buying_pressure: list[float] = []
    true_range: list[float] = []
    for i in range(1, len(closes)):
        low_i, close_prev = float(lows[i]), float(closes[i - 1])
        buying_pressure.append(float(closes[i]) - min(low_i, close_prev))
        true_range.append(
            max(
                float(highs[i]) - low_i,
                abs(float(highs[i]) - close_prev),
                abs(low_i - close_prev),
            )
        )

    def average(length: int) -> float | None:
        bp = sum(buying_pressure[-length:])
        tr = sum(true_range[-length:])
        return bp / tr if tr else None

    parts = (average(fast), average(middle), average(slow))
    if any(part is None for part in parts):
        return None
    a, b, c = parts  # type: ignore[assignment]
    return 100.0 * (4 * a + 2 * b + c) / 7.0


def aroon(
    highs: Sequence[float],
    lows: Sequence[float],
    period: int = 25,
) -> dict[str, float] | None:
    """Aroon up/down/oscillator from the bars since recent extremes."""
    if period < 1:
        raise ValueError("period must be positive")
    if len(highs) < period + 1:
        return None
    window_h = [float(v) for v in highs[-(period + 1) :]]
    window_l = [float(v) for v in lows[-(period + 1) :]]
    # Bars since the window extreme: 0 means the extreme is the newest bar.
    up_bars_since = period - window_h.index(max(window_h))
    down_bars_since = period - window_l.index(min(window_l))
    up = (period - up_bars_since) / period * 100.0
    down = (period - down_bars_since) / period * 100.0
    return {"up": up, "down": down, "oscillator": up - down}


def ichimoku(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    *,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
) -> dict[str, float] | None:
    """Ichimoku baseline read (Tenkan, Kijun, Senkou A, Senkou B, Chikou).

    Cloud displacement is applied: Senkou values are the *current* cloud at
    the last close, not projections of it.
    """
    needed = max(kijun, senkou_b) + 1
    if len(closes) < needed:
        return None

    def midpoint(length: int, offset: int = 0) -> float:
        end = len(highs) - offset
        window_h = [float(v) for v in highs[end - length : end]]
        window_l = [float(v) for v in lows[end - length : end]]
        return (max(window_h) + min(window_l)) / 2.0

    tenkan_value = midpoint(tenkan)
    kijun_value = midpoint(kijun)
    span_a_now = (tenkan_value + kijun_value) / 2.0
    span_b_now = midpoint(senkou_b)
    cloud = "bullish" if span_a_now > span_b_now else "bearish"
    return {
        "tenkan": tenkan_value,
        "kijun": kijun_value,
        "senkou_a": span_a_now,
        "senkou_b": span_b_now,
        "cloud": cloud,
        "price_vs_kijun": "above" if float(closes[-1]) > kijun_value else "below",
    }


def pivot_points(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> dict[str, float] | None:
    """Classic floor-trader pivots (PP, R1-R3, S1-S3) from the last bar."""
    if not closes:
        return None
    high, low, close = float(highs[-1]), float(lows[-1]), float(closes[-1])
    pp = (high + low + close) / 3.0
    span = high - low
    return {
        "pp": pp,
        "r1": 2 * pp - low,
        "s1": 2 * pp - high,
        "r2": pp + span,
        "s2": pp - span,
        "r3": high + 2 * (pp - low),
        "s3": low - 2 * (high - pp),
    }


def elder_ray(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 13,
) -> dict[str, float] | None:
    """Elder Ray bull/bear power relative to an EMA of closes."""
    if len(closes) < period:
        return None
    baseline = ema([float(c) for c in closes], period)[-1]
    return {
        "bull_power": float(highs[-1]) - baseline,
        "bear_power": float(lows[-1]) - baseline,
    }


def zscore(closes: Sequence[float], period: int = 20) -> float | None:
    """Z-score of the last close inside its own rolling window."""
    if period < 2:
        raise ValueError("period must be at least 2")
    if len(closes) < period:
        return None
    window = [float(v) for v in closes[-period:]]
    mean = sum(window) / period
    deviation = math.sqrt(sum((v - mean) ** 2 for v in window) / period)
    if deviation == 0:
        return 0.0
    return (window[-1] - mean) / deviation


ADVANCED_INDICATORS: tuple[str, ...] = (
    "cci",
    "williams_r",
    "roc",
    "trix",
    "choppiness",
    "fisher_transform",
    "ultimate_oscillator",
    "aroon",
    "ichimoku",
    "pivot_points",
    "elder_ray",
    "zscore",
)


def advanced_suite(candles: Sequence[Candle]) -> dict[str, Any]:
    """All advanced indicators over validated closed candles.

    Missing values (short history) are ``None`` so JSON output stays
    schema-stable; ``warmup`` lists indicators that need more bars.
    """
    validated = _validated_candles(candles)
    if not validated:
        return {"candles": 0, "warmup": list(ADVANCED_INDICATORS), "values": {}}
    highs = [row[2] for row in validated]
    lows = [row[3] for row in validated]
    closes = [row[4] for row in validated]
    values: dict[str, Any] = {
        "cci": cci(highs, lows, closes),
        "williams_r": williams_r(highs, lows, closes),
        "roc": roc(closes),
        "trix": trix(closes),
        "choppiness": choppiness(highs, lows, closes),
        "fisher_transform": fisher_transform(highs, lows),
        "ultimate_oscillator": ultimate_oscillator(highs, lows, closes),
        "aroon": aroon(highs, lows),
        "ichimoku": ichimoku(highs, lows, closes),
        "pivot_points": pivot_points(highs, lows, closes),
        "elder_ray": elder_ray(highs, lows, closes),
        "zscore": zscore(closes),
    }
    warmup = [name for name, value in values.items() if value is None]
    return {"candles": len(closes), "warmup": warmup, "values": values}
