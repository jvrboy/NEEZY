"""Offline tests for the train-then-validate study and its knowledge output."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from neezy_backend.knowledge import VERDICTS, load_knowledge, save_knowledge
from neezy_backend.study import (
    StudySettings,
    _clean,
    default_grid,
    evaluate_candles,
    run_study,
)

SMALL = StudySettings(
    candles=1_500,
    lookback=100,
    min_candles=300,
    min_train_trades=5,
    min_test_trades=3,
    grid=default_grid()[:6],
)


def _walk(count: int, seed: int = 3, drift: float = 0.0) -> list[tuple[float, ...]]:
    rng = random.Random(seed)
    candles = []
    price = 1.1
    for index in range(count):
        open_ = price
        close = open_ * (1 + drift + rng.gauss(0.0, 0.0008))
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.0003)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.0003)))
        candles.append((index * 60, open_, high, low, close))
        price = close
    return candles


def _fake_fetch(table: dict[str, object]):
    def fetch(symbol: str, granularity: int, count: int):
        outcome = table[symbol]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return fetch


class StudyTests(unittest.TestCase):
    def test_evaluation_is_deterministic_and_well_formed(self) -> None:
        candles = _walk(1_500, drift=0.0002)
        first = evaluate_candles(candles, SMALL)
        second = evaluate_candles(candles, SMALL)
        self.assertEqual(first, second)
        self.assertIn(first["verdict"], VERDICTS)
        if first["selected"] is not None:
            self.assertEqual(first["selected"]["lookback"], SMALL.lookback)
            self.assertGreaterEqual(first["train"]["trades"], SMALL.min_train_trades)

    def test_unreachable_training_trades_mark_insufficient_data(self) -> None:
        strict = StudySettings(
            candles=1_500,
            lookback=100,
            min_candles=300,
            min_train_trades=10**6,
            grid=default_grid()[:2],
        )
        result = evaluate_candles(_walk(1_500), strict)
        self.assertEqual(result["verdict"], "insufficient_data")
        self.assertIsNone(result["selected"])
        self.assertIsNone(result["test"])

    def test_study_records_errors_and_short_history_without_stopping(self) -> None:
        table = {
            "frxEURUSD": _walk(1_500),
            "frxGBPUSD": ConnectionError("Could not reach any market data endpoint"),
            "frxUSDJPY": _walk(100),
        }
        seen: list[tuple[str, str]] = []
        document = run_study(
            table,
            SMALL,
            fetch=_fake_fetch(table),
            progress=lambda symbol, verdict: seen.append((symbol, verdict)),
        )
        symbols = document["symbols"]
        self.assertEqual(set(symbols), set(table))
        self.assertEqual(symbols["frxGBPUSD"]["verdict"], "error")
        self.assertIn("endpoint", symbols["frxGBPUSD"]["note"])
        self.assertEqual(symbols["frxUSDJPY"]["verdict"], "insufficient_data")
        self.assertEqual(symbols["frxEURUSD"]["market"], "forex")
        self.assertEqual(len(seen), 3)
        self.assertIn("Fixed-rule backtest", document["method"])

    def test_study_output_is_a_valid_knowledge_document(self) -> None:
        table = {"frxEURUSD": _walk(1_500, seed=9), "frxUSDJPY": _walk(1_500, seed=4)}
        document = run_study(table, SMALL, fetch=_fake_fetch(table))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "knowledge.json"
            save_knowledge(document, path)
            text = path.read_text(encoding="utf-8")
            reloaded = load_knowledge(path)
        # Strict JSON: no NaN or Infinity literals may reach the file.
        json.loads(text, parse_constant=_reject_constant)
        self.assertEqual(set(reloaded["symbols"]), set(table))

    def test_settings_reject_unusable_values(self) -> None:
        with self.assertRaises(ValueError):
            StudySettings(train_fraction=1.0)
        with self.assertRaises(ValueError):
            StudySettings(lookback=200, min_candles=500)
        with self.assertRaises(ValueError):
            StudySettings(candles=1_000, min_candles=2_000)
        with self.assertRaises(ValueError):
            StudySettings(grid=())

    def test_non_finite_statistics_become_null(self) -> None:
        cleaned = _clean({"profit_factor": float("inf"), "win_rate": 50.123456})
        self.assertIsNone(cleaned["profit_factor"])
        self.assertEqual(cleaned["win_rate"], 50.1235)


def _reject_constant(name: str) -> None:
    raise AssertionError(f"non-standard JSON constant {name}")


if __name__ == "__main__":
    unittest.main()
