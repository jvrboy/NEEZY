"""The decision cache must change speed only, never results."""

from __future__ import annotations

import random
import unittest

from neezy_backend.backtest import (
    BacktestConfig,
    build_decision_cache,
    run_backtest,
)


def _walk(count: int, seed: int = 11) -> list[tuple[float, ...]]:
    rng = random.Random(seed)
    candles = []
    price = 1.1
    for index in range(count):
        open_ = price
        close = open_ * (1 + rng.gauss(0.0, 0.0008))
        high = max(open_, close) * (1 + abs(rng.gauss(0, 0.0003)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, 0.0003)))
        candles.append((index * 60, open_, high, low, close))
        price = close
    return candles


class DecisionCacheTests(unittest.TestCase):
    def test_cached_results_match_uncached_across_a_grid(self) -> None:
        candles = _walk(900)
        cache = build_decision_cache(candles)
        grid = [
            BacktestConfig(min_score=score, stop_atr_multiple=stop, reward_to_risk=rr)
            for score in (2, 3)
            for stop in (1.0, 1.5)
            for rr in (1.5, 2.5)
        ]
        for config in grid:
            with self.subTest(config=config):
                plain = run_backtest(candles, config).to_dict()
                cached = run_backtest(candles, config, cache=cache).to_dict()
                self.assertEqual(plain, cached)

    def test_cache_must_match_candles_and_lookback(self) -> None:
        candles = _walk(300)
        cache = build_decision_cache(candles, lookback=100)
        with self.assertRaises(ValueError):
            run_backtest(candles, BacktestConfig(lookback=200), cache=cache)
        with self.assertRaises(ValueError):
            run_backtest(candles[:250], BacktestConfig(lookback=100), cache=cache)
        with self.assertRaises(ValueError):
            build_decision_cache(candles, lookback=10)


if __name__ == "__main__":
    unittest.main()
