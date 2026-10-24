"""Snapshot capture logic (roadmap #24).

Centralises the "capture current market snapshot" helper that was previously
copy-pasted between :mod:`database`, :mod:`storage`, :mod:`mcp_tools` and
:mod:`tools`.  The helper is pure (no I/O) so it can be unit tested; the
thin ``save_snapshot`` wrapper keeps the existing DB API backward compatible.
"""

from __future__ import annotations

import time
from typing import Any


def capture_snapshot(
    symbol: str,
    timeframe: str,
    *,
    regime: str = "",
    signal: str = "",
    score: int = 0,
    payload: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a snapshot record dict without touching storage.

    All callers should go through this function so the field set, defaults,
    and timestamp format stay consistent.
    """
    if not symbol or not timeframe:
        raise ValueError("symbol and timeframe are required")
    if not isinstance(symbol, str) or not isinstance(timeframe, str):
        raise TypeError("symbol and timeframe must be strings")
    ts = created_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return {
        "created_at": ts,
        "symbol": symbol,
        "timeframe": timeframe,
        "regime": regime or "",
        "signal": signal or "",
        "score": int(score),
        "payload": dict(payload or {}),
    }


def snapshot_payload(
    indicators: dict[str, Any] | None = None,
    strategies: list[dict[str, Any]] | None = None,
    confluence: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a standard payload section for the snapshot.

    Keeps the shape that :mod:`database` and the UI expect.
    """
    out: dict[str, Any] = {}
    if indicators is not None:
        out["indicators"] = dict(indicators)
    if strategies is not None:
        out["strategies"] = list(strategies)
    if confluence is not None:
        out["confluence"] = dict(confluence)
    if extra:
        out.update(extra)
    return out
