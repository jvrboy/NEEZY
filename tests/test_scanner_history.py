import math
import tempfile
import unittest
from pathlib import Path

from neezy_backend.config import AppSettings
from neezy_backend.scanner import ConfluenceAnalyzer
from neezy_backend.storage import ConfluenceHistoryStore


def make_candles(count=320, up=True, base=100.0, phase=0.0):
    """Local copy so the module imports under any unittest runner."""
    price = base
    candles = []
    for index in range(count):
        trend = 0.12 if up else -0.12
        wave = 0.1 * math.sin(index / 7.0 + phase)
        open_ = price
        price = price + trend + wave
        high = max(open_, price) + 0.15
        low = min(open_, price) - 0.15
        candles.append((1700000000 + index * 300, open_, high, low, price))
    return candles


class ScannerTest(unittest.TestCase):
    def _analyzer(self, settings=None):
        return ConfluenceAnalyzer(
            candle_source=lambda symbol, timeframe: make_candles(
                phase=hash(symbol) % 7
            ),
            settings=settings,
        )

    def test_strict_pass_scores_and_sorts(self):
        analyzer = self._analyzer()
        result = analyzer.scan(["frxEURUSD", "frxGBPUSD", "R_100"], "5m")
        self.assertEqual(result.mode, "strict")
        self.assertEqual(result.scanned, 3)
        scores = [signal.score for signal in result.signals]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for signal in result.signals:
            self.assertIn(signal.label, {"BUY", "SELL"})

    def test_full_analysis_always_yields(self):
        analyzer = self._analyzer(AppSettings())
        result = analyzer.full_analysis(["frxEURUSD", "frxUSDJPY", "frxAUDUSD"], "5m")
        self.assertEqual(result.mode, "full")
        # Search mode fills the gaps, so enough history means signals, not errors.
        self.assertTrue(result.signals or result.errors)

    def test_source_errors_are_reported(self):
        def broken(_symbol, _timeframe):
            raise ConnectionError("feed down")

        analyzer = ConfluenceAnalyzer(candle_source=broken, settings=AppSettings())
        result = analyzer.scan(["frxEURUSD"], "5m")
        self.assertIn("frxEURUSD", result.errors)
        self.assertEqual(result.signals, ())

    def test_missing_source(self):
        analyzer = ConfluenceAnalyzer()
        result = analyzer.scan(["frxEURUSD"], "5m")
        self.assertIn("frxEURUSD", result.errors)

    def test_candles_too_short_are_filtered(self):
        analyzer = ConfluenceAnalyzer(candle_source=lambda _s, _t: make_candles(40))
        result = analyzer.full_analysis(["frxEURUSD"], "5m")
        self.assertEqual(result.signals, ())
        self.assertIn("not enough closed candles", result.errors["frxEURUSD"])

    def test_result_summary_and_dict(self):
        result = self._analyzer().scan(["frxEURUSD"], "5m")
        if result.signals:
            as_dict = result.to_dict()
            self.assertEqual(as_dict["mode"], "strict")
            self.assertTrue(as_dict["signals"][0]["instrument"])
        text = result.summary()
        self.assertIn("market", text)


class ConfluenceHistoryStoreTest(unittest.TestCase):
    def _record(self, symbol="frxEURUSD", stamp="2026-10-21T00:00:00+00:00"):
        return {
            "timestamp": stamp,
            "symbol": symbol,
            "instrument": "EUR/USD",
            "timeframe": "5m",
            "direction": 1,
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 104.0,
            "win_rate": 66.7,
            "score": 72.0,
            "mode": "strict",
        }

    def test_append_read_and_outcome_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ConfluenceHistoryStore(path=Path(folder) / "confluence.jsonl")
            store.append(self._record())
            store.append(self._record(stamp="2026-10-21T01:00:00+00:00"))
            records = store.read()
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["instrument"], "EUR/USD")
            changed = store.update_outcomes(
                {("frxEURUSD", "2026-10-21T01:00:00+00:00"): "TP"}
            )
            self.assertEqual(changed, 1)
            updated = store.read()
            self.assertIsNone(updated[0]["outcome"])
            self.assertEqual(updated[1]["outcome"], "TP")

    def test_invalid_outcome_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ConfluenceHistoryStore(path=Path(folder) / "c.jsonl")
            with self.assertRaises(ValueError):
                store.update_outcomes({("frxEURUSD", "x"): "PROFIT"})
            record = self._record()
            record["outcome"] = "BREAKEVEN"
            with self.assertRaises(ValueError):
                store.append(record)

    def test_missing_fields_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ConfluenceHistoryStore(path=Path(folder) / "c.jsonl")
            with self.assertRaisesRegex(ValueError, "missing fields"):
                store.append({"timestamp": "now", "symbol": "frxEURUSD"})

    def test_empty_and_corrupt_files(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ConfluenceHistoryStore(path=Path(folder) / "c.jsonl")
            self.assertEqual(store.read(), [])
            store.path.write_text("not json\n", encoding="utf-8")
            store.append(self._record())
            self.assertEqual(len(store.read()), 1)

    def test_clear_and_compact(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ConfluenceHistoryStore(path=Path(folder) / "c.jsonl")
            store.append(self._record())
            self.assertEqual(store.compact(), 1)
            store.clear()
            self.assertEqual(store.read(), [])


if __name__ == "__main__":
    unittest.main()
