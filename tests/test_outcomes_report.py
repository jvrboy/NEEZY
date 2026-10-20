import unittest

try:
    from neezy_app.enterprise import format_outcomes
except ModuleNotFoundError as error:  # Tk or optional deps missing
    raise unittest.SkipTest(str(error)) from error

STATS = {
    "count": 4,
    "win_rate": 75.0,
    "avg_return_pct": 0.1234,
    "best_pct": 0.5,
    "worst_pct": -0.2,
}


class FormatOutcomesTest(unittest.TestCase):
    def test_reports_statistics(self):
        text = format_outcomes("EUR/USD", "5m", STATS)
        self.assertIn("EUR/USD · 5m", text)
        self.assertIn("75.0%", text)
        self.assertIn("+0.123%", text)
        self.assertIn("+0.50% / -0.20%", text)

    def test_empty_state(self):
        empty = {**STATS, "count": 0}
        self.assertIn("No resolved signals", format_outcomes("EUR/USD", "5m", empty))


if __name__ == "__main__":
    unittest.main()
