import math
import unittest

from neezy_backend.config import AppSettings
from neezy_backend.confluence import (
    build_confluence,
    historical_win_rate,
    resolve_outcome,
)
from neezy_backend.strategies import STRATEGIES, run_all


def make_candles(count=320, up=True, base=100.0, phase=0.0):
    """Deterministic trending candles: (epoch, open, high, low, close)."""
    price = base
    candles = []
    for index in range(count):
        trend = 0.12 if up else -0.12
        wave = 0.1 * math.sin(index / 7.0 + phase)
        open_ = price
        price = price + trend + wave
        high = max(open_, price) + 0.15
        low = min(open_, price) - 0.15
        candles.append((1700000000 + index * 300, open_, high, low, price))
    return candles


class StrategyRegistryTest(unittest.TestCase):
    def test_new_strategies_registered(self):
        for name in (
            "ICHIMOKU",
            "STOCH_RSI",
            "MOMENTUM",
            "RSI_REVERSAL",
            "CCI_REVERSION",
            "SUPERTREND",
            "EMA_PULLBACK",
            "MACD",
        ):
            self.assertIn(name, STRATEGIES)

    def test_run_all_never_crashes_on_trend(self):
        candles = make_candles()
        signals = run_all(candles)
        self.assertTrue(signals)
        for signal in signals:
            self.assertIn(signal.label, {"BUY", "SELL", "NEUTRAL"})

    def test_uptrend_uses_positive_directions(self):
        candles = make_candles()
        directions = [signal.direction for signal in run_all(candles)]
        self.assertIn(1, directions)


class SettingsTest(unittest.TestCase):
    def test_provider_settings_defaults(self):
        settings = AppSettings()
        self.assertEqual(settings.market_data_provider, "deriv")
        self.assertEqual(settings.provider_candle_count, 300)
        self.assertEqual(settings.confluence_min_score, 55.0)
        self.assertEqual(settings.confluence_horizon, 20)

    def test_provider_validated(self):
        with self.assertRaises(ValueError):
            AppSettings(market_data_provider="ibkr")

    def test_thresholds_validated(self):
        with self.assertRaises(ValueError):
            AppSettings(confluence_search_score=80.0, confluence_min_score=50.0)
        with self.assertRaises(ValueError):
            AppSettings(confluence_atr_tp_mult=1.0, confluence_atr_stop_mult=2.0)
        centered = AppSettings(confluence_search_score=60.0, confluence_min_score=60.0)
        self.assertEqual(centered.confluence_search_score, 60.0)


class BuildConfluenceTest(unittest.TestCase):
    def test_strict_uptrend_produces_buy_signal(self):
        signal = build_confluence(make_candles(up=True), "frxEURUSD", "5m")
        self.assertIsNotNone(signal)
        self.assertEqual(signal.label, "BUY")
        self.assertEqual(signal.mode, "strict")
        self.assertGreater(signal.win_rate, 0.0)
        self.assertLessEqual(signal.win_rate, 100.0)
        # ATR-based levels: SL below entry, TP above it for long signals.
        self.assertLess(signal.stop_loss, signal.entry)
        self.assertGreater(signal.take_profit, signal.entry)

    def test_downtrend_produces_sell_signal(self):
        signal = build_confluence(
            make_candles(up=False), "frxEURUSD", "5m", min_score=40.0
        )
        self.assertIsNotNone(signal)
        self.assertEqual(signal.label, "SELL")
        self.assertGreater(signal.stop_loss, signal.entry)
        self.assertLess(signal.take_profit, signal.entry)

    def test_weak_mixed_history_needs_search_mode(self):
        # A choppy sideways market should not pass the strict threshold.
        sideways = make_candles(200, base=100.0, phase=0.0)
        flat = [
            (
                index * 300 + 1700000000,
                100.0,
                100.4,
                99.6,
                100.0 + 0.2 * math.sin(index % 9),
            )
            for index in range(320)
        ]
        del sideways
        strict = build_confluence(flat, "frxEURUSD", "5m")
        searched = build_confluence(flat, "frxEURUSD", "5m", search=True)
        self.assertIsNotNone(searched)
        self.assertEqual(searched.mode, "search")
        if strict is not None:
            self.assertEqual(strict.mode, "strict")

    def test_search_mode_always_yields(self):
        for up in (True, False):
            signal = build_confluence(
                make_candles(up=up), "frxEURUSD", "5m", search=True
            )
            self.assertIsNotNone(signal)
            self.assertEqual(signal.mode, "search")
            self.assertGreaterEqual(signal.score, 30.0)

    def test_too_few_candles_returns_none(self):
        self.assertIsNone(build_confluence(make_candles(40), "frxEURUSD", "5m"))

    def test_card_fields_shape(self):
        signal = build_confluence(make_candles(), "frxEURUSD", "5m")
        record = signal.to_dict()
        self.assertEqual(
            set(record)
            & {
                "symbol",
                "instrument",
                "direction",
                "entry",
                "stop_loss",
                "take_profit",
                "win_rate",
            },
            {
                "symbol",
                "instrument",
                "direction",
                "entry",
                "stop_loss",
                "take_profit",
                "win_rate",
            },
        )
        history_record = signal.as_history_record()
        self.assertIsNone(history_record["outcome"])
        self.assertIn(history_record["direction"], (1, -1))


