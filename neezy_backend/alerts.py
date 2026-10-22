"""User-defined alert rules evaluated against live analysis results."""

from __future__ import annotations

import json
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import _atomic_json_write, get_data_dir

METRICS = ("price", "rsi", "score", "adx", "signal", "pattern")
OPERATORS = (">", ">=", "<", "<=", "==", "crosses above", "crosses below")
NUMERIC_METRICS = frozenset({"price", "rsi", "score", "adx"})


def is_quiet_hours_now(
    start_hhmm: str,
    end_hhmm: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Return True if ``now`` (UTC by default) falls within ``[start, end)``."""
    try:
        sh, sm = (int(part) for part in start_hhmm.strip().split(":", 1))
        eh, em = (int(part) for part in end_hhmm.strip().split(":", 1))
    except (ValueError, AttributeError):
        return False
    current = now or datetime.now(timezone.utc)
    cur_min = current.hour * 60 + current.minute
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    if start_min == end_min:
        return False
    if start_min < end_min:
        return start_min <= cur_min < end_min
    return cur_min >= start_min or cur_min < end_min


@dataclass(frozen=True, slots=True)
class AlertRule:
    symbol: str
    metric: str
    operator: str
    value: str
    enabled: bool = True
    note: str = ""
    rule_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if self.metric not in METRICS:
            raise ValueError(f"metric must be one of: {', '.join(METRICS)}")
        if self.operator not in OPERATORS:
            raise ValueError(f"operator must be one of: {', '.join(OPERATORS)}")
        if self.metric in NUMERIC_METRICS:
            try:
                number = float(self.value)
            except (TypeError, ValueError):
                raise ValueError(f"{self.metric} alerts need a numeric value") from None
            if not math.isfinite(number):
                raise ValueError("alert value must be finite")
        elif self.operator != "==":
            raise ValueError(f"{self.metric} alerts only support the == operator")
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")

    def describe(self) -> str:
        return f"{self.symbol} {self.metric} {self.operator} {self.value}"

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> AlertRule:
        allowed = cls.__dataclass_fields__.keys()
        data = {key: value for key, value in values.items() if key in allowed}
        data["value"] = str(data.get("value", ""))
        return cls(**data)


def metric_value(
    metric: str, analysis: dict[str, Any], price: float, patterns: list[dict[str, str]]
) -> Any:
    if metric == "price":
        return price
    if metric == "rsi":
        return analysis.get("rsi")
    if metric == "score":
        return analysis.get("score")
    if metric == "adx":
        directional = analysis.get("adx")
        return directional.get("adx") if isinstance(directional, dict) else None
    if metric == "signal":
        return analysis.get("signal")
    if metric == "pattern":
        return [pattern["name"].lower() for pattern in patterns]
    raise ValueError(f"unknown metric {metric!r}")


class AlertEngine:
    """Edge-triggered evaluation: a rule fires once when it *becomes* true."""

    def __init__(
        self,
        rules: list[AlertRule] | None = None,
        *,
        cooldown_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rules: list[AlertRule] = list(rules or [])
        self._previous_values: dict[str, Any] = {}
        self._active: dict[str, bool] = {}
        self._last_fired: dict[str, float] = {}
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._clock = clock

    def evaluate(
        self,
        symbol: str,
        analysis: dict[str, Any],
        price: float,
        patterns: list[dict[str, str]] | None = None,
        *,
        cooldown_seconds: float | None = None,
    ) -> list[AlertRule]:
        effective_cooldown = (
            self.cooldown_seconds
            if cooldown_seconds is None
            else max(0.0, float(cooldown_seconds))
        )
        now = self._clock()
        fired = []
        for rule in self.rules:
            if not rule.enabled or rule.symbol not in {symbol, "*"}:
                continue
            key = f"{rule.rule_id}:{symbol}"
            current = metric_value(rule.metric, analysis, price, patterns or [])
            previous = self._previous_values.get(key)
            self._previous_values[key] = current
            matched = self._matches(rule, current, previous)
            was_active = self._active.get(key, False)
            self._active[key] = matched
            if matched and (not was_active or rule.operator.startswith("crosses")):
                last_time = self._last_fired.get(key)
                if (
                    effective_cooldown > 0.0
                    and last_time is not None
                    and (now - last_time) < effective_cooldown
                ):
                    continue
                self._last_fired[key] = now
                fired.append(rule)
        return fired

    @staticmethod
    def _matches(rule: AlertRule, current: Any, previous: Any) -> bool:
        if current is None:
            return False
        if rule.metric == "pattern":
            return rule.value.strip().lower() in current
        if rule.metric == "signal":
            return str(current).upper() == rule.value.strip().upper()
        threshold = float(rule.value)
        value = float(current)
        if rule.operator == "crosses above":
            return previous is not None and float(previous) <= threshold < value
        if rule.operator == "crosses below":
            return previous is not None and float(previous) >= threshold > value
        return {
            ">": value > threshold,
            ">=": value >= threshold,
            "<": value < threshold,
            "<=": value <= threshold,
            "==": math.isclose(value, threshold, rel_tol=1e-9, abs_tol=1e-12),
        }[rule.operator]

    def reset(self) -> None:
        self._previous_values.clear()
        self._active.clear()
        self._last_fired.clear()


class AlertRuleStore:
    """Atomic JSON persistence for alert rules; corrupt files load as empty."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_data_dir() / "alert-rules.json"

    def load(self) -> list[AlertRule]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        rules = []
        for item in data.get("rules", []) if isinstance(data, dict) else []:
            try:
                rules.append(AlertRule.from_dict(item))
            except (TypeError, ValueError):
                continue
        return rules

    def save(self, rules: list[AlertRule]) -> None:
        _atomic_json_write(self.path, {"rules": [asdict(rule) for rule in rules]})
