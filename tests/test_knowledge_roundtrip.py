"""Round-trip fidelity tests for the knowledge base (roadmap update #57)."""

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from neezy_backend.knowledge import (
    empty_document,
    load_knowledge,
    record_for,
    save_knowledge,
    summary,
)


def _document() -> dict:
    doc = empty_document()
    doc["method"] = "train-then-validate"
    doc["symbols"] = {
        "frxEURUSD": {
            "verdict": "edge",
            "selected": None,
            "train": {"trades": 40, "win_rate": 0.55, "avg_r": 0.12},
            "test": {"trades": 10, "win_rate": 0.5, "avg_r": 0.0},
        },
        "R_100": {
            "verdict": "insufficient_data",
            "selected": None,
            "train": None,
            "test": None,
        },
    }
    return doc


class KnowledgeRoundTripTests(unittest.TestCase):
    def test_save_then_load_preserves_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            saved_at = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
            save_knowledge(_document(), path, generated_at=saved_at)
            loaded = load_knowledge(path)
            self.assertEqual(loaded["schema"], empty_document()["schema"])
            self.assertEqual(loaded["method"], "train-then-validate")
            self.assertEqual(loaded["symbols"]["frxEURUSD"]["train"]["win_rate"], 0.55)
            self.assertIsNone(loaded["symbols"]["R_100"]["train"])
            self.assertEqual(loaded["generated_at"], "2026-10-22T12:00:00+00:00")

    def test_unicode_and_long_values_survive(self):
        doc = _document()
        note = "trend after London open · éurfür " + "x" * 500
        doc["symbols"]["frxEURUSD"]["method_note"] = note
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "k.json"
            save_knowledge(doc, path)
            loaded = load_knowledge(path)
            self.assertEqual(loaded["symbols"]["frxEURUSD"]["method_note"], note)

    def test_invalid_documents_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "invalid.json"
            for bad in (
                "not-a-dict",
                {"schema": 99, "symbols": {}},
                {"schema": empty_document()["schema"], "symbols": {"X": 3}},
                {
                    "schema": empty_document()["schema"],
                    "symbols": {"frxEURUSD": {"verdict": "maybe"}},
                },
                {
                    "schema": empty_document()["schema"],
                    "symbols": {
                        "frxEURUSD": {
                            "verdict": "edge",
                            "train": {"trades": -1},
                        }
                    },
                },
            ):
                with self.subTest(bad=bad):
                    with self.assertRaises(ValueError):
                        save_knowledge(bad, target)

    def test_record_for_returns_none_or_copy(self):
        doc = _document()
        record = record_for("frxEURUSD", doc)
        self.assertIsNotNone(record)
        record["train"]["win_rate"] = 0.0  # mutate the copy
        self.assertEqual(doc["symbols"]["frxEURUSD"]["train"]["win_rate"], 0.55)
        self.assertIsNone(record_for("MISSING", doc))

    def test_summary_counts_symbols(self):
        stats = summary(_document())
        self.assertGreaterEqual(stats.get("symbols", 0), 2)

    def test_generated_at_is_always_set_on_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "k.json"
            doc = _document()
            doc["generated_at"] = None
            save_knowledge(doc, path)
            self.assertIsNotNone(load_knowledge(path)["generated_at"])


if __name__ == "__main__":
    unittest.main()