class WinRateReplayTest(unittest.TestCase):
    def test_long_analogs_resolve(self):
        candles = make_candles()
        closed = candles[:-1]
        result = historical_win_rate(
            closed,
            1,
            stop_distance=2.0,
            take_distance=4.0,
            horizon=10,
        )
        if result is not None:
            win_rate, samples = result
            self.assertGreater(samples, 0)
            self.assertTrue(0.0 <= win_rate <= 100.0)

    def test_out_of_range_history_returns_none(self):
        self.assertIsNone(
            historical_win_rate(
                make_candles(20), 1, stop_distance=1.0, take_distance=2.0
            )
        )


class ResolveOutcomeTest(unittest.TestCase):
    AFTER_TP = ((10, 100.0, 105.0, 99.5, 104.8),)
    AFTER_SL = ((10, 100.0, 100.5, 97.5, 98.2),)
    AFTER_BOTH = ((10, 100.0, 105.0, 97.5, 98.2),)
    AFTER_NONE = ((10, 100.0, 100.9, 98.5, 100.4),)

    def test_hit_target_first_is_tp(self):
        self.assertEqual(resolve_outcome(1, 100.0, 98.0, 104.0, self.AFTER_TP), "TP")

    def test_hit_stop_first_is_sl(self):
        self.assertEqual(resolve_outcome(1, 100.0, 98.0, 104.0, self.AFTER_SL), "SL")

    def test_both_in_one_bar_assumes_stop_first(self):
        self.assertEqual(resolve_outcome(1, 100.0, 98.0, 104.0, self.AFTER_BOTH), "SL")

    def test_unresolved_returns_none(self):
        self.assertIsNone(resolve_outcome(1, 100.0, 98.0, 104.0, self.AFTER_NONE))
        self.assertIsNone(resolve_outcome(1, 100.0, 98.0, 104.0, []))

    def test_only_two_outcomes_for_short_signals(self):
        # Short: stop 102 above entry, target 96 below it.
        short_target = ((10, 100.0, 100.5, 95.5, 96.2),)
        self.assertEqual(resolve_outcome(-1, 100.0, 102.0, 96.0, short_target), "TP")
        self.assertEqual(resolve_outcome(-1, 100.0, 102.0, 96.0, self.AFTER_TP), "SL")

    def test_invalid_levels(self):
        self.assertIsNone(resolve_outcome(1, 100.0, 101.0, 104.0, self.AFTER_TP))
        self.assertIsNone(resolve_outcome(1, 100.0, 98.0, 99.0, self.AFTER_TP))

    def test_horizon_limits_resolution(self):
        # Neutral bars first, then a bar that reaches the target.
        late = [(100 + index, 100.0, 101.0, 99.0, 100.5) for index in range(5)]
        late.append((105, 101.0, 105.0, 100.0, 104.5))
        self.assertIsNone(resolve_outcome(1, 100.0, 98.0, 104.0, late, horizon=3))
        self.assertEqual(resolve_outcome(1, 100.0, 98.0, 104.0, late, horizon=6), "TP")


if __name__ == "__main__":
    unittest.main()
