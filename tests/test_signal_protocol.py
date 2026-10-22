"""Round-trip and validation tests for the ConfluenceSignal typed protocol.

Roadmap #3: the frozen Signal dataclass plus ``to_dict``/``from_dict`` (and
the persisted-history variants) is the contract between confluence, the
history store, and the UI. These tests pin that contract.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from neezy_backend.confluence import ConfluenceFactor, ConfluenceSignal
from neezy_backend.storage import ConfluenceHistoryStore


def sample_signal(**overrides: object) -> ConfluenceSignal:
    """A representative signal; overrides replace fields for variation."""
    values: dict[str, object] = {
        "symbol": "frxEURUSD",
        "instrument": "EUR/USD",
        "timeframe": "15m",
        "direction": 1,
        "entry": 1.0842,
        "stop_loss": 1.0812,
        "take_profit": 1.0902,
        "win_rate": 61.0,
        "score": 72.5,
        "factors": (
            ConfluenceFactor("core score", 1, 1.5, "score +2"),
            ConfluenceFactor("rsi", -1, 0.8, "overbought"),
        ),
        "created_at": "2026-10-22T10:15:00+00:00",
        "mode": "strict",
        "win_rate_basis": "42 analogs",
        "votes": {"BUY": 3, "SELL": 1},
    }
    values.update(overrides)
    return ConfluenceSignal(**values)  # type: ignore[arg-type]


class FactorProtocolTests(unittest.TestCase):
    """ConfluenceFactor.from_dict validation and round-trips."""

    def test_round_trip(self) -> None:
        factor = ConfluenceFactor("core score", 1, 1.25, "score +2")
        self.assertEqual(ConfluenceFactor.from_dict(factor.to_dict()), factor)

    def test_unknown_keys_are_ignored(self) -> None:
        factor = ConfluenceFactor.from_dict(
            {"name": "n", "direction": 0, "weight": 1.0, "future_key": True}
        )
        self.assertEqual(factor.name, "n")
        self.assertEqual(factor.direction, 0)

    def test_bad_direction_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ConfluenceFactor.from_dict({"name": "n", "direction": 7})

    def test_negative_weight_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ConfluenceFactor.from_dict({"name": "n", "direction": 1, "weight": -0.5})

    def test_non_mapping_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ConfluenceFactor.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


class SignalProtocolTests(unittest.TestCase):
    """ConfluenceSignal.from_dict / from_history_record contracts."""

    def test_to_dict_round_trip(self) -> None:
        signal = sample_signal()
        self.assertEqual(ConfluenceSignal.from_dict(signal.to_dict()), signal)

    def test_round_trip_preserves_factors_and_votes(self) -> None:
        signal = sample_signal()
        loaded = ConfluenceSignal.from_dict(signal.to_dict())
        self.assertEqual(loaded.factors, signal.factors)
        self.assertEqual(loaded.votes, signal.votes)
        self.assertEqual(loaded.label, "BUY")

    def test_unknown_keys_are_ignored(self) -> None:
        payload = {**sample_signal().to_dict(), "from_the_future": 1}
        loaded = ConfluenceSignal.from_dict(payload)
        self.assertEqual(loaded.symbol, "frxEURUSD")

    def test_label_key_is_not_required_on_input(self) -> None:
        payload = sample_signal().to_dict()
        payload.pop("label")  # derived, not consumed
        loaded = ConfluenceSignal.from_dict(payload)
        self.assertEqual(loaded.label, "BUY")

    def test_numeric_coercion(self) -> None:
        payload = sample_signal().to_dict()
        payload["entry"] = "1.09"
        payload["score"] = 80
        loaded = ConfluenceSignal.from_dict(payload)
        self.assertEqual(loaded.entry, 1.09)
        self.assertEqual(loaded.score, 80.0)

    def test_bad_direction_is_rejected_with_field_named(self) -> None:
        payload = sample_signal().to_dict()
        payload["direction"] = 4
        with self.assertRaises(ValueError) as ctx:
            ConfluenceSignal.from_dict(payload)
        self.assertIn("direction", str(ctx.exception))

    def test_non_numeric_entry_is_rejected(self) -> None:
        payload = sample_signal().to_dict()
        payload["entry"] = "not-a-number"
        with self.assertRaises(ValueError):
            ConfluenceSignal.from_dict(payload)

    def test_non_string_symbol_is_rejected(self) -> None:
        payload = sample_signal().to_dict()
        payload["symbol"] = 42
        with self.assertRaises(ValueError):
            ConfluenceSignal.from_dict(payload)

    def test_non_mapping_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ConfluenceSignal.from_dict("nope")  # type: ignore[arg-type]

    def test_history_record_round_trip(self) -> None:
        signal = sample_signal()
        record = signal.as_history_record()
        loaded = ConfluenceSignal.from_history_record(record)
        self.assertEqual(loaded.symbol, signal.symbol)
        self.assertEqual(loaded.entry, signal.entry)
        self.assertEqual(loaded.stop_loss, signal.stop_loss)
        self.assertEqual(loaded.take_profit, signal.take_profit)
        self.assertEqual(loaded.created_at, signal.created_at)
        self.assertEqual(loaded.factors, ())
        self.assertEqual(loaded.votes, {})

    def test_history_record_tolerates_outcome_key(self) -> None:
        record = {**sample_signal().as_history_record(), "outcome": "TP"}
        loaded = ConfluenceSignal.from_history_record(record)
        self.assertEqual(loaded.timeframe, "15m")

    def test_history_record_bad_types_are_rejected(self) -> None:
        record = sample_signal().as_history_record()
        record["direction"] = "sideays"
        with self.assertRaises(ValueError):
            ConfluenceSignal.from_history_record(record)


class TypedStoreTests(unittest.TestCase):
    """ConfluenceHistoryStore typed accessors."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = ConfluenceHistoryStore(Path(self._tmp.name) / "history.jsonl")
        self.addCleanup(self._tmp.cleanup)

    def test_append_signal_and_read_back(self) -> None:
        signal = sample_signal()
        entry = self.store.append_signal(signal)
        self.assertIsNone(entry["outcome"])
        loaded = self.store.read_signals()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].symbol, signal.symbol)
        self.assertEqual(loaded[0].entry, signal.entry)

    def test_append_signal_rejects_non_signal(self) -> None:
        with self.assertRaises(TypeError):
            self.store.append_signal({"symbol": "not", "a": "signal"})  # type: ignore[arg-type]

    def test_read_signals_skips_corrupt_but_required_complete_records(self) -> None:
        self.store.append_signal(sample_signal())
        # A record that passes the REQUIRED check but has an impossible value.
        bad = sample_signal().as_history_record()
        bad["direction"] = 9
        self.store.append(bad)
        loaded = self.store.read_signals()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].symbol, "frxEURUSD")

    def test_read_signals_empty_store(self) -> None:
        self.assertEqual(self.store.read_signals(), [])


if __name__ == "__main__":
    unittest.main()
