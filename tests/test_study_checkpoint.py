"""Offline tests for per-market checkpointing and the per-fetch timeout."""

from __future__ import annotations

import io
import json
import random
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from neezy_backend import cli
from neezy_backend.knowledge import load_knowledge
from neezy_backend.study import StudySettings, _bounded_fetch, run_study


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


class BoundedFetchTests(unittest.TestCase):
    def test_returns_value_within_the_deadline(self) -> None:
        candles = _bounded_fetch(
            lambda symbol, seconds, count: [(0, 1.0, 1.0, 1.0, 1.0)],
            "frxEURUSD",
            60,
            1,
            timeout=5,
        )
        self.assertEqual(candles, [(0, 1.0, 1.0, 1.0, 1.0)])

    def test_reraises_fetch_errors_on_the_caller(self) -> None:
        def broken(symbol, seconds, count):
            raise ConnectionError("no endpoint")

        with self.assertRaises(ConnectionError):
            _bounded_fetch(broken, "frxEURUSD", 60, 1, timeout=5)

    def test_stalled_fetch_times_out(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)

        def stalled(symbol, seconds, count):
            release.wait(10)
            return []

        with self.assertRaises(TimeoutError):
            _bounded_fetch(stalled, "frxEURUSD", 60, 1, timeout=0.05)

    def test_timeout_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            StudySettings(fetch_timeout=0)


class RunStudyCheckpointTests(unittest.TestCase):
    def test_on_record_sees_each_symbol_as_it_finishes(self) -> None:
        seen: list[str] = []

        def fake(symbol, seconds, count):
            return _walk(count, seed=sum(map(ord, symbol)))

        settings = StudySettings(candles=2000, min_candles=600)
        run_study(
            ["frxEURUSD", "frxGBPUSD"],
            settings,
            fetch=fake,
            on_record=lambda symbol, record: seen.append(symbol),
        )
        self.assertEqual(seen, ["frxEURUSD", "frxGBPUSD"])

    def test_stalled_market_is_recorded_as_error_and_run_continues(self) -> None:
        release = threading.Event()
        self.addCleanup(release.set)

        def fake(symbol, seconds, count):
            if symbol == "frxGBPUSD":
                release.wait(10)
            return _walk(count, seed=sum(map(ord, symbol)))

        settings = StudySettings(candles=2000, min_candles=600, fetch_timeout=0.05)
        document = run_study(["frxGBPUSD", "frxEURUSD"], settings, fetch=fake)
        self.assertEqual(document["symbols"]["frxGBPUSD"]["verdict"], "error")
        self.assertNotEqual(document["symbols"]["frxEURUSD"]["verdict"], "error")


class CliCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.target = Path(self.directory.name) / "knowledge.json"

    def test_partial_results_are_saved_before_a_later_crash(self) -> None:
        on_disk_during_second: list[list[str]] = []

        def fake(symbol, seconds, count):
            if symbol == "frxGBPUSD":
                # Snapshot what is already on disk when the second market starts.
                if self.target.exists():
                    stored = json.loads(self.target.read_text(encoding="utf-8"))
                    on_disk_during_second.append(sorted(stored["symbols"]))
                raise KeyboardInterrupt
            return _walk(count, seed=sum(map(ord, symbol)))

        out = io.StringIO()
        with mock.patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                cli.main(
                    [
                        "study",
                        "EURUSD",
                        "GBPUSD",
                        "--candles",
                        "2000",
                        "--min-candles",
                        "600",
                        "--out",
                        str(self.target),
                    ],
                    fetch=fake,
                    out=out,
                )
        self.assertEqual(on_disk_during_second, [["frxEURUSD"]])
        stored = load_knowledge(self.target)
        self.assertEqual(set(stored["symbols"]), {"frxEURUSD"})

    def test_dry_run_writes_nothing_during_checkpoints(self) -> None:
        def fake(symbol, seconds, count):
            return _walk(count, seed=sum(map(ord, symbol)))

        out = io.StringIO()
        with mock.patch("sys.stderr", new=io.StringIO()):
            code = cli.main(
                [
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
                ],
                fetch=fake,
                out=out,
            )
        self.assertEqual(code, 0)
        self.assertFalse(self.target.exists())


if __name__ == "__main__":
    unittest.main()
