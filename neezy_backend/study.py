"""Train-then-validate study of the backtest rules, one instrument at a time.

Each instrument's history is split in two. A grid of rule settings is simulated
on the earlier slice and the setting with the best expectancy (and enough
trades) is kept. That one setting is then run on the later slice, which the
search never saw. The verdict records whether it stayed profitable there.

Limits: a spread is charged per trade (``StudySettings.spread_pips``), but
slippage and commission are not modelled, and trades still open at a slice
boundary are closed at the last close in that slice. A result is a statement
about one historical window, not a forecast.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from itertools import accumulate
from typing import Any

from .backtest import (
    BacktestConfig,
    BacktestResult,
    Candle,
    Trade,
    build_decision_cache,
    run_backtest,
)
from .catalog import instrument
from .knowledge import empty_document
from .markets import pip_size
from .stream import fetch_history

Fetch = Callable[[str, int, int], list[Candle]]


def default_grid() -> tuple[BacktestConfig, ...]:
    """Rule settings searched on the training slice (18 combinations)."""
    return tuple(
        BacktestConfig(min_score=score, stop_atr_multiple=stop, reward_to_risk=rr)
        for score in (2, 3)
        for stop in (1.0, 1.5, 2.0)
        for rr in (1.5, 2.0, 3.0)
    )


@dataclass(frozen=True, slots=True)
class StudySettings:
    granularity: int = 60
    candles: int = 12_000
    lookback: int = 200
    train_fraction: float = 0.7
    min_train_trades: int = 30
    min_test_trades: int = 20
    min_candles: int = 2_000
    # Full bid/ask spread charged per trade, in pips (see pip_size). Zero would
    # report pre-cost edges; the default charges one pip, a deliberately rough
    # assumption that the caller should adjust per market.
    spread_pips: float = 1.0
    # Longest wait for one instrument's history. A stalled connection is then
    # recorded as an error for that market instead of blocking the whole run.
    fetch_timeout: float = 240.0
    grid: tuple[BacktestConfig, ...] = field(default_factory=default_grid)

    def __post_init__(self) -> None:
        if self.granularity < 1:
            raise ValueError("granularity must be a positive number of seconds")
        if not 0.5 <= self.train_fraction < 1.0:
            raise ValueError("train_fraction must be between 0.5 and 1.0")
        if self.lookback < 61:
            raise ValueError("lookback must be at least 61 candles")
        if self.min_candles < 3 * self.lookback:
            raise ValueError("min_candles must be at least three times the lookback")
        if self.candles < self.min_candles:
            raise ValueError("candles must be at least min_candles")
        if self.min_train_trades < 1 or self.min_test_trades < 1:
            raise ValueError("trade minimums must be at least 1")
        if not self.grid:
            raise ValueError("grid must contain at least one setting")
        if not math.isfinite(self.spread_pips) or self.spread_pips < 0:
            raise ValueError("spread_pips must be zero or a positive number")
        if not math.isfinite(self.fetch_timeout) or self.fetch_timeout <= 0:
            raise ValueError("fetch_timeout must be a positive number of seconds")


def _clean(stats: dict[str, Any]) -> dict[str, Any]:
    """Round floats and turn non-finite values (e.g. infinite profit factor) to null."""
    cleaned: dict[str, Any] = {}
    for key, value in stats.items():
        if isinstance(value, float):
            cleaned[key] = round(value, 4) if math.isfinite(value) else None
        else:
            cleaned[key] = value
    return cleaned


def _slice_stats(
    trades: Sequence[Trade], *, from_time: int | None, candles_tested: int
) -> dict[str, Any]:
    kept = [
        trade
        for trade in trades
        if trade.exit is not None
        and (from_time is None or trade.entry_time >= from_time)
    ]
    curve = list(accumulate(trade.r_multiple for trade in kept))
    result = BacktestResult(
        trades=kept, equity_curve=curve, candles_tested=candles_tested
    )
    return _clean(result.stats)


def evaluate_candles(
    candles: Sequence[Candle], settings: StudySettings, *, spread: float = 0.0
) -> dict[str, Any]:
    """Train on the earlier slice, validate the chosen setting on the later one.

    ``spread`` is the full bid/ask spread in price units charged on every trade.
    """
    cut = int(len(candles) * settings.train_fraction)
    train = candles[:cut]
    test = candles[max(0, cut - settings.lookback) :]
    boundary = int(candles[cut][0])
    configs = [
        replace(config, lookback=settings.lookback, spread=spread)
        for config in settings.grid
    ]

    train_cache = build_decision_cache(train, settings.lookback)
    best: tuple[float, BacktestConfig, dict[str, Any]] | None = None
    for config in configs:
        outcome = run_backtest(train, config, cache=train_cache)
        stats = _slice_stats(outcome.trades, from_time=None, candles_tested=len(train))
        if stats["trades"] < settings.min_train_trades:
            continue
        if best is None or stats["expectancy_r"] > best[0]:
            best = (stats["expectancy_r"], config, stats)
    if best is None:
        return {
            "verdict": "insufficient_data",
            "selected": None,
            "train": None,
            "test": None,
            "note": (
                f"no setting produced {settings.min_train_trades} training trades"
            ),
        }

    _, config, train_stats = best
    test_cache = build_decision_cache(test, settings.lookback)
    outcome = run_backtest(test, config, cache=test_cache)
    test_stats = _slice_stats(
        outcome.trades, from_time=boundary, candles_tested=len(test)
    )
    if test_stats["trades"] < settings.min_test_trades:
        verdict = "insufficient_data"
        note = f"only {test_stats['trades']} held-out trades"
    elif test_stats["expectancy_r"] > 0:
        verdict, note = "edge", ""
    else:
        verdict, note = "no_edge", "held-out expectancy was not positive"
    return {
        "verdict": verdict,
        "selected": asdict(config),
        "train": train_stats,
        "test": test_stats,
        "note": note,
    }


def describe_method(settings: StudySettings) -> str:
    return (
        f"Fixed-rule backtest on {settings.granularity}s candles, up to "
        f"{settings.candles} per instrument, charging a {settings.spread_pips:g}-pip "
        f"spread per trade. The first "
        f"{settings.train_fraction:.0%} of history is searched over a grid of "
        f"{len(settings.grid)} settings; the setting with the best expectancy "
        f"and at least {settings.min_train_trades} trades is then run once on the "
        f"remaining history. Verdict 'edge' means positive expectancy there with "
        f"at least {settings.min_test_trades} trades."
    )


def _bounded_fetch(
    fetch: Fetch, symbol: str, seconds: int, count: int, timeout: float
) -> list[Candle]:
    """Run ``fetch`` on a worker thread and give up after ``timeout`` seconds.

    The abandoned worker is a daemon thread, so it cannot keep the process alive.
    """
    outcome: dict[str, Any] = {}

    def work() -> None:
        try:
            outcome["candles"] = fetch(symbol, seconds, count)
        except BaseException as error:  # noqa: BLE001 - re-raised on the caller below
            outcome["error"] = error

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f"no history for {symbol} within {timeout:g}s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["candles"]


def run_study(
    symbols: Iterable[str],
    settings: StudySettings | None = None,
    *,
    fetch: Fetch = fetch_history,
    progress: Callable[[str, str], None] | None = None,
    on_record: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Study each symbol and return a knowledge document (not yet saved).

    A failed or timed-out fetch and a short history are recorded against that
    symbol rather than stopping the run, so one unreachable market does not
    hide the rest. ``on_record`` is called as each symbol finishes, so a caller
    can checkpoint partial results.
    """
    settings = settings or StudySettings()
    document = empty_document()
    document["method"] = describe_method(settings)
    records: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        item = instrument(symbol)
        market = item.market if item else "unknown"
        try:
            candles = _bounded_fetch(
                fetch,
                symbol,
                settings.granularity,
                settings.candles,
                settings.fetch_timeout,
            )
        except (ConnectionError, OSError, RuntimeError, ValueError) as error:
            record: dict[str, Any] = {
                "market": market,
                "candles": 0,
                "verdict": "error",
                "selected": None,
                "train": None,
                "test": None,
                "note": str(error)[:300],
            }
        else:
            if len(candles) < settings.min_candles:
                outcome: dict[str, Any] = {
                    "verdict": "insufficient_data",
                    "selected": None,
                    "train": None,
                    "test": None,
                    "note": (
                        f"only {len(candles)} candles, need {settings.min_candles}"
                    ),
                }
            else:
                outcome = evaluate_candles(
                    candles,
                    settings,
                    spread=settings.spread_pips * pip_size(symbol),
                )
            record = {"market": market, "candles": len(candles), **outcome}
        records[symbol] = record
        if on_record is not None:
            on_record(symbol, record)
        if progress is not None:
            progress(symbol, record["verdict"])
    document["symbols"] = records
    return document
