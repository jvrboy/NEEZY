"""Enterprise export helpers: CSV signal sheets and JSON risk bundles.

Pure stdlib, no I/O beyond an explicit write call, so callers can preview the
export text before saving it.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SIGNAL_CSV_FIELDS = (
    "id",
    "created_at",
    "symbol",
    "timeframe",
    "signal",
    "score",
    "rsi",
    "adx",
    "regime",
    "entry",
)


def _row(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project one signal record onto the CSV schema, blank for missing keys."""
    return {field: record.get(field, "") for field in SIGNAL_CSV_FIELDS}


def signals_to_csv(signals: Sequence[Mapping[str, Any]]) -> str:
    """Render signal records as a CSV sheet with a stable header row."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer, fieldnames=list(SIGNAL_CSV_FIELDS), extrasaction="ignore"
    )
    writer.writeheader()
    for record in signals:
        writer.writerow(_row(record))
    return buffer.getvalue()


def risk_report_to_json(report: Mapping[str, Any], indent: int = 2) -> str:
    """Serialise a quant risk report to pretty JSON."""
    return json.dumps(dict(report), indent=indent, sort_keys=True, default=str)


def write_text(path: str | Path, text: str) -> Path:
    """Write export text to disk with a trailing newline and return the path."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = text if text.endswith("\n") else text + "\n"
    destination.write_text(payload, encoding="utf-8")
    return destination


def export_bundle(
    directory: str | Path,
    signals: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any],
) -> list[Path]:
    """Write a signals CSV and a risk JSON next to each other; returns paths."""
    base = Path(directory)
    return [
        write_text(base / "signals.csv", signals_to_csv(signals)),
        write_text(base / "risk_report.json", risk_report_to_json(report)),
    ]
