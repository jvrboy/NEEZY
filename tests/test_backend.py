"""Regression tests for NEEZY's reusable backend services."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from queue import Queue

from neezy_backend.config import AppSettings
from neezy_backend.events import EventBus
from neezy_backend.indicators import analyze, atr, ema, rsi
from neezy_backend.storage import SettingsStore, SignalHistoryStore
from neezy_backend.stream import DerivStreamClient


def make_candles(count: int, *, direction: int = 1) -> list[tuple[float, ...]]:
    candles = []
    previous = 1.1
    for index in range(count):
        close = previous + direction * 0.0001
        open_ = previous
        candles.append(
            (
                index * 60,
                open_,
                max(open_, close) + 0.00005,
                min(open_, close) - 0.00005,
                close,
            )
        )
        previous = close
    return candles


class SettingsTests(unittest.TestCase):
    def test_settings_reject_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            AppSettings().updated(polling_ms=10)
        with self.assertRaises(ValueError):
            AppSettings().updated(theme="Unknown")
        with self.assertRaises(TypeError):
            AppSettings().updated(alerts_enabled=1)
        with self.assertRaises(ValueError):
            AppSettings().updated(alert_min_score=5)

    def test_settings_round_trip_and_corrupt_file_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            expected = AppSettings(
                theme="Midnight blue", compact_mode=True, alert_min_score=3
            )
            store.save(expected)
            self.assertEqual(store.load(), expected)
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(store.load(), AppSettings())

    def test_settings_ignores_unknown_fields_for_forward_compatibility(self) -> None:
        loaded = AppSettings.from_dict({"polling_ms": 250, "future_option": True})
        self.assertEqual(loaded.polling_ms, 250)
        self.assertFalse(hasattr(loaded, "future_option"))


class EventBusTests(unittest.TestCase):
    def test_event_bus_fans_out_and_drains(self) -> None:
        bus = EventBus()
        first = bus.subscribe()
        second = bus.subscribe()
        bus.publish("tick", {"symbol": "frxEURUSD"})
        self.assertEqual(EventBus.drain(first)[0].payload["symbol"], "frxEURUSD")
        self.assertEqual(EventBus.drain(second)[0].kind, "tick")
        self.assertEqual(EventBus.drain(Queue()), [])

    def test_bounded_queue_keeps_newest_event_and_unsubscribe_works(self) -> None:
        bus = EventBus(subscriber_queue_size=2)
        channel = bus.subscribe()
        for value in range(3):
            bus.publish("tick", value)
        self.assertEqual([event.payload for event in EventBus.drain(channel)], [1, 2])
        bus.unsubscribe(channel)
        bus.publish("tick", 3)
        self.assertEqual(EventBus.drain(channel), [])


class IndicatorTests(unittest.TestCase):
    def test_basic_indicator_edges(self) -> None:
        self.assertEqual(ema([], 9), [])
        self.assertEqual(ema([1, 2], 1), [1.0, 2.0])
        self.assertIsNone(rsi([1.0] * 14))
        self.assertEqual(rsi([1.0] * 15), 50.0)
        self.assertEqual(rsi([float(i) for i in range(15)]), 100.0)
        self.assertEqual(rsi([float(15 - i) for i in range(15)]), 0.0)
        self.assertAlmostEqual(atr([2, 3], [1, 2], [1.5, 2.5], period=2), 1.25)

    def test_analysis_waits_for_sixty_closed_candles(self) -> None:
        self.assertIsNone(analyze(make_candles(60)))
        result = analyze(make_candles(61))
        self.assertIsNotNone(result)
        self.assertEqual(result["closed_candles"], 60)

    def test_analysis_excludes_the_in_progress_candle(self) -> None:
        candles = make_candles(90)
        first = analyze(candles)
        candles[-1] = (candles[-1][0], 1.1, 2.0, 0.5, 1.8)
        second = analyze(candles)
        self.assertEqual(first, second)

    def test_analysis_rejects_non_finite_and_inconsistent_ohlc(self) -> None:
        candles = make_candles(61)
        candles[0] = (0, 1.1, float("nan"), 1.0, 1.05)
        with self.assertRaisesRegex(ValueError, "finite"):
            analyze(candles)
        candles = make_candles(61)
        candles[0] = (0, 1.1, 1.0, 1.05, 1.03)
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            analyze(candles)

    def test_trending_market_is_classified_directionally(self) -> None:
        up = analyze(make_candles(100, direction=1))
        down = analyze(make_candles(100, direction=-1))
        self.assertIn(up["signal"], {"BUY", "STRONG BUY"})
        self.assertEqual(up["trend"], "Bullish")
        self.assertIn(down["signal"], {"SELL", "STRONG SELL"})
        self.assertEqual(down["trend"], "Bearish")
        self.assertGreaterEqual(up["score"], 2)
        self.assertLessEqual(down["score"], -2)

    def test_flat_market_remains_neutral(self) -> None:
        result = analyze(make_candles(100, direction=0))
        self.assertEqual(result["signal"], "NEUTRAL")
        self.assertEqual(result["score"], 0)


class HistoryTests(unittest.TestCase):
    def test_history_persists_and_exports_csv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SignalHistoryStore(Path(directory) / "history.jsonl")
            record = store.append(
                symbol="frxEURUSD",
                previous="BUY",
                current="SELL",
                price=1.23456,
                score=-2,
            )
            self.assertEqual(store.read(), [record])
            destination = Path(directory) / "out.csv"
            self.assertEqual(store.export_csv(destination), 1)
            with destination.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["symbol"], "frxEURUSD")
            self.assertEqual(rows[0]["current"], "SELL")
            store.clear()
            self.assertEqual(store.read(), [])

    def test_history_skips_malformed_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            path.write_text("not-json\n", encoding="utf-8")
            self.assertEqual(SignalHistoryStore(path).read(), [])


class StreamTests(unittest.TestCase):
    def test_stream_reports_malformed_payload_without_crashing(self) -> None:
        bus = EventBus()
        channel = bus.subscribe()
        client = DerivStreamClient("wss://example.invalid", bus)
        client._on_message("not-json")
        event = EventBus.drain(channel)[0]
        self.assertEqual(event.kind, "error")
        self.assertIn("malformed", event.payload)

    def test_stream_does_not_send_when_disconnected(self) -> None:
        client = DerivStreamClient("wss://example.invalid", EventBus())
        self.assertFalse(client.send({"ping": 1}))
        client.stop()


if __name__ == "__main__":
    unittest.main()
