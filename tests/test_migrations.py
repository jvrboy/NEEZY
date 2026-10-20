import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neezy_backend.database import SCHEMA_VERSION, LocalDatabase
from neezy_backend.migrations import (
    MIGRATIONS,
    apply_migrations,
    latest_version,
    read_version,
)


def _baseline() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE schema_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO schema_info VALUES ('version', '1');"
        "CREATE TABLE signals (id INTEGER PRIMARY KEY, strategy TEXT, "
        "created_at TEXT);"
        "CREATE TABLE candles (epoch INTEGER);"
    )
    return connection


def _indexes(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type='index'")
    return {row[0] for row in rows}


class MigrationTest(unittest.TestCase):
    def test_upgrades_baseline_to_latest(self):
        connection = _baseline()
        self.assertEqual(apply_migrations(connection), latest_version())
        self.assertEqual(read_version(connection), latest_version())
        self.assertIn("idx_signals_strategy", _indexes(connection))
        self.assertIn("idx_candles_epoch", _indexes(connection))

    def test_is_idempotent(self):
        connection = _baseline()
        apply_migrations(connection)
        self.assertEqual(apply_migrations(connection), latest_version())

    def test_failed_migration_rolls_back(self):
        connection = _baseline()
        bad = ((99, "CREATE TABLE t (a); SELECT * FROM missing_table;"),)
        with self.assertRaises(sqlite3.Error):
            apply_migrations(connection, bad)
        self.assertEqual(read_version(connection), 1)
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 't'"
        ).fetchall()
        self.assertEqual(tables, [])

    def test_duplicate_versions_rejected(self):
        with self.assertRaises(ValueError):
            apply_migrations(_baseline(), ((2, "SELECT 1;"), (2, "SELECT 2;")))

    def test_versions_are_unique_and_increasing(self):
        versions = [version for version, _sql in MIGRATIONS]
        self.assertEqual(versions, sorted(set(versions)))

    def test_missing_version_reads_as_zero(self):
        self.assertEqual(read_version(sqlite3.connect(":memory:")), 0)


class DatabaseMigrationIntegrationTest(unittest.TestCase):
    def test_new_database_is_at_latest_and_reopens_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "neezy.sqlite3"
            with LocalDatabase(path) as db:
                self.assertEqual(read_version(db.connection), SCHEMA_VERSION)
            with LocalDatabase(path) as db:
                self.assertEqual(read_version(db.connection), SCHEMA_VERSION)

    def test_memory_search_survives_boolean_keywords(self):
        with tempfile.TemporaryDirectory() as folder:
            with LocalDatabase(Path(folder) / "neezy.sqlite3") as db:
                db.add_memory("gold and silver rally")
                self.assertEqual(len(db.search_memory("NOT")), 0)
                self.assertEqual(len(db.search_memory("gold AND silver")), 1)

    def test_memory_search_has_a_fallback_without_fts5(self):
        import neezy_backend.database as database_module

        real_connect = sqlite3.connect

        class NoFtsConnection:
            def __init__(self, connection):
                object.__setattr__(self, "_connection", connection)

            def __getattr__(self, name):
                return getattr(self._connection, name)

            def __setattr__(self, name, value):
                if name == "_connection":
                    object.__setattr__(self, name, value)
                else:
                    setattr(self._connection, name, value)

            def execute(self, sql, parameters=()):
                if sql.lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
                    raise sqlite3.OperationalError("no such module: fts5")
                return self._connection.execute(sql, parameters)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "neezy.sqlite3"
            with mock.patch.object(
                database_module.sqlite3,
                "connect",
                side_effect=lambda *args, **kwargs: NoFtsConnection(
                    real_connect(*args, **kwargs)
                ),
            ):
                with LocalDatabase(path) as db:
                    self.assertFalse(db.fts5_available)
                    db.add_memory("mobile runner on Pydroid")
                    matches = db.search_memory("Pydroid mobile")
                    self.assertEqual(len(matches), 1)
                    self.assertIn("Pydroid", matches[0]["content"])


if __name__ == "__main__":
    unittest.main()
