"""Dashboard CLI: live backend overview (Batch 8)."""

from __future__ import annotations

import json
from typing import Any

from ..capabilities import feature_report, version_report
from ..config import AppSettings
from ..metrics_tracing import MetricsStore
from ..scheduler import Scheduler


def cmd_dashboard(args: Any) -> int:
    action = getattr(args, "action", "show")
    if action == "show":
        settings = AppSettings()
        metrics = MetricsStore(settings)
        metrics.record("demo_latency", 42.0)
        sched = Scheduler(settings)
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "version": version_report(),
                        "features": feature_report(),
                        "metrics": metrics.summary(),
                        "scheduler": sched.list_jobs(),
                        "settings": {
                            "reasoning": settings.reasoning_strategy,
                            "thinking": settings.thinking_mode,
                        },
                    },
                    indent=2,
                )
            )
        else:
            feats = feature_report()
            print(f"NEEZY Dashboard v{version_report().get('version')}")
            print(f"Features: {', '.join(k for k, v in feats.items() if v)}")
            rs = settings.reasoning_strategy
            tm = settings.thinking_mode
            print(f"Reasoning: {rs}/{tm} depth={settings.reasoning_depth}")
            print(f"Metrics: {metrics.summary()}")
            print(f"Scheduler jobs: {len(sched.jobs)}")
            tip = "Tip: try `reasoning think 'plan EURUSD trade'`"
            tip += " or `neuro-v2 list --json`"
            print(tip)
        return 0
    print("usage: dashboard show [--json]")
    return 1
