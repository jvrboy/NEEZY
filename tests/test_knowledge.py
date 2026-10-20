"""Tests for the versioned knowledge base that stores backtest findings."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from neezy_backend.knowledge import (
    SCHEMA_VERSION,
    empty_document,
    load_knowledge,
    record_for,
    save_knowledge,
    summary,
    validate_document,
)

RECORD = {
    "market": "forex",
    "candles": 12000,
    "verdict": "no_edge",
    "selected": {"min_score": 2, "stop_atr_multiple": 1.5, "reward_to_risk": 2.0},
    "train": {"trades": 80, "expectancy_r": 0.12},
    "test": {"trades": 35, "expectancy_r": -0.05},
    "note": "",
}


def _document(**symbols: dict) -> dict:
    document = empty_document()
    document["symbols"] = {f"frx{key}": value for key, value in symbols.items()}
    return document


class KnowledgeTests(unittest.TestCase):
    def test_missing_file_loads_as_empty_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            loaded = load_knowledge(Path(directory) / "absent.json")
        self.assertEqual(loaded, empty_document())

    def test_round_trip_stamps_time_and_keeps_records(self) -> None:
        document = _document(EURUSD=RECORD)
        stamp = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            written = save_knowledge(document, path, generated_at=stamp)
            loaded = load_knowledge(written)
        self.assertEqual(loaded["generated_at"], "2026-10-20T12:00:00+00:00")
        self.assertEqual(loaded["symbols"]["frxEURUSD"], RECORD)
        self.assertEqual(loaded["schema"], SCHEMA_VERSION)

    def test_save_writes_sorted_json_and_leaves_no_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            save_knowledge(_document(EURUSD=RECORD), path)
            names = sorted(item.name for item in Path(directory).iterdir())
            raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(names, ["knowledge.json"])
        self.assertEqual(raw["schema"], SCHEMA_VERSION)

    def test_invalid_documents_are_rejected(self) -> None:
        bad_schema = copy.deepcopy(_document(EURUSD=RECORD))
        bad_schema["schema"] = 99
        cases = {
            "schema": bad_schema,
            "unknown symbol": _document(Nonsense=RECORD),
            "bad verdict": _document(EURUSD={**RECORD, "verdict": "maybe"}),
            "unknown config key": _document(
                EURUSD={**RECORD, "selected": {"min_score": 2, "bogus": 1}}
            ),
            "out-of-range config": _document(
                EURUSD={**RECORD, "selected": {"min_score": 9}}
            ),
            "negative trade count": _document(
                EURUSD={**RECORD, "test": {"trades": -1}}
            ),
        }
        for label, document in cases.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    validate_document(document)

    def test_corrupt_file_raises_instead_of_silently_passing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_knowledge(path)

    def test_lookup_and_summary(self) -> None:
        document = _document(
            EURUSD=RECORD,
            GBPUSD={**RECORD, "verdict": "edge"},
        )
        self.assertEqual(record_for("frxEURUSD", document)["verdict"], "no_edge")
        self.assertIsNone(record_for("frxUSDJPY", document))
        report = summary(document)
        self.assertEqual(report["symbols"], 2)
        self.assertEqual(report["verdicts"]["edge"], 1)
        self.assertEqual(report["verdicts"]["no_edge"], 1)
        self.assertEqual(report["verdicts"]["error"], 0)


if __name__ == "__main__":
    unittest.main()
