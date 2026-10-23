"""Persistent exact-hash paper validation without broker order placement.

This module belongs to the lightweight PC runtime. It downloads only bounded JSON,
runs compact inference on MT5 demo candles, and records virtual R-multiple outcomes.
It never imports training/backtest code and has no broker order dependency.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .brain import predict
from .indicators import atr
from .model_hub import (
    MAX_MANIFEST_BYTES,
    MAX_MODEL_BYTES,
    HuggingFaceDownloader,
    ModelUpdateError,
    evaluate_model_gate,
    safe_repo_path,
    sha256_bytes,
)
from .risk import atr_levels
from .storage import _atomic_json_write

Candle = Sequence[float]
PAPER_SCHEMA = 1
PAPER_METHOD = "neezy_exact_hash_mt5_paper_v1"
_MAX_STATE_BYTES = 2_000_000


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        document = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelUpdateError(f"{label} is not valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ModelUpdateError(f"{label} must contain a JSON object")
    return document


def load_paper_candidate(
    downloader: HuggingFaceDownloader,
    manifest_path: str,
    *,
    timeframe: str,
    min_test_samples: int = 50,
    min_balanced_accuracy: float = 0.55,
    min_backtest_trades: int = 20,
) -> dict[str, Any]:
    """Download an immutable candidate, deferring only the paper-evidence gate."""
    manifest = _json_object(
        downloader.download(
            safe_repo_path(manifest_path), max_bytes=MAX_MANIFEST_BYTES
        ),
        "paper candidate manifest",
    )
    model_path = safe_repo_path(manifest.get("model_file", ""))
    content = downloader.download(model_path, max_bytes=MAX_MODEL_BYTES)
    if sha256_bytes(content) != manifest.get("model_sha256"):
        raise ModelUpdateError("paper candidate model hash does not match manifest")
    model = _json_object(content, "paper candidate model")
    symbol = manifest.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise ModelUpdateError("paper candidate manifest has no symbol")
    issues = evaluate_model_gate(
        model,
        manifest,
        symbol=symbol,
        timeframe=timeframe,
        min_test_samples=min_test_samples,
        min_balanced_accuracy=min_balanced_accuracy,
        min_backtest_trades=min_backtest_trades,
        require_paper=False,
    )
    if issues:
        raise ModelUpdateError("paper candidate rejected: " + "; ".join(issues))
    return {"model": model, "manifest": manifest, "content": content}


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be a finite number")
    return result


class PaperValidator:
    """Track one exact model hash across restarts; never place broker orders."""

    def __init__(
        self,
        model: dict[str, Any],
        manifest: dict[str, Any],
        *,
        state_path: Path,
        report_path: Path,
        minimum_probability: float,
        spread: float,
        stop_atr_multiple: float,
        reward_to_risk: float,
        min_trades: int,
        min_days: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.model = model
        self.manifest = manifest
        self.state_path = state_path
        self.report_path = report_path
        self.minimum_probability = _finite(minimum_probability, "probability")
        self.spread = _finite(spread, "paper spread")
        self.stop_atr_multiple = _finite(stop_atr_multiple, "stop multiple")
        self.reward_to_risk = _finite(reward_to_risk, "reward multiple")
        if not 0.5 < self.minimum_probability < 1.0:
            raise ValueError("paper probability must be between 0.5 and 1")
        if self.spread <= 0:
            raise ValueError("paper validation requires a nonzero spread assumption")
        if self.stop_atr_multiple <= 0 or self.reward_to_risk <= 0:
            raise ValueError("paper stop and reward multiples must be positive")
        if (
            isinstance(min_trades, bool)
            or not isinstance(min_trades, int)
            or min_trades < 1
            or isinstance(min_days, bool)
            or not isinstance(min_days, int)
            or min_days < 1
        ):
            raise ValueError("paper trade/day minimums must be positive integers")
        self.min_trades = min_trades
        self.min_days = min_days
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._report_dirty = True
        self._state = self._load()

    def _now(self) -> datetime:
        current = self.clock()
        if current.tzinfo is None:
            raise ValueError("paper validation clock must be timezone-aware")
        return current.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema": PAPER_SCHEMA,
            "model_id": self.manifest["model_id"],
            "model_sha256": self.manifest["model_sha256"],
            "symbol": self.manifest["symbol"],
            "timeframe": self.manifest["timeframe"],
            "started_at": self._now_iso(),
            "last_candle": None,
            "last_signal": None,
            "last_trade": None,
            "open_position": None,
            "returns": [],
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._initial_state()
        try:
            content = self.state_path.read_bytes()
            if len(content) > _MAX_STATE_BYTES:
                raise ValueError("paper state exceeds the size limit")
            state = json.loads(content.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "paper validation state is unreadable; refusing to reset it"
            ) from error
        if not isinstance(state, dict) or state.get("schema") != PAPER_SCHEMA:
            raise ValueError("paper validation state has an unsupported schema")
        required = {"started_at", "last_candle", "open_position", "returns"}
        if not required.issubset(state):
            raise ValueError("paper validation state is incomplete")
        for key in ("model_id", "model_sha256", "symbol", "timeframe"):
            if state.get(key) != self.manifest.get(key):
                raise ValueError("paper validation state belongs to another candidate")
        started_at = state.get("started_at")
        try:
            parsed_start = datetime.fromisoformat(started_at)
            if parsed_start.tzinfo is None:
                raise ValueError("naive timestamp")
        except (TypeError, ValueError) as error:
            raise ValueError("paper validation start time is invalid") from error
        last_candle = state.get("last_candle")
        if last_candle is not None and (
            isinstance(last_candle, bool)
            or not isinstance(last_candle, int)
            or last_candle <= 0
        ):
            raise ValueError("paper validation last candle is invalid")
        returns = state.get("returns")
        if not isinstance(returns, list):
            raise ValueError("paper validation returns are invalid")
        for value in returns:
            _finite(value, "paper return")
        if state.get("open_position") is not None and not isinstance(
            state.get("open_position"), dict
        ):
            raise ValueError("paper validation open position is invalid")
        return state

    @staticmethod
    def _epochs(rows: Sequence[Candle]) -> list[int]:
        epochs = []
        for row in rows:
            value = _finite(row[0], "candle epoch")
            epoch = int(value)
            if epoch <= 0 or epoch != value:
                raise ValueError("candle epochs must be positive integers")
            if epochs and epoch <= epochs[-1]:
                raise ValueError("candles must have strictly increasing epochs")
            epochs.append(epoch)
        return epochs

    def report(self) -> dict[str, Any]:
        now = self._now()
        started = datetime.fromisoformat(self._state["started_at"])
        days = max(0, int((now - started).total_seconds() // 86_400))
        returns = [float(value) for value in self._state["returns"]]
        count = len(returns)
        wins = [value for value in returns if value > 0]
        gross_loss = -sum(value for value in returns if value <= 0)
        expectancy = sum(returns) / count if count else 0.0
        profit_factor = sum(wins) / gross_loss if gross_loss else None
        equity = 0.0
        peak = 0.0
        drawdown = 0.0
        for value in returns:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        enough_history = days >= self.min_days and count >= self.min_trades
        passed = bool(
            enough_history
            and expectancy > 0
            and (profit_factor is None or profit_factor > 1.0)
        )
        status = (
            "passed" if passed else "not_passed" if enough_history else "collecting"
        )
        return {
            "schema": PAPER_SCHEMA,
            "method": PAPER_METHOD,
            "status": status,
            "passed": passed,
            "model_id": self.manifest["model_id"],
            "model_sha256": self.manifest["model_sha256"],
            "symbol": self.manifest["symbol"],
            "timeframe": self.manifest["timeframe"],
            "started_at": self._state["started_at"],
            "updated_at": now.isoformat(timespec="seconds"),
            "days": days,
            "trades": count,
            "minimum_days": self.min_days,
            "minimum_trades": self.min_trades,
            "wins": len(wins),
            "losses": count - len(wins),
            "win_rate": round(len(wins) / count * 100.0, 4) if count else 0.0,
            "expectancy_r": round(expectancy, 6),
            "profit_factor": (
                round(profit_factor, 6) if profit_factor is not None else None
            ),
            "max_drawdown_r": round(drawdown, 6),
            "spread": self.spread,
            "open_simulation": self._state["open_position"] is not None,
            "last_signal": copy.deepcopy(self._state.get("last_signal")),
            "last_trade": copy.deepcopy(self._state.get("last_trade")),
            "notes": (
                "Virtual MT5-demo outcomes only; no broker orders were placed. "
                "Stop-first ambiguous candles and the configured spread apply."
            ),
        }

    def _write_report(self) -> None:
        if not self._report_dirty:
            return
        _atomic_json_write(self.report_path, self.report())
        self._report_dirty = False

    def update(self, rows: Sequence[Candle]) -> dict[str, Any]:
        """Process each available closed candle once and persist before returning."""
        if len(rows) < 82:
            raise ValueError("at least 82 candles are required for paper validation")
        epochs = self._epochs(rows)
        latest = len(rows) - 2
        previous = self._state["last_candle"]
        if previous is None:
            pending = [latest]
        else:
            try:
                previous_index = epochs.index(previous)
            except ValueError as error:
                raise ValueError(
                    "paper candle history has a gap; restart validation from zero"
                ) from error
            pending = list(range(previous_index + 1, latest + 1))
        if not pending:
            self._write_report()
            return self.report()

        state = copy.deepcopy(self._state)
        for index in pending:
            self._process_bar(state, rows[: index + 2])
            state["last_candle"] = epochs[index]
        _atomic_json_write(self.state_path, state)
        self._state = state
        self._report_dirty = True
        self._write_report()
        return self.report()

    def _process_bar(self, state: dict[str, Any], window: Sequence[Candle]) -> None:
        closed = window[-2]
        active = window[-1]
        if state["open_position"] is not None:
            self._manage_position(state, closed)
        if state["open_position"] is not None:
            return
        prediction = predict(
            window, self.model, minimum_probability=self.minimum_probability
        )
        if prediction is None:
            return
        state["last_signal"] = {
            "closed_epoch": int(closed[0]),
            "direction": prediction["direction"],
            "up_probability": prediction["up_probability"],
        }
        direction = prediction["direction"]
        if direction == "NEUTRAL":
            return
        side = 1 if direction == "BUY" else -1
        entry = _finite(active[1], "paper entry") + side * self.spread / 2.0
        closed_rows = window[:-1]
        atr_value = atr(
            [float(row[2]) for row in closed_rows],
            [float(row[3]) for row in closed_rows],
            [float(row[4]) for row in closed_rows],
        )
        if atr_value is None:
            return
        stop, target = atr_levels(
            direction,
            entry,
            atr_value,
            self.stop_atr_multiple,
            self.reward_to_risk,
        )
        state["open_position"] = {
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "target": target,
            "entry_epoch": int(active[0]),
            "signal_epoch": int(closed[0]),
            "bars_held": 0,
            "horizon": int(self.model["horizon"]),
        }

    def _manage_position(self, state: dict[str, Any], bar: Candle) -> None:
        position = state["open_position"]
        open_, high, low, close = (
            _finite(bar[index], "paper candle") for index in range(1, 5)
        )
        if (
            min(open_, high, low, close) <= 0
            or high < max(open_, close)
            or low > min(open_, close)
            or low > high
        ):
            raise ValueError("paper candle has invalid OHLC bounds")
        direction = position.get("direction")
        if direction not in {"BUY", "SELL"}:
            raise ValueError("paper position direction is invalid")
        entry = _finite(position.get("entry"), "paper position entry")
        stop = _finite(position.get("stop"), "paper position stop")
        target = _finite(position.get("target"), "paper position target")
        entry_epoch = position.get("entry_epoch")
        bars_held = position.get("bars_held")
        horizon = position.get("horizon")
        if (
            isinstance(entry_epoch, bool)
            or not isinstance(entry_epoch, int)
            or int(bar[0]) < entry_epoch
            or isinstance(bars_held, bool)
            or not isinstance(bars_held, int)
            or bars_held < 0
            or isinstance(horizon, bool)
            or not isinstance(horizon, int)
            or horizon < 1
        ):
            raise ValueError("paper position timing is invalid")
        if entry <= 0 or not (
            (direction == "BUY" and stop < entry < target)
            or (direction == "SELL" and target < entry < stop)
        ):
            raise ValueError("paper position levels are inconsistent")
        bars_held += 1
        position["bars_held"] = bars_held
        side = 1 if direction == "BUY" else -1
        exit_price = None
        reason = None
        if direction == "BUY":
            hit_stop = low <= stop
            hit_target = high >= target
            stop_fill = min(stop, open_) if open_ < stop else stop
        else:
            hit_stop = high >= stop
            hit_target = low <= target
            stop_fill = max(stop, open_) if open_ > stop else stop
        if hit_stop:
            exit_price, reason = stop_fill, "stop"
        elif hit_target:
            exit_price, reason = target, "target"
        elif bars_held >= horizon:
            exit_price, reason = close, "horizon"
        if exit_price is None:
            return
        exit_fill = exit_price - side * self.spread / 2.0
        risk_distance = abs(entry - stop)
        r_multiple = side * (exit_fill - entry) / risk_distance
        if not math.isfinite(r_multiple):
            raise ValueError("paper outcome is non-finite")
        state["returns"].append(r_multiple)
        state["last_trade"] = {
            "closed_epoch": int(bar[0]),
            "direction": direction,
            "reason": reason,
            "r_multiple": round(r_multiple, 6),
        }
        state["open_position"] = None
