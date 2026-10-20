"""Offline tests for the opt-in use of knowledge records in AI market context."""

from __future__ import annotations

import random
import unittest

from neezy_backend.config import AppSettings
from neezy_backend.context import format_context, market_snapshot
from neezy_backend.knowledge import learned_note


def _walk(count: int, seed: int = 7) -> list[tuple[float, ...]]:
    rng = random.Random(seed)
    candles = []
    price = 1.1
    for index in range(count):
        open_ = price
        close = open_ * (1 + 0.0002 + rng.gauss(0.0, 0.0008))
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.0003)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.0003)))
        candles.append((index * 60, open_, high, low, close))
        price = close
    return candles


def _document() -> dict:
    return {
        "schema": 1,
        "generated_at": "2026-10-20T20:00:00+00:00",
        "method": "test",
        "symbols": {
            "frxEURUSD": {
                "market": "forex",
                "candles": 12000,
                "verdict": "no_edge",
                "selected": None,
                "train": None,
                "test": {"trades": 88, "expectancy_r": -0.2312},
                "note": "",
            }
        },
    }


class LearnedNoteTests(unittest.TestCase):
    def test_unknown_symbol_has_no_note(self) -> None:
        self.assertIsNone(learned_note("frxGBPUSD", _document()))

    def test_note_carries_verdict_held_out_figures_and_caveat(self) -> None:
        note = learned_note("frxEURUSD", _document())
        self.assertEqual(note["verdict"], "no_edge")
        self.assertEqual(note["trades"], 88)
        self.assertEqual(note["expectancy_r"], -0.2312)
        self.assertEqual(note["generated_at"], "2026-10-20T20:00:00+00:00")
        self.assertIn("Not a forecast", note["caveat"])

    def test_error_record_without_test_stats_does_not_crash(self) -> None:
        document = _document()
        document["symbols"]["frxEURUSD"] = {
            "verdict": "error",
            "candles": 0,
            "test": None,
        }
        note = learned_note("frxEURUSD", document)
        self.assertIsNone(note["trades"])
        self.assertIsNone(note["expectancy_r"])


class SnapshotKnowledgeTests(unittest.TestCase):
    def test_default_snapshot_is_unchanged_by_the_knowledge_base(self) -> None:
        snapshot = market_snapshot(_walk(300), symbol="frxEURUSD", timeframe="1m")
        self.assertIsNotNone(snapshot)
        self.assertIsNone(snapshot["learned"])
        self.assertNotIn("Backtest record", format_context(snapshot))

    def test_opted_in_snapshot_adds_the_record_to_the_prompt(self) -> None:
        snapshot = market_snapshot(
            _walk(300),
            symbol="frxEURUSD",
            timeframe="1m",
            knowledge=_document(),
        )
        self.assertEqual(snapshot["learned"]["verdict"], "no_edge")
        text = format_context(snapshot)
        self.assertIn("Backtest record: no_edge (held-out 88 trades", text)
        self.assertIn("-0.231 R", text)

    def test_unstudied_market_adds_nothing(self) -> None:
        snapshot = market_snapshot(
            _walk(300),
            symbol="frxGBPUSD",
            timeframe="1m",
            knowledge=_document(),
        )
        self.assertIsNone(snapshot["learned"])


class SettingsTests(unittest.TestCase):
    def test_knowledge_is_off_by_default(self) -> None:
        self.assertFalse(AppSettings().use_knowledge)
        self.assertFalse(AppSettings.from_dict({}).use_knowledge)


if __name__ == "__main__":
    unittest.main()
