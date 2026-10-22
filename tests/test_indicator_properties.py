"""Property-based tests for the indicator math (roadmap update #37).

Every property is exercised across pseudo-random OHLC series built from
fixed seeds (1..25) with the stdlib ``random.Random`` generator only, so the
suite stays offline and deterministic.  The tests pin the CURRENT contracts
of ``neezy_backend.indicators``: invariants that floating point can only
hold up to rounding noise carry explicit tolerances, and genuine quirks are
flagged with ``# NOTE: known quirk`` comments.
"""

from __future__ import annotations

import math
import random
import unittest
from itertools import pairwise
from typing import ClassVar

from neezy_backend.indicators import (
    adx,
    analyze,
    atr,
    bollinger,
    ema,
    macd_histogram_series,
    rsi,
    rsi_series,
    sma,
    stochastic,
)

SEEDS = tuple(range(1, 26))
PERIODS = (1, 2, 3, 5, 10, 20, 50)
Candle = tuple[int, float, float, float, float]


def random_closes(
    length: int, seed: int, *, vol: float = 0.01, start: float = 1.0
) -> list[float]:
    """Seeded geometric random walk of close prices, strictly positive."""
    rng = random.Random(seed)
    price = start
    closes: list[float] = []
    for _ in range(length):
        price = max(price * (1.0 + rng.gauss(0.0, vol)), 0.01)
        closes.append(price)
    return closes


def random_candles(
    count: int, seed: int, *, vol: float = 0.01, start: float = 1.0
) -> list[Candle]:
    """Seeded random-walk candles with self-consistent OHLC, oldest first."""
    rng = random.Random(seed)
    price = start
    rows: list[Candle] = []
    for index in range(count):
        open_ = price
        close = max(open_ * (1.0 + rng.gauss(0.0, vol)), 0.01)
        high = max(open_, close) * (1.0 + abs(rng.gauss(0.0, vol / 3.0)))
        low = min(open_, close) * (1.0 - abs(rng.gauss(0.0, vol / 3.0)))
        rows.append((index * 60, open_, high, low, close))
        price = close
    return rows


def monotone_closes(
    length: int, seed: int, *, descending: bool = False, start: float = 5.0
) -> list[float]:
    """Seeded strictly monotone closes with steps far above rounding noise."""
    rng = random.Random(seed)
    price = start
    values: list[float] = []
    for _ in range(length):
        price += rng.uniform(0.001, 0.01) * (-1.0 if descending else 1.0)
        values.append(price)
    return values


def trending_candles(
    count: int, *, step: float = 0.001, start: float = 2.0, rising: bool = True
) -> list[Candle]:
    """Strictly monotone candles whose highs/lows touch open/close exactly.

    ``start`` sits high enough that a falling series stays positive.
    """
    rows: list[Candle] = []
    previous = start
    for index in range(count):
        close = start + (index + 1) * step * (1.0 if rising else -1.0)
        rows.append(
            (index * 60, previous, max(previous, close), min(previous, close), close)
        )
        previous = close
    return rows


def flat_candles(count: int, *, price: float = 1.0) -> list[Candle]:
    """Candles where every OHLC field equals the same price."""
    return [(index * 60, price, price, price, price) for index in range(count)]


def spiked_candles(count: int, seed: int, *, factor: float = 50.0) -> list[Candle]:
    """Random walk with the midpoint candle scaled up by ``factor``."""
    rows = random_candles(count, seed)
    middle = count // 2
    stamp, open_, high, low, close = rows[middle]
    rows[middle] = (stamp, open_ * factor, high * factor, low * factor, close * factor)
    return rows


def hlcs(candles: list[Candle]) -> tuple[list[float], list[float], list[float]]:
    """Split candles into parallel high, low, and close sequences."""
    return (
        [row[2] for row in candles],
        [row[3] for row in candles],
        [row[4] for row in candles],
    )


def true_ranges(
    highs: list[float], lows: list[float], closes: list[float]
) -> list[float]:
    """Manual true-range list matching the indicator definition."""
    ranges = [highs[0] - lows[0]]
    for index in range(1, len(closes)):
        ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    return ranges


def expected_rsi(average_gain: float, average_loss: float) -> float:
    """Reference RSI from averaged gains/losses (Wilder conventions)."""
    if average_gain == 0 and average_loss == 0:
        return 50.0
    if average_loss == 0:
        return 100.0
    if average_gain == 0:
        return 0.0
    return 100.0 - 100.0 / (1.0 + average_gain / average_loss)


class IndicatorTestCase(unittest.TestCase):
    """Shared assertions sized for double-precision rounding noise."""

    def assertBetween(self, value: float, low: float, high: float) -> None:
        """Assert ``value`` lies in ``[low, high]`` up to rounding slack."""
        slack = 1e-9 * max(1.0, abs(low), abs(high))
        self.assertGreaterEqual(value, low - slack)
        self.assertLessEqual(value, high + slack)

    def assertCloseTo(self, actual: float, expected: float) -> None:
        """Assert equality up to double-precision rounding noise."""
        self.assertAlmostEqual(actual, expected, delta=1e-9 * max(1.0, abs(expected)))

    def assertAllFinite(self, values: list[float]) -> None:
        """Assert every value in the list is a finite float."""
        for value in values:
            self.assertTrue(math.isfinite(value), f"non-finite value: {value!r}")


