from __future__ import annotations

import unittest

from test_archive_lab import candles

from neezy_backend.lab.evaluation import evaluate
from neezy_backend.observability import equity_summary, snapshot_insights


class ResearchEvaluationTests(unittest.TestCase):
    def test_holdout_is_non_overlapping_and_cost_aware(self):
        rows = candles(200)
        base = evaluate(rows, engine="fxlab", indicator="EWPO", horizon=3)
        cost = evaluate(rows, engine="fxlab", indicator="EWPO", horizon=3, cost_bps=2)
        self.assertGreater(base["observations"], 0)
        self.assertAlmostEqual(base["mean_net_bps"] - cost["mean_net_bps"], 2)
        self.assertEqual(base["split_index"], 140)
        for point in base["results"]:
            self.assertGreater(point["entry_epoch"], point["decision_epoch"])
            self.assertGreaterEqual(point["decision_epoch"], rows[140][0])
        for a, b in zip(base["results"], base["results"][1:], strict=False):
            self.assertGreater(b["entry_epoch"], a["exit_epoch"])

    def test_entry_uses_next_open_and_not_signal_close(self):
        rows = candles(200)
        result = evaluate(rows, engine="fxlab", indicator="EWPO", horizon=3)
        first = result["results"][0]
        i = next(i for i, row in enumerate(rows) if row[0] == first["decision_epoch"])
        expected = (
            first["direction"]
            * (rows[i + 3][4] - rows[i + 1][1])
            / rows[i + 1][1]
            * 10000
        )
        self.assertAlmostEqual(first["gross_bps"], expected)

    def test_invalid_settings_and_empty_signals(self):
        for options in (
            {"horizon": 0},
            {"horizon": True},
            {"cost_bps": -1},
            {"holdout_fraction": 0.8},
            {"threshold": float("nan")},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                evaluate(candles(100), **options)
        result = evaluate(candles(100), threshold=10000)
        self.assertEqual(result["observations"], 0)
        self.assertIsNone(result["hit_rate"])
        with self.assertRaises(ValueError):
            evaluate(candles(20))


class ObservabilityTests(unittest.TestCase):
    def test_window_drawdown_and_bad_samples(self):
        samples = [
            {"time": f"2026-10-24T00:0{i}:00+00:00", "equity": value}
            for i, value in enumerate([100, 120, 90, 108])
        ]
        summary = equity_summary(
            [
                *samples,
                {"time": "bad", "equity": 10},
                {"time": samples[-1]["time"], "equity": 100},
            ]
        )
        self.assertEqual(summary["samples"], 4)
        self.assertEqual(summary["rejected_samples"], 2)
        self.assertEqual(summary["max_drawdown_percent"], 25)
        self.assertEqual(summary["current_drawdown_percent"], 10)
        self.assertEqual(summary["window_change"], 8)

    def test_empty_and_cash_flow_safe_statistics(self):
        self.assertIsNone(equity_summary([])["window_change"])
        result = snapshot_insights(
            {
                "heartbeat_age_seconds": 121,
                "open_trades": [
                    {"symbol": "EURUSD"},
                    {"symbol": "EURUSD"},
                    {"symbol": "USDJPY"},
                ],
            }
        )
        self.assertFalse(result["quality"]["fresh"])
        self.assertEqual(result["positions"]["by_symbol"]["EURUSD"], 2)
        self.assertIn("cash flows", result["warning"])
