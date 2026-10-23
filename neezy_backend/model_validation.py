"""Held-out, model-specific trade simulation for cloud validation jobs.

The PC executor never runs this module's backtest. It only checks the small,
hash-bound validation document produced by a training job. The simulation uses
only the final 15% of candles, matching :func:`brain.train_model`'s untouched
test partition. Signals are formed at a candle close and filled at the next
candle's open; when stop and target share a candle, the stop fills first.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from .brain import (
    _as_of_features,
    _indicator_arrays,
    _score,
    _validate_candles,
    validate_model,
)

Candle = Sequence[float]


def _finite_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("backtest settings must be finite numbers")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("backtest settings must be finite numbers")
    return result


def _result_stats(returns: Sequence[float], candles_tested: int) -> dict[str, Any]:
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value <= 0]
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    count = len(returns)
    return {
        "candles_tested": candles_tested,
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / count * 100.0, 4) if count else 0.0,
        "total_r": round(sum(returns), 6),
        "expectancy_r": round(sum(returns) / count, 6) if count else 0.0,
        "profit_factor": round(gross_win / gross_loss, 6) if gross_loss else None,
        "max_drawdown_r": round(drawdown, 6),
    }


def backtest_model(
    candles: Sequence[Candle],
    model: dict[str, Any],
    *,
    minimum_probability: float = 0.60,
    stop_atr_multiple: float = 1.5,
    reward_to_risk: float = 2.0,
    spread: float = 0.0,
    min_trades: int = 20,
) -> dict[str, Any]:
    """Simulate the exact model on its chronological, untouched test slice.

    ``spread`` is a full bid/ask spread in price units, not pips. One position
    is open at a time and a new signal is considered only after that position
    exits. This deliberately simple simulation is a promotion gate, not a
    promise of live performance.
    """
    validate_model(model)
    probability = _finite_number(minimum_probability)
    stop_multiple = _finite_number(stop_atr_multiple)
    reward = _finite_number(reward_to_risk)
    spread_value = _finite_number(spread)
    if not 0.5 < probability < 1.0:
        raise ValueError("minimum_probability must be between 0.5 and 1")
    if stop_multiple <= 0 or reward <= 0:
        raise ValueError("stop and reward multiples must be positive")
    if spread_value < 0:
        raise ValueError("spread must not be negative")
    if isinstance(min_trades, bool) or not isinstance(min_trades, int):
        raise ValueError("min_trades must be an integer")
    if not 1 <= min_trades <= 100_000:
        raise ValueError("min_trades must be between 1 and 100000")

    rows = _validate_candles(candles)
    if len(rows) < 100:
        raise ValueError("at least 100 candles are required for model validation")
    series = _indicator_arrays(rows)
    horizon = int(model["horizon"])
    ready = bool(model.get("deployment_ready", False))
    test_start = max(80, int(len(rows) * 0.85))
    returns: list[float] = []
    index = test_start
    final_source = len(rows) - 2

    while index < final_source:
        built = _as_of_features(series, index, 0)
        # Sequence models need their own lag window; v1 and ensembles use zero.
        if model["model_type"] == "neezy_seq_mlp_v1":
            built = _as_of_features(series, index, int(model["window"]))
        if built is None:
            index += 1
            continue
        features, atr_value = built
        up_probability, _spread_value = _score(features, model)
        direction = (
            "BUY"
            if ready and up_probability >= probability
            else "SELL"
            if ready and up_probability <= 1.0 - probability
            else "NEUTRAL"
        )
        if direction == "NEUTRAL":
            index += 1
            continue

        entry_index = index + 1
        side = 1 if direction == "BUY" else -1
        # Market buys pay half the spread and market sells receive half less.
        entry = rows[entry_index][1] + side * spread_value / 2.0
        risk_distance = atr_value * stop_multiple
        if (
            entry <= 0
            or risk_distance <= 0
            or (direction == "BUY" and entry - risk_distance <= 0)
        ):
            index += 1
            continue
        stop = entry - side * risk_distance
        target = entry + side * risk_distance * reward
        if target <= 0:
            index += 1
            continue

        last_bar = min(entry_index + horizon - 1, len(rows) - 1)
        exit_index = last_bar
        exit_price = rows[last_bar][4]
        for bar_index in range(entry_index, last_bar + 1):
            bar = rows[bar_index]
            open_, high, low = bar[1], bar[2], bar[3]
            if direction == "BUY":
                hit_stop = low <= stop
                hit_target = high >= target
                # A gap through a stop receives the worse opening price.
                stop_fill = min(stop, open_) if open_ < stop else stop
            else:
                hit_stop = high >= stop
                hit_target = low <= target
                stop_fill = max(stop, open_) if open_ > stop else stop
            if hit_stop:
                exit_index = bar_index
                exit_price = stop_fill
                break
            if hit_target:
                exit_index = bar_index
                exit_price = target
                break

        # Charge the other half-spread on exit as well: ``spread`` is the
        # configured full round-trip bid/ask cost assumption in price units.
        exit_fill = exit_price - side * spread_value / 2.0
        r_multiple = side * (exit_fill - entry) / risk_distance
        if not math.isfinite(r_multiple):
            raise ValueError("model backtest produced a non-finite return")
        returns.append(r_multiple)
        # A signal at the exit candle's close may fill on the following candle.
        index = exit_index

    stats = _result_stats(returns, len(rows) - test_start)
    profit_factor = stats["profit_factor"]
    passed = bool(
        stats["trades"] >= min_trades
        and stats["expectancy_r"] > 0
        and (profit_factor is None or profit_factor > 1.0)
    )
    return {
        "passed": passed,
        "method": "chronological_held_out_trade_backtest_v1",
        "test_start_epoch": rows[test_start][0],
        "minimum_probability": probability,
        "stop_atr_multiple": stop_multiple,
        "reward_to_risk": reward,
        "spread": spread_value,
        "min_trades": min_trades,
        **stats,
        "note": (
            "Held-out historical simulation with next-open entries and "
            "stop-first ambiguous candles; not a forecast."
        ),
    }
