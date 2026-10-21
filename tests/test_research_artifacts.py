"""Integrity, isolation and runtime checks for the bundled real-data experiments."""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neezy_backend import datasets
from neezy_backend.brain import predict, validate_model
from neezy_backend.cli import main
from neezy_backend.database import LocalDatabase
from neezy_backend.mcp_tools import register_app_tools
from neezy_backend.remote import AppCommandBridge
from neezy_backend.tools import ToolPermission, ToolRegistry


class ResearchArtifactsTest(unittest.TestCase):
    def test_models_match_saved_candle_hash_and_identity(self):
        doc = datasets.load_dataset("ml_research.json")
        self.assertEqual(len(doc["symbols"]), 11)
        for symbol, record in doc["symbols"].items():
            with self.subTest(symbol=symbol):
                raw = json.loads(
                    (datasets.DATA_DIR / record["raw_dataset"]).read_text()
                )
                digest = hashlib.sha256(
                    json.dumps(raw["candles"], separators=(",", ":")).encode()
                ).hexdigest()
                self.assertEqual(digest, record["ohlc_sha256"])
                self.assertEqual(len(raw["candles"]), 3000)
                self.assertEqual(record["model"]["symbol"], symbol)
                validate_model(record["model"])
                self.assertGreater(record["report"]["test"]["samples"], 300)

    def test_shipped_model_timeframe_must_match(self):
        self.assertIsNotNone(datasets.shipped_brain_model("R_10", "5m"))
        self.assertIsNone(datasets.shipped_brain_model("R_10", "1m"))
        self.assertIsNone(datasets.shipped_brain_model("not-a-market", "5m"))

    def test_unqualified_models_remain_neutral(self):
        doc = datasets.load_dataset("ml_research.json")
        for record in doc["symbols"].values():
            if record["report"]["deployment_ready"]:
                continue
            rows = json.loads((datasets.DATA_DIR / record["raw_dataset"]).read_text())[
                "candles"
            ]
            self.assertEqual(predict(rows, record["model"])["direction"], "NEUTRAL")

    def test_report_does_not_return_weights_or_mutate_cache(self):
        report = datasets.research_report()
        for record in report["symbols"].values():
            self.assertNotIn("model", record)
        self.assertIn(
            "model", datasets.load_dataset("ml_research.json")["symbols"]["R_10"]
        )

    def test_dataset_callers_cannot_corrupt_cache(self):
        document = datasets.load_dataset(datasets.MARKET_KNOWLEDGE)
        document.clear()
        self.assertIn("RSI", datasets.indicator_names())

    def test_loader_rejects_symlinks_and_non_names(self):
        for value in (1, None, "a\x00.json", "../file.json", "a\\b.json"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                datasets.dataset_path(value)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "outside.json"
            outside.write_text("{}")
            data = root / "data"
            data.mkdir()
            try:
                (data / "escape.json").symlink_to(outside)
            except OSError:
                self.skipTest("symlink creation is not permitted")
            with (
                patch.object(datasets, "DATA_DIR", data),
                self.assertRaises(ValueError),
            ):
                datasets.dataset_path("escape.json")

    def test_research_status_cli_never_fetches(self):
        out = io.StringIO()
        with patch(
            "neezy_backend.research.fetch_history",
            side_effect=AssertionError("network"),
        ):
            self.assertEqual(main(["research", "status"], out=out), 0)
        self.assertEqual(len(json.loads(out.getvalue())["symbols"]), 11)

    def test_new_mcp_helpers_are_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            db = LocalDatabase(Path(directory) / "test.db")
            bridge = AppCommandBridge()
            try:
                registry = register_app_tools(ToolRegistry(), db, bridge)
                for name in (
                    "get_research_report",
                    "get_dataset_inventory",
                    "research_forex_pair",
                ):
                    self.assertIs(
                        registry.get(name).permission, ToolPermission.READ_ONLY
                    )
                report = registry.execute("get_research_report")
                self.assertEqual(len(report["symbols"]), 11)
                with self.assertRaises(ValueError):
                    registry.execute(
                        "research_forex_pair", {"left": "R_10", "right": "R_100"}
                    )
            finally:
                bridge.close()
                db.close()


if __name__ == "__main__":
    unittest.main()
