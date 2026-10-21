"""Named, testable trading strategies built on the indicator library.

Each strategy reads **closed** candles only (the caller's final row is treated
as the in-progress bar) and returns a :class:`StrategySignal` with a direction,
a 0-100 confidence, human-readable reasons, and the metrics behind the call.
Nothing here places orders; it is an educational decision-support layer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .divergence import correlation_divergence, detect_divergences
from .indicators import adx, atr, bollinger, ema, macd_histogram_series, rsi_series
from .trend import (
    band_squeeze,
    cci,
    channel_breakout,
    donchian,
    keltner,
    rate_of_change,
    stoch_rsi,
    supertrend,
)

Candle = Sequence[float]


def _midline(
    highs: Sequence[float], lows: Sequence[float], period: int
) -> float | None:
    """Donchian-midline helper used by the Ichimoku strategy."""
    if len(highs) < period or len(lows) < period:
        return None
    return (max(highs[-period:]) + min(lows[-period:])) / 2.0


@dataclass(frozen=True, slots=True)
class StrategySignal:
    """One strategy's verdict for one market."""

    strategy: str
    direction: int = 0
    confidence: float = 0.0
    summary: str = "No setup"
    reasons: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.direction > 0:
            return "BUY"
        if self.direction < 0:
            return "SELL"
        return "NEUTRAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "label": self.label,
            "direction": self.direction,
            "confidence": round(self.confidence, 1),
            "summary": self.summary,
            "reasons": list(self.reasons),
            "metrics": self.metrics,
        }


def _closed(candles: Sequence[Candle]) -> list[Candle]:
    return list(candles[:-1]) if len(candles) > 1 else []


def _last(values: Sequence[float | None]) -> float | None:
    for value in reversed(values):
        if value is not None:
            return float(value)
    return None


def supertrend_strategy(
    candles: Sequence[Candle], period: int = 10, multiplier: float = 3.0
) -> StrategySignal:
    """Trade the Supertrend direction, with extra confidence near a fresh flip."""
    closed = _closed(candles)
    if len(closed) < period + 5:
        return StrategySignal("SUPERTREND", summary="Not enough closed candles")
    highs = [row[2] for row in closed]
    lows = [row[3] for row in closed]
    closes = [row[4] for row in closed]
    entries = supertrend(highs, lows, closes, period, multiplier)
    known = [entry for entry in entries if entry["direction"]]
    if not known:
        return StrategySignal("SUPERTREND", summary="Supertrend still warming up")
    direction = int(known[-1]["direction"])
    line = known[-1]["supertrend"]
    average = known[-1]["atr"]
    bars_since_flip = 0
    for entry in reversed(known):
        if int(entry["direction"]) != direction:
            break
        bars_since_flip += 1
    distance = None
    if isinstance(line, (int, float)) and closes[-1]:
        distance = (closes[-1] - float(line)) / closes[-1] * 100.0
    confidence = 50.0
    if average and isinstance(line, (int, float)):
        gap = abs(closes[-1] - float(line)) / float(average) if average else 0.0
        confidence += min(gap, 3.0) / 3.0 * 25.0
    confidence += min(bars_since_flip, 20) / 20.0 * 25.0
    reasons = [
        f"Supertrend {period}/{multiplier:g} reads {'up' if direction > 0 else 'down'}",
        f"{bars_since_flip} bar(s) since the last flip",
    ]
    if distance is not None:
        reasons.append(f"price is {distance:+.2f}% from the line")
    return StrategySignal(
        strategy="SUPERTREND",
        direction=direction,
        confidence=min(confidence, 100.0),
        summary=(
            f"Price is in a Supertrend {'uptrend' if direction > 0 else 'downtrend'}"
        ),
        reasons=tuple(reasons),
        metrics={
            "line": round(float(line), 8) if isinstance(line, (int, float)) else None,
            "distance_pct": round(distance, 3) if distance is not None else None,
            "bars_since_flip": bars_since_flip,
            "atr": average,
            "period": period,
            "multiplier": multiplier,
        },
    )


