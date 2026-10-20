"""Versioned SQLite schema migrations.

Version 1 is the baseline created by ``database._SCHEMA``. Append new
``(version, sql)`` entries to ``MIGRATIONS``; never edit or reorder shipped ones.
Each migration runs in its own transaction together with its version bump, so a
failure leaves the database exactly at the previous version.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

BASELINE_VERSION = 1

MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        2,
        "CREATE INDEX IF NOT EXISTS idx_signals_strategy "
        "ON signals (strategy, created_at DESC);",
    ),
    (
        3,
        "CREATE INDEX IF NOT EXISTS idx_candles_epoch ON candles (epoch);",
    ),
)


def latest_version(migrations: Sequence[tuple[int, str]] = MIGRATIONS) -> int:
    """Highest schema version the code knows how to produce."""
    return max((version for version, _sql in migrations), default=BASELINE_VERSION)


def read_version(connection: sqlite3.Connection) -> int:
    """Return the stored schema version, or 0 when it is missing or unreadable."""
    try:
        row = connection.execute(
            "SELECT value FROM schema_info WHERE key = 'version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def apply_migrations(
    connection: sqlite3.Connection,
    migrations: Sequence[tuple[int, str]] = MIGRATIONS,
) -> int:
    """Apply every pending migration in order; returns the resulting version."""
    versions = [version for version, _sql in migrations]
    if len(set(versions)) != len(versions):
        raise ValueError("duplicate migration versions")
    current = read_version(connection)
    for version, sql in sorted(migrations):
        if version <= current:
            continue
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{sql}\n"
            f"UPDATE schema_info SET value = '{int(version)}' WHERE key = 'version';\n"
            "COMMIT;"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error:
            if connection.in_transaction:
                connection.rollback()
            raise
        current = version
    return current
