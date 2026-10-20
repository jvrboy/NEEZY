"""Fully local SQLite storage for candles, signals, snapshots, and AI usage.

The database lives in the per-user NEEZY data directory (``NEEZY_HOME``
overrides it) and is the single on-PC source of truth for history. SQLite is
part of the Python standard library, so this adds no dependency and no server.
WAL mode keeps the UI responsive while a backtest or AI call writes.

Nothing here is ever uploaded: the file only leaves the machine if the user
exports it.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .storage import get_data_dir

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_info (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    saved_at TEXT NOT NULL,
    PRIMARY KEY (symbol, timeframe, epoch)
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    strategy TEXT NOT NULL DEFAULT '',
    signal TEXT NOT NULL,
    direction INTEGER NOT NULL DEFAULT 0,
    score REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    price REAL,
    payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_time
    ON signals (symbol, created_at DESC);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    regime TEXT NOT NULL DEFAULT '',
    signal TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_time
    ON snapshots (symbol, created_at DESC);
CREATE TABLE IF NOT EXISTS ai_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    key_label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    prompt_chars INTEGER NOT NULL DEFAULT 0,
    response_chars INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ai_calls_time ON ai_calls (created_at DESC);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


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


class LocalDatabase:
    """Thread-safe wrapper around one SQLite file with bounded retention."""

    TABLES = ("candles", "signals", "snapshots", "ai_calls", "kv")

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        retention_days: int = 90,
        store_candles: bool = True,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        self.path = Path(path) if path else get_data_dir() / "neezy.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.store_candles = store_candles
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.path, check_same_thread=False, timeout=10.0
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.executescript(_SCHEMA)
            self._connection.execute(
                "INSERT OR IGNORE INTO schema_info (key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self._connection.commit()

    # ------------------------------------------------------------------ lifecycle
    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> LocalDatabase:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --------------------------------------------------------------------- candles
    def save_candles(
        self,
        symbol: str,
        timeframe: str,
        candles: Iterable[Sequence[float]],
    ) -> int:
        """Upsert OHLC rows; returns the number written."""
        if not self.store_candles:
            return 0
        stamp = _now().isoformat(timespec="seconds")
        rows = []
        for candle in candles:
            if len(candle) < 5:
                continue
            epoch, open_, high, low, close = candle[:5]
            values = [float(open_), float(high), float(low), float(close)]
            if not all(math.isfinite(value) and value > 0 for value in values):
                continue
            rows.append((symbol, timeframe, int(epoch), *values, stamp))
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

    def load_candles(
        self, symbol: str, timeframe: str, limit: int = 500
    ) -> list[tuple[int, float, float, float, float]]:
        if limit < 1:
            raise ValueError("limit must be positive")
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

    def candle_count(self, symbol: str | None = None) -> int:
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

    # --------------------------------------------------------------------- signals
    def save_signal(
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

    def recent_signals(
        self, limit: int = 50, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be positive")
        query = "SELECT * FROM signals"
        params: list[Any] = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._connection.execute(query, params).fetchall()
        return [self._signal_row(row) for row in rows]

    @staticmethod
    def _signal_row(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        payload = record.get("payload")
        if isinstance(payload, str):
            try:
                record["payload"] = json.loads(payload)
            except json.JSONDecodeError:
                record["payload"] = None
        return record

    # ------------------------------------------------------------------- snapshots
    def save_snapshot(
        self, *, symbol: str, timeframe: str, result: dict[str, Any]
    ) -> int:
        """Store one ``analyze()`` result for later review."""
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

    def latest_snapshot(
        self, symbol: str, timeframe: str | None = None
    ) -> dict[str, Any] | None:
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

    # -------------------------------------------------------------------- AI usage
    def record_ai_call(
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

    def ai_usage(self, limit: int = 100) -> dict[str, Any]:
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

    # ------------------------------------------------------------------------ kv
    def set_value(self, key: str, value: Any) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT OR REPLACE INTO kv (key, value, updated_at) VALUES (?, ?, ?)",
                (
                    key,
                    json.dumps(_json_safe(value)),
                    _now().isoformat(timespec="seconds"),
                ),
            )
            self._connection.commit()

    def get_value(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM kv WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return default

    # ---------------------------------------------------------------- maintenance
    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts = {
                table: int(
                    self._connection.execute(
                        f"SELECT COUNT(*) AS n FROM {table}"
                    ).fetchone()["n"]
                )
                for table in self.TABLES
            }
        size = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(self.path) + suffix)
            try:
                size += candidate.stat().st_size
            except OSError:
                continue
        return {
            "path": str(self.path),
            "size_bytes": size,
            "size_mb": round(size / (1024 * 1024), 2),
            "counts": counts,
            "retention_days": self.retention_days,
            "store_candles": self.store_candles,
            "journal_mode": self._journal_mode(),
        }

    def _journal_mode(self) -> str:
        with self._lock:
            row = self._connection.execute("PRAGMA journal_mode").fetchone()
        return str(row[0]) if row else "unknown"

    def prune(
        self, *, retention_days: int | None = None, now: datetime | None = None
    ) -> dict[str, int]:
        """Delete rows older than the retention window; safe to run on a timer."""
        days = self.retention_days if retention_days is None else int(retention_days)
        if days < 1:
            raise ValueError("retention_days must be positive")
        cutoff = (now or _now()) - timedelta(days=days)
        stamp = cutoff.isoformat(timespec="seconds")
        epoch_cutoff = int(cutoff.timestamp())
        removed: dict[str, int] = {}
        with self._lock:
            for table in ("signals", "snapshots", "ai_calls"):
                cursor = self._connection.execute(
                    f"DELETE FROM {table} WHERE created_at < ?",
                    (stamp,),
                )
                removed[table] = cursor.rowcount
            cursor = self._connection.execute(
                "DELETE FROM candles WHERE epoch < ?", (epoch_cutoff,)
            )
            removed["candles"] = cursor.rowcount
            self._connection.commit()
        return removed

    def vacuum(self) -> None:
        with self._lock:
            self._connection.commit()
            self._connection.execute("VACUUM")

    def export_json(self, destination: Path | str) -> dict[str, int]:
        """Write a portable JSON dump; returns the row counts per table."""
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "exported_at": _now().isoformat(timespec="seconds"),
            "schema_version": SCHEMA_VERSION,
            "tables": {},
        }
        counts: dict[str, int] = {}
        with self._lock:
            for table in self.TABLES:
                rows = [
                    dict(row)
                    for row in self._connection.execute(
                        f"SELECT * FROM {table}"
                    ).fetchall()
                ]
                payload["tables"][table] = rows
                counts[table] = len(rows)
        destination.write_text(
            json.dumps(_json_safe(payload), indent=2), encoding="utf-8"
        )
        return counts

    def clear(self, table: str | None = None) -> None:
        """Delete the contents of one table, or all data tables."""
        targets = [table] if table else ["candles", "signals", "snapshots", "ai_calls"]
        for name in targets:
            if name not in self.TABLES or name == "kv":
                raise ValueError(f"unknown or protected table {name!r}")
        with self._lock:
            for name in targets:
                self._connection.execute(f"DELETE FROM {name}")
            self._connection.commit()
