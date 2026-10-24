"""Model router: select/persist the best neural artifact per market (roadmap #advanced).

Registry is a small JSON file; routing prefers holdout Sharpe then val loss.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .brain_advanced import TrainingRun

REGISTRY_FILENAME = "model_router.json"


def route_best(
    runs: list[TrainingRun],
    *,
    min_holdout_samples: int = 20,
) -> TrainingRun | None:
    """Pick the run with the best holdout (higher Sharpe wins, then lower loss)."""
    if not runs:
        return None

    def key(r: TrainingRun) -> tuple[float, float]:
        hold = (
            r.metrics.get("holdout", {})
            if isinstance(r.metrics.get("holdout"), dict)
            else {}
        )
        sharpe = hold.get("sharpe") or hold.get("test_sharpe_unannualized") or 0.0
        try:
            s = float(sharpe)
        except Exception:
            s = 0.0
        loss = r.best_val_loss if r.best_val_loss is not None else float("inf")
        # Negate Sharpe so min() picks highest
        return (-s, loss)

    return min(runs, key=key)


def save_registry(path: str | Path, entries: dict[str, dict[str, Any]]) -> Path:
    """Persist a registry mapping ``symbol:timeframe -> manifest``."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write via tmp+replace
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)
    return p


def load_registry(path: str | Path) -> dict[str, dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def entry_for(
    registry: dict[str, dict[str, Any]], symbol: str, timeframe: str
) -> dict[str, Any] | None:
    return registry.get(f"{symbol}:{timeframe}")
