"""Neuro v2 CLI: TCN, diffusion-lite, meta-learner, hyper-search, evolution."""

from __future__ import annotations

import json
from typing import Any

from ..neural_v2 import ARCH_V2, V2_INFO, train_v2
from ..neuro_search import neuro_evolution_search


def cmd_neuro_v2(args: Any) -> int:
    action = getattr(args, "action", "list")
    if action == "list":
        if getattr(args, "json", False):
            print(json.dumps({k: V2_INFO[k] for k in ARCH_V2}, indent=2))
        else:
            for k in ARCH_V2:
                print(f"{k}: {V2_INFO[k]['note']}")
        return 0
    if action == "search":
        res = neuro_evolution_search([], trials=int(getattr(args, "trials", 8) or 8))
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "best_arch": res.best_arch,
                        "best_score": res.best_score,
                        "best_params": res.best_params,
                        "trials": res.trials,
                    },
                    indent=2,
                )
            )
        else:
            print(f"best {res.best_arch} score={res.best_score}")
        return 0
    if action == "train":
        arch = getattr(args, "arch", "neezy_tcn_v2")
        candles = [[i, 100.0, 102.0, 98.0, 100.0 + (i % 5) * 0.2] for i in range(300)]
        # Use a simple trending set to ensure training succeeds
        for i in range(len(candles)):
            base = 100 + i * 0.02
            candles[i] = [
                float(i),
                base,
                base + 1,
                base - 1,
                base + (0.3 if i % 2 == 0 else -0.3),
            ]
        try:
            out = train_v2(candles, architecture=arch)
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {"arch": arch, "report": out.get("report", {})}, indent=2
                    )
                )
            else:
                n_ex = out.get("report", {}).get("labeled_examples", "?")
                print(f"trained {arch}: {n_ex} examples")
        except Exception as exc:  # noqa: BLE001
            print(f"train failed: {exc}")
            return 1
        return 0
    print("usage: neuro-v2 <list|search|train> [--arch ...]")
    return 1
