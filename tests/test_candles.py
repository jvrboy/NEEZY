"""Tests for the candle accessor layer (roadmap #2).

Covers the shared validator, the in-memory store, accessor fetch/persist/
read/ensure/refresh behavior with injected delegates, SQLite integration,
the CLI ``db save``/``db candles`` wiring, and the tools-registry path that
previously imported stream fetches directly.
"""

from __future__ import annotations

import io
import math
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from neezy_backend.candles import (
    Candle,
    CandleAccessor,
    CandleError,
    InMemoryCandleStore,
    accessor,
    normalize_candles,
    validate_candle_row,
    validate_candle_rows,
)
from neezy_backend.database import LocalDatabase

BASE_EPOCH = 1_700_000_000


def make_candles(
    count: int, start: int = BASE_EPOCH, seed: float = 1.1
) -> list[Candle]:
    """Strictly consistent ascending OHLC rows, oldest first."""
    rows: list[Candle] = []
    previous_close = seed
    for index in range(count):
        epoch = start + index * 60
        open_ = previous_close
        close = open_ + 0.0001
        high = max(open_, close) + 0.0002
        low = min(open_, close) - 0.0002
        rows.append((epoch, open_, high, low, close))
        previous_close = close
    return rows


def fake_fetch(symbol: str, seconds: int, count: int) -> list[Candle]:
    return make_candles(count)


class ValidateCandleRowTests(unittest.TestCase):
    def test_sequence_row_passes_through(self) -> None:
        row = (BASE_EPOCH, 1.1, 1.2, 1.09, 1.15)
        self.assertEqual(validate_candle_row(row), row)

    def test_mapping_row_accepted(self) -> None:
        candle = validate_candle_row(
            {"epoch": 5, "open": 2.0, "high": 2.5, "low": 1.9, "close": 2.2}
        )
        self.assertEqual(candle, (5, 2.0, 2.5, 1.9, 2.2))

    def test_short_row_rejected(self) -> None:
        with self.assertRaisesRegex(CandleError, "malformed candle row"):
            validate_candle_row((BASE_EPOCH, 1.0, 1.1))

    def test_non_numeric_row_rejected(self) -> None:
        with self.assertRaises(CandleError):
            validate_candle_row((BASE_EPOCH, "n/a", 1.0, 1.0, 1.0))

    def test_zero_and_negative_prices_rejected(self) -> None:
        for prices in (
            (0.0, 0.1, 0.05, 0.05),
            (-1.0, 0.1, 0.05, 0.05),
            (1.0, 0.1, 0.05, 0.05),
        ):
            row = (7, prices[0], prices[1], prices[2], prices[3])
            with self.assertRaises(CandleError):
                validate_candle_row(row)

    def test_non_finite_prices_rejected(self) -> None:
        with self.assertRaises(CandleError):
            validate_candle_row((7, math.inf, 1.1, 0.9, 1.0))
        with self.assertRaises(CandleError):
            validate_candle_row((7, 1.0, float("nan"), 0.9, 1.0))

    def test_inverted_high_low_rejected(self) -> None:
        with self.assertRaisesRegex(CandleError, "malformed"):
            validate_candle_row((7, 1.1, 1.0, 1.2, 1.1))

    def test_open_outside_range_rejected(self) -> None:
        with self.assertRaises(CandleError):
            validate_candle_row((7, 1.3, 1.2, 1.0, 1.1))

    def test_bad_epoch_rejected(self) -> None:
        # epoch 0 is a legitimate synthetic/tests index; negatives are not.
        self.assertEqual(validate_candle_row((0, 1.1, 1.2, 1.0, 1.1))[0], 0)
        with self.assertRaises(CandleError):
            validate_candle_row((-5, 1.1, 1.2, 1.0, 1.1))

    def test_error_names_the_source(self) -> None:
        with self.assertRaisesRegex(CandleError, "deriv feed"):
            validate_candle_row((7, 1.3, 1.2, 1.0, 1.1), source="deriv feed")

    def test_validate_rows_collects_in_order(self) -> None:
        rows = make_candles(3)
        self.assertEqual(validate_candle_rows(rows), rows)
        self.assertEqual(validate_candle_rows([]), [])