def ema_pullback_strategy(
    candles: Sequence[Candle], fast: int = 9, slow: int = 21, trend: int = 50
) -> StrategySignal:
    """Buy the first close back above the fast EMA inside an established uptrend."""
    closed = _closed(candles)
    if len(closed) < trend + 5:
        return StrategySignal("EMA_PULLBACK", summary="Not enough closed candles")
    closes = [row[4] for row in closed]
    lows = [row[3] for row in closed]
    fast_ema, slow_ema, trend_ema = (
        ema(closes, fast),
        ema(closes, slow),
        ema(closes, trend),
    )
    up = fast_ema[-1] > slow_ema[-1] and closes[-1] > trend_ema[-1]
    down = fast_ema[-1] < slow_ema[-1] and closes[-1] < trend_ema[-1]
    if not (up or down):
        return StrategySignal(
            "EMA_PULLBACK",
            summary="No aligned EMA trend to pull back into",
            metrics={"ema_fast": fast_ema[-1], "ema_slow": slow_ema[-1]},
        )
    direction = 1 if up else -1
    touched = (
        lows[-2] <= fast_ema[-2] if direction > 0 else closed[-2][2] >= fast_ema[-2]
    )
    reclaimed = (
        closes[-1] > fast_ema[-1] if direction > 0 else closes[-1] < fast_ema[-1]
    )
    separation = abs(fast_ema[-1] - slow_ema[-1]) / closes[-1] * 100.0
    confidence = 45.0 + (25.0 if touched else 0.0) + (20.0 if reclaimed else 0.0)
    confidence += min(separation * 10.0, 10.0)
    reasons = [
        f"EMA {fast}/{slow} stacked {'bullishly' if direction > 0 else 'bearishly'}",
        f"price {'above' if direction > 0 else 'below'} EMA {trend}",
    ]
    if touched:
        reasons.append("prior bar tested the fast EMA")
    if reclaimed:
        reasons.append("close reclaimed the fast EMA")
    return StrategySignal(
        strategy="EMA_PULLBACK",
        direction=direction if (touched and reclaimed) else 0,
        confidence=min(confidence, 100.0),
        summary=(
            "Pullback entry in an uptrend"
            if direction > 0 and touched and reclaimed
            else "Pullback entry in a downtrend"
            if touched and reclaimed
            else "Trend is aligned but no pullback trigger yet"
        ),
        reasons=tuple(reasons),
        metrics={
            "ema_fast": round(fast_ema[-1], 8),
            "ema_slow": round(slow_ema[-1], 8),
            "ema_trend": round(trend_ema[-1], 8),
            "pullback_touched": touched,
            "reclaimed": reclaimed,
        },
    )


def divergence_strategy(candles: Sequence[Candle], lookback: int = 5) -> StrategySignal:
    """Trade RSI/MACD divergence against the prior swing."""
    closed = _closed(candles)
    if len(closed) < 35:
        return StrategySignal("DIVERGENCE", summary="Not enough closed candles")
    found = detect_divergences(closed, lookback)
    if not found:
        return StrategySignal(
            "DIVERGENCE", summary="No RSI or MACD divergence near the last swing"
        )
    best = found[0]
    direction = 1 if best["kind"] == "bullish" else -1
    reasons = (
        f"{best['oscillator'].upper()} divergence {best['kind']}",
        f"confirmed {best['bars_ago']} bar(s) ago",
        f"strength {best['strength']:.0%}",
    )
    return StrategySignal(
        strategy="DIVERGENCE",
        direction=direction,
        confidence=min(100.0, 40.0 + best["strength"] * 60.0),
        summary=f"{best['kind'].title()} {best['oscillator'].upper()} divergence",
        reasons=reasons,
        metrics=best,
    )