class EmaPropertyTests(IndicatorTestCase):
    """Properties of ``indicators.ema``."""

    def test_output_length_matches_input_length(self) -> None:
        """EMA returns exactly one output per input value, including empty."""
        for seed in SEEDS:
            rng = random.Random(1000 + seed)
            lengths = [0, 1] + [rng.randint(2, 300) for _ in range(3)]
            for length in lengths:
                values = random_closes(length, seed)
                for period in PERIODS:
                    with self.subTest(seed=seed, length=length, period=period):
                        self.assertEqual(len(ema(values, period)), length)

    def test_output_stays_within_input_bounds(self) -> None:
        """Every EMA value is a convex combination of the inputs."""
        for seed in SEEDS:
            values = random_closes(300, seed)
            low, high = min(values), max(values)
            for period in PERIODS:
                for value in ema(values, period):
                    self.assertBetween(value, low, high)

    def test_long_series_stays_within_input_bounds(self) -> None:
        """The bounds property also holds at the 5000-bar scale cap."""
        for seed in SEEDS:
            values = random_closes(5000, seed)
            low, high = min(values), max(values)
            for period in (2, 14, 50):
                for value in ema(values, period):
                    self.assertBetween(value, low, high)

    def test_constant_series_is_fixed_point(self) -> None:
        """EMA of a constant series stays at that constant."""
        # NOTE: known quirk — for awkward constants the recurrence wobbles by
        # about one ulp (123.456 drifts ~1.4e-14), so equality is approximate.
        for constant in (1.0, 1.5, 0.1, 123.456):
            for period in (2, 3, 5, 14, 20):
                result = ema([constant] * 200, period)
                for value in result:
                    self.assertCloseTo(value, constant)

    def test_first_output_echoes_first_input(self) -> None:
        """The EMA is seeded with the first input value."""
        for seed in SEEDS:
            values = random_closes(50, seed)
            for period in (2, 5, 20):
                with self.subTest(seed=seed, period=period):
                    self.assertEqual(ema(values, period)[0], values[0])

    def test_period_one_echoes_input_exactly(self) -> None:
        """With alpha = 1 the EMA degenerates to the raw series."""
        for seed in SEEDS:
            values = random_closes(100, seed)
            self.assertEqual(ema(values, 1), values)

    def test_matches_recurrence_formula(self) -> None:
        """Outputs follow result[i] = alpha * v[i] + (1 - alpha) * result[i-1]."""
        for seed in SEEDS:
            values = random_closes(120, seed)
            for period in (2, 5, 20):
                alpha = 2.0 / (period + 1.0)
                expected = [float(values[0])]
                for value in values[1:]:
                    expected.append(value * alpha + expected[-1] * (1.0 - alpha))
                for got, want in zip(ema(values, period), expected, strict=True):
                    self.assertCloseTo(got, want)

    def test_non_decreasing_input_yields_non_decreasing_output(self) -> None:
        """EMA preserves upward order for every period."""
        for seed in SEEDS:
            values = monotone_closes(300, seed)
            for period in (2, 5, 14, 50):
                for previous, current in pairwise(ema(values, period)):
                    self.assertLessEqual(previous, current)

    def test_non_increasing_input_yields_non_increasing_output(self) -> None:
        """EMA preserves downward order for every period."""
        for seed in SEEDS:
            values = monotone_closes(300, seed, descending=True)
            for period in (2, 5, 14, 50):
                for previous, current in pairwise(ema(values, period)):
                    self.assertGreaterEqual(previous, current)

    def test_step_response_converges_faster_for_shorter_periods(self) -> None:
        """After a level jump, short-period EMAs sit closer to the new level."""
        step = [0.0] * 60 + [1.0] * 60
        fast2, fast5 = ema(step, 2)[-1], ema(step, 5)[-1]
        mid, slow = ema(step, 20)[-1], ema(step, 50)[-1]
        self.assertGreaterEqual(fast2, 0.999)
        self.assertGreaterEqual(fast2, fast5)
        self.assertGreater(fast5, mid)
        self.assertGreater(mid, slow)
        self.assertGreater(slow, 0.5)
        self.assertLess(mid, 1.0)
        self.assertLess(slow, 1.0)

    def test_single_value_edge(self) -> None:
        """A one-element series yields exactly that element."""
        for period in (1, 2, 5, 20):
            with self.subTest(period=period):
                self.assertEqual(ema([7.25], period), [7.25])

    def test_empty_input_returns_empty_list(self) -> None:
        """An empty series yields an empty EMA (no error, no padding)."""
        for period in (1, 2, 5, 20):
            with self.subTest(period=period):
                self.assertEqual(ema([], period), [])

    def test_non_positive_period_raises(self) -> None:
        """Periods below one are rejected with ValueError."""
        for period in (0, -1, -14):
            with self.subTest(period=period), self.assertRaises(ValueError):
                ema([1.0, 2.0, 3.0], period)


