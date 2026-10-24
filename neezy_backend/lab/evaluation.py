"""Chronological, non-overlapping holdout diagnostics for research signals.

Parameters are supplied before the split; there is no parameter search, fitting,
model promotion, or order execution. A decision on close[i] enters open[i+1]
and exits close[i+horizon]. Fixed round-trip costs are subtracted in basis
points. This is a simplified hypothetical experiment, not a broker backtest.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any

from .service import analyze, validate_rows

DEFAULT_FIELDS = {
    ("fras", "FRAS"): "score",
    ("fxlab", "EWPO"): "pressure",
    ("fxlab", "RCBI"): "direction",
    ("tideforge", "CC"): "directional_score",
    ("tideforge", "FSCR"): "consensus",
    ("tideglass", "CC"): "score",
    ("tideglass", "FSCR"): "consensus",
}


def evaluate(
    rows,
    *,
    horizon: int = 5,
    holdout_fraction: float = 0.3,
    threshold: float = 0.0,
    cost_bps: float = 0.0,
    value_field: str | None = None,
    **analysis_options,
) -> dict[str, Any]:
    if (
        isinstance(horizon, bool)
        or not isinstance(horizon, int)
        or not 1 <= horizon <= 100
    ):
        raise ValueError("horizon must be an integer in 1..100 bars")
    for name, value, lo, hi in (
        ("holdout_fraction", holdout_fraction, 0.1, 0.5),
        ("threshold", threshold, 0.0, 10000.0),
        ("cost_bps", cost_bps, 0.0, 1000.0),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not lo <= value <= hi
        ):
            raise ValueError(f"{name} must be finite in [{lo}, {hi}]")
    candles = validate_rows(rows)
    if len(candles) < 50:
        raise ValueError("holdout evaluation needs at least 50 closed bars")
    analysis_options.pop("include_series", None)
    report = analyze(candles, include_series=True, **analysis_options)
    field = value_field or DEFAULT_FIELDS.get((report["engine"], report["indicator"]))
    if not field or not any(field in point["values"] for point in report["series"]):
        raise ValueError("choose an existing signed numeric output with --value-field")
    split = math.ceil(len(candles) * (1 - holdout_fraction))
    results = []
    next_decision = split
    for i in range(split, len(candles) - horizon):
        if i < next_decision:
            continue
        point = report["series"][i]
        score = point["values"].get(field)
        if (
            not point["ready"]
            or isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(score)
            or abs(score) <= threshold
        ):
            continue
        direction = 1 if score > 0 else -1
        entry = candles[i + 1][1]
        exit_price = candles[i + horizon][4]
        gross = direction * (exit_price - entry) / entry * 10000
        results.append(
            {
                "decision_epoch": candles[i][0],
                "entry_epoch": candles[i + 1][0],
                "exit_epoch": candles[i + horizon][0],
                "direction": direction,
                "gross_bps": gross,
                "net_bps": gross - cost_bps,
            }
        )
        next_decision = i + horizon
    net = [result["net_bps"] for result in results]
    return {
        "schema": 1,
        "kind": "chronological-holdout",
        "advisory_only": True,
        "engine": report["engine"],
        "indicator": report["indicator"],
        "symbol": report["symbol"],
        "bars": len(candles),
        "value_field": field,
        "horizon": horizon,
        "threshold": threshold,
        "cost_bps": cost_bps,
        "params": report["params"],
        "split_index": split,
        "holdout_start_epoch": candles[split][0],
        "observations": len(results),
        "hit_rate": sum(value > 0 for value in net) / len(net) if net else None,
        "mean_net_bps": mean(net) if net else None,
        "mean_gross_bps": mean(result["gross_bps"] for result in results)
        if results
        else None,
        "results": results,
        "assumptions": [
            "fixed parameters; no fitting or automatic optimization",
            "non-overlapping observations in the final chronological holdout",
            "next-bar open entry; horizon-bar close exit",
            "fixed round-trip cost; no leverage, sizing, spread model or market impact",
            "unadjusted hypothetical observations, not evidence of profitability",
        ],
    }