def donchian_strategy(candles: Sequence[Candle], period: int = 20) -> StrategySignal:
    """Channel breakout with an ATR-scaled confidence."""
    closed = _closed(candles)
    if len(closed) < period + 2:
        return StrategySignal("DONCHIAN", summary="Not enough closed candles")
    state = channel_breakout(closed, period)
    highs = [row[2] for row in closed]
    lows = [row[3] for row in closed]
    closes = [row[4] for row in closed]
    latest = donchian(highs, lows, period)[-1]
    average = atr(highs, lows, closes)
    if state is None:
        return StrategySignal(
            "DONCHIAN",
            summary=f"Inside the {period}-bar channel",
            metrics={"upper": latest["upper"], "lower": latest["lower"]},
        )
    direction = 1 if state == "breakout" else -1
    edge = (
        closes[-1] - float(latest["upper"])
        if direction > 0
        else float(latest["lower"]) - closes[-1]
    )
    extension = abs(edge) / float(average) if average else 0.0
    confidence = min(100.0, 55.0 + min(extension, 2.0) / 2.0 * 45.0)
    return StrategySignal(
        strategy="DONCHIAN",
        direction=direction,
        confidence=confidence,
        summary=f"{period}-bar channel {state}",
        reasons=(
            f"close cleared the {period}-bar {'high' if direction > 0 else 'low'}",
            f"extension {extension:.2f} ATR",
        ),
        metrics={
            "upper": latest["upper"],
            "lower": latest["lower"],
            "extension_atr": round(extension, 3),
        },
    )


def squeeze_strategy(candles: Sequence[Candle], period: int = 20) -> StrategySignal:
    """Bollinger squeeze with a directional band break."""
    closed = _closed(candles)
    if len(closed) < period + 10:
        return StrategySignal("SQUEEZE", summary="Not enough closed candles")
    squeeze = band_squeeze(closed, period)
    bands = bollinger([row[4] for row in closed])
    if bands is None:
        return StrategySignal("SQUEEZE", summary="Bollinger bands unavailable")
    close = closed[-1][4]
    direction = 1 if close > bands["upper"] else -1 if close < bands["lower"] else 0
    if not squeeze["squeeze"]:
        return StrategySignal(
            "SQUEEZE",
            summary="Volatility is not compressed",
            metrics=squeeze,
        )
    confidence = (
        50.0 + (45.0 if direction else 0.0) + (1.0 - squeeze["percentile"]) * 5.0
    )
    return StrategySignal(
        strategy="SQUEEZE",
        direction=direction,
        confidence=min(confidence, 100.0),
        summary=(
            "Squeeze release"
            if direction
            else "Squeeze building, waiting for the break"
        ),
        reasons=(
            f"bandwidth at the {squeeze['percentile']:.0%} percentile",
            "closed outside the band" if direction else "price still inside the bands",
        ),
        metrics={**squeeze, "upper": bands["upper"], "lower": bands["lower"]},
    )


def macd_strategy(
    candles: Sequence[Candle], fast: int = 12, slow: int = 26, signal: int = 9
) -> StrategySignal:
    """MACD histogram sign plus momentum direction."""
    closed = _closed(candles)
    if len(closed) < slow + signal + 5:
        return StrategySignal("MACD", summary="Not enough closed candles")
    closes = [row[4] for row in closed]
    histogram = macd_histogram_series(closes, fast, slow, signal)
    latest, previous = histogram[-1], histogram[-2]
    rising = latest > previous
    direction = 1 if latest > 0 and rising else -1 if latest < 0 and not rising else 0
    scale = max(abs(value) for value in histogram[-30:]) or 1e-9
    confidence = 45.0 + min(abs(latest) / scale, 1.0) * 35.0 + 20.0
    return StrategySignal(
        strategy="MACD",
        direction=direction,
        confidence=min(confidence, 100.0),
        summary=(
            "MACD momentum expanding" if direction else "MACD momentum is not aligned"
        ),
        reasons=(
            f"histogram {latest:+.6f}",
            "histogram rising" if rising else "histogram falling",
        ),
        metrics={
            "histogram": latest,
            "previous": previous,
            "fast": fast,
            "slow": slow,
            "signal": signal,
        },
    )


