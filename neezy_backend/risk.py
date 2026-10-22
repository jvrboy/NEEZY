"""Position sizing and ATR-based risk levels for planning, not order execution."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from .markets import pip_size

STANDARD_LOT_UNITS = 100_000


@dataclass(frozen=True, slots=True)
class RiskPlan:
    direction: str
    entry: float
    stop: float
    target: float
    stop_pips: float
    target_pips: float
    risk_amount: float
    reward_amount: float
    lots: float
    units: int
    reward_to_risk: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _positive(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return value


def atr_levels(
    direction: str,
    entry: float,
    atr_value: float,
    stop_multiple: float = 1.5,
    reward_to_risk: float = 2.0,
) -> tuple[float, float]:
    """Return (stop, target) placed ``stop_multiple`` ATRs from entry."""
    direction = direction.upper()
    if direction not in {"BUY", "SELL"}:
        raise ValueError("direction must be BUY or SELL")
    entry = _positive("entry", entry)
    distance = _positive("atr", atr_value) * _positive("stop_multiple", stop_multiple)
    reward = distance * _positive("reward_to_risk", reward_to_risk)
    if direction == "BUY":
        if entry - distance <= 0:
            raise ValueError("ATR stop would be at or below zero")
        return entry - distance, entry + reward
    return entry + distance, entry - reward


def position_size(
    *,
    symbol: str,
    balance: float,
    risk_percent: float,
    entry: float,
    stop: float,
    reward_to_risk: float = 2.0,
    pip_value_per_lot: float = 10.0,
    lot_step: float = 0.01,
) -> RiskPlan:
    """Size a position so that hitting ``stop`` loses ``risk_percent`` of balance.

    ``pip_value_per_lot`` is the account-currency value of one pip on one
    standard lot (10 for USD-quoted pairs on a USD account). Lots are rounded
    *down* to ``lot_step`` so the plan never risks more than requested.
    """
    balance = _positive("balance", balance)
    risk_percent = _positive("risk_percent", risk_percent)
    if risk_percent > 100:
        raise ValueError("risk_percent must not exceed 100")
    entry, stop = _positive("entry", entry), _positive("stop", stop)
    reward_to_risk = _positive("reward_to_risk", reward_to_risk)
    pip_value_per_lot = _positive("pip_value_per_lot", pip_value_per_lot)
    lot_step = _positive("lot_step", lot_step)
    if entry == stop:
        raise ValueError("stop must differ from entry")
    direction = "BUY" if stop < entry else "SELL"
    distance = abs(entry - stop)
    target = entry + distance * reward_to_risk * (1 if direction == "BUY" else -1)
    if target <= 0:
        raise ValueError("target would be at or below zero")
    stop_pips = distance / pip_size(symbol)
    risk_budget = balance * risk_percent / 100.0
    raw_lots = risk_budget / (stop_pips * pip_value_per_lot)
    lots = math.floor(raw_lots / lot_step + 1e-9) * lot_step
    lots = round(lots, 8)
    risk_amount = lots * stop_pips * pip_value_per_lot
    return RiskPlan(
        direction=direction,
        entry=entry,
        stop=stop,
        target=target,
        stop_pips=stop_pips,
        target_pips=stop_pips * reward_to_risk,
        risk_amount=risk_amount,
        reward_amount=risk_amount * reward_to_risk,
        lots=lots,
        units=round(lots * STANDARD_LOT_UNITS),
        reward_to_risk=reward_to_risk,
    )


def resolve_stop(
    direction: str | None,
    entry: float,
    atr_value: float | None,
    *,
    stop: float | None = None,
    stop_atr: float = 1.5,
    reward_risk: float = 2.0,
) -> tuple[float, float]:
    """Return a validated ``(stop, target)`` pair from explicit or ATR levels.

    Either an explicit ``stop`` is used (direction inferred from which side of
    entry it sits, exactly like :func:`position_size`), or the stop/target are
    derived from ``direction`` and ``atr_value`` via :func:`atr_levels`.
    Raises ``ValueError`` when neither path is possible.
    """
    if stop is not None:
        entry, stop = _positive("entry", entry), _positive("stop", stop)
        if entry == stop:
            raise ValueError("stop must differ from entry")
        distance = abs(entry - stop)
        side = 1 if stop < entry else -1
        return stop, entry + distance * reward_risk * side
    if direction is None or atr_value is None:
        raise ValueError(
            "provide an explicit stop, or both a direction and an ATR value"
        )
    return atr_levels(
        direction, entry, atr_value, stop_multiple=stop_atr, reward_to_risk=reward_risk
    )
