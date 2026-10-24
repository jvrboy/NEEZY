"""Flow-Risk Adaptive Structure (FRAS) — causal OHLC-only technical indicator.

FRAS combines an efficiency-ratio adaptive average, prior-window channel location,
ATR-scaled momentum, and a volatility-regime multiplier. No future bar is read.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from math import isfinite, sqrt, tanh
from statistics import median
from typing import Iterable, Optional


@dataclass(frozen=True)
class Candle:
    epoch: int
    open: float
    high: float
    low: float
    close: float

    def validate(self) -> None:
        values = (self.open, self.high, self.low, self.close)
        if not all(isfinite(v) for v in values):
            raise ValueError("OHLC prices must be finite")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("High must be >= open, close, and low")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("Low must be <= open, close, and high")


@dataclass(frozen=True)
class IndicatorPoint:
    epoch: int
    score: Optional[float]
    signal: str
    regime: str
    efficiency_ratio: Optional[float]
    atr: Optional[float]
    atr_ratio: Optional[float]
    adaptive_average: Optional[float]
    trend_component: Optional[float]
    breakout_component: Optional[float]
    momentum_component: Optional[float]

    def to_dict(self) -> dict:
        return asdict(self)


def _clip(x: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, x))


def _true_ranges(candles: list[Candle]) -> list[float]:
    out = []
    for i, c in enumerate(candles):
        if i == 0:
            out.append(c.high - c.low)
        else:
            prev = candles[i - 1].close
            out.append(max(c.high - c.low, abs(c.high - prev), abs(c.low - prev)))
    return out


def _wilder_atr(true_ranges: list[float], period: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(true_ranges)
    if len(true_ranges) < period:
        return out
    value = sum(true_ranges[:period]) / period
    out[period - 1] = value
    for i in range(period, len(true_ranges)):
        value = (value * (period - 1) + true_ranges[i]) / period
        out[i] = value
    return out


def calculate(
    candles: Iterable[Candle],
    *,
    atr_period: int = 14,
    efficiency_period: int = 20,
    channel_period: int = 20,
    volatility_median_period: int = 50,
    signal_threshold: float = 35.0,
    shock_ratio: float = 2.25,
    quiet_ratio: float = 0.55,
    minimum_efficiency_for_signal: float = 0.20,
) -> list[IndicatorPoint]:
    """Calculate FRAS for an ordered candle series.

    Parameters are intentionally configurable, but defaults are not optimized for
    any one pair or timeframe. Signals are descriptive research outputs only.
    """
    bars = list(candles)
    if min(atr_period, efficiency_period, channel_period, volatility_median_period) < 2:
        raise ValueError("All lookback periods must be >= 2")
    if not 0 < signal_threshold <= 100:
        raise ValueError("signal_threshold must be in (0, 100]")
    if not 0 <= minimum_efficiency_for_signal <= 1:
        raise ValueError("minimum_efficiency_for_signal must be in [0, 1]")
    for c in bars:
        c.validate()
    if any(bars[i].epoch <= bars[i - 1].epoch for i in range(1, len(bars))):
        raise ValueError(
            "Candles must be strictly chronological without duplicate epochs"
        )

    n = len(bars)
    if not n:
        return []
    closes = [c.close for c in bars]
    tr = _true_ranges(bars)
    atrs = _wilder_atr(tr, atr_period)
    kama: list[Optional[float]] = [None] * n
    kama[0] = closes[0]
    ers: list[Optional[float]] = [None] * n
    fast_sc = 2.0 / (2 + 1)
    slow_sc = 2.0 / (30 + 1)

    for i in range(1, n):
        if i >= efficiency_period:
            change = abs(closes[i] - closes[i - efficiency_period])
            volatility = sum(
                abs(closes[j] - closes[j - 1])
                for j in range(i - efficiency_period + 1, i + 1)
            )
            er = change / volatility if volatility > 0 else 0.0
            ers[i] = _clip(er, 0.0, 1.0)
            sc = (ers[i] * (fast_sc - slow_sc) + slow_sc) ** 2
            kama[i] = kama[i - 1] + sc * (closes[i] - kama[i - 1])
        else:
            kama[i] = kama[i - 1] + slow_sc**2 * (closes[i] - kama[i - 1])

    result: list[IndicatorPoint] = []
    for i, c in enumerate(bars):
        atr = atrs[i]
        er = ers[i]
        atr_ratio: Optional[float] = None
        score: Optional[float] = None
        tc = bc = mc = None
        regime = "warming_up"
        signal = "WARMUP"
        if atr is not None and er is not None and i >= channel_period:
            prior_high = max(b.high for b in bars[i - channel_period : i])
            prior_low = min(b.low for b in bars[i - channel_period : i])
            channel_half = (prior_high - prior_low) / 2.0
            trend_distance = (c.close - float(kama[i])) / max(1.5 * atr, 1e-15)
            tc = tanh(trend_distance)
            denom = channel_half + 0.25 * atr
            bc = _clip(
                (c.close - (prior_high + prior_low) / 2.0) / max(denom, 1e-15),
                -1.0,
                1.0,
            )
            mom = (c.close - closes[i - efficiency_period]) / max(
                atr * sqrt(efficiency_period), 1e-15
            )
            mc = tanh(mom)
            eligible_atrs = [
                x
                for x in atrs[max(0, i - volatility_median_period + 1) : i + 1]
                if x is not None
            ]
            atr_med = median(eligible_atrs) if eligible_atrs else 0.0
            atr_ratio = atr / atr_med if atr_med > 0 else 1.0
            if atr_ratio > shock_ratio:
                volatility_weight = max(0.35, shock_ratio / atr_ratio)
            elif atr_ratio < quiet_ratio:
                volatility_weight = max(0.35, atr_ratio / quiet_ratio)
            else:
                volatility_weight = 1.0
            persistence_weight = 0.55 + 0.45 * er
            raw = 0.45 * tc + 0.35 * bc + 0.20 * mc
            score = 100.0 * _clip(
                raw * persistence_weight * volatility_weight, -1.0, 1.0
            )
            if er >= 0.35:
                regime = "directional"
            elif er <= 0.20:
                regime = "choppy"
            else:
                regime = "mixed"
            if atr_ratio > 3.5:
                regime += ":volatility_shock"
            if er < minimum_efficiency_for_signal:
                signal = "FILTERED_CHOP"
            elif score >= signal_threshold:
                signal = "LONG_BIAS"
            elif score <= -signal_threshold:
                signal = "SHORT_BIAS"
            else:
                signal = "NEUTRAL"
        result.append(
            IndicatorPoint(
                epoch=c.epoch,
                score=score,
                signal=signal,
                regime=regime,
                efficiency_ratio=er,
                atr=atr,
                atr_ratio=atr_ratio,
                adaptive_average=kama[i],
                trend_component=tc,
                breakout_component=bc,
                momentum_component=mc,
            )
        )
    return result
