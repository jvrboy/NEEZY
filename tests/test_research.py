"""Offline regression tests; generated candles are fixtures, not training evidence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neezy_backend.config import AppSettings
from neezy_backend.research import pair_research, training_run
from tests.test_brain import _candles


class ResearchTests(unittest.TestCase):
    def test_settings_round_trip_and_invalid_values(self):
        cfg = AppSettings(ml_epochs=3, ml_horizon=7, pair_cost_bps=5.0)
        self.assertEqual(AppSettings.from_dict(cfg.to_dict()), cfg)
        for changes in (
            {"ml_epochs": 0},
            {"ml_probability": float("nan")},
            {"ml_seed": True},
            {"pair_exit_z": 3.0},
            {"pair_stop_z": 1.5},
            {"pair_lookback": 500},
            {"pair_min_correlation": float("inf")},
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaises((ValueError, TypeError)),
            ):
                AppSettings(**changes)

    def test_pair_alignment_and_costs(self):
        left = _candles(900)
        right = _candles(900, seed=18)
        settings = AppSettings(pair_min_correlation=0.0, pair_entry_z=0.8)
        free = pair_research(left, right, settings=settings.updated(pair_cost_bps=0))
        paid = pair_research(left, right, settings=settings)
        self.assertEqual(free["entries"], paid["entries"])
        self.assertGreater(paid["cost_log_return"], 0)
        self.assertAlmostEqual(
            paid["net_log_return"], free["net_log_return"] - paid["cost_log_return"]
        )
        self.assertEqual(paid["aligned_candles"], 899)
        self.assertAlmostEqual(
            sum(row["pnl"] for row in paid["path"]), paid["net_log_return"]
        )

    def test_pair_rejects_bad_or_short_data(self):
        for rows in ([], _candles(100), list(reversed(_candles(900)))):
            with self.assertRaises(ValueError):
                pair_research(rows, _candles(900))

    def test_pair_does_not_change_past_positions_when_future_is_changed(self):
        left, right = _candles(1000), _candles(1000, seed=19)
        cfg = AppSettings(pair_min_correlation=0.0)
        before = pair_research(left, right, settings=cfg)
        changed = left[:]
        changed[-3] = (changed[-3][0], *[v * 1.1 for v in changed[-3][1:]])
        after = pair_research(changed, right, settings=cfg)
        self.assertEqual(before["path"][:-3], after["path"][:-3])
        self.assertEqual(before["hedge_beta"], after["hedge_beta"])

    def test_training_checkpoints_success_and_failure(self):
        def fetch(symbol, *_args, **_kwargs):
            if symbol == "unavailable":
                raise ConnectionError("offline")
            return _candles(500)

        with tempfile.TemporaryDirectory() as directory:
            checkpoint = str(Path(directory) / "run.json")
            result = training_run(
                ["frxEURUSD", "unavailable"],
                settings=AppSettings(ml_epochs=1),
                fetch=fetch,
                checkpoint=checkpoint,
            )
            self.assertTrue(Path(checkpoint).exists())
        self.assertEqual(result["symbols"]["unavailable"]["status"], "error")
        record = result["symbols"]["frxEURUSD"]
        self.assertEqual(record["status"], "trained")
        self.assertEqual(len(record["ohlc_sha256"]), 64)
        self.assertGreater(record["report"]["train"]["samples"], 0)
        self.assertGreater(record["report"]["test"]["samples"], 0)

    def test_no_training_when_fetch_fails(self):
        with patch("neezy_backend.research.train_model") as trainer:
            result = training_run(["missing"], fetch=lambda *_a, **_kw: [])
            trainer.assert_not_called()
        self.assertEqual(result["symbols"]["missing"]["status"], "error")

    def test_reject_unsupported_timeframe(self):
        with self.assertRaises(ValueError):
            training_run([], timeframe="nonsense")


if __name__ == "__main__":
    unittest.main()
