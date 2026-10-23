"""Numerical compatibility and read-only tooling for backend microkernels."""

import io
import json
import unittest

from neezy_backend.cli import main
from neezy_backend.kernel_benchmark import (
    _fixture,
    _reference_atr,
    _reference_ema,
    _reference_macd,
    benchmark_kernels,
)
from neezy_backend.microkernels import (
    atr_kernel,
    ema_kernel,
    kernel_status,
    macd_histogram_kernel,
)


class MicrokernelCompatibilityTests(unittest.TestCase):
    def test_ema_matches_original_algorithm_exactly(self):
        _highs, _lows, closes = _fixture(512)
        for size in (0, 1, 2, 14, 60, 512):
            for period in (1, 2, 9, 21, 50):
                with self.subTest(size=size, period=period):
                    values = closes[:size]
                    self.assertEqual(
                        ema_kernel(values, period), _reference_ema(values, period)
                    )

    def test_macd_matches_original_algorithm_exactly(self):
        _highs, _lows, closes = _fixture(512)
        for size in (0, 1, 2, 35, 60, 512):
            with self.subTest(size=size):
                values = closes[:size]
                self.assertEqual(
                    macd_histogram_kernel(values, 12, 26, 9),
                    _reference_macd(values),
                )

    def test_atr_matches_original_algorithm(self):
        highs, lows, closes = _fixture(512)
        for size in (1, 2, 14, 15, 60, 512):
            for period in (1, 5, 14, 50):
                with self.subTest(size=size, period=period):
                    self.assertEqual(
                        atr_kernel(highs[:size], lows[:size], closes[:size], period),
                        _reference_atr(
                            highs[:size], lows[:size], closes[:size], period
                        ),
                    )

    def test_validation_and_empty_behavior_are_preserved(self):
        with self.assertRaisesRegex(ValueError, "positive"):
            ema_kernel([1.0], 0)
        with self.assertRaisesRegex(ValueError, "shorter"):
            macd_histogram_kernel([1.0], 26, 12, 9)
        self.assertIsNone(atr_kernel([], [], [], 14))
        self.assertIsNone(atr_kernel([1.0], [], [1.0], 14))

    def test_status_is_dependency_free(self):
        status = kernel_status()
        self.assertTrue(status["deterministic"])
        self.assertFalse(status["native_dependency"])
        self.assertEqual(set(status["kernels"]), {"ema", "macd_histogram", "atr"})


class KernelCliTests(unittest.TestCase):
    def test_status_json(self):
        out = io.StringIO()
        self.assertEqual(main(["kernels", "status", "--json"], out=out), 0)
        self.assertEqual(json.loads(out.getvalue())["backend"], "python-fused-v1")

    def test_small_benchmark_is_correctness_checked(self):
        report = benchmark_kernels(iterations=2, size=60)
        self.assertEqual(report["candles"], 60)
        self.assertEqual(report["correctness"], "exact")
        self.assertEqual(set(report["kernels"]), {"ema", "macd_histogram", "atr"})
        for values in report["kernels"].values():
            self.assertGreaterEqual(values["optimized_ms"], 0)
            self.assertGreaterEqual(values["reference_ms"], 0)

    def test_benchmark_cli_and_bounds(self):
        out = io.StringIO()
        self.assertEqual(
            main(
                ["kernels", "benchmark", "--iterations", "1", "--candles", "60"],
                out=out,
            ),
            0,
        )
        self.assertIn("Correctness-checked", out.getvalue())
        with self.assertRaisesRegex(ValueError, "iterations"):
            benchmark_kernels(iterations=0)
        with self.assertRaisesRegex(ValueError, "size"):
            benchmark_kernels(size=10)


if __name__ == "__main__":
    unittest.main()