class NormalizeCandlesTests(unittest.TestCase):
    def test_sorted_oldest_first(self) -> None:
        rows = make_candles(4)
        shuffled = [rows[2], rows[0], rows[3], rows[1]]
        self.assertEqual(normalize_candles(shuffled), rows)

    def test_duplicates_keep_freshest_reading(self) -> None:
        old = (BASE_EPOCH, 1.0, 1.1, 0.9, 1.05)
        fresh = (BASE_EPOCH, 1.0, 1.2, 0.9, 1.15)
        merged = normalize_candles([old, fresh])
        self.assertEqual(merged, [fresh])

    def test_garbage_fails_loud(self) -> None:
        with self.assertRaises(CandleError):
            normalize_candles([*make_candles(3), ("oops",)])


class InMemoryCandleStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryCandleStore()

    def test_roundtrip_keeps_order(self) -> None:
        rows = make_candles(10)
        self.store.save_candles("frxEURUSD", "1m", rows)
        self.assertEqual(self.store.load_candles("frxEURUSD", "1m"), rows)

    def test_limit_returns_tail(self) -> None:
        rows = make_candles(10)
        self.store.save_candles("frxEURUSD", "1m", rows)
        self.assertEqual(self.store.load_candles("frxEURUSD", "1m", limit=3), rows[-3:])

    def test_zero_limit_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.load_candles("frxEURUSD", "1m", limit=0)

    def test_overwrite_and_upsert_same_epoch(self) -> None:
        self.store.save_candles("frxEURUSD", "1m", make_candles(5))
        updated = (BASE_EPOCH, 9.0, 9.5, 8.9, 9.2)
        self.assertEqual(self.store.save_candles("frxEURUSD", "1m", [updated]), 1)
        rows = self.store.load_candles("frxEURUSD", "1m")
        self.assertEqual(rows[0], updated)
        self.assertEqual(len(rows), 5)

    def test_bad_rows_rejected_without_partial_writes(self) -> None:
        self.store.save_candles("frxEURUSD", "1m", make_candles(5))
        with self.assertRaises(CandleError):
            self.store.save_candles(
                "frxEURUSD", "1m", [*make_candles(3), (BASE_EPOCH, 0, 0, 0, 0)]
            )
        self.assertEqual(self.store.candle_count("frxEURUSD"), 5)

    def test_isolation_by_symbol_and_timeframe(self) -> None:
        self.store.save_candles("frxEURUSD", "1m", make_candles(2))
        self.store.save_candles("frxGBPUSD", "1m", make_candles(3))
        self.store.save_candles("frxEURUSD", "5m", make_candles(4))
        self.assertEqual(self.store.candle_count(), 9)
        self.assertEqual(self.store.candle_count("frxEURUSD"), 6)
        self.assertEqual(self.store.candle_count("frxGBPUSD"), 3)
        self.assertEqual(
            self.store.load_candles("frxGBPUSD", "1m"),
            make_candles(3),
        )

    def test_concurrent_writes_are_safe(self) -> None:
        rows = make_candles(60)
        errors: list[Exception] = []

        def worker(offset: int) -> None:
            try:
                self.store.save_candles("frxEURUSD", "1m", rows[offset : offset + 30])
            except (CandleError, ValueError, OSError) as error:
                errors.append(error)

        threads = [threading.Thread(target=worker, args=(i,)) for i in (0, 20, 30)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertEqual(self.store.candle_count("frxEURUSD"), 60)


class CandleAccessorFetchTests(unittest.TestCase):
    def test_fetch_delegates_and_trims(self) -> None:
        calls: list[tuple[str, int, int]] = []

        def stream(symbol: str, seconds: int, count: int) -> list[Candle]:
            calls.append((symbol, seconds, count))
            return make_candles(count + 10)

        got = CandleAccessor(stream_fetch=stream).fetch("frxEURUSD", "15m", 20)
        self.assertEqual(len(got), 20)
        self.assertEqual(got[-1][0], BASE_EPOCH + 29 * 60)
        self.assertEqual(calls, [("frxEURUSD", 900, 20)])

    def test_fetch_validates_rows(self) -> None:
        broken = CandleAccessor(
            stream_fetch=lambda *args: [(1.5, 1.0, 1.0, 1.0, 1.0), "x"]
        )
        with self.assertRaises(CandleError):
            broken.fetch("frxEURUSD", "1m", 5)

    def test_fetch_late_binds_stream_patch_target(self) -> None:
        with mock.patch(
            "neezy_backend.stream.fetch_candles", return_value=make_candles(3)
        ) as probe:
            got = accessor().fetch("frxEURUSD", "5m", 3)
        self.assertEqual(len(got), 3)
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(probe.call_args.args[:3], ("frxEURUSD", 300, 3))

    def test_history_pages_and_dedupes(self) -> None:
        deep = make_candles(10)

        def history(symbol: str, seconds: int, total: int) -> list[Candle]:
            return [*deep, *make_candles(4)]

        got = CandleAccessor(stream_history=history).history("frxEURUSD", "1m", 10)
        self.assertEqual(got, deep)

    def test_history_validates_total(self) -> None:
        with self.assertRaises(CandleError):
            CandleAccessor().history("frxEURUSD", "1m", 0)

    def test_mt5_source_requires_delegate_and_gets_timeframe_name(self) -> None:
        seen: list[tuple[str, str, int]] = []
        bridge = CandleAccessor(
            mt5_fetch=lambda s, tf, c: (
                seen.append((s, tf, c)),
                make_candles(c, seed=100.0),
            )[1]
        )
        got = bridge.fetch("frxEURUSD", "1h", 5, source="mt5")
        self.assertEqual(len(got), 5)
        self.assertEqual(seen, [("frxEURUSD", "1h", 5)])

        with self.assertRaisesRegex(CandleError, "mt5_fetch"):
            CandleAccessor().fetch("frxEURUSD", "1h", 5, source="mt5")

    def test_unknown_source_rejected(self) -> None:
        with self.assertRaisesRegex(CandleError, "unknown candle source"):
            CandleAccessor().fetch("frxEURUSD", "1m", 5, source="binance")

    def test_count_bounds(self) -> None:
        for bad in (0, -1, 5001, "many"):
            with self.assertRaises(CandleError):
                CandleAccessor().fetch("frxEURUSD", "1m", bad)

    def test_unknown_timeframe_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CandleAccessor().fetch("frxEURUSD", "7m", 5)


class CandleAccessorStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryCandleStore()
        self.calls: list[int] = []

        def counting_stream(symbol: str, seconds: int, count: int) -> list[Candle]:
            self.calls.append(count)
            # Fetched windows sit after the seed candles so ensure() merges.
            return make_candles(count, start=BASE_EPOCH + 10_000 * 60)

        self.accessor = CandleAccessor(self.store, stream_fetch=counting_stream)
        self.timeframe = "1m"

    def test_missing_store_raises(self) -> None:
        bare = CandleAccessor()
        for call in (
            lambda: bare.persist("frxEURUSD", "1m", []),
            lambda: bare.read("frxEURUSD", "1m"),
            lambda: bare.latest("frxEURUSD", "1m"),
            lambda: bare.count(),
            lambda: bare.ensure("frxEURUSD", "1m", 10),
        ):
            with self.assertRaisesRegex(CandleError, "no candle store"):
                call()

    def test_persist_normalizes_before_writing(self) -> None:
        rows = make_candles(4)
        unsorted = [rows[3], rows[1], rows[2], rows[0]]
        self.assertEqual(self.accessor.persist("frxEURUSD", "1m", unsorted), 4)
        self.assertEqual(self.store.load_candles("frxEURUSD", "1m"), rows)

    def test_read_and_latest(self) -> None:
        rows = make_candles(6)
        self.accessor.persist("frxEURUSD", "1m", rows)
        self.assertEqual(self.accessor.read("frxEURUSD", "1m", limit=3), rows[-3:])
        self.assertEqual(self.accessor.latest("frxEURUSD", "1m"), rows[-1])
        self.assertIsNone(self.accessor.latest("frxEURUSD", "1d"))

    def test_refresh_fetches_and_persists(self) -> None:
        rows = self.accessor.refresh("frxEURUSD", "1m", 10)
        self.assertEqual(len(rows), 10)
        self.assertEqual(self.store.candle_count("frxEURUSD"), 10)
        self.assertEqual(self.calls, [10])

    def test_refresh_without_store_only_fetches(self) -> None:
        calls: list[int] = []

        def stream(symbol: str, seconds: int, count: int) -> list[Candle]:
            calls.append(count)
            return make_candles(count)

        bare = CandleAccessor(stream_fetch=stream)
        got = bare.refresh("frxEURUSD", "1m", 4)
        self.assertEqual(len(got), 4)
        self.assertEqual(calls, [4])

    def test_ensure_skips_fetching_when_store_is_full(self) -> None:
        self.accessor.persist("frxEURUSD", "1m", make_candles(15))
        rows = self.accessor.ensure("frxEURUSD", "1m", 10)
        self.assertEqual(len(rows), 10)
        self.assertEqual(self.calls, [], "should not fetch when already enough")

    def test_ensure_fetches_only_the_missing_tail(self) -> None:
        self.accessor.persist("frxEURUSD", "1m", make_candles(6))
        rows = self.accessor.ensure("frxEURUSD", "1m", 10)
        self.assertEqual(len(rows), 10)
        self.assertEqual(self.calls, [4])

    def test_ensure_validates_min_count(self) -> None:
        with self.assertRaises(CandleError):
            self.accessor.ensure("frxEURUSD", "1m", 0)


class CandleAccessorDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = LocalDatabase(Path(self.directory.name) / "candles.sqlite3")
        self.addCleanup(self.database.close)

    def test_persist_and_read_through_sqlite(self) -> None:
        def stream(symbol: str, seconds: int, count: int) -> list[Candle]:
            return make_candles(count)

        accessor = CandleAccessor(self.database, stream_fetch=stream)
        accessor.refresh("frxEURUSD", "1m", 12)
        self.assertEqual(self.database.candle_count("frxEURUSD"), 12)
        rows = accessor.read("frxEURUSD", "1m", limit=5)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0][0], BASE_EPOCH + 7 * 60)
        epochs = [row[0] for row in accessor.read("frxEURUSD", "1m", limit=100)]
        self.assertEqual(epochs, sorted(epochs))

    def test_ensure_roundtrip_through_sqlite(self) -> None:
        calls: list[int] = []

        def stream(symbol: str, seconds: int, count: int) -> list[Candle]:
            calls.append(count)
            return make_candles(count)

        accessor = CandleAccessor(self.database, stream_fetch=stream)
        accessor.ensure("frxEURUSD", "5m", 10)
        accessor.ensure("frxEURUSD", "5m", 10)
        self.assertEqual(calls, [10])
        self.assertEqual(len(accessor.read("frxEURUSD", "5m", limit=50)), 10)