class SmaPropertyTests(IndicatorTestCase):
    """Properties of ``indicators.sma``."""

    def test_output_length_matches_input_length(self) -> None:
        """SMA returns exactly one slot per input value, including empty."""
        for seed in SEEDS:
            rng = random.Random(2000 + seed)
            lengths = [0, 1] + [rng.randint(2, 300) for _ in range(3)]
            for length in lengths:
                values = random_closes(length, seed)
                for period in (1, 2, 5, 20, 50):
                    with self.subTest(seed=seed, length=length, period=period):
                        self.assertEqual(len(sma(values, period)), length)

    def test_warmup_prefix_is_none_then_floats(self) -> None:
        """Exactly period-1 leading Nones, then floats, once warmed up."""
        values = random_closes(60, 3)
        for period in (1, 2, 5, 14, 20):
            result = sma(values, period)
            with self.subTest(period=period):
                self.assertTrue(all(v is None for v in result[: period - 1]))
                self.assertTrue(all(v is not None for v in result[period - 1 :]))

    def test_series_shorter_than_period_is_all_none(self) -> None:
        """Without a full window the SMA never forms a value."""
        for length, period in ((0, 3), (1, 3), (2, 3), (4, 5), (19, 20)):
            with self.subTest(length=length, period=period):
                expected = [None] * length
                self.assertEqual(sma(random_closes(length, 4), period), expected)

    def test_formed_values_stay_within_input_bounds(self) -> None:
        """Every formed mean lies between the global min and max."""
        for seed in SEEDS:
            values = random_closes(300, seed)
            low, high = min(values), max(values)
            for period in (2, 5, 20, 50):
                for value in sma(values, period):
                    if value is not None:
                        self.assertBetween(value, low, high)

    def test_formed_values_match_window_means(self) -> None:
        """Each formed value equals the mean of the trailing window."""
        for seed in SEEDS:
            values = random_closes(120, seed)
            for period in (2, 5, 20):
                result = sma(values, period)
                for index in range(period - 1, len(values)):
                    window = values[index - period + 1 : index + 1]
                    self.assertCloseTo(result[index], sum(window) / period)

    def test_flat_series_yields_flat_average(self) -> None:
        """A constant series averages to the same constant."""
        # NOTE: known quirk — the running-sum accumulator wobbles by one ulp
        # for awkward constants, so equality is approximate.
        for constant in (1.0, 1.5, 0.1, 123.456):
            for period in (2, 3, 5, 20):
                result = sma([constant] * 200, period)
                for value in result:
                    if value is not None:
                        self.assertCloseTo(value, constant)

    def test_period_one_tracks_input(self) -> None:
        """With period one the SMA follows the input bar by bar."""
        # NOTE: known quirk — unlike ema(v, 1), the accumulator can wobble a
        # single ulp (0.1 + 0.2 - 0.1 -> 0.20000000000000004), so approximate.
        for seed in SEEDS:
            values = random_closes(100, seed)
            result = sma(values, 1)
            for got, want in zip(result, values, strict=True):
                self.assertCloseTo(got, want)

    def test_non_decreasing_input_yields_non_decreasing_output(self) -> None:
        """Sliding windows over rising data produce rising averages."""
        for seed in SEEDS:
            values = monotone_closes(300, seed)
            for period in (2, 5, 20):
                formed = [v for v in sma(values, period) if v is not None]
                for previous, current in pairwise(formed):
                    self.assertLessEqual(previous, current)

    def test_single_value_edge(self) -> None:
        """Length-one input: [x] for period 1, [None] for longer periods."""
        self.assertEqual(sma([7.25], 1), [7.25])
        self.assertEqual(sma([7.25], 2), [None])

    def test_non_positive_period_raises(self) -> None:
        """Periods below one are rejected with ValueError."""
        for period in (0, -5):
            with self.subTest(period=period), self.assertRaises(ValueError):
                sma([1.0, 2.0], period)


