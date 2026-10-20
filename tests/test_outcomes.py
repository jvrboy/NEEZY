import unittest

from neezy_backend.outcomes import evaluate_outcomes, summarize

CANDLES = [(i, 100.0, 101.0, 99.0, 100.0 + i) for i in range(10)]


def _signal(**overrides):
    base = {
        "id": 1,
        "symbol": "frxEURUSD",
        "direction": 1,
        "price": 102.0,
        "created_at": 2,
    }
    base.update(overrides)
    return base


class OutcomeTest(unittest.TestCase):
    def test_long_signal_uses_close_after_horizon(self):
        (outcome,) = evaluate_outcomes([_signal()], CANDLES, horizon=3)
        self.assertEqual(outcome.exit, 104.0)
        self.assertAlmostEqual(outcome.return_pct, (104 - 102) / 102 * 100)
        self.assertTrue(outcome.hit)

    def test_short_signal_profits_when_price_falls(self):
        (outcome,) = evaluate_outcomes(
            [_signal(direction=-1, price=110.0)], CANDLES, horizon=3
        )
        self.assertGreater(outcome.return_pct, 0)

    def test_unresolved_and_neutral_signals_skipped(self):
        signals = [_signal(created_at=9), _signal(direction=0), _signal(price=None)]
        self.assertEqual(evaluate_outcomes(signals, CANDLES, horizon=3), [])

    def test_iso_timestamps_supported(self):
        stamp = "1970-01-01T00:00:02+00:00"
        outcomes = evaluate_outcomes([_signal(created_at=stamp)], CANDLES, horizon=3)
        self.assertEqual(len(outcomes), 1)

    def test_invalid_horizon(self):
        with self.assertRaises(ValueError):
            evaluate_outcomes([], CANDLES, horizon=0)

    def test_summary(self):
        outcomes = evaluate_outcomes(
            [_signal(), _signal(id=2, direction=-1)], CANDLES, horizon=3
        )
        stats = summarize(outcomes)
        self.assertEqual(stats["count"], 2)
        self.assertEqual(stats["win_rate"], 50.0)
        self.assertGreater(stats["best_pct"], stats["worst_pct"])

    def test_empty_summary(self):
        self.assertEqual(summarize([])["count"], 0)


if __name__ == "__main__":
    unittest.main()
