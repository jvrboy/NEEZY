"""Advanced indicator suite: warmup guards and mathematical properties."""

import math
import unittest

from neezy_backend.indicators import (
    advanced_suite,
    aroon,
    cci,
    choppiness,
    elder_ray,
    fisher_transform,
    ichimoku,
    pivot_points,
    roc,
    trix,
    ultimate_oscillator,
    williams_r,
    zscore,
)


def synthetic(
    count: int = 120, phase: float = 9.0
) -> list[tuple[int, float, float, float, float]]:
    """Valid, deterministic OHLC candles driven by a sine drift."""
    candles = []
    price = 1.10
    for index in range(count):
        drift = math.sin(index / phase) * 0.0015
        open_ = price
        close = price + drift
        high = max(open_, close) + 0.0006
        low = min(open_, close) - 0.0006
        price = close
        candles.append((1700000000 + index * 300, open_, high, low, close))
    return candles


class WarmupTests(unittest.TestCase):
    def test_all_none_on_empty(self):
        suite = advanced_suite([])
        self.assertEqual(suite["candles"], 0)
        self.assertEqual(len(suite["warmup"]), 12)

    def test_short_history_reports_warmup(self):
        suite = advanced_suite(synthetic(20))
        self.assertEqual(suite["candles"], 20)
        self.assertIn("ichimoku", suite["warmup"])

    def test_full_history_no_warmup(self):
        suite = advanced_suite(synthetic(120))
        self.assertEqual(suite["warmup"], [])
        self.assertEqual(len(suite["values"]), 12)

    def test_period_validation(self):
        closes = [float(index) for index in range(30)]
        with self.assertRaises(ValueError):
            cci(closes, closes, closes, period=1)
        with self.assertRaises(ValueError):
            williams_r(closes, closes, closes, period=0)
        with self.assertRaises(ValueError):
            roc(closes, period=0)
        with self.assertRaises(ValueError):
            trix(closes, period=0)
        with self.assertRaises(ValueError):
            choppiness(closes, closes, closes, period=1)
        with self.assertRaises(ValueError):
            fisher_transform(closes, closes, period=1)
        with self.assertRaises(ValueError):
            aroon(closes, closes, period=0)
        with self.assertRaises(ValueError):
            zscore(closes, period=1)


class PropertyTests(unittest.TestCase):
    def setUp(self):
        self.candles = synthetic()
        self.opens = [row[1] for row in self.candles]
        self.highs = [row[2] for row in self.candles]
        self.lows = [row[3] for row in self.candles]
        self.closes = [row[4] for row in self.candles]

    def test_cci_finite_and_bounded_scale(self):
        value = cci(self.highs, self.lows, self.closes)
        self.assertIsInstance(value, float)
        self.assertTrue(math.isfinite(value))
        self.assertGreater(value, -400)
        self.assertLess(value, 400)

    def test_williams_r_range(self):
        for offset in (0, 7, 30):
            value = williams_r(
                self.highs[offset:], self.lows[offset:], self.closes[offset:]
            )
            self.assertIsNotNone(value)
            self.assertGreaterEqual(value, -100.0)
            self.assertLessEqual(value, 0.0)

    def test_williams_r_at_extremes(self):
        # Last close at the period high -> 0; at the low -> -100.
        highs = [2.0] * 14
        lows = [1.0] * 14
        closes_top = [1.0] * 13 + [2.0]
        closes_bottom = [2.0] * 13 + [1.0]
        self.assertAlmostEqual(williams_r(highs, lows, closes_top), 0.0)
        self.assertAlmostEqual(williams_r(highs, lows, closes_bottom), -100.0)

    def test_roc_zero_when_flat(self):
        flat = [1.5] * 30
        self.assertAlmostEqual(roc(flat, 12), 0.0)

    def test_roc_sign_follows_direction(self):
        rising = [1.0 + index * 0.01 for index in range(30)]
        falling = [2.0 - index * 0.01 for index in range(30)]
        self.assertGreater(roc(rising, 12), 0)
        self.assertLess(roc(falling, 12), 0)

    def test_trix_small_for_smooth_series(self):
        self.assertLess(abs(trix(self.closes)), 5.0)

    def test_choppiness_bounds(self):
        value = choppiness(self.highs, self.lows, self.closes)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 100.0)

    def test_fisher_finite(self):
        value = fisher_transform(self.highs, self.lows)
        self.assertTrue(math.isfinite(value))

    def test_ultimate_oscillator_bounds(self):
        value = ultimate_oscillator(self.highs, self.lows, self.closes)
        self.assertIsNotNone(value)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 100.0)

    def test_aroon_extreme_freshness(self):
        # Highest high on the final bar -> up is 100.
        highs = [1.0 + index * 0.1 for index in range(26)]
        lows = [0.5 + index * 0.1 for index in range(26)]
        result = aroon(highs, lows, period=25)
        self.assertAlmostEqual(result["up"], 100.0)
        self.assertLess(result["down"], 100.0)
        self.assertAlmostEqual(result["oscillator"], result["up"] - result["down"])

    def test_ichimoku_cloud_consistency(self):
        result = ichimoku(self.highs, self.lows, self.closes)
        self.assertIn(result["cloud"], {"bullish", "bearish"})
        self.assertIn(result["price_vs_kijun"], {"above", "below"})
        bullish = result["senkou_a"] > result["senkou_b"]
        self.assertEqual(bullish, result["cloud"] == "bullish")

    def test_pivot_symmetry(self):
        result = pivot_points(self.highs, self.lows, self.closes)
        self.assertGreater(result["r1"], result["pp"])
        self.assertLess(result["s1"], result["pp"])
        self.assertGreater(result["r2"], result["r1"])
        self.assertLess(result["s2"], result["s1"])
        # Classic identities: R2 - S2 = 2 x (H - L) and PP = (H+L+C)/3.
        span = result["r2"] - result["s1"] - 2 * (result["pp"] - result["s1"])
        del span
        self.assertAlmostEqual(
            result["r2"] - result["s2"],
            2.0 * (result["r2"] - result["pp"]),
            places=12,
        )
        high, low, close = self.highs[-1], self.lows[-1], self.closes[-1]
        self.assertAlmostEqual(result["pp"], (high + low + close) / 3.0, places=12)

    def test_elder_ray_bracket_price(self):
        result = elder_ray(self.highs, self.lows, self.closes)
        self.assertIsNotNone(result)
        # Bull power is high minus EMA, bear power is low minus EMA.
        self.assertGreater(result["bull_power"], result["bear_power"])

    def test_zscore_range_and_flat(self):
        self.assertLess(abs(zscore(self.closes)), 4.0)
        self.assertAlmostEqual(zscore([1.0] * 25), 0.0)


class SuiteShapeTests(unittest.TestCase):
    def test_suite_contains_every_indicator(self):
        suite = advanced_suite(synthetic())
        self.assertEqual(
            set(suite["values"]),
            {
                "cci",
                "williams_r",
                "roc",
                "trix",
                "choppiness",
                "fisher_transform",
                "ultimate_oscillator",
                "aroon",
                "ichimoku",
                "pivot_points",
                "elder_ray",
                "zscore",
            },
        )

    def test_suite_all_values_present_when_warm(self):
        suite = advanced_suite(synthetic(150))
        self.assertTrue(all(value is not None for value in suite["values"].values()))


if __name__ == "__main__":
    unittest.main()