class RsiPropertyTests(IndicatorTestCase):
    """Properties of ``indicators.rsi`` and ``indicators.rsi_series``."""

    def test_output_length_matches_input_length(self) -> None:
        """rsi_series returns one slot per close, including empty input."""
        for seed in SEEDS:
            rng = random.Random(3000 + seed)
            lengths = [0, 1] + [rng.randint(2, 120) for _ in range(3)]
            for length in lengths:
                closes = random_closes(length, seed)
                for period in (1, 2, 5, 14):
                    with self.subTest(seed=seed, length=length, period=period):
                        self.assertEqual(len(rsi_series(closes, period)), length)

    def test_warmup_prefix_is_none_then_floats(self) -> None:
        """The first ``period`` slots are None; later slots hold floats."""
        closes = random_closes(60, 3)
        for period in (1, 2, 5, 14):
            result = rsi_series(closes, period)
            with self.subTest(period=period):
                self.assertTrue(all(v is None for v in result[:period]))
                self.assertTrue(all(v is not None for v in result[period:]))

    def test_series_not_longer_than_period_is_all_none(self) -> None:
        """Without period+1 closes no RSI value ever forms."""
        for length, period in ((0, 3), (1, 3), (2, 3), (3, 3), (13, 14)):
            with self.subTest(length=length, period=period):
                expected = [None] * length
                self.assertEqual(rsi_series(random_closes(length, 4), period), expected)

    def test_period_plus_one_forms_exactly_one_value(self) -> None:
        """The first formable length yields a single value at index period."""
        period = 9
        closes = random_closes(period + 1, 5)
        result = rsi_series(closes, period)
        self.assertTrue(all(v is None for v in result[:period]))
        self.assertIsNotNone(result[period])
        self.assertEqual(rsi(closes, period), result[period])

    def test_values_stay_within_zero_to_hundred(self) -> None:
        """Wilder RSI is bounded to [0, 100] on random walks."""
        for seed in SEEDS:
            closes = random_closes(300, seed)
            for period in (2, 5, 14):
                for value in rsi_series(closes, period):
                    if value is not None:
                        self.assertBetween(value, 0.0, 100.0)

    def test_all_up_series_pins_at_one_hundred(self) -> None:
        """Every formed RSI of a strictly rising series is exactly 100."""
        for seed in SEEDS:
            closes = monotone_closes(80, seed)
            formed = [v for v in rsi_series(closes, 14) if v is not None]
            self.assertTrue(formed)
            for value in formed:
                self.assertEqual(value, 100.0)

    def test_all_down_series_pins_at_zero(self) -> None:
        """Every formed RSI of a strictly falling series is exactly 0."""
        for seed in SEEDS:
            closes = monotone_closes(80, seed, descending=True)
            formed = [v for v in rsi_series(closes, 14) if v is not None]
            self.assertTrue(formed)
            for value in formed:
                self.assertEqual(value, 0.0)

    def test_constant_series_pins_at_fifty(self) -> None:
        """No movement at all maps to the neutral 50 convention."""
        for constant in (1.0, 1.5, 0.1, 123.456):
            result = rsi_series([constant] * 40, 14)
            self.assertTrue(all(v is None for v in result[:14]))
            for value in result[14:]:
                self.assertEqual(value, 50.0)

    def test_rsi_helper_returns_last_value_or_none(self) -> None:
        """rsi() is the last slot: None for empty or unformed series."""
        self.assertIsNone(rsi([]))
        self.assertIsNone(rsi([1.0]))
        self.assertIsNone(rsi([1.0] * 14))
        formed = rsi_series([1.0] * 15, 14)
        self.assertEqual(rsi([1.0] * 15, 14), formed[-1])

    def test_matches_wilder_recurrence(self) -> None:
        """Values follow Wilder seeding then smoothed gains and losses."""
        period = 9
        for seed in SEEDS:
            closes = random_closes(80, seed)
            result = rsi_series(closes, period)
            gains = losses = 0.0
            for before, after in pairwise(closes[: period + 1]):
                delta = after - before
                gains += max(delta, 0.0)
                losses += max(-delta, 0.0)
            average_gain, average_loss = gains / period, losses / period
            for index in range(period, len(closes)):
                expected = expected_rsi(average_gain, average_loss)
                self.assertCloseTo(result[index], expected)
                if index + 1 < len(closes):
                    delta = closes[index + 1] - closes[index]
                    average_gain = (
                        average_gain * (period - 1) + max(delta, 0.0)
                    ) / period
                    average_loss = (
                        average_loss * (period - 1) + max(-delta, 0.0)
                    ) / period

    def test_non_positive_period_raises(self) -> None:
        """Periods below one are rejected with ValueError."""
        for period in (0, -2):
            with self.subTest(period=period), self.assertRaises(ValueError):
                rsi_series([1.0, 2.0], period)


