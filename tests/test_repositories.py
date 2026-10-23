"""Tests for the typed repository layer over SQLite (roadmap #5).

Covers each repository's contract directly, the LocalDatabase delegate
parity (public names and behaviours preserved), shared lock concurrency,
and the combined retention prune path.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from neezy_backend.candles import Candle
from neezy_backend.database import LocalDatabase
from neezy_backend.repositories import (
    CandleRepo,
    SignalRepo,
    SnapshotRepo,
    UsageRepo,
    _json_safe,
)

BASE_EPOCH = 1_700_000_000


def candles(count: int, start: int = BASE_EPOCH) -> list[Candle]:
    rows: list[Candle] = []
    price = 1.1
    for index in range(count):
        epoch = start + index * 60
        open_ = price
        close = open_ + 0.0001
        high = max(open_, close) + 0.0002
        low = min(open_, close) - 0.0002
        rows.append((epoch, open_, high, low, close))
        price = close
    return rows


class RepositoryBases(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "repos.sqlite3"
        self.db = LocalDatabase(self.path)
        self.addCleanup(self.db.close)


class CandleRepoTests(RepositoryBases):
    def test_upsert_tail_and_count(self) -> None:
        repo = CandleRepo(self.db)
        self.assertEqual(repo.upsert("frxEURUSD", "5m", candles(30)), 30)
        tail = repo.tail("frxEURUSD", "5m", 5)
        self.assertEqual(
            [row[0] for row in tail], [BASE_EPOCH + i * 60 for i in range(25, 30)]
        )
        self.assertEqual(repo.count("frxEURUSD"), 30)
        self.assertEqual(repo.count(), 30)
        self.assertEqual(repo.count("frxGBPUSD"), 0)

    def test_upsert_overwrites_same_epoch(self) -> None:
        repo = CandleRepo(self.db)
        repo.upsert("frxEURUSD", "5m", candles(5))
        updated = (BASE_EPOCH, 9.0, 9.5, 8.9, 9.2)
        self.assertEqual(repo.upsert("frxEURUSD", "5m", [updated]), 1)
        rows = repo.tail("frxEURUSD", "5m", 10)
        self.assertEqual(rows[0], updated)
        self.assertEqual(len(rows), 5)

    def test_upsert_skips_malformed_rows(self) -> None:
        repo = CandleRepo(self.db)
        written = repo.upsert(
            "frxEURUSD",
            "5m",
            [
                (1, 1.0, 1.1, 0.9, 1.05),
                (2, float("nan"), 1.1, 0.9, 1.05),
                (3, 1.0, 1.1),
                "garbage",
            ],
        )
        self.assertEqual(written, 1)
        self.assertEqual(repo.count("frxEURUSD"), 1)

    def test_expiry_and_validation(self) -> None:
        repo = CandleRepo(self.db)
        repo.upsert("frxEURUSD", "5m", candles(10))
        self.assertEqual(repo.prune_before(BASE_EPOCH + 3 * 60), 3)
        self.assertEqual(repo.count("frxEURUSD"), 7)
        with self.assertRaises(ValueError):
            repo.prune_before("not-int")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            repo.tail("frxEURUSD", "5m", 0)
        with self.assertRaises(ValueError):
            repo.upsert("  ", "5m", [])
        self.assertEqual(repo.upsert("frxEURUSD", "5m", []), 0)

    def test_store_candles_switch_disables_writes(self) -> None:
        db = LocalDatabase(
            Path(self.directory.name) / "quiet.sqlite3", store_candles=False
        )
        try:
            repo = CandleRepo(db)
            self.assertEqual(repo.upsert("frxEURUSD", "5m", candles(3)), 0)
            self.assertEqual(repo.count(), 0)
        finally:
            db.close()


class SignalRepoTests(RepositoryBases):
    def test_insert_recent_and_payload_decode(self) -> None:
        repo = SignalRepo(self.db)
        row_id = repo.insert(
            symbol="frxEURUSD",
            timeframe="5m",
            signal="BUY",
            score=2.5,
            price=1.1,
            strategy="SUPERTREND",
            direction=1,
            confidence=0.8,
            payload={"nested": {"value": 1.0}, "list": [1, 2.5, "x"]},
        )
        self.assertGreater(row_id, 0)
        rows = repo.recent(limit=10)
        self.assertEqual(len(rows), 1)
        record = rows[0]
        self.assertEqual(record["signal"], "BUY")
        self.assertEqual(record["payload"]["nested"]["value"], 1.0)
        self.assertEqual(record["payload"]["list"], [1, 2.5, "x"])

    def test_recent_filters_by_symbol_and_limit(self) -> None:
        repo = SignalRepo(self.db)
        repo.insert(symbol="frxEURUSD", timeframe="5m", signal="BUY", score=1)
        repo.insert(symbol="frxGBPUSD", timeframe="5m", signal="SELL", score=-1)
        self.assertEqual(len(repo.recent(limit=10)), 2)
        self.assertEqual(
            [r["signal"] for r in repo.recent(limit=10, symbol="frxEURUSD")], ["BUY"]
        )
        self.assertEqual(repo.recent(limit=1)[0]["signal"], "SELL")

    def test_insert_validation(self) -> None:
        repo = SignalRepo(self.db)
        for kwargs in (
            {"symbol": "", "timeframe": "5m", "signal": "BUY", "score": 1},
            {"symbol": "frxEURUSD", "timeframe": "", "signal": "BUY", "score": 1},
            {"symbol": "frxEURUSD", "timeframe": "5m", "signal": "  ", "score": 1},
            {
                "symbol": "frxEURUSD",
                "timeframe": "5m",
                "signal": "BUY",
                "score": "high",
            },
        ):
            with self.assertRaises(ValueError):
                repo.insert(**kwargs)

    def test_count_and_prune_before(self) -> None:
        repo = SignalRepo(self.db)
        repo.insert(symbol="frxEURUSD", timeframe="5m", signal="BUY", score=1)
        past = "2000-01-01T00:00:00+00:00"
        self.assertEqual(repo.prune_before(past), 0)
        self.assertEqual(repo.prune_before("2999-01-01T00:00:00+00:00"), 1)
        self.assertEqual(repo.count(), 0)


class SnapshotRepoTests(RepositoryBases):
    def test_save_latest_with_optional_timeframe(self) -> None:
        repo = SnapshotRepo(self.db)
        first = repo.save(
            symbol="frxEURUSD",
            timeframe="5m",
            result={
                "regime": "trend",
                "signal": "BUY",
                "score": 2,
                "payload": [1, 2.5, None],
            },
        )
        later = repo.save(
            symbol="frxEURUSD",
            timeframe="5m",
            result={"regime": "range", "signal": "HOLD", "score": 0},
        )
        repo.save(symbol="frxEURUSD", timeframe="1h", result={"score": 1})
        repo.save(symbol="frxGBPUSD", timeframe="5m", result={})
        latest = repo.latest("frxEURUSD", "5m")
        self.assertEqual(latest["id"], later)
        self.assertEqual(
            latest["payload"], {"regime": "range", "signal": "HOLD", "score": 0}
        )
        self.assertGreaterEqual(first, 1)
        self.assertEqual(repo.latest("frxEURUSD", "1h")["timeframe"], "1h")
        self.assertEqual(repo.latest("frxGBPUSD")["symbol"], "frxGBPUSD")
        self.assertIsNone(repo.latest("frxUSDJPY"))

    def test_save_validation_and_prune(self) -> None:
        repo = SnapshotRepo(self.db)
        with self.assertRaises(ValueError):
            repo.save(symbol="frxEURUSD", timeframe="", result={})  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            repo.save(symbol="frxEURUSD", timeframe="5m", result=[])  # type: ignore[arg-type]
        stamp = "2000-01-01T00:00:00+00:00"
        self.assertEqual(repo.prune_before(stamp), 0)


class UsageRepoTests(RepositoryBases):
    def test_record_usage_and_tallies(self) -> None:
        repo = UsageRepo(self.db)
        repo.record(provider="openrouter", model="a/b", status="ok", latency_ms=120)
        repo.record(provider="gemini", model="c/d", status="quota")
        usage = repo.usage(limit=10)
        self.assertEqual(usage["total"], 2)
        self.assertEqual(usage["by_provider"]["openrouter"], 1)
        self.assertIn("quota", usage["by_status"])
        labels = {row["status"] for row in usage["calls"]}
        self.assertEqual(labels, {"ok", "quota"})

    def test_record_validation_and_detail_truncation(self) -> None:
        repo = UsageRepo(self.db)
        with self.assertRaises(ValueError):
            repo.record(provider="  ", model="m", status="ok")
        row_id = repo.record(
            provider="p",
            model="m",
            status="error",
            detail="x" * 900,
        )
        self.assertGreater(row_id, 0)
        with self.assertRaises(ValueError):
            repo.usage(limit=0)

    def test_prune_before(self) -> None:
        repo = UsageRepo(self.db)
        repo.record(provider="p", model="m", status="ok")
        future = "2999-01-01T00:00:00+00:00"
        self.assertGreaterEqual(repo.prune_before(future), 1)
        self.assertEqual(repo.usage()["total"], 0)


class LocalDatabaseDelegateParityTests(RepositoryBases):
    """The historical LocalDatabase wrapper methods keep their contracts."""

    def test_save_load_count_go_through_repositories(self) -> None:
        rows = candles(12)
        self.assertEqual(self.db.save_candles("frxEURUSD", "5m", rows), 12)
        self.assertEqual(
            self.db.load_candles("frxEURUSD", "5m", 5),
            self.db.candles.tail("frxEURUSD", "5m", 5),
        )
        self.assertEqual(
            self.db.candle_count("frxEURUSD"), self.db.candles.count("frxEURUSD")
        )

    def test_signal_wrappers_match_repo_rows(self) -> None:
        self.db.save_signal(
            symbol="frxEURUSD",
            timeframe="15m",
            signal="HOLD",
            score=0.5,
            strategy="MACD",
            payload={"k": "v"},
        )
        from_wrapper = self.db.recent_signals(limit=5)
        from_repo = self.db.signals.recent(limit=5)
        self.assertEqual(from_wrapper, from_repo)
        self.assertEqual(from_wrapper[0]["payload"], {"k": "v"})

    def test_snapshot_wrappers_match_repo_latest(self) -> None:
        self.db.save_snapshot(symbol="frxEURUSD", timeframe="5m", result={"score": 3})
        self.assertEqual(self.db.latest_snapshot("frxEURUSD", "5m")["score"], 3)
        self.assertEqual(self.db.snapshots.latest("frxEURUSD", "5m")["score"], 3)

    def test_prune_uses_repository_counts(self) -> None:
        self.db.save_candles("frxEURUSD", "5m", candles(3))
        self.db.save_snapshot(symbol="frxEURUSD", timeframe="5m", result={})
        self.db.record_ai_call(provider="p", model="m", status="ok")
        removed = self.db.prune(retention_days=1)
        self.assertEqual(set(removed), {"signals", "snapshots", "ai_calls", "candles"})
        self.assertEqual(removed["candles"], 3)
        with self.assertRaises(ValueError):
            self.db.prune(retention_days=0)

    def test_shared_lock_is_used_by_repositories(self) -> None:
        self.assertIs(self.db.candles._lock, self.db._lock)
        self.assertIs(self.db.signals.database, self.db)
        errors: list[Exception] = []

        def writer(offset: int) -> None:
            try:
                for index in range(20):
                    start = BASE_EPOCH + (offset * 20 + index) * 120
                    self.db.save_candles("frxEURUSD", "5m", candles(2, start=start))
            except (ValueError, OSError, RuntimeError) as error:
                errors.append(error)

        def reader() -> None:
            try:
                for _ in range(20):
                    self.db.load_candles("frxEURUSD", "5m", 5)
            except (ValueError, OSError, RuntimeError) as error:
                errors.append(error)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(2)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(self.db.candle_count("frxEURUSD"), 80)


class JsonSafeParityTests(unittest.TestCase):
    def test_non_finite_floats_drop_to_none(self) -> None:
        self.assertIsNone(_json_safe(float("nan")))
        self.assertIsNone(_json_safe(float("inf")))
        self.assertEqual(
            _json_safe({"a": [1.5, float("nan"), "x"]})["a"], [1.5, None, "x"]
        )

    def test_unknown_types_stringified(self) -> None:
        self.assertEqual(_json_safe((1, 2)), [1, 2])
        self.assertEqual(_json_safe(Path("x")), "x")


if __name__ == "__main__":
    unittest.main()
