"""Advanced backend metrics & tracing (Batch 8).

In-memory metrics store with retention, tracing spans, health checks.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from .config import AppSettings


@dataclass
class MetricPoint:
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class Span:
    trace_id: str
    span_id: str
    name: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    status: str = "ok"
    attrs: dict[str, Any] = field(default_factory=dict)

    def finish(self, status: str = "ok") -> None:
        self.ended_at = time.time()
        self.status = status

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return round((self.ended_at - self.started_at) * 1000, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attrs": self.attrs,
        }


class MetricsStore:
    """Simple in-memory metrics + tracing store."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or AppSettings()
        self._metrics: dict[str, deque[MetricPoint]] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        self._spans: list[Span] = []
        self._health: dict[str, Any] = {"status": "ok", "checks": {}}

    # metrics
    def record(
        self, name: str, value: float, labels: dict[str, str] | None = None
    ) -> None:
        self._metrics[name].append(
            MetricPoint(name=name, value=value, labels=labels or {})
        )

    def series(self, name: str, limit: int = 100) -> list[MetricPoint]:
        return list(self._metrics.get(name, []))[-limit:]

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, dq in self._metrics.items():
            vals = [p.value for p in dq]
            if vals:
                out[name] = {
                    "count": len(vals),
                    "avg": round(sum(vals) / len(vals), 4),
                    "last": vals[-1],
                }
        return out

    # tracing
    def start_span(
        self,
        name: str,
        trace_id: str | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> Span:
        tid = trace_id or f"tr-{uuid.uuid4().hex[:8]}"
        sid = f"sp-{uuid.uuid4().hex[:8]}"
        # Sample
        if self.settings.tracing_enabled and self.settings.tracing_sample_rate < 1.0:
            import random

            if random.random() > self.settings.tracing_sample_rate:
                # Still create but mark sampled false
                pass
        span = Span(trace_id=tid, span_id=sid, name=name, attrs=attrs or {})
        self._spans.append(span)
        return span

    def spans(self, limit: int = 50) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._spans[-limit:]]

    # health
    def health_check(self, name: str, ok: bool, detail: str = "") -> None:
        self._health["checks"][name] = {"ok": ok, "detail": detail, "at": time.time()}
        self._health["status"] = (
            "ok"
            if all(v["ok"] for v in self._health["checks"].values())
            else "degraded"
        )

    def health(self) -> dict[str, Any]:
        return dict(self._health)

    def prune(self, now: float | None = None) -> int:
        """Prune metrics older than retention; returns removed count."""
        cutoff = (now or time.time()) - self.settings.metrics_retention_days * 86400
        removed = 0
        for dq in self._metrics.values():
            while dq and dq[0].timestamp < cutoff:
                dq.popleft()
                removed += 1
        return removed