class CliDbWiringTests(unittest.TestCase):
    """``db save`` / ``db candles`` go through the accessor end to end."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = mock.patch.dict(os.environ, {"NEEZY_HOME": self.directory.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_db_save_then_candles_reads_accessor_output(self) -> None:
        from neezy_backend.cli import main

        out = io.StringIO()
        exit_code = main(
            ["db", "save", "EURUSD", "-t", "5m", "-n", "7"],
            fetch=lambda s, sec, c: make_candles(c),
            out=out,
        )
        self.assertEqual(exit_code, 0)
        self.assertIn("Stored 7 candles", out.getvalue())

        query = io.StringIO()
        exit_code = main(
            ["db", "candles", "EURUSD", "-t", "5m", "--limit", "3", "--json"],
            out=query,
        )
        self.assertEqual(exit_code, 0)
        payload = query.getvalue()
        self.assertIn('"epoch"', payload)
        self.assertIn('"close"', payload)
        self.assertNotIn("None", payload.replace("None',", ""))

    def test_db_save_deep_history_pages(self) -> None:
        from neezy_backend.cli import main

        seen: list[tuple[str, int, int]] = []

        def fetch(symbol: str, seconds: int, count: int) -> list[Candle]:
            seen.append((symbol, seconds, count))
            return make_candles(count)

        exit_code = main(
            ["db", "save", "EURUSD", "-t", "1m", "-n", "5010"],
            fetch=fetch,
            out=io.StringIO(),
        )
        self.assertEqual(exit_code, 0)
        # The CLI delegate pages deep history: one request caps at 5000.
        self.assertEqual(seen[0], ("frxEURUSD", 60, 5010))
        candle_count = LocalDatabase().candle_count("frxEURUSD")
        self.assertGreaterEqual(candle_count, 5010)


class ToolsRegistryAccessorTests(unittest.TestCase):
    """The fancy tools now fetch through the single accessor, late-bound."""

    def test_read_market_uses_accessor_delegation(self) -> None:
        from neezy_backend.tools import ToolRegistry, register_default_tools

        registry = ToolRegistry()
        with mock.patch(
            "neezy_backend.stream.fetch_candles", return_value=make_candles(100)
        ) as probe:
            register_default_tools(registry)
            output = registry.execute("read_market", dry_run=False)
        self.assertIn("Market:", output)
        self.assertEqual(probe.call_args.args, ("frxEURUSD", 900, 100))

    def test_scan_strategies_validator_keeps_bad_data_out(self) -> None:
        from neezy_backend.tools import ToolRegistry, register_default_tools

        registry = ToolRegistry()
        garbage = [(1, 1.0, 1.0, 1.0, 1.0), "broken"]
        with mock.patch(
            "neezy_backend.stream.fetch_candles", new=lambda *a: garbage, create=True
        ):
            register_default_tools(registry)
            with self.assertRaisesRegex(CandleError, "malformed"):
                registry.execute("scan_strategies", dry_run=False)


if __name__ == "__main__":
    unittest.main()
