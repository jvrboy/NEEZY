"""Watchlist import/export helpers (roadmap #94)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .markets import SYMBOLS, display_name

SCHEMA_VERSION = 1


def export_watchlist(
    destination: Path | str,
    *,
    symbols: list[str],
    meta: dict[str, Any] | None = None,
) -> Path:
    """Write *symbols* to *destination* as JSON (schema v1)."""
    path = Path(destination)
    unknown = [s for s in symbols if s not in SYMBOLS]
    if unknown:
        raise ValueError(f"Unknown symbols: {', '.join(unknown)}")
    doc = {
        "schema_version": SCHEMA_VERSION,
        "symbols": list(symbols),
        "count": len(symbols),
        "meta": dict(meta or {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def import_watchlist(source: Path | str) -> dict[str, Any]:
    """Read a watchlist JSON file and validate it.

    Returns the parsed doc dict (so callers can inspect ``symbols`` and ``meta``).
    Raises ``ValueError`` on bad schema or unknown symbols.
    """
    path = Path(source)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Watchlist file must contain a JSON object")
    ver = raw.get("schema_version")
    if ver != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported watchlist schema_version {ver!r}; expected {SCHEMA_VERSION}"
        )
    symbols = raw.get("symbols")
    if not isinstance(symbols, list) or not symbols:
        raise ValueError("Watchlist must have a non-empty 'symbols' list")
    unknown = [s for s in symbols if s not in SYMBOLS]
    if unknown:
        raise ValueError(f"Unknown symbols in file: {', '.join(unknown)}")
    # Normalise display for callers (not stored)
    display = {s: display_name(s) for s in symbols}
    return {
        "schema_version": SCHEMA_VERSION,
        "symbols": list(symbols),
        "display": display,
        "count": len(symbols),
        "meta": dict(raw.get("meta") or {}),
        "source": str(path),
    }


def watchlist_summary(symbols: list[str]) -> str:
    """Human-readable one-liner for CLI output."""
    names = [display_name(s) for s in symbols]
    return f"{len(symbols)} symbols: " + ", ".join(names)
