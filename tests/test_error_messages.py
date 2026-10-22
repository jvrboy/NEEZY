"""Error-message quality tests (roadmap update #68).

User-facing exceptions must name the offending field/value and stay
actionable. Vague errors are the top support burden.
"""

import unittest

from neezy_backend.config import AppSettings
from neezy_backend.providers import ProviderError, _check_candles
from neezy_backend.risk import atr_levels, position_size, resolve_stop
from neezy_backend.sandbox import resolve_within
from neezy_backend.stream import parse_candle


class ErrorMessageQualityTests(unittest.TestCase):
    def test_settings_errors_name_the_field(self):
        for field, value in (
            ("polling_ms", 10),
            ("theme", "Unknown"),
            ("strategy", "NOT_REAL"),
            ("mcp_port", 80),
        ):
            with self.subTest(field=field):
                with self.assertRaises((ValueError, TypeError)) as raised:
                    AppSettings().updated(**{field: value})
                message = str(raised.exception)
                self.assertIn(field, message)

    def test_settings_errors_state_the_bound(self):
        with self.assertRaises(ValueError) as raised:
            AppSettings().updated(polling_ms=10)
        self.assertIn("between", str(raised.exception))

    def test_risk_errors_explain_what_is_needed(self):
        with self.assertRaises(ValueError) as raised:
            resolve_stop(None, 1.1, None)
        self.assertIn("direction", str(raised.exception))
        self.assertIn("stop", str(raised.exception))

    def test_atr_levels_rejects_bad_direction_with_guidance(self):
        with self.assertRaises(ValueError) as raised:
            atr_levels("HOLD", 1.1, 0.002)
        self.assertIn("BUY", str(raised.exception))

    def test_position_size_rejects_zero_distance(self):
        with self.assertRaises(ValueError) as raised:
            position_size(
                symbol="frxEURUSD",
                balance=10_000,
                risk_percent=1.0,
                entry=1.1,
                stop=1.1,
            )
        self.assertIn("differ", str(raised.exception))

    def test_sandbox_error_names_the_escape(self):
        with self.assertRaises(ValueError) as raised:
            resolve_within("/tmp", "../../etc/passwd")
        self.assertIn("outside", str(raised.exception))
        self.assertIn("..", str(raised.exception) or "outside" in str(raised.exception))

    def test_candle_error_identifies_the_problem(self):
        with self.assertRaises(ValueError) as raised:
            parse_candle(
                {"epoch": 1, "open": 1.0, "high": 0.5, "low": 0.4, "close": 1.0}
            )
        self.assertIn("OHLC", str(raised.exception))

    def test_provider_error_names_the_source(self):
        with self.assertRaises(ProviderError) as raised:
            _check_candles("nope", "finnhub")
        self.assertIn("finnhub", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
