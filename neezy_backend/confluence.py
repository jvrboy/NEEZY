"""Multi-factor confluence engine.

The confluence engine is the backend the ANALYSIS button and the strategy
scanner use. It combines every analysis tool available - the core indicator
score, all named strategies, oscillator divergence, the shipped learned edge
weights, and the market regime - into one weighted vote, then translates the
result into a card-shaped signal:

    INSTRUMENT | BUY/SELL | ENTRY | SL | TP | WIN RATE

The win rate is "trained" on the market's own closed-candle history: bars whose
cheap per-bar confluence proxies match the current reading are replayed forward
with the ATR-based stop/target and counted as hit-TP-first or hit-SL-first.
This is an educational in-sample replay, not a forecast. Nothing here places
orders or contacts a broker.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config import AppSettings
from .datasets import weight_for
from .indicators import adx, atr, bollinger, ema, macd_histogram_series, rsi_series
from .strategies import run_all
from .trend import supertrend

Candle = Sequence[float]

DEFAULT_MIN_SCORE = 55.0
DEFAULT_SEARCH_SCORE = 30.0
DEFAULT_STOP_MULT = 1.5
DEFAULT_TP_MULT = 2.5
DEFAULT_HORIZON = 20
DEFAULT_MIN_ANALOGS = 4
MIN_CLOSED_CANDLES = 70


@dataclass(frozen=True, slots=True)
class ConfluenceFactor:
    """One weighted vote inside the confluence."""

    name: str
    direction: int
    weight: float
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction": self.direction,
            "weight": round(self.weight, 3),
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> ConfluenceFactor:
        """Build a factor from its serialized form.

        Unknown keys are ignored (forward-compatible); known keys are
        type-checked so a corrupt record fails loudly at the boundary.
        """
        if not isinstance(values, dict):
            raise ValueError(f"factor must be a mapping, got {type(values).__name__}")
        name = values.get("name", "")
        detail = values.get("detail", "")
        if not isinstance(name, str) or not isinstance(detail, str):
            raise ValueError("factor name and detail must be strings")
        try:
            direction = int(values.get("direction", 0))
            weight = float(values.get("weight", 0.0))
        except (TypeError, ValueError) as err:
            msg = f"factor {name!r}: direction/weight must be numeric"
            raise ValueError(msg) from err
        if direction not in (-1, 0, 1):
            raise ValueError(f"factor {name!r}: direction must be -1, 0, or 1")
        if weight < 0:
            raise ValueError(f"factor {name!r}: weight must not be negative")
        return cls(name=name, direction=direction, weight=weight, detail=detail)


@dataclass(frozen=True, slots=True)
class ConfluenceSignal:
    """A card-ready directional signal with confluence metadata."""

    symbol: str
    instrument: str
    timeframe: str
    direction: int
    entry: float
    stop_loss: float
    take_profit: float
    win_rate: float
    score: float
    factors: tuple[ConfluenceFactor, ...] = ()
    created_at: str = ""
    mode: str = "strict"
    win_rate_basis: str = ""
    votes: dict[str, int] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """BUY or SELL - the direction is never neutral once a signal exists."""
        return "BUY" if self.direction > 0 else "SELL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "label": self.label,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "win_rate": round(self.win_rate, 1),
            "score": round(self.score, 1),
            "mode": self.mode,
            "win_rate_basis": self.win_rate_basis,
            "factors": [factor.to_dict() for factor in self.factors],
            "votes": dict(self.votes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> ConfluenceSignal:
        """Build a signal from its ``to_dict`` wire form.

        Unknown keys are ignored so newer producers stay readable by older
        consumers; every known key is validated and coerced, and impossible
        values raise ``ValueError`` with the offending field named.
        """
        if not isinstance(values, dict):
            raise ValueError(f"signal must be a mapping, got {type(values).__name__}")
        for key in ("symbol", "instrument", "timeframe", "created_at"):
            value = values.get(key, "")
            if value is not None and not isinstance(value, str):
                raise ValueError(f"signal field {key!r} must be a string")
        try:
            direction = int(values.get("direction", 0))
        except (TypeError, ValueError) as err:
            raise ValueError("signal field 'direction' must be an integer") from err
        if direction not in (-1, 0, 1):
            raise ValueError("signal field 'direction' must be -1, 0, or 1")
        numeric: dict[str, float] = {}
        for key in ("entry", "stop_loss", "take_profit", "win_rate", "score"):
            try:
                numeric[key] = float(values.get(key, 0.0))
            except (TypeError, ValueError) as err:
                raise ValueError(f"signal field {key!r} must be numeric") from err
        raw_factors = values.get("factors") or []
        if not isinstance(raw_factors, list):
            raise ValueError("signal field 'factors' must be a list")
        factors = tuple(ConfluenceFactor.from_dict(item) for item in raw_factors)
        raw_votes = values.get("votes") or {}
        if not isinstance(raw_votes, dict):
            raise ValueError("signal field 'votes' must be a mapping")
        try:
            votes = {str(key): int(value) for key, value in raw_votes.items()}
        except (TypeError, ValueError) as err:
            raise ValueError("signal field 'votes' values must be integers") from err
        mode = values.get("mode", "strict")
        basis = values.get("win_rate_basis", "")
        if not isinstance(mode, str) or not isinstance(basis, str):
            raise ValueError("signal 'mode' and 'win_rate_basis' must be strings")
        return cls(
            symbol=values.get("symbol", ""),
            instrument=values.get("instrument", ""),
            timeframe=values.get("timeframe", ""),
            direction=direction,
            entry=numeric["entry"],
            stop_loss=numeric["stop_loss"],
            take_profit=numeric["take_profit"],
            win_rate=numeric["win_rate"],
            score=numeric["score"],
            factors=factors,
            created_at=values.get("created_at", ""),
            mode=mode,
            win_rate_basis=basis,
            votes=votes,
        )

    def as_history_record(self) -> dict[str, Any]:
        """Fields persisted to the local confluence history store."""
        return {
            "timestamp": self.created_at,
            "symbol": self.symbol,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "direction": self.direction,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "win_rate": round(self.win_rate, 1),
            "score": round(self.score, 1),
            "mode": self.mode,
            "outcome": None,
        }

    @classmethod
    def from_history_record(cls, record: dict[str, Any]) -> ConfluenceSignal:
        """Build a signal from a persisted history record.

        The persisted shape (:meth:`as_history_record` plus the store-managed
        ``outcome`` key) carries no factors or votes, so those default empty;
        ``outcome`` itself is store metadata and is deliberately not part of
        the signal. Unknown keys are ignored.
        """
        if not isinstance(record, dict):
            raise ValueError(
                f"history record must be a mapping, got {type(record).__name__}"
            )
        return cls.from_dict(
            {
                "symbol": record.get("symbol", ""),
                "instrument": record.get("instrument", ""),
                "timeframe": record.get("timeframe", ""),
                "direction": record.get("direction", 0),
                "entry": record.get("entry", 0.0),
                "stop_loss": record.get("stop_loss", 0.0),
                "take_profit": record.get("take_profit", 0.0),
                "win_rate": record.get("win_rate", 0.0),
                "score": record.get("score", 0.0),
                "created_at": record.get("timestamp", ""),
                "mode": record.get("mode", "strict"),
            }
        )


# ---------------------------------------------------------------------------
# Historical win rate ("further training" pass over the local candle buffer)
# ---------------------------------------------------------------------------


def _direction_series(closes: Sequence[float]) -> list[int]:
    return [1 if value > 0 else -1 if value < 0 else 0 for value in closes]


class _ProxyBundle:
    """Cheap per-bar confluence proxies used for analog matching."""

    def __init__(self, closed: Sequence[Candle]) -> None:
        closes = [row[4] for row in closed]
        highs = [row[2] for row in closed]
        lows = [row[3] for row in closed]
        ema9, ema21, ema50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
        histogram = macd_histogram_series(closes)
        rsi = rsi_series(closes, 14)
        st_series = supertrend(highs, lows, closes)
        self.votes: tuple[list[int], ...] = (
            _direction_series([a - b for a, b in zip(ema9, ema21, strict=True)]),
            _direction_series([a - b for a, b in zip(closes, ema50, strict=True)]),
            _direction_series(histogram),
            [
                1
                if value is not None and value > 50
                else -1
                if value is not None and value < 50
                else 0
                for value in rsi
            ],
            [int(entry["direction"] or 0) for entry in st_series],
        )

    def agreement(self, index: int, direction: int) -> int:
        total = 0
        for series in self.votes:
            if series[index] == direction:
                total += 1
        return total


def historical_win_rate(
    closed: Sequence[Candle],
    direction: int,
    *,
    stop_distance: float,
    take_distance: float,
    horizon: int = DEFAULT_HORIZON,
    min_analogs: int = DEFAULT_MIN_ANALOGS,
    max_scan: int = 400,
) -> tuple[float, int] | None:
    """Replay analog bars and count TP-first versus SL-first outcomes.

    Returns ``(win_rate, samples)`` or ``None`` when the history is too short or
    no analog with the current agreement level exists. When both the stop and
    the target are touched inside one candle the stop is assumed to fill first,
    matching the backtest methodology used across the backend.
    """
    if len(closed) < horizon + 3:
        return None
    bundle = _ProxyBundle(closed)
    current = bundle.agreement(len(closed) - 1, direction)
    # Relax the match threshold until enough analog bars are found, but never
    # below a bare majority of the proxy set.
    threshold = current
    floor = 3
    for _ in range(3):
        if threshold <= floor:
            break
        analogs = _count_analogs(
            bundle, closed, direction, threshold, horizon, max_scan
        )
        if analogs >= min_analogs:
            break
        threshold -= 1
    wins = losses = 0
    start = max(4, len(closed) - max_scan)
    for index in range(start, len(closed) - horizon):
        if bundle.agreement(index, direction) < threshold:
            continue
        entry = closed[index][4]
        stop = entry - direction * stop_distance
        target = entry + direction * take_distance
        outcome = _replay(closed, index, direction, stop, target, horizon)
        if outcome == "TP":
            wins += 1
        elif outcome == "SL":
            losses += 1
    samples = wins + losses
    if samples <= 0:
        return None
    return 100.0 * wins / samples, samples


def _count_analogs(
    bundle: _ProxyBundle,
    closed: Sequence[Candle],
    direction: int,
    threshold: int,
    horizon: int,
    max_scan: int,
) -> int:
    start = max(4, len(closed) - max_scan)
    return sum(
        1
        for index in range(start, len(closed) - horizon)
        if bundle.agreement(index, direction) >= threshold
    )


def _replay(
    closed: Sequence[Candle],
    index: int,
    direction: int,
    stop: float,
    target: float,
    horizon: int,
) -> str | None:
    """Walk forward one analog bar; always returns TP first or SL first."""
    for offset in range(index + 1, min(index + 1 + horizon, len(closed))):
        high, low = closed[offset][2], closed[offset][3]
        if direction > 0:
            hit_stop, hit_target = low <= stop, high >= target
        else:
            hit_stop, hit_target = high >= stop, low <= target
        if hit_stop and hit_target:
            return "SL"  # conservative: the stop fills first inside one candle
        if hit_stop:
            return "SL"
        if hit_target:
            return "TP"
    return None


def resolve_outcome(
    direction: int,
    entry: float,
    stop_loss: float,
    take_profit: float,
    candles_after: Sequence[Candle],
    horizon: int = DEFAULT_HORIZON,
) -> str | None:
    """Outcome of one recorded signal: exactly ``TP`` or ``SL``, or None.

    ``candles_after`` holds the closed candles that formed after the signal.
    When both levels sit inside one candle the stop is assumed to fill first.
    Returns ``None`` while neither level has been reached - the only permitted
    final states are TP and SL, never a third outcome.
    """
    if direction == 0 or len(candles_after) == 0:
        return None
    if direction > 0:
        if take_profit <= entry or stop_loss >= entry:
            return None
    else:
        if take_profit >= entry or stop_loss <= entry:
            return None
    for offset in range(min(horizon, len(candles_after))):
        high, low = candles_after[offset][2], candles_after[offset][3]
        if direction > 0:
            hit_stop, hit_target = low <= stop_loss, high >= take_profit
        else:
            hit_stop, hit_target = high >= stop_loss, low <= take_profit
        if hit_stop and hit_target:
            return "SL"
        if hit_stop:
            return "SL"
        if hit_target:
            return "TP"
    return None


# ---------------------------------------------------------------------------
# Confluence builder
# ---------------------------------------------------------------------------


def _factors(
    closed: list[Candle], symbol: str
) -> tuple[tuple[ConfluenceFactor, ...], dict[str, int], float | None]:
    """Collect the weighted votes from every backend analysis tool."""
    factors: list[ConfluenceFactor] = []
    votes = {"buy": 0, "sell": 0, "neutral": 0}
    highs = [row[2] for row in closed]
    lows = [row[3] for row in closed]
    closes = [row[4] for row in closed]

    ema9, ema21, ema50 = ema(closes, 9), ema(closes, 21), ema(closes, 50)
    core = (1 if ema9[-1] > ema21[-1] else -1) + (1 if closes[-1] > ema50[-1] else -1)
    factors.append(
        ConfluenceFactor(
            "EMA stack",
            1 if core > 0 else -1 if core < 0 else 0,
            1.2,
            f"EMA 9/21 {'above' if ema9[-1] > ema21[-1] else 'below'} and price "
            f"{'above' if closes[-1] > ema50[-1] else 'below'} EMA 50",
        )
    )
    histogram = macd_histogram_series(closes)
    macd_direction = 1 if histogram[-1] > 0 else -1 if histogram[-1] < 0 else 0
    factors.append(
        ConfluenceFactor(
            "MACD momentum", macd_direction, 1.0, f"histogram {histogram[-1]:+.6f}"
        )
    )
    rsi = rsi_series(closes, 14)[-1]
    rsi_direction = (
        1 if rsi is not None and rsi < 35 else -1 if rsi is not None and rsi > 65 else 0
    )
    rsi_detail = (
        "oversold"
        if rsi_direction > 0
        else "overbought"
        if rsi_direction < 0
        else f"neutral at {rsi:.1f}"
        if rsi is not None
        else "warming up"
    )
    factors.append(ConfluenceFactor("RSI", rsi_direction, 0.7, rsi_detail))
    dm = adx(highs, lows, closes)
    if dm is not None:
        trend_direction = (
            1
            if dm["plus_di"] > dm["minus_di"]
            else -1
            if dm["minus_di"] > dm["plus_di"]
            else 0
        )
        factors.append(
            ConfluenceFactor(
                "ADX trend",
                trend_direction,
                min(dm["adx"], 50.0) / 50.0,
                f"ADX {dm['adx']:.1f}, "
                f"DI {'+' if trend_direction > 0 else '-'} dominant",
            )
        )
    bands = bollinger(closes)
    if bands is not None:
        band_direction = (
            1 if bands["percent_b"] < 0.1 else -1 if bands["percent_b"] > 0.9 else 0
        )
        factors.append(
            ConfluenceFactor(
                "Bollinger extreme",
                band_direction,
                0.6,
                f"%B {bands['percent_b']:.2f}",
            )
        )
    for signal in run_all(closed):
        if signal.direction:
            factors.append(
                ConfluenceFactor(
                    signal.strategy.replace("_", " ").title(),
                    signal.direction,
                    0.9,
                    signal.summary,
                )
            )
    learned = weight_for(symbol)
    if learned is not None:
        try:
            edge = float(learned.get("edge_weight", 0.0) or 0.0)
            factors.append(
                ConfluenceFactor(
                    "Learned edge weight",
                    1 if edge > 0 else -1 if edge < 0 else 0,
                    0.5,
                    f"edge weight {edge:+.3f} from past studies",
                )
            )
        except (TypeError, ValueError):
            pass
    for factor in factors:
        if factor.direction > 0:
            votes["buy"] += 1
        elif factor.direction < 0:
            votes["sell"] += 1
        else:
            votes["neutral"] += 1
    return tuple(factors), votes, atr(highs, lows, closes)


def build_confluence(
    candles: Sequence[Candle],
    symbol: str,
    timeframe: str,
    *,
    min_score: float = DEFAULT_MIN_SCORE,
    search: bool = False,
    stop_mult: float = DEFAULT_STOP_MULT,
    tp_mult: float = DEFAULT_TP_MULT,
    horizon: int = DEFAULT_HORIZON,
    min_analogs: int = DEFAULT_MIN_ANALOGS,
    instrument: str = "",
) -> ConfluenceSignal | None:
    """Combine every backend tool into one card-ready confluence signal.

    Strict mode returns ``None`` unless the weighted vote clears ``min_score``.
    Search mode (the ANALYSIS button) never returns None with enough candles:
    it relaxes the score, and when even the relaxed vote is split it takes the
    dominant side from the strongest factors, so the button always provides a
    signal.
    """
    closed = list(candles[:-1]) if len(candles) > 1 else []
    if len(closed) < MIN_CLOSED_CANDLES:
        return None
    factors, votes, atr_value = _factors(closed, symbol)
    buy_weight = sum(factor.weight for factor in factors if factor.direction > 0)
    sell_weight = sum(factor.weight for factor in factors if factor.direction < 0)
    total = buy_weight + sell_weight
    score = (buy_weight - sell_weight) / total * 100.0 if total else 0.0
    if not search and abs(score) < min_score:
        return None
    direction = 1 if score >= 0 else -1
    if total == 0:
        # No directional factor at all - fall back to the cheapest momentum read
        closes = [row[4] for row in closed]
        direction = 1 if closes[-1] > closes[-2] else -1
        score = 25.0 if search else 0.0
        if not search:
            return None
    if search:
        score = max(abs(score), DEFAULT_SEARCH_SCORE)
    entry = float(closed[-1][4])
    if atr_value is None or atr_value <= 0:
        atr_value = sum(high - low for _, _, high, low, _ in closed[-14:]) / 14.0
    stop_distance = max(stop_mult * atr_value, entry * 1e-6)
    take_distance = max(tp_mult * atr_value, entry * 1e-6)
    stop_loss = entry - direction * stop_distance
    take_profit = entry + direction * take_distance
    analog = historical_win_rate(
        closed,
        direction,
        stop_distance=stop_distance,
        take_distance=take_distance,
        horizon=horizon,
        min_analogs=min_analogs,
    )
    if analog is not None:
        win_rate, samples = analog
        basis = f"{samples} analog bars replayed {horizon} bars forward"
    else:
        win_rate = min(92.0, 50.0 + abs(score) * 0.3)
        basis = "confluence-strength estimate (not enough matching history)"
    from .markets import display_name

    return ConfluenceSignal(
        symbol=symbol,
        instrument=instrument or display_name(symbol),
        timeframe=timeframe,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        win_rate=win_rate,
        score=abs(score),
        factors=factors,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        mode="search" if search else "strict",
        win_rate_basis=basis,
        votes=votes,
    )


def scan_candles(
    candles_by_symbol: dict[str, Sequence[Candle]],
    timeframe: str,
    settings: AppSettings | None = None,
) -> list[ConfluenceSignal]:
    """Run strict confluence over a candle map, then search mode to fill gaps."""
    config = settings
    min_score = config.confluence_min_score if config is not None else DEFAULT_MIN_SCORE
    stop_mult = (
        config.confluence_atr_stop_mult if config is not None else DEFAULT_STOP_MULT
    )
    tp_mult = config.confluence_atr_tp_mult if config is not None else DEFAULT_TP_MULT
    horizon = config.confluence_horizon if config is not None else DEFAULT_HORIZON
    min_analogs = (
        config.confluence_min_analogs if config is not None else DEFAULT_MIN_ANALOGS
    )
    signals: list[ConfluenceSignal] = []
    pending: dict[str, Sequence[Candle]] = {}
    for symbol, candles in candles_by_symbol.items():
        strict = build_confluence(
            candles,
            symbol,
            timeframe,
            min_score=min_score,
            stop_mult=stop_mult,
            tp_mult=tp_mult,
            horizon=horizon,
            min_analogs=min_analogs,
        )
        if strict is not None:
            signals.append(strict)
        else:
            pending[symbol] = candles
    for symbol, candles in pending.items():
        searched = build_confluence(
            candles,
            symbol,
            timeframe,
            search=True,
            stop_mult=stop_mult,
            tp_mult=tp_mult,
            horizon=horizon,
            min_analogs=min_analogs,
        )
        if searched is not None:
            signals.append(searched)
    signals.sort(key=lambda signal: -signal.score)
    return signals


def describe_factor_set(signal: ConfluenceSignal) -> str:
    """Compact factor breakdown for the detail panel and CLI output."""
    lines = [
        f"{factor.name} {'+' if factor.direction > 0 else '-'} "
        f"(w={factor.weight:g}): {factor.detail}"
        for factor in signal.factors
    ]
    return "\n".join(lines)


def format_signal(signal: ConfluenceSignal) -> str:
    """One-line card summary used by the CLI."""
    return (
        f"{signal.instrument:<18} {signal.label:<4} "
        f"E {signal.entry:.6g}  SL {signal.stop_loss:.6g}  "
        f"TP {signal.take_profit:.6g}  WIN {signal.win_rate:.1f}%  "
        f"[{signal.mode} {signal.score:.0f}]"
    )