def keltner_strategy(candles: Sequence[Candle], period: int = 20) -> StrategySignal:
    """Keltner channel trend ride: close outside the channel with EMA agreement."""
    closed = _closed(candles)
    if len(closed) < period + 5:
        return StrategySignal("KELTNER", summary="Not enough closed candles")
    highs = [row[2] for row in closed]
    lows = [row[3] for row in closed]
    closes = [row[4] for row in closed]
    bands = keltner(highs, lows, closes, period)[-1]
    if bands["upper"] is None or bands["lower"] is None:
        return StrategySignal("KELTNER", summary="Keltner channel warming up")
    close = closes[-1]
    ema_series = ema(closes, period)
    direction = 0
    if close > float(bands["upper"]) and ema_series[-1] > ema_series[-2]:
        direction = 1
    elif close < float(bands["lower"]) and ema_series[-1] < ema_series[-2]:
        direction = -1
    span = max(float(bands["upper"]) - float(bands["lower"]), 1e-9)
    position = (close - float(bands["lower"])) / span
    slope_label = "positive" if ema_series[-1] >= ema_series[-2] else "negative"
    confidence = 40.0 + abs(position - 0.5) * 2.0 * 50.0 if direction else 30.0
    return StrategySignal(
        strategy="KELTNER",
        direction=direction,
        confidence=min(confidence, 100.0),
        summary=(
            f"Close outside the Keltner channel with an {period}-bar EMA "
            f"{'rising' if direction > 0 else 'falling'}"
            if direction
            else "Price inside the Keltner channel"
        ),
        reasons=(
            f"channel position {position:.0%}",
            f"EMA {period} slope {slope_label}",
        ),
        metrics={
            "upper": bands["upper"],
            "lower": bands["lower"],
            "position": round(position, 3),
        },
    )


def ichimoku_strategy(
    candles: Sequence[Candle],
    conversion: int = 9,
    base: int = 26,
    cloud: int = 52,
) -> StrategySignal:
    """Ichimoku-style read: cloud position plus conversion/base alignment."""
    closed = _closed(candles)
    if len(closed) < cloud + 5:
        return StrategySignal("ICHIMOKU", summary="Not enough closed candles")
    highs = [row[2] for row in closed]
    lows = [row[3] for row in closed]
    closes = [row[4] for row in closed]
    close = closes[-1]
    tenkan = _midline(highs, lows, conversion)
    kijun = _midline(highs, lows, base)
    # The cloud is projected `base` bars forward, so it reads the flat lines
    # drawn from the bars `base` and `cloud + base` periods back.
    senkou_a = _midline(highs[:-base], lows[:-base], cloud)
    senkou_b = _midline(highs[: -(base + cloud)], lows[: -(base + cloud)], cloud)
    if tenkan is None or kijun is None or senkou_a is None or senkou_b is None:
        return StrategySignal("ICHIMOKU", summary="Ichimoku lines still warming up")
    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)
    above_cloud = close > cloud_top
    below_cloud = close < cloud_bottom
    inside = not above_cloud and not below_cloud
    direction = 0
    if above_cloud and tenkan > kijun:
        direction = 1
    elif below_cloud and tenkan < kijun:
        direction = -1
    span = max(cloud_top - cloud_bottom, 1e-9)
    cloud_middle = (cloud_top + cloud_bottom) / 2.0
    alignment = (
        55.0
        + (25.0 if tenkan > kijun else 0.0)
        + min(abs((close - cloud_middle) / span), 1.0) * 20.0
    )
    return StrategySignal(
        strategy="ICHIMOKU",
        direction=direction,
        confidence=min(100.0, alignment) if direction else min(alignment, 60.0),
        summary=(
            f"Price {'above' if above_cloud else 'below' if below_cloud else 'inside'} "
            "the Kumo cloud"
        ),
        reasons=(
            f"close {close:.6g} vs cloud {cloud_bottom:.6g}-{cloud_top:.6g}",
            f"conversion {'above' if tenkan > kijun else 'below'} base line",
        ),
        metrics={
            "tenkan": round(tenkan, 8),
            "kijun": round(kijun, 8),
            "cloud_top": round(cloud_top, 8),
            "cloud_bottom": round(cloud_bottom, 8),
            "inside_cloud": inside,
        },
    )


