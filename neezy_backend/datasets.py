"""Shipped knowledge datasets: JSON files inside the package ``data`` folder.

Every JSON file in ``neezy_backend/data`` is a knowledge dataset the desktop
app and the CLI can consult offline: curated reference material, strategy
notes, and per-symbol model weights derived from out-of-sample study runs
(see ``knowledge.py``). Datasets are read-only at runtime and cached after
first load; ``clear_cache`` forces a reload during tests or hot edits.

Nothing in a dataset is a forecast: entries carry caveats and the weights
come from backtests over historical candles with a charged spread.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"

MARKET_KNOWLEDGE = "market_knowledge.json"
STRATEGY_PLAYBOOK = "strategy_playbook.json"
MODEL_WEIGHTS = "model_weights.json"


def dataset_path(name: str) -> Path:
    """Resolve a dataset name to a path inside the package data folder.

    Rejects anything that is not a plain ``*.json`` file name so the loader
    can never be pointed outside ``DATA_DIR``.
    """
    if not name or not name.endswith(".json"):
        raise ValueError("dataset name must end with .json")
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError("dataset name must be a plain file name")
    target = DATA_DIR / name
    if not target.exists():
        raise FileNotFoundError(f"no such dataset: {name}")
    return target


def _read(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read dataset {path.name}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"dataset {path.name} must contain a JSON object")
    return document


@lru_cache(maxsize=None)
def load_dataset(name: str) -> dict[str, Any]:
    """Load and cache one dataset; a missing or malformed file raises."""
    return _read(dataset_path(name))


def list_datasets() -> list[str]:
    """Sorted file names of every dataset shipped in the data folder."""
    return sorted(path.name for path in DATA_DIR.glob("*.json") if path.is_file())


def market_knowledge() -> dict[str, Any]:
    """Curated indicator, pattern, risk and Deriv-API reference material."""
    return load_dataset(MARKET_KNOWLEDGE)


def strategy_playbook() -> dict[str, Any]:
    """Reference sheet for the named strategies and the consensus rule."""
    return load_dataset(STRATEGY_PLAYBOOK)


def model_weights() -> dict[str, Any]:
    """Per-symbol edge weights derived from the out-of-sample study records."""
    return load_dataset(MODEL_WEIGHTS)


def indicator_names() -> list[str]:
    """Indicator titles covered by the market-knowledge dataset."""
    entries = market_knowledge().get("indicators", [])
    return [str(entry.get("name", "")) for entry in entries if entry.get("name")]


def weight_for(symbol: str) -> dict[str, Any] | None:
    """The learned model-weight record for one Deriv symbol, or None."""
    record = model_weights().get("symbols", {}).get(symbol)
    return dict(record) if record is not None else None


def dataset_summary() -> dict[str, Any]:
    """Compact inventory used by the UI and ``neezy-cli datasets``."""
    inventory: dict[str, Any] = {}
    for name in list_datasets():
        document = _read(dataset_path(name))
        keys = sorted(key for key in document if key not in {"schema"})
        inventory[name] = {"keys": keys, "bytes": dataset_path(name).stat().st_size}
    weights = model_weights().get("symbols", {})
    return {
        "data_dir": str(DATA_DIR),
        "datasets": inventory,
        "weighted_symbols": len(weights),
    }


def clear_cache() -> None:
    """Drop cached datasets so the next load re-reads the files."""
    load_dataset.cache_clear()
