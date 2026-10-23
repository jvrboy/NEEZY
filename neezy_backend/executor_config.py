"""Strict, secret-free configuration for the lightweight PC executor."""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .markets import TIMEFRAMES
from .model_hub import safe_repo_path
from .storage import get_data_dir


@dataclass(frozen=True, slots=True)
class ExecutorConfig:
    symbols: tuple[str, ...] = ("frxEURUSD",)
    timeframe: str = "15m"
    candle_count: int = 400
    poll_seconds: float = 15.0
    status_host: str = "127.0.0.1"
    status_port: int = 8787
    hf_repo_id: str = ""
    hf_revision: str = "main"
    model_poll_seconds: float = 10_800.0
    request_timeout: float = 20.0
    execution_enabled: bool = False
    paper_candidate: str = ""
    paper_spread: float = 0.0
    minimum_probability: float = 0.65
    risk_per_trade_percent: float = 0.25
    max_daily_loss_percent: float = 2.0
    max_position_size: float = 0.10
    max_open_positions: int = 1
    max_daily_trades: int = 4
    stop_atr_multiple: float = 1.5
    reward_to_risk: float = 2.0
    pip_value_per_lot: float = 10.0
    lot_step: float = 0.01
    min_test_samples: int = 50
    min_balanced_accuracy: float = 0.55
    min_backtest_trades: int = 20
    min_paper_trades: int = 20
    min_paper_days: int = 14

    def __post_init__(self) -> None:
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be a non-empty unique list")
        for symbol in self.symbols:
            if (
                not isinstance(symbol, str)
                or not symbol
                or any(not (char.isalnum() or char in "_.-") for char in symbol)
            ):
                raise ValueError("symbols may contain only letters, numbers, . _ and -")
        if self.timeframe not in TIMEFRAMES:
            raise ValueError("unsupported executor timeframe")
        if self.status_host not in {"127.0.0.1", "localhost"}:
            raise ValueError("status API must bind to loopback only")
        if self.hf_repo_id and (
            self.hf_repo_id.count("/") != 1
            or any(not part for part in self.hf_repo_id.split("/"))
        ):
            raise ValueError("hf_repo_id must look like 'owner/repository'")
        if not isinstance(self.paper_candidate, str):
            raise TypeError("paper_candidate must be a string")
        if self.paper_candidate:
            safe_repo_path(self.paper_candidate)
            if self.execution_enabled:
                raise ValueError("paper_candidate requires execution_enabled=false")
            if not self.hf_repo_id:
                raise ValueError("paper_candidate requires hf_repo_id")
            if self.paper_spread <= 0:
                raise ValueError("paper_candidate requires a nonzero paper_spread")

        integers = {
            "candle_count": (self.candle_count, 100, 5000),
            "status_port": (self.status_port, 1, 65535),
            "max_open_positions": (self.max_open_positions, 1, 50),
            "max_daily_trades": (self.max_daily_trades, 1, 100),
            "min_test_samples": (self.min_test_samples, 50, 100_000),
            "min_backtest_trades": (self.min_backtest_trades, 20, 100_000),
            "min_paper_trades": (self.min_paper_trades, 20, 100_000),
            "min_paper_days": (self.min_paper_days, 14, 3650),
        }
        for name, (value, low, high) in integers.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if not low <= value <= high:
                raise ValueError(f"{name} must be between {low} and {high}")

        numbers = {
            "poll_seconds": (self.poll_seconds, 5.0, 3600.0),
            "model_poll_seconds": (self.model_poll_seconds, 300.0, 86_400.0),
            "request_timeout": (self.request_timeout, 1.0, 60.0),
            "paper_spread": (self.paper_spread, 0.0, 10.0),
            "minimum_probability": (self.minimum_probability, 0.500001, 0.999999),
            "risk_per_trade_percent": (self.risk_per_trade_percent, 0.01, 5.0),
            "max_daily_loss_percent": (self.max_daily_loss_percent, 0.1, 20.0),
            "max_position_size": (self.max_position_size, 0.01, 100.0),
            "stop_atr_multiple": (self.stop_atr_multiple, 0.1, 20.0),
            "reward_to_risk": (self.reward_to_risk, 0.5, 20.0),
            "pip_value_per_lot": (self.pip_value_per_lot, 0.000001, 1_000_000.0),
            "lot_step": (self.lot_step, 0.000001, 100.0),
            "min_balanced_accuracy": (self.min_balanced_accuracy, 0.5, 1.0),
        }
        for name, (value, low, high) in numbers.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if not math.isfinite(float(value)) or not low <= float(value) <= high:
                raise ValueError(f"{name} must be between {low:g} and {high:g}")
        if not isinstance(self.execution_enabled, bool):
            raise TypeError("execution_enabled must be a boolean")
        if not isinstance(self.hf_revision, str) or not self.hf_revision:
            raise ValueError("hf_revision must not be empty")
        if any(char in self.hf_revision for char in "/\\ "):
            raise ValueError("hf_revision must be a branch name or commit hash")

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> ExecutorConfig:
        if not isinstance(document, dict):
            raise ValueError("executor config must contain a JSON object")
        known = {item.name for item in fields(cls)}
        unknown = sorted(set(document) - known)
        if unknown:
            raise ValueError("unknown executor config fields: " + ", ".join(unknown))
        values = dict(document)
        if "symbols" in values:
            symbols = values["symbols"]
            if not isinstance(symbols, list) or any(
                not isinstance(symbol, str) for symbol in symbols
            ):
                raise ValueError("symbols must be a JSON list of strings")
            values["symbols"] = tuple(symbols)
        return cls(**values)

    def to_public_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["symbols"] = list(self.symbols)
        return result


def default_config_path() -> Path:
    override = os.environ.get("NEEZY_EXECUTOR_CONFIG")
    return Path(override).expanduser() if override else get_data_dir() / "executor.json"


def load_executor_config(path: Path | None = None) -> ExecutorConfig:
    """Load config; a missing default file gives safe observer-only defaults."""
    chosen = path or default_config_path()
    if not chosen.exists():
        if path is not None:
            raise FileNotFoundError(f"executor config not found: {chosen}")
        return ExecutorConfig()
    try:
        document = json.loads(chosen.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read executor config: {error}") from error
    return ExecutorConfig.from_dict(document)
