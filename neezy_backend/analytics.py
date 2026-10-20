"""Cross-market analytics: return correlations and opportunity ranking."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any


def log_returns(closes: Sequence[float]) -> list[float]:
    return [
        math.log(after / before)
        for before, after in pairwise(closes)
        if before > 0 and after > 0
    ]


def pearson(first: Sequence[float], second: Sequence[float]) -> float | None:
    """Pearson correlation of the overlapping tail of two series."""
    length = min(len(first), len(second))
    if length < 3:
        return None
    a, b = list(first[-length:]), list(second[-length:])
    mean_a, mean_b = sum(a) / length, sum(b) / length
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b, strict=True))
    spread_a = math.sqrt(sum((x - mean_a) ** 2 for x in a))
    spread_b = math.sqrt(sum((y - mean_b) ** 2 for y in b))
    if not spread_a or not spread_b:
        return None
    return max(-1.0, min(1.0, covariance / (spread_a * spread_b)))


def correlation_matrix(
    closes_by_symbol: Mapping[str, Sequence[float]], window: int = 100
) -> dict[str, dict[str, float | None]]:
    """Correlation of log returns over the last ``window`` closes per symbol."""
    if window < 4:
        raise ValueError("window must be at least 4")
    returns = {
        symbol: log_returns(list(closes)[-window:])
        for symbol, closes in closes_by_symbol.items()
    }
    symbols = list(returns)
    matrix: dict[str, dict[str, float | None]] = {symbol: {} for symbol in symbols}
    for i, first in enumerate(symbols):
        matrix[first][first] = 1.0 if len(returns[first]) >= 3 else None
        for second in symbols[i + 1 :]:
            value = pearson(returns[first], returns[second])
            matrix[first][second] = matrix[second][first] = value
    return matrix


def strongest_pairs(
    matrix: Mapping[str, Mapping[str, float | None]], limit: int = 5
) -> list[tuple[str, str, float]]:
    """Most strongly (positively or negatively) correlated distinct pairs."""
    seen, pairs = set(), []
    for first, row in matrix.items():
        for second, value in row.items():
            key = frozenset((first, second))
            if first == second or value is None or key in seen:
                continue
            seen.add(key)
            pairs.append((first, second, value))
    pairs.sort(key=lambda item: abs(item[2]), reverse=True)
    return pairs[:limit]


def opportunity_score(result: Mapping[str, Any]) -> float:
    """0-100 composite of signal score, ADX trend strength, and RSI room.

    Higher means the indicator set agrees more strongly; it is a ranking aid,
    not a probability of profit.
    """
    score = abs(int(result.get("score", 0))) / 4.0 * 60.0
    directional = result.get("adx")
    if isinstance(directional, Mapping) and directional.get("adx") is not None:
        score += min(float(directional["adx"]), 50.0) / 50.0 * 25.0
    rsi_value = result.get("rsi")
    if rsi_value is not None:
        bullish = "BUY" in str(result.get("signal", ""))
        bearish = "SELL" in str(result.get("signal", ""))
        room = (100 - rsi_value) if bullish else rsi_value if bearish else 50.0
        score += max(0.0, min(room, 70.0)) / 70.0 * 15.0
    return round(min(score, 100.0), 1)


def rank_opportunities(
    results: Mapping[str, Mapping[str, Any]], include_neutral: bool = False
) -> list[dict[str, Any]]:
    ranked = [
        {
            "symbol": symbol,
            "signal": result.get("signal"),
            "score": result.get("score"),
            "regime": result.get("regime", "Unknown"),
            "opportunity": opportunity_score(result),
        }
        for symbol, result in results.items()
        if include_neutral or result.get("signal") != "NEUTRAL"
    ]
    ranked.sort(key=lambda item: item["opportunity"], reverse=True)
    return ranked
