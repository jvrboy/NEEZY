"""Always-on, lightweight MT5 demo executor and monitoring service."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from .brain import predict
from .execution_guard import ExecutionGuard
from .executor_config import ExecutorConfig, load_executor_config
from .indicators import atr
from .model_hub import (
    HuggingFaceDownloader,
    ModelUpdateError,
    ModelUpdateManager,
)
from .mt5_bridge import MT5Bridge, bridge_from_settings
from .paper_validation import PaperValidator, load_paper_candidate
from .risk import atr_levels, position_size
from .status_api import StatusServer, StatusState
from .storage import get_data_dir

logger = logging.getLogger("neezy.executor")
_TRADE_MODES = {0: "DEMO", 1: "CONTEST", 2: "REAL"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _public_position(position: dict[str, Any]) -> dict[str, Any]:
    return {
        key: position.get(key)
        for key in (
            "ticket",
            "symbol",
            "type",
            "volume",
            "price_open",
            "sl",
            "tp",
            "profit",
            "magic",
        )
    }


def _candle_rows(rows: list[dict[str, Any]]) -> list[tuple[float, ...]]:
    return [
        (
            float(row["time"]),
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
        )
        for row in rows
    ]


class ExecutorService:
    """Coordinate broker reads, validated inference, and demo-only order sends."""

    def __init__(
        self,
        config: ExecutorConfig,
        *,
        bridge: MT5Bridge | None = None,
        managers: dict[str, ModelUpdateManager] | None = None,
        state: StatusState | None = None,
        guard: ExecutionGuard | None = None,
    ) -> None:
        self.config = config
        self.home = get_data_dir()
        self.bridge = bridge or bridge_from_settings()
        self.state = state or StatusState(
            persistence_path=self.home / "executor-status.json"
        )
        self.guard = guard or ExecutionGuard(config, self.home / "executor-risk.json")
        self._stop = threading.Event()
        self._status_server: StatusServer | None = None
        self._next_model_check = 0.0
        self._active_models: dict[str, dict[str, Any]] = {}
        self._model_status: dict[str, dict[str, Any]] = {}
        self._startup_issues: list[dict[str, str]] = []
        self._paper_artifact: dict[str, Any] | None = None
        self._paper_validator: PaperValidator | None = None
        self._paper_status: dict[str, Any] = {"status": "not_configured"}
        self._next_paper_load = 0.0

        if config.paper_candidate:
            self.managers = {}
            self._paper_status = {"status": "loading"}
        elif managers is not None:
            self.managers = managers
        elif config.hf_repo_id:
            token = os.environ.get("HF_TOKEN")
            self.managers = {
                symbol: ModelUpdateManager(
                    self.home / "models",
                    symbol=symbol,
                    timeframe=config.timeframe,
                    downloader=HuggingFaceDownloader(
                        config.hf_repo_id,
                        revision=config.hf_revision,
                        token=token,
                        timeout=config.request_timeout,
                    ),
                    min_test_samples=config.min_test_samples,
                    min_balanced_accuracy=config.min_balanced_accuracy,
                    min_backtest_trades=config.min_backtest_trades,
                    min_paper_trades=config.min_paper_trades,
                    min_paper_days=config.min_paper_days,
                )
                for symbol in config.symbols
            }
        else:
            self.managers = {}

        for symbol, manager in self.managers.items():
            try:
                active = manager.load_active()
                if active:
                    self._active_models[symbol] = active
                self._model_status[symbol] = manager.status()
            except ModelUpdateError as error:
                self._model_status[symbol] = {"active": False, "error": str(error)}
                self._startup_issues.append(
                    {
                        "severity": "warning",
                        "code": "active_model_invalid",
                        "message": f"{symbol}: {error}",
                    }
                )
        for symbol in config.symbols:
            self._model_status.setdefault(
                symbol,
                {"active": False, "configured": bool(self.managers)},
            )

        self.state.update(
            execution={
                "enabled": config.execution_enabled,
                "mode": "paper-validation" if config.paper_candidate else "demo-only",
                "broker": "MetaTrader 5",
            },
            timeframe=config.timeframe,
            models=self._model_status,
            open_trades=[],
            equity_history=[],
        )
        if config.paper_candidate:
            self.state.update(paper_validation=self._paper_status)

    def request_stop(self) -> None:
        self._stop.set()

    def _refresh_models(self, issues: list[dict[str, str]]) -> None:
        now = time.monotonic()
        if now < self._next_model_check:
            return
        self._next_model_check = now + self.config.model_poll_seconds
        for symbol, manager in self.managers.items():
            try:
                result = manager.check_for_update()
                self._model_status[symbol] = {**manager.status(), "update": result}
                if result["status"] == "activated":
                    active = manager.load_active()
                    if active is None:
                        raise ModelUpdateError("activated model pointer is empty")
                    self._active_models[symbol] = active
                elif result["status"] == "rejected":
                    issues.append(
                        {
                            "severity": "warning",
                            "code": "model_rejected",
                            "message": (
                                f"{symbol}: candidate {result.get('model_id')} "
                                "rejected: " + "; ".join(result.get("issues", []))
                            ),
                        }
                    )
            except (ModelUpdateError, OSError, ValueError) as error:
                self._model_status[symbol] = {
                    **self._model_status.get(symbol, {}),
                    "update": {"status": "error", "error": str(error)},
                }
                issues.append(
                    {
                        "severity": "warning",
                        "code": "model_update_failed",
                        "message": f"{symbol}: {error}; keeping the previous model",
                    }
                )

    def _load_paper_validator(self) -> None:
        if self._paper_validator is not None:
            return
        now = time.monotonic()
        if now < self._next_paper_load:
            return
        self._next_paper_load = now + 300.0
        try:
            artifact = load_paper_candidate(
                HuggingFaceDownloader(
                    self.config.hf_repo_id,
                    revision=self.config.hf_revision,
                    token=os.environ.get("HF_TOKEN"),
                    timeout=self.config.request_timeout,
                ),
                self.config.paper_candidate,
                timeframe=self.config.timeframe,
                min_test_samples=self.config.min_test_samples,
                min_balanced_accuracy=self.config.min_balanced_accuracy,
                min_backtest_trades=self.config.min_backtest_trades,
            )
            manifest = artifact["manifest"]
            symbol = manifest["symbol"]
            if symbol not in self.config.symbols:
                raise ModelUpdateError(
                    f"paper candidate symbol {symbol} is not in configured symbols"
                )
            model_id = manifest["model_id"]
            self._paper_validator = PaperValidator(
                artifact["model"],
                manifest,
                state_path=self.home / "paper" / f"{model_id}.json",
                report_path=self.home / "paper-reports" / f"{model_id}.json",
                minimum_probability=self.config.minimum_probability,
                spread=self.config.paper_spread,
                stop_atr_multiple=self.config.stop_atr_multiple,
                reward_to_risk=self.config.reward_to_risk,
                min_trades=self.config.min_paper_trades,
                min_days=self.config.min_paper_days,
            )
            self._paper_artifact = artifact
            self._paper_status = self._paper_validator.report()
        except (ModelUpdateError, OSError, ValueError, KeyError, TypeError) as error:
            self._paper_status = {"status": "error", "error": str(error)}
        self.state.update(paper_validation=self._paper_status)

    def _evaluate_paper(self, issues: list[dict[str, str]]) -> None:
        self._load_paper_validator()
        if self._paper_validator is None or self._paper_artifact is None:
            message = self._paper_status.get("error", "candidate is still loading")
            issues.append(
                {
                    "severity": "warning",
                    "code": "paper_candidate_unavailable",
                    "message": f"paper validation unavailable: {message}",
                }
            )
            return
        symbol = self._paper_artifact["manifest"]["symbol"]
        rows = _candle_rows(
            self.bridge.fetch_candles(
                symbol,
                timeframe=self.config.timeframe,
                count=self.config.candle_count,
            )
        )
        if len(rows) < 82:
            self._paper_status = {
                **self._paper_validator.report(),
                "status": "waiting_for_candles",
                "candle_count": len(rows),
            }
        else:
            self._paper_status = self._paper_validator.update(rows)
        self.state.update(paper_validation=self._paper_status)

    def _place_order(
        self,
        symbol: str,
        prediction: dict[str, Any],
        candles: list[tuple[float, ...]],
    ) -> None:
        direction = prediction["direction"]
        quote = self.bridge.get_quote(symbol)
        if quote.get("error") or quote.get("mock"):
            raise RuntimeError(quote.get("error") or "refusing a simulated quote")
        entry = float(quote["ask"] if direction == "BUY" else quote["bid"])
        closed = candles[:-1]
        atr_value = atr(
            [row[2] for row in closed],
            [row[3] for row in closed],
            [row[4] for row in closed],
        )
        if atr_value is None:
            raise ValueError("not enough closed candles for an ATR stop")
        stop, target = atr_levels(
            direction,
            entry,
            atr_value,
            self.config.stop_atr_multiple,
            self.config.reward_to_risk,
        )

        # Repeat account, position, and daily-loss reads at the moment of sending.
        account = self.bridge.get_account_info()
        positions = self.bridge.get_positions()
        deals = self.bridge.get_account_history(days=1, limit=500)
        risk = self.guard.refresh(
            account,
            positions,
            deals,
            bot_magic=self.bridge.magic,
        )
        plan = position_size(
            symbol=symbol,
            balance=float(account["balance"]),
            risk_percent=self.config.risk_per_trade_percent,
            entry=entry,
            stop=stop,
            reward_to_risk=self.config.reward_to_risk,
            pip_value_per_lot=self.config.pip_value_per_lot,
            lot_step=self.config.lot_step,
        )
        uncapped = min(plan.lots, self.config.max_position_size)
        volume = round(
            math.floor(uncapped / self.config.lot_step + 1e-9) * self.config.lot_step,
            8,
        )
        blockers = self.guard.authorize_order(
            account=account,
            positions=positions,
            risk=risk,
            direction=direction,
            volume=volume,
            entry=entry,
            stop=stop,
            target=target,
        )
        model_id = self._active_models[symbol]["manifest"]["model_id"]
        if blockers:
            self.state.update(
                last_order={
                    "time": _now_iso(),
                    "symbol": symbol,
                    "direction": direction,
                    "success": False,
                    "sent": False,
                    "blockers": blockers,
                }
            )
            return

        result = self.bridge.place_order(
            symbol,
            direction,
            volume,
            price=entry,
            sl=stop,
            tp=target,
            comment=f"NEEZY demo {model_id[-12:]}",
        )
        success = bool(result.get("success")) and not result.get("mock")
        if success:
            self.guard.record_filled_order()
        self.state.update(
            last_order={
                "time": _now_iso(),
                "symbol": symbol,
                "direction": direction,
                "volume": volume,
                "sl": stop,
                "tp": target,
                "success": success,
                "sent": success,
                "ticket": result.get("ticket"),
                "error": result.get("error"),
            }
        )

    def _evaluate_symbol(
        self,
        symbol: str,
        account: dict[str, Any],
        positions: list[dict[str, Any]],
        risk: dict[str, Any],
        issues: list[dict[str, str]],
    ) -> None:
        active = self._active_models.get(symbol)
        if active is None:
            if self.config.execution_enabled:
                issues.append(
                    {
                        "severity": "critical",
                        "code": "model_missing",
                        "message": (
                            f"{symbol}: no validated active model; orders are blocked"
                        ),
                    }
                )
            return
        rows = _candle_rows(
            self.bridge.fetch_candles(
                symbol,
                timeframe=self.config.timeframe,
                count=self.config.candle_count,
            )
        )
        if len(rows) < 82:
            self._model_status[symbol]["last_prediction"] = {
                "status": "waiting_for_candles",
                "count": len(rows),
            }
            return
        closed_epoch = int(rows[-2][0])
        if not self.guard.should_evaluate(symbol, closed_epoch):
            return
        prediction = predict(
            rows,
            active["model"],
            minimum_probability=self.config.minimum_probability,
        )
        if prediction is None:
            return
        # Persist first: a process crash must not re-send this candle's signal.
        self.guard.mark_evaluated(symbol, closed_epoch)
        self._model_status[symbol]["last_prediction"] = {
            "closed_epoch": closed_epoch,
            "direction": prediction["direction"],
            "up_probability": prediction["up_probability"],
            "down_probability": prediction["down_probability"],
            "model_id": active["manifest"]["model_id"],
        }
        if prediction["direction"] == "NEUTRAL" or not self.config.execution_enabled:
            return
        before = self.state.snapshot().get("last_order", {})
        self._place_order(symbol, prediction, rows)
        after = self.state.snapshot().get("last_order", {})
        if after is not before and after.get("success") is False:
            issues.append(
                {
                    "severity": "warning",
                    "code": "order_not_sent",
                    "message": (
                        f"{symbol}: " + "; ".join(after.get("blockers", []))
                        if after.get("blockers")
                        else (
                            f"{symbol}: "
                            f"{after.get('error', 'broker rejected the order')}"
                        )
                    ),
                }
            )

    def run_once(self) -> dict[str, Any]:
        issues = [*self._startup_issues]
        self._startup_issues.clear()
        if not self.config.paper_candidate:
            self._refresh_models(issues)
        connection = self.bridge.connect()
        simulated = bool(connection.get("mock") or self.bridge.mock)
        connected = bool(connection.get("success")) and not simulated
        self.state.update(
            broker={
                "connected": connected,
                "simulated": simulated,
                "error": connection.get("error"),
            }
        )
        if not connected:
            issues.append(
                {
                    "severity": "critical",
                    "code": "broker_offline",
                    "message": connection.get("error")
                    or "a real MT5 terminal is not connected; no live data or orders",
                }
            )
            self.state.update(
                account={},
                open_trades=[],
                risk={"can_trade": False, "blockers": ["broker offline"]},
                models=self._model_status,
            )
            return self._finish(issues)

        account = self.bridge.get_account_info()
        if account.get("error"):
            issues.append(
                {
                    "severity": "critical",
                    "code": "account_unavailable",
                    "message": str(account["error"]),
                }
            )
            self.state.update(
                account={},
                open_trades=[],
                risk={"can_trade": False, "blockers": ["account unavailable"]},
            )
            return self._finish(issues)
        positions = self.bridge.get_positions()
        deals = self.bridge.get_account_history(days=1, limit=500)
        risk = self.guard.refresh(
            account,
            positions,
            deals,
            bot_magic=self.bridge.magic,
        )
        mode = account.get("trade_mode")
        mode_label = _TRADE_MODES.get(mode, str(mode).upper())
        paper_mode = bool(self.config.paper_candidate)
        if mode_label != "DEMO" and (self.config.execution_enabled or paper_mode):
            issues.append(
                {
                    "severity": "critical",
                    "code": "demo_account_required",
                    "message": (
                        "unattended execution and paper validation require an "
                        "MT5 demo account"
                    ),
                }
            )
        self.state.record_equity(float(account["equity"]))
        self.state.update(
            account={
                "trade_mode": mode_label,
                "balance": account.get("balance"),
                "equity": account.get("equity"),
                "currency": account.get("currency"),
            },
            open_trades=[_public_position(position) for position in positions],
            risk=risk,
            models=self._model_status,
        )
        if paper_mode:
            if mode_label == "DEMO":
                try:
                    self._evaluate_paper(issues)
                except (
                    OSError,
                    RuntimeError,
                    ValueError,
                    KeyError,
                    TypeError,
                ) as error:
                    issues.append(
                        {
                            "severity": "warning",
                            "code": "paper_validation_failed",
                            "message": str(error),
                        }
                    )
        else:
            for symbol in self.config.symbols:
                try:
                    self._evaluate_symbol(symbol, account, positions, risk, issues)
                except (
                    OSError,
                    RuntimeError,
                    ValueError,
                    KeyError,
                    TypeError,
                ) as error:
                    issues.append(
                        {
                            "severity": "warning",
                            "code": "evaluation_failed",
                            "message": f"{symbol}: {error}",
                        }
                    )
        self.state.update(models=self._model_status)
        return self._finish(issues)

    def _finish(self, issues: list[dict[str, str]]) -> dict[str, Any]:
        critical = any(issue["severity"] == "critical" for issue in issues)
        warning = any(issue["severity"] == "warning" for issue in issues)
        status = "critical" if critical else "degraded" if warning else "ok"
        self.state.heartbeat(status, issues)
        return self.state.snapshot()

    def run(self) -> None:
        self._status_server = StatusServer(
            self.state, self.config.status_host, self.config.status_port
        )
        self._status_server.start()
        logger.info(
            "NEEZY executor started; status API on %s:%s (loopback only)",
            *self._status_server.address,
        )
        try:
            while not self._stop.is_set():
                try:
                    self.run_once()
                except Exception as error:
                    logger.exception("executor iteration failed")
                    self.state.heartbeat(
                        "critical",
                        [
                            {
                                "severity": "critical",
                                "code": "iteration_failed",
                                "message": str(error),
                            }
                        ],
                    )
                self._stop.wait(self.config.poll_seconds)
        finally:
            self._status_server.stop()
            self.bridge.disconnect()
            self.state.heartbeat("stopped", [])
            logger.info("NEEZY executor stopped")


def _configure_logging() -> None:
    log_dir = get_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "executor.log",
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(file_handler)
    logger.addHandler(console)
    logger.propagate = False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NEEZY lightweight PC executor")
    parser.add_argument("--config", type=Path, help="executor JSON config path")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument(
        "--once", action="store_true", help="run one read/evaluation pass"
    )
    args = parser.parse_args(argv)
    try:
        config = load_executor_config(args.config)
    except (OSError, ValueError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2
    if args.check_config:
        print(json.dumps(config.to_public_dict(), indent=2, allow_nan=False))
        return 0

    _configure_logging()
    try:
        service = ExecutorService(config)
    except (OSError, ValueError) as error:
        logger.error("executor startup refused: %s", error)
        return 2
    if args.once:
        snapshot = service.run_once()
        print(json.dumps(snapshot, indent=2, allow_nan=False))
        service.bridge.disconnect()
        return 1 if snapshot["status"] == "critical" else 0

    def stop(_signum: int, _frame: Any) -> None:
        service.request_stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    service.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
