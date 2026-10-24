"""Signal fusion, anomaly detection, explainability (Batch 8)."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any


def fuse_signals(
    signals: list[dict[str, Any]], *, weights: dict[str, float] | None = None
) -> dict[str, Any]:
    """Weighted fusion of signal dicts each with ``score`` and optional ``confidence``."""
    if not signals:
        return {"fused_score": 0.0, "confidence": 0.0, "contributors": 0}
    w = weights or {}
    total_w = 0.0
    fused = 0.0
    conf_sum = 0.0
    for s in signals:
        name = s.get("source", s.get("name", "unknown"))
        weight = w.get(name, 1.0)
        score = float(s.get("score", 0))
        conf = float(s.get("confidence", 0.5))
        fused += score * weight * conf
        conf_sum += conf * weight
        total_w += weight
    norm = conf_sum / total_w if total_w else 0.5
    return {
        "fused_score": round(fused / max(total_w, 1), 4),
        "confidence": round(min(0.95, norm), 4),
        "contributors": len(signals),
        "weights": w,
    }


def detect_anomalies(values: Sequence[float], *, z_threshold: float = 3.0) -> list[int]:
    """Return indices where |z| > threshold (simple z-score, stdlib)."""
    if len(values) < 3:
        return []
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
    if stdev < 1e-12:
        return []
    return [i for i, v in enumerate(values) if abs((v - mean) / stdev) > z_threshold]


def explain_score(contributors: dict[str, float]) -> dict[str, Any]:
    """Explain a score by ranking contributors (positive/negative)."""
    total = sum(abs(v) for v in contributors.values()) or 1.0
    ranked = sorted(contributors.items(), key=lambda kv: abs(kv[1]), reverse=True)
    return {
        "ranked": [
            {"name": k, "value": v, "share": round(abs(v) / total, 3)}
            for k, v in ranked
        ],
        "total_abs": total,
        "top_driver": ranked[0][0] if ranked else None,
    }


def isolation_score(value: float, history: Sequence[float]) -> float:
    """Isolation-like score: distance from median scaled by IQR proxy."""
    if not history:
        return 0.0
    med = statistics.median(history)
    mad = statistics.median([abs(x - med) for x in history]) or 1.0
    return round(min(1.0, abs(value - med) / (3 * mad)), 4)
