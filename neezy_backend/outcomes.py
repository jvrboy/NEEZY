"""Measure how past signals actually played out.

Pure functions with no I/O: feed them rows from ``LocalDatabase.recent_signals``
and candles from ``LocalDatabase.load_candles`` to compare live results with the
backtest.
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class Outcome:
    """Result of one directional signal after a fixed number of candles."""

    signal_id: int | None
    symbol: str
    direction: int
    entry: float
    exit: float
    return_pct: float
    bars_held: int

    @property
    def hit(self) -> bool:
        return self.return_pct > 0


def _epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def evaluate_outcomes(
    signals: Sequence[Mapping[str, Any]],
    candles: Sequence[Sequence[float]],
    horizon: int = 10,
) -> list[Outcome]:
    """Score signals by the close ``horizon`` candles after they fired.

    Signals without a direction or price, and signals whose horizon has not yet
    elapsed, are skipped. ``candles`` must be ordered oldest to newest rows of
    ``(epoch, open, high, low, close)``.
    """
    if horizon < 1:
        raise ValueError("horizon must be positive")
    epochs = [float(candle[0]) for candle in candles]
    outcomes: list[Outcome] = []
    for signal in signals:
        direction = int(signal.get("direction") or 0)
        entry = signal.get("price")
        when = _epoch(signal.get("created_at"))
        if direction == 0 or entry is None or float(entry) <= 0 or when is None:
            continue
        exit_index = bisect.bisect_left(epochs, when) + horizon - 1
        if exit_index >= len(candles):
            continue
        exit_price = float(candles[exit_index][4])
        change = direction * (exit_price - float(entry)) / float(entry) * 100.0
        outcomes.append(
            Outcome(
                signal_id=signal.get("id"),
                symbol=str(signal.get("symbol", "")),
                direction=direction,
                entry=float(entry),
                exit=exit_price,
                return_pct=change,
                bars_held=horizon,
            )
        )
    return outcomes


def summarize(outcomes: Sequence[Outcome]) -> dict[str, float]:
    """Aggregate outcomes into win rate and return statistics."""
    if not outcomes:
        return {
            "count": 0,
            "win_rate": 0.0,
            "avg_return_pct": 0.0,
            "best_pct": 0.0,
            "worst_pct": 0.0,
        }
    returns = [outcome.return_pct for outcome in outcomes]
    return {
        "count": len(returns),
        "win_rate": 100.0 * sum(1 for value in returns if value > 0) / len(returns),
        "avg_return_pct": sum(returns) / len(returns),
        "best_pct": max(returns),
        "worst_pct": min(returns),
    }