def stochrsi_strategy(
    candles: Sequence[Candle], period: int = 14, smooth: int = 3
) -> StrategySignal:
    """Stochastic RSI band exit: oversold recovery is long, overbought fades short."""
    closed = _closed(candles)
    if len(closed) < period + smooth + 10:
        return StrategySignal("STOCH_RSI", summary="Not enough closed candles")
    closes = [row[4] for row in closed]
    series = stoch_rsi(closes, period, smooth)
    latest, previous = series[-1], series[-2]
    if latest is None or previous is None:
        return StrategySignal("STOCH_RSI", summary="Stochastic RSI still warming up")
    if previous < 20 <= latest:
        direction, label = 1, "oversold recovery"
    elif previous > 80 >= latest:
        direction, label = -1, "overbought rollover"
    else:
        return StrategySignal(
            "STOCH_RSI",
            summary=f"Stochastic RSI at {latest:.1f}, no band exit",
            metrics={"stoch_rsi": latest, "previous": previous},
        )
    return StrategySignal(
        strategy="STOCH_RSI",
        direction=direction,
        confidence=70.0 + abs(latest - 50.0) * 0.3,
        summary=f"Stochastic RSI {label}",
        reasons=(
            f"left the {'lower' if direction > 0 else 'upper'} band at {latest:.1f}",
            f"prior reading {previous:.1f}",
        ),
        metrics={"stoch_rsi": latest, "previous": previous, "period": period},
    )


def momentum_strategy(
    candles: Sequence[Candle], period: int = 10, strength: int = 25
) -> StrategySignal:
    """Rate-of-change burst confirmed by an ADX above the trend threshold."""
    closed = _closed(candles)
    if len(closed) < strength * 2 + 5:
        return StrategySignal("MOMENTUM", summary="Not enough closed candles")
    highs = [row[2] for row in closed]
    lows = [row[3] for row in closed]
    closes = [row[4] for row in closed]
    roc_series = rate_of_change(closes, period)
    roc = roc_series[-1]
    dm = adx(highs, lows, closes, strength)
    if roc is None or dm is None:
        return StrategySignal("MOMENTUM", summary="Momentum engine still warming up")
    trending = dm["adx"] >= 20.0
    direction = 1 if roc > 0 else -1 if roc < 0 else 0
    if not trending or direction == 0:
        return StrategySignal(
            "MOMENTUM",
            summary="Rate of change without directional confirmation",
            metrics={"roc": roc, "adx": dm["adx"]},
        )
    magnitude = min(abs(roc) / 1.0, 1.0)
    confidence = 45.0 + min(dm["adx"], 50.0) * 0.6 + magnitude * 35.0
    return StrategySignal(
        strategy="MOMENTUM",
        direction=direction,
        confidence=min(confidence, 100.0),
        summary="Momentum burst inside a trending market",
        reasons=(
            f"ROC {roc:+.3f}% over {period} bars",
            f"ADX {dm['adx']:.1f} confirms a trend",
        ),
        metrics={
            "roc": roc,
            "adx": dm["adx"],
            "plus_di": dm["plus_di"],
            "minus_di": dm["minus_di"],
        },
    )


def rsi_reversal_strategy(
    candles: Sequence[Candle], period: int = 14, extreme: float = 30.0
) -> StrategySignal:
    """Mean-reversion entry when RSI leaves an extreme against a band touch."""
    closed = _closed(candles)
    if len(closed) < period + 15:
        return StrategySignal("RSI_REVERSAL", summary="Not enough closed candles")
    closes = [row[4] for row in closed]
    series = rsi_series(closes, period)
    latest, previous = series[-1], series[-2]
    bands = bollinger(closes)
    if latest is None or previous is None or bands is None:
        return StrategySignal("RSI_REVERSAL", summary="RSI or bands still warming up")
    oversold_recover = previous < 100.0 - extreme <= latest
    overbought_fade = previous > extreme >= latest
    close = closes[-1]
    band_touch = (
        close <= bands["lower"]
        if oversold_recover
        else close >= bands["upper"]
        if overbought_fade
        else False
    )
    if not (oversold_recover or overbought_fade):
        return StrategySignal(
            "RSI_REVERSAL",
            summary=f"RSI {latest:.1f} inside neutral ground",
            metrics={"rsi": latest, "previous": previous},
        )
    direction = 1 if oversold_recover else -1
    confidence = (
        55.0 + (25.0 if band_touch else 0.0) + min(abs(latest - 50.0), 50.0) * 0.2
    )
    return StrategySignal(
        strategy="RSI_REVERSAL",
        direction=direction,
        confidence=min(confidence, 100.0),
        summary=(
            "RSI left oversold with room to the mean"
            if direction > 0
            else "RSI left overbought with room to the mean"
        ),
        reasons=(
            f"RSI moved "
            f"{'up from oversold' if direction > 0 else 'down from overbought'} "
            f"({previous:.1f} to {latest:.1f})",
            (
                "close "
                + (
                    "at the lower Bollinger band"
                    if direction > 0
                    else "at the upper Bollinger band"
                )
            )
            if band_touch
            else "no Bollinger band touch",
        ),
        metrics={"rsi": latest, "previous": previous, "band_touch": band_touch},
    )


