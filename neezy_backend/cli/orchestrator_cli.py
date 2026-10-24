"""Orchestrator & fusion CLI (Batch 8)."""

from __future__ import annotations

import json
from typing import Any

from ..metrics_tracing import MetricsStore
from ..orchestrator import Orchestrator, Task
from ..signal_fusion import detect_anomalies, explain_score, fuse_signals


def cmd_orchestrator(args: Any) -> int:
    action = getattr(args, "action", "demo")
    if action == "demo":
        orch = Orchestrator(max_parallel=2)
        orch.add_task(Task(id="fetch", name="fetch candles"))
        orch.add_task(
            Task(
                id="analyse",
                name="analyse",
                depends_on=["fetch"],
                fn=lambda ctx: {"context_update": {"score": 42}},
            )
        )
        orch.add_task(Task(id="report", name="report", depends_on=["analyse"]))
        res = orch.run({"symbol": "EURUSD"})
        summ = orch.summary(res)
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        k: {"ok": v.ok, "output": v.output, "error": v.error}
                        for k, v in res.items()
                    },
                    indent=2,
                )
            )
        else:
            print(f"orchestrator: {summ}")
        return 0
    print("usage: orchestrator demo")
    return 1


def cmd_fusion(args: Any) -> int:
    demo = [
        {"source": "trend", "score": 1.2, "confidence": 0.7},
        {"source": "momentum", "score": -0.4, "confidence": 0.6},
        {"source": "neural", "score": 0.8, "confidence": 0.5},
    ]
    fused = fuse_signals(demo)
    expl = explain_score({s["source"]: s["score"] for s in demo})
    anoms = detect_anomalies([1, 1.1, 0.9, 10.0, 1.0])
    if getattr(args, "json", False):
        print(
            json.dumps({"fused": fused, "explain": expl, "anomalies": anoms}, indent=2)
        )
    else:
        print(f"fused={fused} anomalies={anoms} top={expl['top_driver']}")
    return 0


def cmd_metrics(args: Any) -> int:
    store = MetricsStore()
    store.record("latency_ms", 123.4, labels={"endpoint": "predict"})
    store.record("latency_ms", 98.1)
    span = store.start_span("demo-span")
    span.finish()
    store.health_check("db", True, "ok")
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "summary": store.summary(),
                    "health": store.health(),
                    "spans": store.spans(limit=2),
                },
                indent=2,
            )
        )
    else:
        print(f"metrics={store.summary()} health={store.health()['status']}")
    return 0
