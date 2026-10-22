"""Performance regression smoke tests (roadmap update #164).

Generous ceilings that catch order-of-magnitude regressions, not
micro-benchmarks: indicator suite, confluence analysis, and DB insert.
Timings are intentionally wide (10-50x typical) to avoid flakiness on
shared CI runners.
"""

import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from neezy_backend.database import LocalDatabase
from neezy_backend.indicators import analyze
from neezy_backend.providers import ProviderResponseCache, _check_candles


def _walk(
    count: int = 5000, seed: int = 11
) -> list[tuple[int, float, float, float, float]]:
    state = seed
    price = 1.1000
    rows = []
    for i in range(count):
        state = (state * 1103515245 + 12345) % (2**31)
        drift = ((state >> 16) % 1000 - 500) / 50000.0
        open_ = price
        close = max(0.0001, open_ + drift)
        high = max(open_, close) + 0.0002
        low = min(open_, close) - 0.0002
        rows.append((1_700_000_000 + i * 300, open_, high, low, close))
        price = close
    return rows


class PerfSmokeTests(unittest.TestCase):
    def test_indicator_analysis_on_5k_candles_under_2s(self):
        candles = _walk(5000)
        start = time.monotonic()
        result = analyze(candles)
        elapsed = time.monotonic() - start
        self.assertIn("rsi", result)
        self.assertLess(elapsed, 2.0, f"analyze took {elapsed:.2f}s")

    def test_candle_validation_5k_rows_under_1s(self):
        rows = [[1700000000 + i, 1.1, 1.2, 1.05, 1.15] for i in range(5000)]
        start = time.monotonic()
        _check_candles(rows, "perf")
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 1.0, f"validation took {elapsed:.2f}s")

    def test_bulk_candle_insert_5k_under_3s(self):
        candles = _walk(5000)
        with TemporaryDirectory() as directory:
            database = LocalDatabase(Path(directory) / "perf.sqlite3")
            try:
                start = time.monotonic()
                written = database.save_candles("frxEURUSD", "5m", candles)
                elapsed = time.monotonic() - start
                self.assertEqual(written, len(candles))
                self.assertLess(elapsed, 3.0, f"insert took {elapsed:.2f}s")
            finally:
                database.close()

    def test_response_cache_is_faster_than_validation(self):
        cache = ProviderResponseCache(ttl_seconds=60.0)
        candles = [(1700000000 + i, 1.1, 1.2, 1.05, 1.15) for i in range(5000)]
        key = ("finnhub", "frxEURUSD", "5m", 5000)
        cache.put(key, candles)
        start = time.monotonic()
        for _ in range(100):
            cache.get(key)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 0.5, f"100 cache hits took {elapsed:.2f}s")
        self.assertEqual(cache.stats()["hits"], 100)


class ResponseCacheUnitTests(unittest.TestCase):
    def test_ttl_expiry_evicts_entries(self):
        cache = ProviderResponseCache(ttl_seconds=0.001)
        cache.put(("k",), [])
        time.sleep(0.01)
        self.assertIsNone(cache.get(("k",)))

    def test_invalidate_clears_everything(self):
        cache = ProviderResponseCache()
        cache.put(("a",), [(1, 1.0, 1.0, 1.0, 1.0)])
        cache.invalidate()
        self.assertIsNone(cache.get(("a",)))
        self.assertEqual(cache.stats()["entries"], 0)

    def test_max_entries_evicts_oldest(self):
        cache = ProviderResponseCache(max_entries=2)
        cache.put(("a",), [])
        cache.put(("b",), [])
        cache.put(("c",), [])
        self.assertEqual(cache.stats()["entries"], 2)
        self.assertIsNone(cache.get(("a",)))

    def test_returned_candles_are_copies(self):
        cache = ProviderResponseCache()
        candles = [(1, 1.0, 1.0, 1.0, 1.0)]
        cache.put(("k",), candles)
        fetched = cache.get(("k",))
        assert fetched is not None
        fetched.append((2, 2.0, 2.0, 2.0, 2.0))
        again = cache.get(("k",))
        assert again is not None
        self.assertEqual(len(again), 1)

    def test_bad_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            ProviderResponseCache(ttl_seconds=0)
        with self.assertRaises(ValueError):
            ProviderResponseCache(max_entries=0)


if __name__ == "__main__":
    unittest.main()
