"""Versioned JSON knowledge base: what the backtester learned per instrument.

Each record is produced by a train-then-validate study (see ``study.py``): the
parameters picked on the in-sample slice, how they did on the held-out slice,
and a verdict. The file ships inside the package and is read-only at runtime;
``save_knowledge`` rewrites it atomically after a study run.

Results are simulations over historical candles. A verdict of ``edge`` means the
rule set was profitable out of sample for that instrument over that window. It
is not a forecast.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backtest import BacktestConfig
from .catalog import instrument
from .storage import _atomic_json_write

SCHEMA_VERSION = 1
VERDICTS = ("edge", "no_edge", "insufficient_data", "error")
_CONFIG_FIELDS = frozenset(field.name for field in fields(BacktestConfig))

KNOWLEDGE_PATH = Path(__file__).resolve().parent / "data" / "knowledge.json"


def empty_document() -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": None,
        "method": "",
        "symbols": {},
    }


def _check_stats(name: str, stats: Any) -> None:
    if stats is None:
        return
    if not isinstance(stats, Mapping):
        raise ValueError(f"{name} must be an object or null")
    trades = stats.get("trades")
    if not isinstance(trades, int) or isinstance(trades, bool) or trades < 0:
        raise ValueError(f"{name}.trades must be a non-negative integer")


def _check_record(symbol: str, record: Any) -> None:
    if instrument(symbol) is None:
        raise ValueError(f"{symbol} is not in the instrument catalogue")
    if not isinstance(record, Mapping):
        raise ValueError(f"{symbol} record must be an object")
    verdict = record.get("verdict")
    if verdict not in VERDICTS:
        raise ValueError(f"{symbol} verdict must be one of {', '.join(VERDICTS)}")
    selected = record.get("selected")
    if selected is not None:
        if not isinstance(selected, Mapping):
            raise ValueError(f"{symbol} selected must be an object or null")
        unknown = set(selected) - _CONFIG_FIELDS
        if unknown:
            raise ValueError(f"{symbol} selected has unknown keys {sorted(unknown)}")
        try:
            BacktestConfig(**selected)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{symbol} selected is invalid: {error}") from error
    _check_stats(f"{symbol}.train", record.get("train"))
    _check_stats(f"{symbol}.test", record.get("test"))


def validate_document(document: Any) -> dict[str, Any]:
    """Return the document when well formed; raise ValueError describing the fault."""
    if not isinstance(document, Mapping):
        raise ValueError("knowledge document must be an object")
    if document.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"unsupported knowledge schema {document.get('schema')!r}")
    symbols = document.get("symbols")
    if not isinstance(symbols, Mapping):
        raise ValueError("symbols must be an object keyed by Deriv symbol")
    for symbol, record in symbols.items():
        _check_record(str(symbol), record)
    return dict(document)


def load_knowledge(path: Path | str | None = None) -> dict[str, Any]:
    """Load the knowledge base. A missing file is an empty base; bad content raises."""
    target = Path(path) if path else KNOWLEDGE_PATH
    if not target.exists():
        return empty_document()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"could not read {target}: {error}") from error
    return validate_document(raw)


def save_knowledge(
    document: Mapping[str, Any],
    path: Path | str | None = None,
    *,
    generated_at: datetime | None = None,
) -> Path:
    """Validate then atomically write the knowledge base; returns the path."""
    stamped = dict(document)
    stamped["generated_at"] = (generated_at or datetime.now(timezone.utc)).isoformat(
        timespec="seconds"
    )
    checked = validate_document(stamped)
    target = Path(path) if path else KNOWLEDGE_PATH
    _atomic_json_write(target, checked)
    return target


def record_for(
    symbol: str, document: Mapping[str, Any] | None = None
) -> dict[str, Any] | None:
    """The learned record for one Deriv symbol, or None when never studied."""
    base = document if document is not None else load_knowledge()
    record = base.get("symbols", {}).get(symbol)
    return dict(record) if record is not None else None


def summary(document: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Counts per verdict across the knowledge base."""
    base = document if document is not None else load_knowledge()
    counts = {verdict: 0 for verdict in VERDICTS}
    for record in base.get("symbols", {}).values():
        counts[record["verdict"]] += 1
    return {
        "generated_at": base.get("generated_at"),
        "symbols": len(base.get("symbols", {})),
        "verdicts": counts,
    }
