"""Pure read-only diagnostics over bounded executor snapshots.

Equity changes may include deposits/withdrawals. These window statistics are not
strategy returns, account-wide drawdown, performance forecasts, or VaR.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Any


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def equity_summary(samples: Any) -> dict[str, Any]:
    valid = []
    rejected = 0
    previous_time = None
    source = samples[-240:] if isinstance(samples, list) else []
    for sample in source:
        if not isinstance(sample, dict):
            rejected += 1
            continue
        value = _number(sample.get("equity"))
        try:
            timestamp = datetime.fromisoformat(sample.get("time", ""))
        except (TypeError, ValueError):
            timestamp = None
        if (
            value is None
            or value < 0
            or timestamp is None
            or timestamp.tzinfo is None
            or (previous_time is not None and timestamp <= previous_time)
        ):
            rejected += 1
            continue
        previous_time = timestamp
        valid.append((sample["time"], value))
    first = valid[0][1] if valid else None
    last = valid[-1][1] if valid else None
    peak = 0.0
    maximum_drawdown = 0.0
    for _time, value in valid:
        peak = max(peak, value)
        if peak > 0:
            maximum_drawdown = max(maximum_drawdown, (peak - value) / peak * 100)
    change = last - first if len(valid) > 1 else None
    return {
        "samples": len(valid),
        "rejected_samples": rejected,
        "first_time": valid[0][0] if valid else None,
        "last_time": valid[-1][0] if valid else None,
        "window_change": round(change, 8) if change is not None else None,
        "window_change_percent": round(change / first * 100, 6)
        if change is not None and first
        else None,
        "max_drawdown_percent": round(maximum_drawdown, 6) if len(valid) > 1 else None,
        "current_drawdown_percent": round((peak - last) / peak * 100, 6)
        if peak and last is not None and len(valid) > 1
        else None,
        "scope": "last 240 accepted equity observations, not full account history",
    }


def snapshot_insights(snapshot: dict[str, Any]) -> dict[str, Any]:
    heartbeat = _number(snapshot.get("heartbeat_age_seconds"))
    stale = heartbeat is None or heartbeat > 120
    positions = snapshot.get("open_trades")
    positions = positions if isinstance(positions, list) else []
    symbols = Counter(
        position["symbol"]
        for position in positions
        if isinstance(position, dict) and isinstance(position.get("symbol"), str)
    )
    issues = snapshot.get("issues")
    issues = issues if isinstance(issues, list) else []
    severity = Counter(
        str(issue.get("severity", "unknown"))
        for issue in issues
        if isinstance(issue, dict)
    )
    models = snapshot.get("models")
    models = models if isinstance(models, dict) else {}
    active = sum(
        isinstance(model, dict) and model.get("active") is True
        for model in models.values()
    )
    return {
        "schema": 1,
        "read_only": True,
        "quality": {
            "fresh": not stale,
            "stale_after_seconds": 120,
            "heartbeat_age_seconds": heartbeat,
            "issue_count": len(issues),
            "severity_counts": dict(severity),
            "active_models": active,
            "registered_models": len(models),
        },
        "equity": equity_summary(snapshot.get("equity_history")),
        "positions": {
            "total": len(positions),
            "by_symbol": dict(sorted(symbols.items())),
            "largest_symbol_share_percent": round(
                max(symbols.values()) / len(positions) * 100, 2
            )
            if symbols and positions
            else None,
            "measurement": (
                "position counts only, not notional exposure or portfolio risk"
            ),
        },
        "warning": (
            "Equity changes can include cash flows. "
            "Window statistics are not a strategy backtest."
        ),
    }
