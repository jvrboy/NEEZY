"""Boundary tests for signal outcome resolution (roadmap update #49).

Pins the conservative rule: when TP and SL both sit inside one candle the
stop fills first. Exact touches, gap opens, and horizon truncation covered.
"""

import unittest
from typing import ClassVar

from neezy_backend.confluence import resolve_outcome
from neezy_backend.outcomes import evaluate_outcomes

Candle = tuple[int, float, float, float, float]


def _candle(epoch: int, high: float, low: float, close: float) -> Candle:
    return (epoch, (high + low) / 2, high, low, close)


class ResolveOutcomeBoundaryTests(unittest.TestCase):
    def test_both_levels_in_one_candle_resolves_sl_for_long(self):
        candles = [_candle(2, 102.0, 98.0, 101.0)]
        result = resolve_outcome(1, 100.0, 99.0, 101.0, candles, horizon=5)
        self.assertEqual(result, "SL")

    def test_both_levels_in_one_candle_resolves_sl_for_short(self):
        candles = [_candle(2, 102.0, 98.0, 101.0)]
        result = resolve_outcome(-1, 100.0, 101.0, 99.0, candles, horizon=5)
        self.assertEqual(result, "SL")

    def test_exact_touch_counts_as_hit(self):
        # High exactly equals the long target.
        candles = [_candle(2, 101.0, 99.5, 100.5)]
        self.assertEqual(resolve_outcome(1, 100.0, 99.0, 101.0, candles, 5), "TP")
        # Low exactly equals the long stop.
        candles = [_candle(2, 100.5, 99.0, 100.2)]
        self.assertEqual(resolve_outcome(1, 100.0, 99.0, 101.0, candles, 5), "SL")

    def test_gap_open_beyond_target_counts_as_tp(self):
        # Candle opens beyond the target; the target still fills.
        candles = [_candle(2, 105.0, 103.0, 104.0)]
        self.assertEqual(resolve_outcome(1, 100.0, 99.0, 101.0, candles, 5), "TP")

    def test_gap_open_beyond_stop_counts_as_sl(self):
        candles = [_candle(2, 98.5, 95.0, 96.0)]
        self.assertEqual(resolve_outcome(1, 100.0, 99.0, 101.0, candles, 5), "SL")

    def test_neither_level_reached_returns_none(self):
        candles = [_candle(2, 100.9, 99.1, 100.5)]
        self.assertIsNone(resolve_outcome(1, 100.0, 99.0, 101.0, candles, 5))

    def test_resolution_can_take_multiple_candles(self):
        # First candle: nothing. Second: target hit.
        candles = [_candle(2, 100.5, 99.5, 100.2), _candle(3, 101.5, 100.0, 101.2)]
        self.assertEqual(resolve_outcome(1, 100.0, 99.0, 101.0, candles, 5), "TP")

    def test_horizon_truncates_the_walk(self):
        # Target would hit on candle 3, but horizon is 2.
        candles = [
            _candle(2, 100.5, 99.5, 100.2),
            _candle(3, 100.6, 99.6, 100.3),
            _candle(4, 101.5, 100.0, 101.2),
        ]
        self.assertIsNone(resolve_outcome(1, 100.0, 99.0, 101.0, candles, 2))

    def test_empty_candles_returns_none(self):
        self.assertIsNone(resolve_outcome(1, 100.0, 99.0, 101.0, [], 5))


class EvaluateOutcomesEdgeTests(unittest.TestCase):
    CANDLES: ClassVar[list[Candle]] = [
        (i, 100.0, 101.0, 99.0, 100.0 + i) for i in range(10)
    ]

    def _signal(self, **overrides):
        base = {
            "id": 1,
            "symbol": "frxEURUSD",
            "direction": 1,
            "price": 102.0,
            "created_at": 2,
        }
        base.update(overrides)
        return base

    def test_signal_at_last_candle_is_skipped(self):
        # Horizon cannot elapse; the signal is skipped, not resolved early.
        self.assertEqual(
            evaluate_outcomes([self._signal(created_at=9)], self.CANDLES, horizon=3),
            [],
        )

    def test_zero_or_negative_price_is_skipped(self):
        self.assertEqual(
            evaluate_outcomes(
                [self._signal(price=0.0), self._signal(price=-1.0)],
                self.CANDLES,
                horizon=1,
            ),
            [],
        )

    def test_non_positive_horizon_rejected(self):
        for bad in (0, -1):
            with self.subTest(horizon=bad):
                with self.assertRaises(ValueError):
                    evaluate_outcomes([], self.CANDLES, horizon=bad)

    def test_unparseable_timestamp_is_skipped(self):
        self.assertEqual(
            evaluate_outcomes(
                [self._signal(created_at="not-a-date")], self.CANDLES, horizon=1
            ),
            [],
        )

    def test_entry_exactly_at_a_candle_epoch_counts_from_it(self):
        # bisect places epoch-2 at index 2; horizon 1 reads close of index 2.
        (outcome,) = evaluate_outcomes(
            [self._signal(price=100.0)], self.CANDLES, horizon=1
        )
        self.assertEqual(outcome.exit, 102.0)


if __name__ == "__main__":
    unittest.main()
