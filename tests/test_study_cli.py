"""Offline tests for ``neezy-cli study`` and deep history routing in the CLI."""

from __future__ import annotations

import io
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neezy_backend import cli
from neezy_backend.knowledge import load_knowledge, save_knowledge


def _walk(count: int, seed: int) -> list[tuple[float, ...]]:
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


class StudyCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.target = Path(self.directory.name) / "knowledge.json"

    @staticmethod
    def fake_fetch(symbol, seconds, count):
        if symbol == "frxGBPUSD":
            raise ConnectionError("Could not reach any market data endpoint")
        return _walk(count, seed=sum(map(ord, symbol)))

    def run_cli(self, *argv, fetch=None):
        out = io.StringIO()
        with mock.patch("sys.stderr", new=io.StringIO()):
            code = cli.main(list(argv), fetch=fetch or self.fake_fetch, out=out)
        return code, out.getvalue()

    def test_study_writes_knowledge_and_reports_json(self) -> None:
        code, text = self.run_cli(
            "study",
            "EURUSD",
            "GBPUSD",
            "--candles",
            "2000",
            "--min-candles",
            "600",
            "--out",
            str(self.target),
            "--json",
        )
        self.assertEqual(code, 0)
        data = json.loads(text)
        self.assertEqual(data["saved_to"], str(self.target))
        self.assertEqual(set(data["symbols"]), {"frxEURUSD", "frxGBPUSD"})
        self.assertEqual(data["symbols"]["frxGBPUSD"]["verdict"], "error")
        stored = load_knowledge(self.target)
        self.assertEqual(set(stored["symbols"]), {"frxEURUSD", "frxGBPUSD"})
        self.assertEqual(data["summary"]["symbols"], 2)

    def test_error_keeps_previous_verdict(self) -> None:
        previous = {
            "schema": 1,
            "method": "old",
            "symbols": {
                "frxGBPUSD": {
                    "market": "forex",
                    "candles": 5000,
                    "verdict": "edge",
                    "selected": None,
                    "train": None,
                    "test": None,
                    "note": "",
                }
            },
        }
        save_knowledge(previous, self.target)
        code, text = self.run_cli(
            "study",
            "GBPUSD",
            "--candles",
            "2000",
            "--min-candles",
            "600",
            "--out",
            str(self.target),
            "--json",
        )
        self.assertEqual(code, 0)
        data = json.loads(text)
        self.assertEqual(data["kept_previous"], ["frxGBPUSD"])
        self.assertEqual(
            load_knowledge(self.target)["symbols"]["frxGBPUSD"]["verdict"], "edge"
        )

    def test_zero_spread_is_reported_separately_from_the_default(self) -> None:
        base = [
            "study",
            "EURUSD",
            "--candles",
            "2000",
            "--min-candles",
            "600",
            "--out",
            str(self.target),
            "--dry-run",
            "--json",
        ]
        _, default_text = self.run_cli(*base)
        _, zero_text = self.run_cli(*base, "--spread-pips", "0")
        default = json.loads(default_text)["symbols"]["frxEURUSD"]
        zero = json.loads(zero_text)["symbols"]["frxEURUSD"]
        if default["selected"] and zero["selected"]:
            self.assertEqual(default["selected"]["spread"], 0.0001)
            self.assertEqual(zero["selected"]["spread"], 0.0)

    def test_dry_run_does_not_touch_the_file(self) -> None:
        code, text = self.run_cli(
            "study",
            "EURUSD",
            "--candles",
            "2000",
            "--min-candles",
            "600",
            "--out",
            str(self.target),
            "--dry-run",
        )
        self.assertEqual(code, 0)
        self.assertIn("Dry run", text)
        self.assertFalse(self.target.exists())

    def test_table_output_names_each_market(self) -> None:
        code, text = self.run_cli(
            "study",
            "EURUSD",
            "GBPUSD",
            "--candles",
            "2000",
            "--min-candles",
            "600",
            "--out",
            str(self.target),
        )
        self.assertEqual(code, 0)
        self.assertIn("frxEURUSD", text)
        self.assertIn("error", text)
        self.assertIn("not a forecast", text)

    def test_invalid_settings_exit_with_error(self) -> None:
        code, _ = self.run_cli(
            "study",
            "EURUSD",
            "--candles",
            "1000",
            "--out",
            str(self.target),
            "--dry-run",
        )
        self.assertEqual(code, 2)

    def test_knowledge_reads_saved_records(self) -> None:
        record = {
            "market": "forex",
            "candles": 12000,
            "verdict": "no_edge",
            "selected": None,
            "train": None,
            "test": {"trades": 40, "expectancy_r": -0.2},
            "note": "",
        }
        save_knowledge(
            {
                "schema": 1,
                "method": "test",
                "symbols": {"frxEURUSD": record, "frxUSDJPY": dict(record)},
            },
            self.target,
        )
        code, text = self.run_cli("knowledge", "--file", str(self.target), "--json")
        self.assertEqual(code, 0)
        data = json.loads(text)
        self.assertEqual(data["summary"]["symbols"], 2)
        self.assertEqual(data["summary"]["verdicts"]["no_edge"], 2)

        code, text = self.run_cli(
            "knowledge", "EURUSD", "GBPUSD", "--file", str(self.target)
        )
        self.assertEqual(code, 0)
        self.assertIn("frxEURUSD", text)
        self.assertIn("Never studied: frxGBPUSD", text)

    def test_knowledge_with_no_file_says_nothing_studied(self) -> None:
        code, text = self.run_cli("knowledge", "--file", str(self.target))
        self.assertEqual(code, 0)
        self.assertIn("Nothing studied yet", text)

    def test_unknown_category_is_rejected(self) -> None:
        code, _ = self.run_cli(
            "study",
            "--category",
            "no_such_category",
            "--out",
            str(self.target),
            "--dry-run",
        )
        self.assertEqual(code, 2)

    def test_default_fetch_pages_deep_history_only_when_needed(self) -> None:
        with (
            mock.patch.object(cli, "fetch_candles", return_value=[]) as shallow,
            mock.patch.object(cli, "fetch_history", return_value=[]) as deep,
        ):
            cli._default_fetch("frxEURUSD", 60, 300)
            self.assertEqual(shallow.call_args.args, ("frxEURUSD", 60, 300))
            deep.assert_not_called()
            cli._default_fetch("frxEURUSD", 60, 12_000)
            self.assertEqual(deep.call_args.args, ("frxEURUSD", 60, 12_000))
            self.assertEqual(shallow.call_count, 1)


if __name__ == "__main__":
    unittest.main()
