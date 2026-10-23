"""Responsive ASCII chart rendering and its existing-CLI integration."""

import io
import json
import unittest

from neezy_backend.cli import main
from neezy_backend.terminal_chart import render_ascii_chart
from tests.cloud_fixtures import candles


class AsciiChartTests(unittest.TestCase):
    def test_chart_is_ascii_bounded_and_excludes_forming_candle(self):
        rows = candles(80)
        chart = render_ascii_chart(rows, width=44, height=8)
        self.assertEqual(chart.total_closed, 79)
        self.assertLessEqual(chart.plotted, 44)
        self.assertEqual(chart.close, rows[-2][4])
        self.assertNotEqual(chart.close, rows[-1][4])
        self.assertEqual(len(chart.lines), 8)
        for line in chart.lines:
            self.assertLessEqual(len(line), 44)
            self.assertTrue(all(ord(char) < 128 for char in line))

    def test_bullish_bearish_and_doji_bodies_have_distinct_ascii_marks(self):
        rows = [
            (1, 1.0, 3.0, 0.5, 2.0),
            (2, 2.0, 3.0, 0.5, 1.0),
            (3, 1.0, 2.0, 0.5, 1.0),
            (4, 100.0, 101.0, 99.0, 100.0),
        ]
        chart = render_ascii_chart(rows, width=30, height=8)
        rendered = "\n".join(chart.lines)
        self.assertIn("#", rendered)
        self.assertIn("=", rendered)
        self.assertIn("+", rendered)
        self.assertEqual(chart.close, 1.0)

    def test_constant_prices_have_a_stable_midline(self):
        rows = [(index, 1.0, 1.0, 1.0, 1.0) for index in range(8)]
        chart = render_ascii_chart(rows, width=28, height=6)
        self.assertEqual(chart.high, chart.low)
        self.assertTrue(any("+" in line for line in chart.lines))

    def test_empty_and_invalid_ohlc_data_fail(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            render_ascii_chart([])
        with self.assertRaisesRegex(ValueError, "bounds"):
            render_ascii_chart([(1, 1.0, 0.5, 2.0, 1.0), (2, 1.0, 1.0, 1.0, 1.0)])
        with self.assertRaisesRegex(ValueError, "finite"):
            render_ascii_chart(
                [(1, 1.0, float("inf"), 0.5, 1.0), (2, 1.0, 1.0, 1.0, 1.0)]
            )


class ChartCliTests(unittest.TestCase):
    def test_cli_uses_injected_fetcher_and_prints_real_ohlc(self):
        calls = []
        rows = candles(80)

        def fetch(symbol, seconds, count):
            calls.append((symbol, seconds, count))
            return rows

        out = io.StringIO()
        code = main(
            [
                "chart",
                "EURUSD",
                "-t",
                "15m",
                "-n",
                "80",
                "--width",
                "44",
                "--height",
                "8",
            ],
            fetch=fetch,
            out=out,
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls, [("frxEURUSD", 900, 80)])
        self.assertIn("79 closed", out.getvalue())
        self.assertIn("Closed candles only", out.getvalue())
        for line in out.getvalue().splitlines():
            self.assertLessEqual(len(line), 44, repr(line))
            self.assertTrue(all(ord(char) < 128 for char in line))

    def test_json_chart_is_machine_readable(self):
        out = io.StringIO()
        code = main(
            ["chart", "EURUSD", "--json", "-n", "20"],
            fetch=lambda symbol, seconds, count: candles(count),
            out=out,
        )
        self.assertEqual(code, 0)
        document = json.loads(out.getvalue())
        self.assertEqual(document["symbol"], "frxEURUSD")
        self.assertEqual(document["closed_candles"], 19)
        self.assertIsInstance(document["chart"], list)


if __name__ == "__main__":
    unittest.main()
