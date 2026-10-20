"""Walk-forward backtester for the closed-candle signal engine.

The simulation never looks ahead: a decision made at the close of candle ``i``
is filled at the *open* of candle ``i + 1``. Stops and targets are checked
against each later candle's high/low; when both are touched inside the same
candle the stop is assumed to fill first (the conservative choice). Results are
expressed in R multiples (1R = the initial stop distance) so they are
independent of account size. Past simulated results do not predict the future.
"""

from __future__ import annotations

import hashlib
import math
import struct
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from .indicators import analyze

Candle = Sequence[float]


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    min_score: int = 2
    stop_atr_multiple: float = 1.5
    reward_to_risk: float = 2.0
    lookback: int = 200
    spread: float = 0.0
    exit_on_opposite: bool = True
    max_bars_in_trade: int = 0

    def __post_init__(self) -> None:
        if not 1 <= self.min_score <= 4:
            raise ValueError("min_score must be between 1 and 4")
        for name in ("stop_atr_multiple", "reward_to_risk"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.lookback < 61:
            raise ValueError("lookback must be at least 61 candles")
        if not math.isfinite(self.spread) or self.spread < 0:
            raise ValueError("spread must not be negative")
        if self.max_bars_in_trade < 0:
            raise ValueError("max_bars_in_trade must not be negative")


@dataclass(slots=True)
class Trade:
    direction: str
    entry_time: int
    entry: float
    stop: float
    target: float
    exit_time: int | None = None
    exit: float | None = None
    reason: str = ""
    r_multiple: float = 0.0
    bars: int = 0


@dataclass(slots=True)
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    candles_tested: int = 0

    @property
    def stats(self) -> dict[str, Any]:
        closed = [trade for trade in self.trades if trade.exit is not None]
        returns = [trade.r_multiple for trade in closed]
        wins = [value for value in returns if value > 0]
        losses = [value for value in returns if value <= 0]
        gross_win, gross_loss = sum(wins), -sum(losses)
        peak = drawdown = 0.0
        for equity in self.equity_curve:
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        mean = sum(returns) / len(returns) if returns else 0.0
        variance = (
            sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
            if len(returns) > 1
            else 0.0
        )
        deviation = math.sqrt(variance)
        return {
            "candles_tested": self.candles_tested,
            "trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(closed) * 100.0 if closed else 0.0,
            "total_r": sum(returns),
            "expectancy_r": mean,
            "profit_factor": (gross_win / gross_loss)
            if gross_loss
            else (math.inf if gross_win else 0.0),
            "max_drawdown_r": drawdown,
            "sharpe_per_trade": mean / deviation if deviation else 0.0,
            "avg_bars": sum(trade.bars for trade in closed) / len(closed)
            if closed
            else 0.0,
            "long_trades": sum(trade.direction == "BUY" for trade in closed),
            "short_trades": sum(trade.direction == "SELL" for trade in closed),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "stats": self.stats,
            "trades": [asdict(trade) for trade in self.trades],
            "equity_curve": self.equity_curve,
        }


def _direction(signal: dict[str, Any] | None, min_score: int) -> str | None:
    if not signal or abs(signal["score"]) < min_score:
        return None
    if "BUY" in signal["signal"]:
        return "BUY"
    if "SELL" in signal["signal"]:
        return "SELL"
    return None


def _close(trade: Trade, time: int, price: float, reason: str, bars: int) -> None:
    risk = abs(trade.entry - trade.stop)
    move = price - trade.entry if trade.direction == "BUY" else trade.entry - price
    trade.exit_time, trade.exit, trade.reason, trade.bars = time, price, reason, bars
    trade.r_multiple = move / risk if risk else 0.0


@dataclass(frozen=True, slots=True)
class DecisionCache:
    """Minimal decision metrics for one fingerprinted candle series.

    Analysis depends only on candles and lookback, not on stops, targets, or
    score thresholds, so a parameter grid can share one cache. Only fields used
    by the simulator are retained; full ``analyze()`` outputs contain per-window
    close arrays and can multiply cache memory on long histories.
    """

    lookback: int
    length: int
    fingerprint: str
    values: dict[int, dict[str, Any] | None]


def _rows(candles: Sequence[Candle]) -> list[tuple[float, ...]]:
    rows = []
    for candle in candles:
        if len(candle) < 5:
            raise ValueError(
                "each candle must contain timestamp, open, high, low, close"
            )
        rows.append(tuple(float(value) for value in candle[:5]))
    return rows


def _fingerprint(rows: Sequence[Sequence[float]]) -> str:
    digest = hashlib.blake2b(digest_size=16)
    for row in rows:
        digest.update(struct.pack("!5d", *row))
    return digest.hexdigest()


def build_decision_cache(
    candles: Sequence[Candle], lookback: int = 200
) -> DecisionCache:
    """Precompute the analysis the simulator would otherwise repeat per config."""
    if lookback < 61:
        raise ValueError("lookback must be at least 61 candles")
    rows = _rows(candles)
    values: dict[int, dict[str, Any] | None] = {}
    for index in range(61, len(rows) - 1):
        analysis = analyze(rows[max(0, index + 2 - lookback) : index + 2])
        values[index] = (
            None
            if analysis is None
            else {
                "signal": analysis["signal"],
                "score": analysis["score"],
                "atr": analysis["atr"],
            }
        )
    return DecisionCache(
        lookback=lookback,
        length=len(rows),
        fingerprint=_fingerprint(rows),
        values=values,
    )


def run_backtest(
    candles: Sequence[Candle],
    config: BacktestConfig | None = None,
    *,
    cache: DecisionCache | None = None,
) -> BacktestResult:
    """Simulate the signal engine over historical candles, oldest first.

    Pass a ``cache`` built from the same candles and lookback to skip re-running
    the indicator analysis; the result is identical to running without one.
    """
    config = config or BacktestConfig()
    rows = _rows(candles)
    if cache is not None and (
        cache.lookback != config.lookback
        or cache.length != len(rows)
        or cache.fingerprint != _fingerprint(rows)
    ):
        raise ValueError("cache was built for different candles or lookback")
    result = BacktestResult(candles_tested=len(rows))
    equity = 0.0
    trade: Trade | None = None
    entry_index = 0
    half_spread = config.spread / 2.0
    # Decision at close of candle i uses rows[..i] plus row i+1 as the
    # "in-progress" candle that analyze() discards; the fill is row i+1's open.
    for i in range(61, len(rows) - 1):
        nxt = rows[i + 1]
        if trade is not None:
            bar = rows[i]
            bars = i - entry_index + 1
            hit_stop = (
                bar[3] <= trade.stop
                if trade.direction == "BUY"
                else bar[2] >= trade.stop
            )
            hit_target = (
                bar[2] >= trade.target
                if trade.direction == "BUY"
                else bar[3] <= trade.target
            )
            if hit_stop:
                _close(trade, int(bar[0]), trade.stop, "stop", bars)
            elif hit_target:
                _close(trade, int(bar[0]), trade.target, "target", bars)
            elif config.max_bars_in_trade and bars >= config.max_bars_in_trade:
                _close(trade, int(bar[0]), bar[4], "time", bars)
            if trade.exit is not None:
                equity += trade.r_multiple
                result.equity_curve.append(equity)
                trade = None
        if cache is not None:
            analysis = cache.values[i]
        else:
            window = rows[max(0, i + 2 - config.lookback) : i + 2]
            analysis = analyze(window)
        direction = _direction(analysis, config.min_score)
        if trade is not None:
            if config.exit_on_opposite and direction and direction != trade.direction:
                price = (
                    nxt[1] - half_spread
                    if trade.direction == "BUY"
                    else nxt[1] + half_spread
                )
                _close(
                    trade, int(nxt[0]), price, "opposite signal", i + 1 - entry_index
                )
                equity += trade.r_multiple
                result.equity_curve.append(equity)
                trade = None
            else:
                continue
        if direction is None or analysis is None or not analysis["atr"]:
            continue
        distance = analysis["atr"] * config.stop_atr_multiple
        if direction == "BUY":
            entry = nxt[1] + half_spread
            stop, target = entry - distance, entry + distance * config.reward_to_risk
        else:
            entry = nxt[1] - half_spread
            stop, target = entry + distance, entry - distance * config.reward_to_risk
        if stop <= 0 or target <= 0:
            continue
        trade = Trade(direction, int(nxt[0]), entry, stop, target)
        result.trades.append(trade)
        entry_index = i + 1
    if trade is not None and rows:
        last = rows[-1]
        _close(trade, int(last[0]), last[4], "end of data", len(rows) - entry_index)
        equity += trade.r_multiple
        result.equity_curve.append(equity)
    return result
