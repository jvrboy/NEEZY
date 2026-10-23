"""Typed repository layer over the local SQLite tables. (roadmap #5)

``LocalDatabase`` used to embed every ``INSERT``/``SELECT`` for candles,
signals, snapshots and AI usage inline in one 600-line class. This module
wraps each table in a repository class with explicit method contracts, so:

* callers never build SQL (the wrapper methods on :class:`LocalDatabase`
  now delegate here, keeping every public name and behaviour);
* schema migrations and future storage engines have one narrow boundary;
* row → dict conversion (JSON payloads, ordering) lives next to the SQL.

Repositories receive the :class:`LocalDatabase` instance and execute through
its connection and re-entrant lock, so thread safety and WAL behaviour are
unchanged. Timestamps and JSON-safety helpers are shared from here.
"""

from __future__ import annotations

import json
import math
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .candles import Candle, CandleError, validate_candle_row

if TYPE_CHECKING:
    from .database import LocalDatabase

SQL_ROWS = Iterable[sqlite3.Row]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value: Any) -> Any:
    """Make analysis output storable: drop non-finite floats and series blobs."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


# Validity checks shared by the repositories so both direct-repo and
# LocalDatabase paths enforce the same contracts.
def _check_limit(limit: int, *, minimum: int = 1) -> int:
    if not isinstance(limit, int) or limit < minimum:
        raise ValueError("limit must be a positive integer")
    return limit


def _check_identity(symbol: str, timeframe: str) -> tuple[str, str]:
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("symbol must be a non-empty string")
    if not isinstance(timeframe, str) or not timeframe.strip():
        raise ValueError("timeframe must be a non-empty string")
    return symbol, timeframe


class Repository:
    """Common plumbing: execute through the LocalDatabase lock/connection."""

    def __init__(self, database: LocalDatabase) -> None:
        self.database = database

    @property
    def _connection(self) -> sqlite3.Connection:
        return self.database.connection

    @property
    def _lock(self) -> Any:
        return self.database._lock


class CandleRepo(Repository):
    """Upsert/read/count/prune the ``candles`` table."""

    def upsert(
        self,
        symbol: str,
        timeframe: str,
        candles: Iterable[Any],
    ) -> int:
        """Upsert valid OHLC rows (malformed rows are skipped); count written.

        The historical :class:`LocalDatabase.save_candles` contract is lenient:
        bad rows are dropped, good rows are written, and the count reflects
        only what was written. The fetch-side pipelines (stream/providers and
        :class:`CandleAccessor`) fail loud instead; this boundary stays
        backwards compatible with persisted offline imports.
        """
        symbol, timeframe = _check_identity(symbol, timeframe)
        if not self.database.store_candles:
            return 0
        stamp = _now().isoformat(timespec="seconds")
        rows: list[tuple[Any, ...]] = []
        for candidate in candles:
            try:
                candle = validate_candle_row(candidate, source="candle repository")
            except CandleError:
                continue  # documented skip: mirrors historical save_candles
            rows.append(
                (
                    symbol,
                    timeframe,
                    candle[0],
                    candle[1],
                    candle[2],
                    candle[3],
                    candle[4],
                    stamp,
                )
            )
        if not rows:
            return 0
        with self._lock:
            self._connection.executemany(
                "INSERT OR REPLACE INTO candles "
                "(symbol, timeframe, epoch, open, high, low, close, saved_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._connection.commit()
        return len(rows)

    def tail(self, symbol: str, timeframe: str, limit: int = 500) -> list[Candle]:
        """The ``limit`` most recent stored rows, oldest first."""
        symbol, timeframe = _check_identity(symbol, timeframe)
        _check_limit(limit)
        with self._lock:
            rows = self._connection.execute(
                "SELECT epoch, open, high, low, close FROM candles "
                "WHERE symbol = ? AND timeframe = ? ORDER BY epoch DESC LIMIT ?",
                (symbol, timeframe, limit),
            ).fetchall()
        return [
            (int(row["epoch"]), row["open"], row["high"], row["low"], row["close"])
            for row in reversed(rows)
        ]

    def count(self, symbol: str | None = None) -> int:
        with self._lock:
            if symbol is None:
                row = self._connection.execute(
                    "SELECT COUNT(*) AS n FROM candles"
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT COUNT(*) AS n FROM candles WHERE symbol = ?", (symbol,)
                ).fetchone()
        return int(row["n"]) if row else 0

    def prune_before(self, epoch_cutoff: int) -> int:
        """Delete candles older than the epoch cutoff; rows removed."""
        if not isinstance(epoch_cutoff, int):
            raise ValueError("epoch_cutoff must be an integer epoch")
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM candles WHERE epoch < ?", (epoch_cutoff,)
            )
            self._connection.commit()
        return cursor.rowcount


class SignalRepo(Repository):
    """Append/read/count/prune persisted signal transitions."""

    def insert(
        self,
        *,
        symbol: str,
        timeframe: str,
        signal: str,
        score: float,
        price: float | None = None,
        strategy: str = "",
        direction: int = 0,
        confidence: float = 0.0,
        payload: dict[str, Any] | None = None,
    ) -> int:
        """Append one signal transition; returns the new row id."""
        symbol, timeframe = _check_identity(symbol, timeframe)
        if not isinstance(signal, str) or not signal.strip():
            raise ValueError("signal must be a non-empty string")
        armament = (score, confidence)
        if any(not isinstance(value, (int, float)) for value in armament):
            raise ValueError("score and confidence must be numbers")
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO signals (created_at, symbol, timeframe, strategy, "
                "signal, direction, score, confidence, price, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now().isoformat(timespec="seconds"),
                    symbol,
                    timeframe,
                    strategy,
                    signal,
                    int(direction),
                    float(score),
                    float(confidence),
                    None if price is None else float(price),
                    None if payload is None else json.dumps(_json_safe(payload)),
                ),
            )
            self._connection.commit()
        return int(cursor.lastrowid or 0)

    def recent(
        self, limit: int = 50, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        """Saved transitions, newest first, JSON payloads decoded."""
        _check_limit(limit)
        query = "SELECT * FROM signals"
        params: list[Any] = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self.row_record(row) for row in rows]

    def count(self, symbol: str | None = None) -> int:
        with self._lock:
            if symbol is None:
                row = self._connection.execute(
                    "SELECT COUNT(*) AS n FROM signals"
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT COUNT(*) AS n FROM signals WHERE symbol = ?", (symbol,)
                ).fetchone()
        return int(row["n"]) if row else 0

    def prune_before(self, stamp: str) -> int:
        """Delete transition rows saved before the ISO stamp; rows removed."""
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM signals WHERE created_at < ?", (stamp,)
            )
            self._connection.commit()
        return cursor.rowcount

    @staticmethod
    def row_record(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        payload = record.get("payload")
        if isinstance(payload, str):
            try:
                record["payload"] = json.loads(payload)
            except json.JSONDecodeError:
                record["payload"] = None
        return record


class SnapshotRepo(Repository):
    """Save/read/prune stored ``analyze()`` snapshots."""

    def save(self, *, symbol: str, timeframe: str, result: dict[str, Any]) -> int:
        """Store one snapshot payload; returns the new row id."""
        symbol, timeframe = _check_identity(symbol, timeframe)
        if not isinstance(result, dict):
            raise ValueError("result must be a mapping of snapshot fields")
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO snapshots (created_at, symbol, timeframe, regime, "
                "signal, score, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _now().isoformat(timespec="seconds"),
                    symbol,
                    timeframe,
                    str(result.get("regime", "")),
                    str(result.get("signal", "")),
                    int(result.get("score", 0)),
                    json.dumps(_json_safe(result)),
                ),
            )
            self._connection.commit()
        return int(cursor.lastrowid or 0)

    def latest(
        self, symbol: str, timeframe: str | None = None
    ) -> dict[str, Any] | None:
        """Newest snapshot for the symbol (optionally one timeframe)."""
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol must be a non-empty string")
        query = "SELECT * FROM snapshots WHERE symbol = ?"
        params: list[Any] = [symbol]
        if timeframe:
            query += " AND timeframe = ?"
            params.append(timeframe)
        query += " ORDER BY id DESC LIMIT 1"
        with self._lock:
            row = self._connection.execute(query, params).fetchone()
        if row is None:
            return None
        record = dict(row)
        try:
            record["payload"] = json.loads(record["payload"])
        except (json.JSONDecodeError, TypeError):
            record["payload"] = None
        return record

    def prune_before(self, stamp: str) -> int:
        """Delete snapshots saved before the ISO stamp; rows removed."""
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM snapshots WHERE created_at < ?", (stamp,)
            )
            self._connection.commit()
        return cursor.rowcount


class UsageRepo(Repository):
    """Record/read/prune AI provider usage rows."""

    def record(
        self,
        *,
        provider: str,
        model: str,
        status: str,
        key_label: str = "",
        latency_ms: int = 0,
        prompt_chars: int = 0,
        response_chars: int = 0,
        detail: str = "",
    ) -> int:
        """Append one usage row; returns the new row id.

        ``status`` is a free label the AI client assigns (ok / error / quota /
        request-error / bad-response); it is stored verbatim for reporting.
        """
        if not provider.strip() or not model.strip():
            raise ValueError("provider and model must be non-empty")
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO ai_calls (created_at, provider, model, key_label, "
                "status, latency_ms, prompt_chars, response_chars, detail) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _now().isoformat(timespec="seconds"),
                    provider,
                    model,
                    key_label,
                    status,
                    int(latency_ms),
                    int(prompt_chars),
                    int(response_chars),
                    detail[:500],
                ),
            )
            self._connection.commit()
        return int(cursor.lastrowid or 0)

    def usage(self, limit: int = 100) -> dict[str, Any]:
        """Recent rows plus per-provider and per-status tallies."""
        _check_limit(limit)
        with self._lock:
            rows = self._connection.execute(
                "SELECT provider, model, status, latency_ms, created_at "
                "FROM ai_calls ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        by_provider: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for row in rows:
            by_provider[row["provider"]] = by_provider.get(row["provider"], 0) + 1
            by_status[row["status"]] = by_status.get(row["status"], 0) + 1
        return {
            "calls": [dict(row) for row in rows],
            "by_provider": by_provider,
            "by_status": by_status,
            "total": len(rows),
        }

    def prune_before(self, stamp: str) -> int:
        """Delete usage rows saved before the ISO stamp; rows removed."""
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM ai_calls WHERE created_at < ?", (stamp,)
            )
            self._connection.commit()
        return cursor.rowcount


__all__ = [
    "CandleRepo",
    "SignalRepo",
    "SnapshotRepo",
    "UsageRepo",
]