def cci_reversion_strategy(
    candles: Sequence[Candle], period: int = 20, extreme: float = 100.0
) -> StrategySignal:
    """Fade CCI extremes back toward the mean once the reading normalizes."""
    closed = _closed(candles)
    if len(closed) < period + 10:
        return StrategySignal("CCI_REVERSION", summary="Not enough closed candles")
    highs = [row[2] for row in closed]
    lows = [row[3] for row in closed]
    closes = [row[4] for row in closed]
    series = cci(highs, lows, closes, period)
    latest, previous = series[-1], series[-2]
    if latest is None or previous is None:
        return StrategySignal("CCI_REVERSION", summary="CCI still warming up")
    up = previous < -extreme <= latest
    down = previous > extreme >= latest
    if not (up or down):
        return StrategySignal(
            "CCI_REVERSION",
            summary=f"CCI {latest:.1f} not at an extreme",
            metrics={"cci": latest, "previous": previous},
        )
    direction = 1 if up else -1
    scale = max((abs(item) for item in series if item is not None), default=extreme)
    strength = min(abs(latest) / max(scale, 1e-9), 1.0)
    return StrategySignal(
        strategy="CCI_REVERSION",
        direction=direction,
        confidence=min(100.0, 55.0 + strength * 40.0),
        summary="CCI extreme normalization",
        reasons=(
            f"CCI swung {previous:.1f} to {latest:.1f}",
            "statistical mean reversion window",
        ),
        metrics={"cci": latest, "previous": previous, "period": period},
    )


def correlation_divergence_strategy(
    first: Sequence[float],
    second: Sequence[float],
    window: int = 50,
    baseline: int = 200,
) -> StrategySignal:
    """Pair-level signal when two markets decouple from their usual link."""
    result = correlation_divergence(first, second, window, baseline)
    if result is None:
        return StrategySignal(
            "CORRELATION_DIVERGENCE", summary="Not enough overlapping history"
        )
    directional = result["state"] in {"decoupling", "inverted"}
    return StrategySignal(
        strategy="CORRELATION_DIVERGENCE",
        direction=0,
        confidence=min(100.0, result["strength"] * 100.0) if directional else 0.0,
        summary=f"Pair is {result['state']}",
        reasons=(result["interpretation"],),
        metrics=result,
    )


@dataclass(frozen=True, slots=True)
class StrategySpec:
    name: str
    label: str
    description: str
    runner: Callable[..., StrategySignal]
    pair: bool = False


STRATEGIES: dict[str, StrategySpec] = {
    "SUPERTREND": StrategySpec(
        "SUPERTREND",
        "Supertrend",
        "ATR band trend following with flip detection.",
        supertrend_strategy,
    ),
    "EMA_PULLBACK": StrategySpec(
        "EMA_PULLBACK",
        "EMA pullback",
        "Buy/sell the first reclaim of the fast EMA inside an aligned trend.",
        ema_pullback_strategy,
    ),
    "DIVERGENCE": StrategySpec(
        "DIVERGENCE",
        "RSI/MACD divergence",
        "Trade a price swing that the oscillator refuses to confirm.",
        divergence_strategy,
    ),
    "DONCHIAN": StrategySpec(
        "DONCHIAN",
        "Donchian breakout",
        "Breakout of the prior N-bar high/low with ATR confirmation.",
        donchian_strategy,
    ),
    "SQUEEZE": StrategySpec(
        "SQUEEZE",
        "Bollinger squeeze",
        "Low-volatility compression, resolved by a band break.",
        squeeze_strategy,
    ),
    "MACD": StrategySpec(
        "MACD",
        "MACD momentum",
        "Histogram sign combined with the direction of momentum.",
        macd_strategy,
    ),
    "KELTNER": StrategySpec(
        "KELTNER",
        "Keltner channel",
        "Channel breakout with EMA agreement.",
        keltner_strategy,
    ),
    "ICHIMOKU": StrategySpec(
        "ICHIMOKU",
        "Ichimoku cloud",
        "Kumo cloud position with Tenkan/Kijun alignment.",
        ichimoku_strategy,
    ),
    "STOCH_RSI": StrategySpec(
        "STOCH_RSI",
        "Stochastic RSI",
        "Band-exit timing from the stochastic of RSI.",
        stochrsi_strategy,
    ),
    "MOMENTUM": StrategySpec(
        "MOMENTUM",
        "ROC momentum burst",
        "Rate-of-change burst confirmed by ADX trend strength.",
        momentum_strategy,
    ),
    "RSI_REVERSAL": StrategySpec(
        "RSI_REVERSAL",
        "RSI band reversal",
        "Mean reversion after RSI leaves an extreme with band touch.",
        rsi_reversal_strategy,
    ),
    "CCI_REVERSION": StrategySpec(
        "CCI_REVERSION",
        "CCI mean reversion",
        "Fade normalized CCI extremes back toward the statistical mean.",
        cci_reversion_strategy,
    ),
    "CORRELATION_DIVERGENCE": StrategySpec(
        "CORRELATION_DIVERGENCE",
        "Correlation divergence",
        "Cross-market decoupling between a pair of markets.",
        correlation_divergence_strategy,
        pair=True,
    ),
}

