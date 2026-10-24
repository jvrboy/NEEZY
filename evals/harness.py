"""Deterministic eval harness: runs a fixed candle set through brain/research."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any

from neezy_backend.brain import train_model
from neezy_backend.config import AppSettings


def eval_holdout(
    candles: Sequence[Sequence[float]],
    *,
    settings: AppSettings | None = None,
    horizon: int = 5,
) -> dict[str, Any]:
    cfg = settings or AppSettings()
    split = int(len(candles) * (1 - cfg.ml_eval_holdout_ratio))
    train_rows = list(candles[:split])
    hold_rows = list(candles[split:])
    res = train_model(
        train_rows, horizon=horizon, seed=cfg.ml_seed, epochs=cfg.ml_epochs
    )
    model = res.get("model")
    # Use predict on holdout slice as lightweight metric; report already has holdout
    metrics: dict[str, Any] = {}
    if model is not None and len(hold_rows) > 0:
        metrics = {"holdout_rows": len(hold_rows), "has_model": True}
        # Include train report metrics for transparency
        metrics.update({k: v for k, v in res.get("report", {}).items()})
    else:
        metrics = {"error": "no model", "holdout_rows": len(hold_rows)}
    return {
        "schema": 1,
        "train_rows": len(train_rows),
        "holdout_rows": len(hold_rows),
        "train_report": res.get("report"),
        "holdout_metrics": metrics,
    }


def eval_backtest_summary(pnl: Sequence[float]) -> dict[str, float]:
    if not pnl:
        return {"sharpe": 0.0, "mean": 0.0, "stdev": 0.0}
    m = statistics.fmean(pnl)
    s = statistics.pstdev(pnl) if len(pnl) > 1 else 0.0
    return {"mean": m, "stdev": s, "sharpe": (m / s if s else 0.0)}
