from __future__ import annotations

import unittest

from neezy_backend.model_validation import backtest_model
from tests.cloud_fixtures import candles, valid_model


class ModelBacktestTests(unittest.TestCase):
    def test_forced_model_has_only_held_out_trade_statistics(self):
        result = backtest_model(candles(), valid_model(), min_trades=1)
        self.assertEqual(result["method"], "chronological_held_out_trade_backtest_v1")
        self.assertGreater(result["trades"], 0)
        self.assertEqual(result["candles_tested"], 60)
        self.assertEqual(result["test_start_epoch"], candles()[340][0])
        self.assertIn("next-open", result["note"])

    def test_research_only_model_cannot_pass(self):
        result = backtest_model(candles(), valid_model(ready=False), min_trades=1)
        self.assertEqual(result["trades"], 0)
        self.assertFalse(result["passed"])

    def test_probability_and_cost_validation(self):
        with self.assertRaises(ValueError):
            backtest_model(candles(), valid_model(), minimum_probability=0.5)
        with self.assertRaises(ValueError):
            backtest_model(candles(), valid_model(), spread=-0.1)
        with self.assertRaises(ValueError):
            backtest_model(candles(), valid_model(), min_trades=0)


if __name__ == "__main__":
    unittest.main()