class MacdPropertyTests(IndicatorTestCase):
    """Properties of ``indicators.macd_histogram_series``."""

    def test_output_length_matches_input_length(self) -> None:
        """The histogram aligns one-to-one with the closes."""
        for seed in SEEDS:
            rng = random.Random(4000 + seed)
            lengths = [0, 1] + [rng.randint(2, 300) for _ in range(3)]
            for length in lengths:
                closes = random_closes(length, seed)
                with self.subTest(seed=seed, length=length):
                    self.assertEqual(len(macd_histogram_series(closes)), length)

    def test_outputs_are_finite(self) -> None:
        """Line minus signal never produces NaN or infinity."""
        for seed in SEEDS:
            histogram = macd_histogram_series(random_closes(300, seed))
            self.assertAllFinite(histogram)

    def test_custom_periods_keep_length_contract(self) -> None:
        """Non-default fast/slow/signal periods still align by bar."""
        for seed in SEEDS:
            closes = random_closes(200, seed)
            for fast, slow, signal in ((2, 5, 2), (5, 20, 5), (8, 34, 9)):
                histogram = macd_histogram_series(closes, fast, slow, signal)
                with self.subTest(seed=seed, fast=fast, slow=slow, signal=signal):
                    self.assertEqual(len(histogram), len(closes))
                    self.assertAllFinite(histogram)

    def test_histogram_matches_ema_composition(self) -> None:
        """Histogram == (fast EMA - slow EMA) - EMA(line, signal)."""
        for seed in SEEDS:
            closes = random_closes(200, seed)
            line = [
                a - b for a, b in zip(ema(closes, 12), ema(closes, 26), strict=True)
            ]
            signal_line = ema(line, 9)
            expected = [a - b for a, b in zip(line, signal_line, strict=True)]
            for got, want in zip(macd_histogram_series(closes), expected, strict=True):
                self.assertCloseTo(got, want)

    def test_constant_series_histogram_is_zero(self) -> None:
        """Constant closes give a zero MACD line, signal, and histogram."""
        # NOTE: known quirk — awkward constants leave ~1e-14 residue from the
        # EMA recurrence, so the zero is asserted with rounding tolerance.
        for constant in (1.0, 1.5, 0.1, 123.456):
            histogram = macd_histogram_series([constant] * 300)
            for value in histogram:
                self.assertCloseTo(value, 0.0)

    def test_single_close_gives_zero_histogram(self) -> None:
        """One close makes fast and slow EMAs equal, so the histogram is 0."""
        self.assertEqual(macd_histogram_series([7.25]), [0.0])

    def test_monotone_input_signs_the_macd_line(self) -> None:
        """Rallies keep the fast EMA at or above the slow EMA, slides below."""
        for seed in SEEDS:
            rising = monotone_closes(300, seed)
            line = [
                a - b for a, b in zip(ema(rising, 12), ema(rising, 26), strict=True)
            ]
            for value in line:
                self.assertGreaterEqual(value, -1e-9)
            falling = monotone_closes(300, seed, descending=True)
            line = [
                a - b for a, b in zip(ema(falling, 12), ema(falling, 26), strict=True)
            ]
            for value in line:
                self.assertLessEqual(value, 1e-9)

    def test_linear_ramp_keeps_histogram_non_negative(self) -> None:
        """A constant-step rally leaves the histogram at or above zero.

        Random-step rallies can decelerate, which legitimately sags the line
        below its own signal, so the ramp here keeps a constant step.
        """
        ramp = [1.0 + 0.001 * index for index in range(300)]
        for value in macd_histogram_series(ramp):
            self.assertGreaterEqual(value, -1e-9)

    def test_invalid_periods_raise(self) -> None:
        """Non-positive periods or fast >= slow are rejected."""
        closes = [1.0, 2.0, 3.0]
        for kwargs in (
            {"fast": 0},
            {"slow": 0},
            {"signal": 0},
            {"fast": -1},
            {"fast": 26, "slow": 26},
            {"fast": 30, "slow": 26},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                macd_histogram_series(closes, **kwargs)


class AtrPropertyTests(IndicatorTestCase):
    """Properties of ``indicators.atr``."""

    def test_non_negative_and_finite(self) -> None:
        """True ranges are non-negative, so their average is too."""
        for seed in SEEDS:
            highs, lows, closes = hlcs(random_candles(200, seed))
            for period in (1, 5, 14, 50):
                value = atr(highs, lows, closes, period)
                with self.subTest(seed=seed, period=period):
                    self.assertIsNotNone(value)
                    self.assertGreaterEqual(value, 0.0)
                    self.assertTrue(math.isfinite(value))

    def test_stays_within_true_range_bounds(self) -> None:
        """The Wilder average never leaves [min TR, max TR]."""
        for seed in SEEDS:
            highs, lows, closes = hlcs(random_candles(200, seed))
            ranges = true_ranges(highs, lows, closes)
            for period in (5, 14, 50):
                value = atr(highs, lows, closes, period)
                self.assertBetween(value, min(ranges), max(ranges))

    def test_matches_wilder_recurrence(self) -> None:
        """Seeded simple average of the first period TRs, then smoothing."""
        period = 14
        for seed in SEEDS:
            highs, lows, closes = hlcs(random_candles(150, seed))
            ranges = true_ranges(highs, lows, closes)
            average = sum(ranges[:period]) / period
            for current in ranges[period:]:
                average = (average * (period - 1) + current) / period
            self.assertCloseTo(atr(highs, lows, closes, period), average)

    def test_flat_candles_yield_zero(self) -> None:
        """No range anywhere means exactly zero ATR."""
        highs, lows, closes = hlcs(flat_candles(60))
        for period in (1, 5, 14, 50):
            with self.subTest(period=period):
                self.assertEqual(atr(highs, lows, closes, period), 0.0)

    def test_single_candle_is_high_minus_low(self) -> None:
        """With one candle the ATR is just its high minus its low."""
        self.assertEqual(atr([1.5], [1.0], [1.25]), 0.5)
        self.assertCloseTo(atr([1.2], [1.0], [1.1]), 1.2 - 1.0)

    def test_mismatched_or_empty_inputs_return_none(self) -> None:
        """Length mismatches and empty input are None, not errors."""
        self.assertIsNone(atr([], [], []))
        self.assertIsNone(atr([1.0], [], [1.0]))
        self.assertIsNone(atr([1.0], [1.0], [1.0, 2.0]))
        self.assertIsNone(atr([1.0, 2.0], [1.0], [1.0, 2.0]))

    def test_non_positive_period_raises(self) -> None:
        """Periods below one are rejected with ValueError."""
        for period in (0, -3):
            with self.subTest(period=period), self.assertRaises(ValueError):
                atr([1.0], [1.0], [1.0], period)

    def test_inverted_first_bar_can_return_negative(self) -> None:
        """ATR trusts caller OHLC: high < low on bar zero goes negative."""
        # NOTE: known quirk — unlike analyze(), atr() does not validate candle
        # consistency, so an inverted first bar yields a negative "range".
        self.assertEqual(atr([1.0], [2.0], [1.5]), -1.0)


class BollingerPropertyTests(IndicatorTestCase):
    """Properties of ``indicators.bollinger``."""

    def test_band_ordering_and_finiteness(self) -> None:
        """upper >= middle >= lower, with finite %B and bandwidth."""
        for seed in SEEDS:
            bands = bollinger(random_closes(100, seed))
            self.assertIsNotNone(bands)
            for key in ("upper", "middle", "lower", "percent_b", "bandwidth"):
                self.assertIn(key, bands)
                self.assertTrue(math.isfinite(bands[key]))
            self.assertGreaterEqual(bands["upper"], bands["middle"])
            self.assertGreaterEqual(bands["middle"], bands["lower"])
            self.assertGreaterEqual(bands["bandwidth"], 0.0)

    def test_middle_is_the_window_mean(self) -> None:
        """middle equals the plain mean of the last ``period`` closes."""
        for seed in SEEDS:
            closes = random_closes(100, seed)
            for period in (5, 20, 50):
                bands = bollinger(closes, period)
                window = closes[-period:]
                with self.subTest(seed=seed, period=period):
                    self.assertCloseTo(bands["middle"], sum(window) / period)
                    self.assertBetween(bands["middle"], min(window), max(window))

    def test_bands_are_symmetric_around_middle(self) -> None:
        """upper - middle equals middle - lower (same deviation multiple)."""
        for seed in SEEDS:
            bands = bollinger(random_closes(100, seed))
            upper_gap = bands["upper"] - bands["middle"]
            lower_gap = bands["middle"] - bands["lower"]
            self.assertCloseTo(upper_gap, lower_gap)

    def test_flat_series_collapses_to_the_middle(self) -> None:
        """Flat closes pinch the bands: %B 0.5 and zero bandwidth."""
        bands = bollinger([1.5] * 20)
        self.assertEqual(bands["upper"], 1.5)
        self.assertEqual(bands["middle"], 1.5)
        self.assertEqual(bands["lower"], 1.5)
        self.assertEqual(bands["percent_b"], 0.5)
        self.assertEqual(bands["bandwidth"], 0.0)
        # NOTE: known quirk — for awkward constants the window mean wobbles by
        # one ulp, so width is tiny-but-nonzero and %B lands on a rounding
        # artifact (0.25 or 0.75) instead of taking the exact 0.5 branch.
        wobbly = bollinger([123.456] * 20)
        self.assertCloseTo(wobbly["upper"], 123.456)
        self.assertCloseTo(wobbly["lower"], 123.456)
        self.assertLess(abs(wobbly["bandwidth"]), 1e-12)
        self.assertBetween(wobbly["percent_b"], 0.0, 1.0)

    def test_monotone_extension_never_lowers_middle(self) -> None:
        """Appending ever-higher closes never drags the middle down."""
        for seed in SEEDS:
            closes = random_closes(60, seed)
            previous_middle = bollinger(closes, 20)["middle"]
            for extra in range(1, 31):
                grown = [*closes, closes[-1] + 0.1 * extra]
                middle = bollinger(grown, 20)["middle"]
                self.assertGreaterEqual(middle, previous_middle)
                previous_middle = middle

    def test_short_input_returns_none(self) -> None:
        """Fewer closes than the period returns None, including empty."""
        self.assertIsNone(bollinger([], 20))
        self.assertIsNone(bollinger([1.0], 20))
        self.assertIsNone(bollinger(random_closes(19, 6), 20))
        self.assertIsNotNone(bollinger(random_closes(20, 6), 20))

    def test_invalid_parameters_raise(self) -> None:
        """period < 2 and deviations <= 0 are rejected."""
        closes = [1.0] * 25
        for kwargs in (
            {"period": 1},
            {"period": 0},
            {"deviations": 0.0},
            {"deviations": -2.0},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                bollinger(closes, **kwargs)


class StochasticPropertyTests(IndicatorTestCase):
    """Properties of ``indicators.stochastic``."""

    def test_k_and_d_stay_within_zero_to_hundred(self) -> None:
        """%K and %D are percentages for well-formed candles."""
        for seed in SEEDS:
            highs, lows, closes = hlcs(random_candles(200, seed))
            for period, smooth in ((14, 3), (5, 1), (20, 5)):
                result = stochastic(highs, lows, closes, period, smooth)
                with self.subTest(seed=seed, period=period, smooth=smooth):
                    self.assertIsNotNone(result)
                    self.assertBetween(result["k"], 0.0, 100.0)
                    self.assertBetween(result["d"], 0.0, 100.0)

    def test_flat_candles_pin_at_fifty(self) -> None:
        """Zero-span windows resolve to the neutral 50 convention."""
        highs, lows, closes = hlcs(flat_candles(60))
        result = stochastic(highs, lows, closes)
        self.assertEqual(result["k"], 50.0)
        self.assertEqual(result["d"], 50.0)

    def test_rising_candles_pin_at_one_hundred(self) -> None:
        """Closes ending on the window high read fully overbought."""
        highs, lows, closes = hlcs(trending_candles(60))
        result = stochastic(highs, lows, closes)
        self.assertEqual(result["k"], 100.0)
        self.assertEqual(result["d"], 100.0)

    def test_falling_candles_pin_at_zero(self) -> None:
        """Closes ending on the window low read fully oversold."""
        highs, lows, closes = hlcs(trending_candles(60, rising=False))
        result = stochastic(highs, lows, closes)
        self.assertEqual(result["k"], 0.0)
        self.assertEqual(result["d"], 0.0)

    def test_short_or_mismatched_inputs_return_none(self) -> None:
        """Not enough bars or mismatched lengths return None."""
        self.assertIsNone(stochastic([], [], []))
        self.assertIsNone(stochastic([1.0], [1.0], [1.0]))
        self.assertIsNone(stochastic([1.0] * 15, [1.0] * 15, [1.0] * 15, 14, 3))
        self.assertIsNone(stochastic([1.0] * 5, [1.0] * 4, [1.0] * 5))

    def test_minimum_length_with_unit_periods(self) -> None:
        """period=1 and smooth=1 work from a single candle: mid-range 50."""
        result = stochastic([1.2], [0.8], [1.0], 1, 1)
        self.assertEqual(result, {"k": 50.0, "d": 50.0})

    def test_invalid_parameters_raise(self) -> None:
        """Non-positive period or smooth is rejected."""
        rows = hlcs(random_candles(30, 2))
        for kwargs in ({"period": 0}, {"smooth": 0}, {"period": -1}, {"smooth": -3}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                stochastic(*rows, **kwargs)


class AdxPropertyTests(IndicatorTestCase):
    """Properties of ``indicators.adx``."""

    def test_values_stay_within_zero_to_hundred(self) -> None:
        """ADX and both DIs are percentages on random candles."""
        for seed in SEEDS:
            highs, lows, closes = hlcs(random_candles(120, seed))
            for period in (5, 14):
                result = adx(highs, lows, closes, period)
                with self.subTest(seed=seed, period=period):
                    self.assertIsNotNone(result)
                    for key in ("adx", "plus_di", "minus_di"):
                        self.assertBetween(result[key], 0.0, 100.0)

    def test_rising_candles_plus_di_dominates(self) -> None:
        """A pure rally puts all directional movement on +DI."""
        highs, lows, closes = hlcs(trending_candles(60))
        result = adx(highs, lows, closes)
        self.assertEqual(result["plus_di"], 100.0)
        self.assertEqual(result["minus_di"], 0.0)
        self.assertEqual(result["adx"], 100.0)

    def test_falling_candles_minus_di_dominates(self) -> None:
        """A pure slide puts all directional movement on -DI."""
        highs, lows, closes = hlcs(trending_candles(60, rising=False))
        result = adx(highs, lows, closes)
        self.assertEqual(result["plus_di"], 0.0)
        self.assertEqual(result["minus_di"], 100.0)
        self.assertEqual(result["adx"], 100.0)

    def test_flat_candles_read_zero(self) -> None:
        """No directional movement at all reads as zero everywhere."""
        highs, lows, closes = hlcs(flat_candles(60))
        result = adx(highs, lows, closes)
        self.assertEqual(result, {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0})

    def test_short_or_mismatched_inputs_return_none(self) -> None:
        """Fewer than 2*period+1 bars or mismatched lengths return None."""
        self.assertIsNone(adx([], [], []))
        self.assertIsNone(adx([1.0], [1.0], [1.0], 1))
        self.assertIsNone(adx([1.0] * 28, [1.0] * 28, [1.0] * 28, 14))
        self.assertIsNone(adx([1.0] * 5, [1.0] * 4, [1.0] * 5))

    def test_invalid_period_raises(self) -> None:
        """Periods below one are rejected with ValueError."""
        for period in (0, -1):
            with self.subTest(period=period), self.assertRaises(ValueError):
                adx([1.0], [1.0], [1.0], period)


class AnalyzePropertyTests(IndicatorTestCase):
    """Properties of the composed ``indicators.analyze`` report."""

    SIGNALS: ClassVar[set[str]] = {
        "STRONG BUY",
        "BUY",
        "NEUTRAL",
        "SELL",
        "STRONG SELL",
    }
    TRENDS: ClassVar[set[str]] = {"Bullish", "Bearish", "Mixed"}
    REGIMES: ClassVar[set[str]] = {"Trending", "Squeeze", "Ranging", "Unknown"}

    def test_result_contract_on_random_candles(self) -> None:
        """Every random history yields a complete, in-range report."""
        for seed in SEEDS:
            result = analyze(random_candles(200, seed))
            self.assertIsNotNone(result)
            closes = result["closes"]
            with self.subTest(seed=seed):
                self.assertEqual(result["closed_candles"], 199)
                self.assertEqual(len(closes), 199)
                self.assertIn(result["signal"], self.SIGNALS)
                self.assertIn(result["trend"], self.TRENDS)
                self.assertIn(result["regime"], self.REGIMES)
                self.assertBetween(result["score"], -4, 4)
                self.assertIsInstance(result["why"], list)
                self.assertEqual(len(result["why"]), 4)
                self.assertTrue(all(isinstance(r, str) for r in result["why"]))
                self.assertBetween(result["rsi"], 0.0, 100.0)
                self.assertGreaterEqual(result["atr"], 0.0)
                atr_pct = result["atr"] / closes[-1] * 100.0
                self.assertCloseTo(result["atr_pct"], atr_pct)
                for key in ("ema9", "ema21", "ema50", "macd_histogram"):
                    self.assertTrue(math.isfinite(result[key]))
                self.assertBetween(result["ema9"], min(closes), max(closes))
                self.assertBetween(result["ema50"], min(closes), max(closes))
                self.assertBetween(result["stochastic"]["k"], 0.0, 100.0)
                self.assertBetween(result["adx"]["adx"], 0.0, 100.0)
                self.assertGreaterEqual(
                    result["bollinger"]["upper"], result["bollinger"]["middle"]
                )

    def test_sixty_closed_candles_is_the_minimum(self) -> None:
        """The report needs 61 rows: the last one is treated as forming."""
        self.assertIsNone(analyze(trending_candles(60)))
        result = analyze(trending_candles(61))
        self.assertIsNotNone(result)
        self.assertEqual(result["closed_candles"], 60)

    def test_forming_bar_never_changes_the_report(self) -> None:
        """Only closed candles count: mutating the last row is invisible."""
        rows = random_candles(100, 3)
        base = analyze(rows)
        wild = [*rows[:-1], (rows[-1][0], 1.0, 9.0, 0.1, 1.0)]
        self.assertEqual(analyze(wild), base)

    def test_invalid_candles_raise(self) -> None:
        """Malformed rows are rejected, including the forming bar."""
        rows = random_candles(100, 3)
        short_row = [*rows[:-1], (rows[-1][0], 1.0, 1.0)]
        with self.assertRaises(ValueError):
            analyze(short_row)
        nan_row = [*rows[:-1], (rows[-1][0], 1.0, math.nan, 1.0, 1.0)]
        with self.assertRaises(ValueError):
            analyze(nan_row)
        # NOTE: the in-progress final row is validated even though it is then
        # dropped, so garbage in the forming bar also raises ValueError.
        inconsistent = [*rows[:-1], (rows[-1][0], 1.0, 0.5, 1.5, 1.2)]
        with self.assertRaises(ValueError):
            analyze(inconsistent)

    def test_strong_uptrend_reads_bullish_buy(self) -> None:
        """A pure rally is Bullish/BUY with pinned RSI 100."""
        result = analyze(trending_candles(200))
        self.assertEqual(result["trend"], "Bullish")
        self.assertEqual(result["signal"], "BUY")
        self.assertEqual(result["score"], 2)
        self.assertEqual(result["rsi"], 100.0)
        self.assertEqual(result["regime"], "Trending")
        self.assertGreater(result["ema9"], result["ema21"])
        self.assertGreater(result["closes"][-1], result["ema50"])

    def test_strong_downtrend_reads_bearish_sell(self) -> None:
        """A pure slide is Bearish/SELL with pinned RSI 0."""
        result = analyze(trending_candles(200, rising=False))
        self.assertEqual(result["trend"], "Bearish")
        self.assertEqual(result["signal"], "SELL")
        self.assertEqual(result["score"], -2)
        self.assertEqual(result["rsi"], 0.0)
        self.assertEqual(result["regime"], "Trending")
        self.assertLess(result["ema9"], result["ema21"])
        self.assertLess(result["closes"][-1], result["ema50"])


class IndicatorEdgeCaseTests(IndicatorTestCase):
    """Explicit edge-case contracts across every indicator."""

    def test_spike_series_keeps_everything_finite_and_bounded(self) -> None:
        """One huge candle cannot break bounds or produce NaN/inf."""
        for seed in SEEDS:
            highs, lows, closes = hlcs(spiked_candles(200, seed))
            low, high = min(closes), max(closes)
            for value in ema(closes, 14):
                self.assertBetween(value, low, high)
            for value in rsi_series(closes, 14):
                if value is not None:
                    self.assertBetween(value, 0.0, 100.0)
            ranges = true_ranges(highs, lows, closes)
            spike_atr = atr(highs, lows, closes)
            self.assertGreaterEqual(spike_atr, 0.0)
            self.assertBetween(spike_atr, min(ranges), max(ranges))
            self.assertAllFinite(macd_histogram_series(closes))
            bands = bollinger(closes)
            for key in ("upper", "middle", "lower", "percent_b", "bandwidth"):
                self.assertTrue(math.isfinite(bands[key]))
            self.assertBetween(stochastic(highs, lows, closes)["k"], 0.0, 100.0)
            directional = adx(highs, lows, closes)
            for key in ("adx", "plus_di", "minus_di"):
                self.assertBetween(directional[key], 0.0, 100.0)

    def test_empty_and_single_element_contracts(self) -> None:
        """Length-0 and length-1 inputs pin the exact code contracts."""
        self.assertEqual(ema([], 5), [])
        self.assertEqual(ema([3.5], 5), [3.5])
        self.assertEqual(sma([], 5), [])
        self.assertEqual(sma([3.5], 1), [3.5])
        self.assertEqual(sma([3.5], 5), [None])
        self.assertEqual(rsi_series([], 14), [])
        self.assertEqual(rsi_series([3.5], 14), [None])
        self.assertIsNone(rsi([]))
        self.assertIsNone(rsi([3.5]))
        self.assertEqual(macd_histogram_series([]), [])
        self.assertEqual(macd_histogram_series([3.5]), [0.0])
        self.assertIsNone(atr([], [], []))
        self.assertEqual(atr([1.5], [1.0], [1.25]), 0.5)
        self.assertIsNone(bollinger([], 20))
        self.assertIsNone(bollinger([3.5], 20))
        self.assertIsNone(stochastic([], [], []))
        self.assertIsNone(adx([], [], []))

    def test_strictly_decreasing_series_contracts(self) -> None:
        """Falling data flows through every indicator as expected."""
        closes = monotone_closes(200, 9, descending=True)
        result = ema(closes, 14)
        for previous, current in pairwise(result):
            self.assertGreaterEqual(previous, current)
        formed = [v for v in rsi_series(closes, 14) if v is not None]
        self.assertTrue(formed)
        self.assertEqual(set(formed), {0.0})
        highs, lows, falling = hlcs(trending_candles(60, rising=False))
        self.assertEqual(stochastic(highs, lows, falling)["k"], 0.0)
        self.assertEqual(adx(highs, lows, falling)["minus_di"], 100.0)


if __name__ == "__main__":
    unittest.main()
