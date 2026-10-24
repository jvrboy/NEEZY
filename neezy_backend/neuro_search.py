"""Neuro evolution / architecture search lite (Batch 8).

Deterministic genetic-style search over architecture ids and hyperparams.
No external deps; results are serializable for manifests.
"""

from __future__ import annotations

import random
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from .brain_advanced import ALL_ARCHITECTURES
from .config import AppSettings
from .neural_v2 import ARCH_V2

Candle = Sequence[float]
ALL_NEURAL = tuple(list(ALL_ARCHITECTURES) + list(ARCH_V2))


@dataclass
class SearchResult:
    best_arch: str
    best_score: float
    best_params: dict[str, Any]
    history: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: int = 0
    trials: int = 0


def _simulate_score(arch: str, params: dict[str, Any], seed: int) -> float:
    rng = random.Random(hash((arch, tuple(sorted(params.items())), seed)) & 0xFFFFFFFF)
    base = 0.5
    if "deep" in arch or "tcn" in arch or "transformer" in arch:
        base += 0.05
    if params.get("epochs", 30) > 40:
        base += 0.02
    base += rng.uniform(-0.05, 0.05)
    return max(0.0, min(1.0, round(base, 4)))


def neuro_evolution_search(
    candles: Sequence[Candle],
    *,
    candidates: Sequence[str] | None = None,
    trials: int = 12,
    seed: int = 17,
    settings: AppSettings | None = None,
) -> SearchResult:
    """Evolution-lite search: sample arch + params, track best by simulated score.

    Real scoring would train each candidate; here we simulate to stay fast/offline
    while preserving the search API for wiring.
    """
    cfg = settings or AppSettings()
    tri = trials if trials else cfg.neuro_search_trials
    cands = list(candidates) if candidates else list(ALL_NEURAL)
    rng = random.Random(seed)
    start = time.time()
    history: list[dict[str, Any]] = []
    best_arch = cands[0]
    best_score = -1.0
    best_params: dict[str, Any] = {}
    for i in range(tri):
        arch = rng.choice(cands)
        params = {
            "epochs": rng.randint(10, 60),
            "horizon": rng.randint(3, 10),
            "window": rng.randint(5, 20) if "seq" in arch else 0,
        }
        score = _simulate_score(arch, params, seed + i)
        history.append({"trial": i, "arch": arch, "params": params, "score": score})
        if score > best_score:
            best_score = score
            best_arch = arch
            best_params = dict(params)
    elapsed = int((time.time() - start) * 1000)
    return SearchResult(
        best_arch=best_arch,
        best_score=best_score,
        best_params=best_params,
        history=history,
        elapsed_ms=elapsed,
        trials=tri,
    )
