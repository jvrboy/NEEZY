"""Shared helpers for the NEEZY CLI command modules.

Output formatting (JSON emit, tables), argument coercion, and small
utilities used by every command family. Command handlers live in the
sibling modules; the package entry point is ``neezy_backend.cli``.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from typing import Any, TextIO

from ..database import LocalDatabase
from ..markets import SYMBOLS


def _symbol(value: str) -> str:
    candidates = {key.upper(): key for key in SYMBOLS}
    candidates.update(
        {name.replace("/", "").upper(): key for key, name in SYMBOLS.items()}
    )
    key = value.replace("/", "").upper()
    if key in candidates:
        return candidates[key]
    if ("FRX" + key) in candidates:
        return candidates["FRX" + key]
    raise argparse.ArgumentTypeError(
        f"unknown market {value!r}; run 'neezy-cli markets' to list them"
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    raise TypeError(f"not serialisable: {type(value).__name__}")


def _emit(out: TextIO, data: Any) -> None:
    out.write(json.dumps(_finite(data), indent=2, default=_json_default) + "\n")


def _finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(item) for item in value]
    return value


def _table(out: TextIO, headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    cells = [[str(cell) for cell in row] for row in rows]
    widths = [
        max(len(header), *(len(row[i]) for row in cells)) if cells else len(header)
        for i, header in enumerate(headers)
    ]
    out.write(
        "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=True)) + "\n"
    )
    out.write("  ".join("-" * w for w in widths) + "\n")
    for row in cells:
        out.write(
            "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)) + "\n"
        )


def _without_series(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "closes"}


def _closed(candles):
    return list(candles[:-1]) if len(candles) > 1 else []


def _open_database() -> LocalDatabase:
    return LocalDatabase()
