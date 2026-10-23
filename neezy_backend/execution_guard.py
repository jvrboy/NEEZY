"""Persistent, fail-closed risk gates for the unattended demo executor."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any

from .executor_config import ExecutorConfig
from .storage import _atomic_json_write


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


def _demo_account(account: dict[str, Any]) -> bool:
    mode = account.get("trade_mode")
    if isinstance(mode, str):
        return mode.strip().upper() in {"DEMO", "0"}
    return mode == 0 and not isinstance(mode, bool)


class ExecutionGuard:
    """Enforce daily and per-order limits using restart-persistent local state."""

    def __init__(
        self,
        config: ExecutorConfig,
        state_path: Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.state_path = state_path
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {
                "schema": 1,
                "day": None,
                "day_start_balance": None,
                "trades": 0,
                "last_candles": {},
            }
        import json

        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                "executor risk state is unreadable; refusing to reset safety limits"
            ) from error
        if not isinstance(state, dict) or state.get("schema") != 1:
            raise ValueError("executor risk state has an unsupported schema")
        candles = state.get("last_candles")
        baseline = state.get("day_start_balance")
        malformed_candles = not isinstance(candles, dict) or any(
            not isinstance(symbol, str)
            or isinstance(epoch, bool)
            or not isinstance(epoch, int)
            or epoch <= 0
            for symbol, epoch in candles.items()
        )
        malformed_baseline = baseline is not None and (
            isinstance(baseline, bool)
            or not isinstance(baseline, (int, float))
            or not math.isfinite(float(baseline))
            or float(baseline) <= 0
        )
        if (
            not isinstance(state.get("trades"), int)
            or isinstance(state.get("trades"), bool)
            or state["trades"] < 0
            or (state.get("day") is not None and not isinstance(state.get("day"), str))
            or malformed_candles
            or malformed_baseline
        ):
            raise ValueError("executor risk state is malformed; refusing to continue")
        return state

    def _save(self) -> None:
        _atomic_json_write(self.state_path, self._state)

    def _now(self) -> datetime:
        current = self.clock()
        if current.tzinfo is None:
            raise ValueError("executor clock must return an aware datetime")
        return current.astimezone(timezone.utc)

    @staticmethod
    def _realized_since(deals: list[dict[str, Any]], start: datetime) -> float:
        start_epoch = start.timestamp()
        total = 0.0
        for deal in deals:
            try:
                epoch = float(deal.get("time", 0))
            except (TypeError, ValueError):
                continue
            if not math.isfinite(epoch) or epoch < start_epoch:
                continue
            for field in ("profit", "commission", "swap", "fee"):
                value = deal.get(field, 0.0) or 0.0
                total += _finite(value, f"deal {field}")
        return total

    def refresh(
        self,
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        deals: list[dict[str, Any]],
        *,
        bot_magic: int,
    ) -> dict[str, Any]:
        """Refresh UTC daily loss and return the current order blockers."""
        now = self._now()
        day = now.date().isoformat()
        midnight = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        balance = _finite(account.get("balance"), "account balance")
        equity = _finite(account.get("equity"), "account equity")
        if balance <= 0 or equity < 0:
            raise ValueError("account balance/equity is outside safe bounds")
        realized = self._realized_since(deals, midnight)
        if self._state.get("day") != day:
            # Reconstruct the opening balance if the service starts mid-day. If
            # it was already running, the persisted baseline remains authoritative.
            self._state.update(
                day=day,
                day_start_balance=balance - realized,
                trades=0,
            )
            self._save()
        baseline = _finite(self._state.get("day_start_balance"), "day-start balance")
        if baseline <= 0:
            raise ValueError("day-start balance must be positive")
        daily_pnl = equity - baseline
        daily_loss = max(0.0, -daily_pnl / baseline * 100.0)
        unprotected = [
            position.get("ticket")
            for position in positions
            if position.get("magic") == bot_magic
            and _finite(position.get("sl", 0.0) or 0.0, "position stop") <= 0
        ]
        blockers = []
        if daily_loss >= self.config.max_daily_loss_percent:
            blockers.append("maximum daily loss reached")
        if self._state["trades"] >= self.config.max_daily_trades:
            blockers.append("maximum daily trade count reached")
        if unprotected:
            blockers.append("a bot-owned position has no broker-side stop loss")
        if not _demo_account(account):
            blockers.append("unattended execution is restricted to a demo account")
        return {
            "day": day,
            "day_start_balance": round(baseline, 8),
            "equity": equity,
            "daily_pnl": round(daily_pnl, 8),
            "daily_loss_percent": round(daily_loss, 6),
            "daily_loss_limit_percent": self.config.max_daily_loss_percent,
            "trades_today": self._state["trades"],
            "daily_trade_limit": self.config.max_daily_trades,
            "unprotected_bot_positions": unprotected,
            "can_trade": not blockers,
            "blockers": blockers,
        }

    def authorize_order(
        self,
        *,
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        risk: dict[str, Any],
        direction: str,
        volume: float,
        entry: float,
        stop: float,
        target: float,
    ) -> list[str]:
        """Return all reasons not to send; every check is repeated at order time."""
        reasons = list(risk.get("blockers", []))
        if not self.config.execution_enabled:
            reasons.append("execution_enabled is false")
        if account.get("mock") or not _demo_account(account):
            reasons.append("a real connected MT5 demo account is required")
        if len(positions) >= self.config.max_open_positions:
            reasons.append("maximum open position count reached")
        volume_value = _finite(volume, "order volume")
        entry_value = _finite(entry, "entry")
        stop_value = _finite(stop, "stop loss")
        target_value = _finite(target, "take profit")
        if volume_value <= 0 or volume_value > self.config.max_position_size:
            reasons.append("order volume exceeds the hard position-size cap")
        if entry_value <= 0 or stop_value <= 0 or target_value <= 0:
            reasons.append("broker-side stop loss and take profit are required")
        elif direction == "BUY":
            if not stop_value < entry_value < target_value:
                reasons.append("BUY levels must satisfy SL < entry < TP")
        elif direction == "SELL":
            if not target_value < entry_value < stop_value:
                reasons.append("SELL levels must satisfy TP < entry < SL")
        else:
            reasons.append("order direction must be BUY or SELL")
        return list(dict.fromkeys(reasons))

    def should_evaluate(self, symbol: str, closed_epoch: int) -> bool:
        previous = self._state["last_candles"].get(symbol)
        return previous is None or closed_epoch > previous

    def mark_evaluated(self, symbol: str, closed_epoch: int) -> None:
        """Persist before any order send so a crash cannot duplicate a signal."""
        if isinstance(closed_epoch, bool) or not isinstance(closed_epoch, int):
            raise ValueError("closed candle epoch must be an integer")
        previous = self._state["last_candles"].get(symbol)
        if previous is not None and closed_epoch <= previous:
            return
        self._state["last_candles"][symbol] = closed_epoch
        self._save()

    def record_filled_order(self) -> None:
        self._state["trades"] += 1
        self._save()