SINGLE_MARKET_STRATEGIES = tuple(
    name for name, spec in STRATEGIES.items() if not spec.pair
)


def get_strategy(name: str) -> StrategySpec:
    try:
        return STRATEGIES[name.upper()]
    except KeyError:
        raise ValueError(
            f"unknown strategy {name!r}; choose from {', '.join(STRATEGIES)}"
        ) from None


def strategy_names() -> list[str]:
    return list(STRATEGIES)


def evaluate(name: str, candles: Sequence[Candle], **params: Any) -> StrategySignal:
    """Run one named single-market strategy on a candle sequence."""
    spec = get_strategy(name)
    if spec.pair:
        raise ValueError(f"{spec.name} needs two markets; use correlate_pair() instead")
    return spec.runner(candles, **params)


def run_all(candles: Sequence[Candle], **params: Any) -> list[StrategySignal]:
    """Every single-market strategy for one market, strongest first."""
    signals = [evaluate(name, candles, **params) for name in SINGLE_MARKET_STRATEGIES]
    signals.sort(key=lambda item: (-abs(item.direction), -item.confidence))
    return signals


def consensus(signals: Sequence[StrategySignal]) -> dict[str, Any]:
    """Vote-weighted consensus across strategies."""
    if not signals:
        return {"label": "NEUTRAL", "direction": 0, "confidence": 0.0, "votes": {}}
    buys = sum(signal.confidence for signal in signals if signal.direction > 0)
    sells = sum(signal.confidence for signal in signals if signal.direction < 0)
    total = buys + sells
    votes = {
        "buy": sum(1 for signal in signals if signal.direction > 0),
        "sell": sum(1 for signal in signals if signal.direction < 0),
        "neutral": sum(1 for signal in signals if signal.direction == 0),
    }
    if total <= 0:
        return {"label": "NEUTRAL", "direction": 0, "confidence": 0.0, "votes": votes}
    net = (buys - sells) / total
    direction = 1 if net > 0.15 else -1 if net < -0.15 else 0
    return {
        "label": "BUY" if direction > 0 else "SELL" if direction < 0 else "NEUTRAL",
        "direction": direction,
        "confidence": round(abs(net) * 100.0, 1),
        "votes": votes,
        "buy_weight": round(buys, 1),
        "sell_weight": round(sells, 1),
    }


def evaluate_pair(
    first: Sequence[float],
    second: Sequence[float],
    window: int = 50,
    baseline: int = 200,
) -> StrategySignal:
    """Convenience wrapper around the pair strategy."""
    return correlation_divergence_strategy(first, second, window, baseline)


def describe_strategies() -> list[dict[str, Any]]:
    """Registry metadata for the CLI and the settings tab."""
    return [
        {
            "name": spec.name,
            "label": spec.label,
            "description": spec.description,
            "pair": spec.pair,
        }
        for spec in STRATEGIES.values()
    ]
