"""Determinism tests for the backtester (roadmap update #56).

The same candles and config must produce an identical result twice.
"""

import unittest

from neezy_backend.backtest import BacktestConfig, run_backtest


def _candles(
    count: int = 400, seed: int = 7
) -> list[tuple[int, float, float, float, float]]:
    """Deterministic pseudo-random walk, stable across runs and platforms."""
    state = seed
    price = 1.1000
    candles = []
    for i in range(count):
        state = (state * 1103515245 + 12345) % (2**31)
        drift = ((state >> 16) % 1000 - 500) / 50000.0
        open_ = price
        close = max(0.0001, open_ + drift)
        high = max(open_, close) + abs(drift) / 2 + 0.0002
        low = min(open_, close) - abs(drift) / 2 - 0.0002
        candles.append((1_700_000_000 + i * 300, open_, high, low, close))
        price = close
    return candles


class BacktestDeterminismTests(unittest.TestCase):
    def test_same_inputs_identical_reports(self):
        config = BacktestConfig()
        first = run_backtest(_candles(), config)
        second = run_backtest(_candles(), config)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_different_seed_changes_result(self):
        config = BacktestConfig()
        first = run_backtest(_candles(seed=7), config)
        second = run_backtest(_candles(seed=8), config)
        self.assertNotEqual(first.to_dict(), second.to_dict())

    def test_result_dict_is_json_stable(self):
        import json

        report = run_backtest(_candles(200), BacktestConfig()).to_dict()
        round_tripped = json.loads(json.dumps(report))
        self.assertEqual(report, round_tripped)


if __name__ == "__main__":
    unittest.main()
