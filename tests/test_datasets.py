"""Schema versioning for the shipped knowledge datasets (roadmap update #19)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neezy_backend import datasets
from neezy_backend.insights import insight_line, knowledge_brief, playbook_entry


class DatasetTests(unittest.TestCase):
    def test_every_shipped_dataset_is_valid_json(self) -> None:
        for name in datasets.list_datasets():
            with self.subTest(name):
                self.assertIsInstance(datasets.load_dataset(name), dict)

    def test_market_knowledge_has_indicators(self) -> None:
        self.assertIn("RSI", datasets.indicator_names())

    def test_playbook_lists_named_strategies(self) -> None:
        entry = playbook_entry("SUPERTREND")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "SUPERTREND")
        self.assertIn("best_regime", entry)

    def test_weights_cover_the_study_symbols(self) -> None:
        document = datasets.model_weights()
        self.assertGreater(len(document.get("symbols", {})), 50)

    def test_weight_for_unknown_symbol_is_none(self) -> None:
        self.assertIsNone(datasets.weight_for("NOT_A_SYMBOL"))

    def test_insight_line_carries_the_caveat(self) -> None:
        document = datasets.model_weights()
        symbol = next(iter(document["symbols"]))
        line = insight_line(symbol)
        self.assertIsNotNone(line)
        self.assertIn("not a forecast", line)

    def test_insight_line_unknown_symbol_is_none(self) -> None:
        self.assertIsNone(insight_line("NOT_A_SYMBOL"))

    def test_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            datasets.dataset_path("../knowledge.json")

    def test_summary_reports_inventory(self) -> None:
        summary = datasets.dataset_summary()
        self.assertIn("market_knowledge.json", summary["datasets"])
        self.assertGreater(summary["weighted_symbols"], 0)

    def test_cache_clear_reloads(self) -> None:
        datasets.load_dataset(datasets.MARKET_KNOWLEDGE)
        datasets.clear_cache()
        self.assertIn("RSI", datasets.indicator_names())

    def test_knowledge_brief_lists_strategies(self) -> None:
        brief = knowledge_brief()
        self.assertIn("SUPERTREND", brief["strategies"])
        self.assertGreater(brief["weighted_symbols"], 0)


class SchemaVersionTests(unittest.TestCase):
    """Every load goes through the versioned, migrating loader."""

    def test_every_shipped_dataset_declares_the_current_version(self) -> None:
        for name in datasets.list_datasets():
            with self.subTest(name):
                document = datasets.load_dataset(name)
                self.assertEqual(document["schema_version"], datasets.SCHEMA_VERSION)

    def test_shipped_files_are_stamped_on_disk(self) -> None:
        for name in datasets.list_datasets():
            with self.subTest(name):
                raw = json.loads((datasets.DATA_DIR / name).read_text(encoding="utf-8"))
                self.assertEqual(raw.get("schema_version"), datasets.SCHEMA_VERSION)

    def test_research_candle_snapshots_are_stamped_on_disk(self) -> None:
        snapshots = sorted((datasets.DATA_DIR / "research_candles").glob("*.json"))
        self.assertGreater(len(snapshots), 0)
        for path in snapshots:
            with self.subTest(path.name):
                raw = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(raw.get("schema_version"), datasets.SCHEMA_VERSION)

    def test_legacy_document_migrates_forward(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(
                json.dumps({"schema": 1, "symbols": {"R_10": {"edge_weight": 0.2}}}),
                encoding="utf-8",
            )
            self.addCleanup(datasets.clear_cache)
            with patch.object(datasets, "DATA_DIR", Path(directory)):
                document = datasets.load_dataset("legacy.json")
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["symbols"]["R_10"]["edge_weight"], 0.2)

    def test_migration_is_a_pure_annotation(self) -> None:
        """A v0 file and its stamped v1 twin must load identically."""
        body = {"schema": 1, "strategies": [{"name": "SUPERTREND"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "legacy.json").write_text(json.dumps(body), encoding="utf-8")
            (root / "stamped.json").write_text(
                json.dumps({**body, "schema_version": 1}), encoding="utf-8"
            )
            self.addCleanup(datasets.clear_cache)
            with patch.object(datasets, "DATA_DIR", root):
                legacy = datasets.load_dataset("legacy.json")
                stamped = datasets.load_dataset("stamped.json")
        self.assertEqual(legacy, stamped)

    def test_future_version_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.json"
            path.write_text(
                json.dumps({"schema_version": 99, "symbols": {}}), encoding="utf-8"
            )
            with patch.object(datasets, "DATA_DIR", Path(directory)):
                with self.assertRaises(ValueError) as raised:
                    datasets.load_dataset("future.json")
        message = str(raised.exception)
        self.assertIn("future.json", message)
        self.assertIn("99", message)
        self.assertIn(str(datasets.SCHEMA_VERSION), message)

    def test_non_integer_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "garbled.json"
            path.write_text(json.dumps({"schema_version": "one"}), encoding="utf-8")
            with patch.object(datasets, "DATA_DIR", Path(directory)):
                with self.assertRaises(ValueError) as raised:
                    datasets.load_dataset("garbled.json")
        self.assertIn("garbled.json", str(raised.exception))

    def test_negative_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "negative.json"
            path.write_text(json.dumps({"schema_version": -1}), encoding="utf-8")
            with patch.object(datasets, "DATA_DIR", Path(directory)):
                with self.assertRaises(ValueError):
                    datasets.load_dataset("negative.json")

    def test_migration_never_rewrites_the_file_on_disk(self) -> None:
        payload = '{"schema": 1, "note": "legacy layout"}'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(payload, encoding="utf-8")
            self.addCleanup(datasets.clear_cache)
            with patch.object(datasets, "DATA_DIR", Path(directory)):
                document = datasets.load_dataset("legacy.json")
            self.assertEqual(
                path.read_text(encoding="utf-8"), payload
            )  # on disk: untouched
        self.assertEqual(document["schema_version"], 1)  # in memory: migrated

    def test_loading_all_shipped_files_never_rewrites_them(self) -> None:
        before = {
            path.name: path.read_bytes() for path in datasets.DATA_DIR.rglob("*.json")
        }
        for name in datasets.list_datasets():
            datasets.load_dataset(name)
        after = {
            path.name: path.read_bytes() for path in datasets.DATA_DIR.rglob("*.json")
        }
        self.assertEqual(before, after)

    def test_loading_twice_gives_identical_results(self) -> None:
        first = datasets.load_dataset(datasets.MARKET_KNOWLEDGE)
        second = datasets.load_dataset(datasets.MARKET_KNOWLEDGE)
        self.assertEqual(first, second)
        first["schema_version"] = 999  # mutate the returned copy only
        third = datasets.load_dataset(datasets.MARKET_KNOWLEDGE)
        self.assertEqual(third, second)

    def test_summary_hides_version_metadata_from_inventory_keys(self) -> None:
        summary = datasets.dataset_summary()
        for name, info in summary["datasets"].items():
            with self.subTest(name):
                self.assertNotIn("schema_version", info["keys"])
                self.assertNotIn("schema", info["keys"])


if __name__ == "__main__":
    unittest.main()
