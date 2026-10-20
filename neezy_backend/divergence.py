"""Divergence analytics: price vs oscillator, and correlation breakdowns.

Two families live here:

* **Classical divergence** — price makes a lower low while RSI or the MACD
  histogram makes a higher low (bullish), and the mirror image for bearish.
* **Correlation divergence** — two markets that normally move together stop
  doing so. Tracked as the gap between a short rolling correlation and a long
  baseline, which is how decoupling and regime breaks show up early.

All functions take plain sequences and return JSON-safe dictionaries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .analytics import log_returns, pearson
from .indicators import macd_histogram_series, rsi_series

Candle = Sequence[float]

OSCILLATORS = ("rsi", "macd")


def pivot_indices(
    values: Sequence[float | None], kind: str, left: int = 2, right: int = 2
) -> list[int]:
    """Indices of fractal swing lows/highs (strict on both sides)."""
    if kind not in {"low", "high"}:
        raise ValueError("kind must be 'low' or 'high'")
    if left < 1 or right < 1:
        raise ValueError("pivot windows must be positive")
    pivots: list[int] = []
    for index in range(left, len(values) - right):
        value = values[index]
        if value is None:
            continue
        window = values[index - left : index + right + 1]
        if any(item is None for item in window):
            continue
        others = [
            item
            for offset, item in enumerate(window)
            if offset != left and item is not None
        ]
        if kind == "low" and all(value < item for item in others):
            pivots.append(index)
        elif kind == "high" and all(value > item for item in others):
            pivots.append(index)
    return pivots


def oscillator_series(
    closes: Sequence[float], oscillator: str = "rsi"
) -> list[float | None]:
    """Aligned RSI or MACD-histogram series used for divergence comparison."""
    if oscillator == "rsi":
        return list(rsi_series(closes))
    if oscillator == "macd":
        values = macd_histogram_series(closes)
        return [value if abs(value) > 1e-12 else 0.0 for value in values]
    raise ValueError(f"unknown oscillator {oscillator!r}; choose from {OSCILLATORS}")


def _divergence_between(
    candles: Sequence[Candle],
    oscillator_values: Sequence[float | None],
    pivots: Sequence[int],
    *,
    kind: str,
    oscillator: str,
    tolerance: float = 1e-9,
) -> dict[str, Any] | None:
    if len(pivots) < 2:
        return None
    first, second = pivots[-2], pivots[-1]
    first_oscillator = oscillator_values[first]
    second_oscillator = oscillator_values[second]
    if first_oscillator is None or second_oscillator is None:
        return None
    first_price = float(candles[first][4])
    second_price = float(candles[second][4])
    if kind == "low":
        price_break = second_price < first_price - tolerance
        oscillator_recovery = second_oscillator > first_oscillator + tolerance
        label = "bullish"
    else:
        price_break = second_price > first_price + tolerance
        oscillator_recovery = second_oscillator < first_oscillator - tolerance
        label = "bearish"
    if not (price_break and oscillator_recovery):
        return None
    price_span = max(abs(first_price), abs(second_price), 1e-9)
    price_change = abs(second_price - first_price) / price_span
    oscillator_scale = max(abs(first_oscillator), abs(second_oscillator), 1e-9)
    oscillator_change = abs(second_oscillator - first_oscillator) / oscillator_scale
    strength = min(
        1.0, 0.55 * min(price_change * 60.0, 1.0) + 0.45 * min(oscillator_change, 1.0)
    )
    return {
        "kind": label,
        "oscillator": oscillator,
        "bars_ago": len(candles) - 1 - second,
        "strength": round(strength, 3),
        "price_points": [
            {"index": first, "price": first_price},
            {"index": second, "price": second_price},
        ],
        "oscillator_points": [
            {"index": first, "value": round(float(first_oscillator), 4)},
            {"index": second, "value": round(float(second_oscillator), 4)},
        ],
    }


def detect_divergence(
    candles: Sequence[Candle],
    oscillator: str = "rsi",
    lookback: int = 5,
    *,
    pivot_width: int = 2,
) -> dict[str, Any] | None:
    """Most recent classical divergence, or ``None`` when there is none.

    ``lookback`` bounds how many bars back the second pivot may sit, so a stale
    divergence from earlier in the history is not reported as current.
    """
    if lookback < 1:
        raise ValueError("lookback must be positive")
    if len(candles) < 30:
        return None
    closes = [float(row[4]) for row in candles]
    oscillator_values = oscillator_series(closes, oscillator)
    horizon = max(lookback * 3, 12)

    candidates: list[dict[str, Any]] = []
    for kind in ("low", "high"):
        pivots = [
            index
            for index in pivot_indices(
                oscillator_values, kind, pivot_width, pivot_width
            )
            if index >= len(candles) - horizon
        ]
        found = _divergence_between(
            candles,
            oscillator_values,
            pivots,
            kind=kind,
            oscillator=oscillator,
        )
        if found is not None and found["bars_ago"] <= lookback:
            candidates.append(found)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["bars_ago"], -item["strength"]))
    return candidates[0]


def detect_divergences(
    candles: Sequence[Candle], lookback: int = 5
) -> list[dict[str, Any]]:
    """Every divergence across RSI and MACD, strongest first."""
    found = []
    for oscillator in OSCILLATORS:
        signal = detect_divergence(candles, oscillator, lookback)
        if signal is not None:
            found.append(signal)
    found.sort(key=lambda item: (-item["strength"], item["bars_ago"]))
    return found


def rsi_divergence(
    candles: Sequence[Candle], lookback: int = 5
) -> dict[str, Any] | None:
    """RSI divergence wrapper."""
    return detect_divergence(candles, "rsi", lookback)


def macd_divergence(
    candles: Sequence[Candle], lookback: int = 5
) -> dict[str, Any] | None:
    """MACD-histogram divergence wrapper."""
    return detect_divergence(candles, "macd", lookback)


def correlation_divergence(
    first: Sequence[float],
    second: Sequence[float],
    window: int = 50,
    baseline: int = 200,
    *,
    threshold: float = 0.25,
) -> dict[str, Any] | None:
    """Compare short-run correlation with a long baseline for one pair.

    Returns ``state`` of ``"decoupling"``, ``"converging"``, ``"inverted"`` or
    ``"stable"``, plus the strength of the move away from the baseline.
    """
    if window < 4:
        raise ValueError("window must be at least 4")
    if baseline < window:
        raise ValueError("baseline must be at least as long as window")
    if threshold <= 0:
        raise ValueError("threshold must be positive")
    length = min(len(first), len(second))
    if length < window + 2:
        return None
    first_tail = list(first[-min(length, baseline + 1) :])
    second_tail = list(second[-min(length, baseline + 1) :])
    returns_first = log_returns(first_tail)
    returns_second = log_returns(second_tail)
    recent_first = returns_first[-window:]
    recent_second = returns_second[-window:]
    recent = pearson(recent_first, recent_second)
    long_run = pearson(returns_first, returns_second)
    if recent is None or long_run is None:
        return None
    delta = recent - long_run
    if long_run * recent < 0 and abs(long_run) >= 0.2:
        state, interpretation = (
            "inverted",
            "the pair flipped from moving together to moving apart",
        )
    elif abs(recent) <= abs(long_run) / 2 and abs(delta) >= threshold:
        state, interpretation = (
            "decoupling",
            "the short-term link is much weaker than its baseline",
        )
    elif abs(recent) >= abs(long_run) + threshold and long_run * recent > 0:
        state, interpretation = (
            "converging",
            "the pair is tracking its baseline more tightly than usual",
        )
    else:
        state, interpretation = "stable", "the pair is behaving like its baseline"
    strength = min(1.0, abs(delta) / max(threshold * 2.0, 1e-9))
    return {
        "state": state,
        "baseline": round(long_run, 3),
        "recent": round(recent, 3),
        "delta": round(delta, 3),
        "strength": round(strength, 3),
        "window": window,
        "baseline_window": baseline,
        "observations": len(returns_first),
        "interpretation": interpretation,
    }


def rank_correlation_divergences(
    closes_by_symbol: Mapping[str, Sequence[float]],
    window: int = 50,
    baseline: int = 200,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Top pair-level correlation breaks across a basket of markets."""
    if limit < 1:
        raise ValueError("limit must be positive")
    symbols = list(closes_by_symbol)
    ranked: list[dict[str, Any]] = []
    for position, first in enumerate(symbols):
        for second in symbols[position + 1 :]:
            result = correlation_divergence(
                closes_by_symbol[first], closes_by_symbol[second], window, baseline
            )
            if result is None:
                continue
            ranked.append({"first": first, "second": second, **result})
    ranked.sort(key=lambda item: (-item["strength"], -abs(item["delta"])))
    return ranked[:limit]
