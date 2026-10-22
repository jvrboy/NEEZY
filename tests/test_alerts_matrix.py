"""Boundary matrix tests for alert rules (roadmap update #48).

Every operator is exercised at, just above/below, and exactly on the
threshold so off-by-one behavior is pinned.
"""

import unittest

from neezy_backend.alerts import AlertEngine, AlertRule


def _rule(operator: str, value: str, metric: str = "price", **kwargs) -> AlertRule:
    return AlertRule(
        symbol="frxEURUSD", metric=metric, operator=operator, value=value, **kwargs
    )


def _analysis() -> tuple[dict, float, list]:
    return {"rsi": 50.0, "score": 2, "signal": "BUY"}, 1.1000, []


class AlertOperatorMatrixTests(unittest.TestCase):
    def test_greater_than_boundaries(self):
        for value, current, expect in (
            ("70", 70.0, False),  # exactly at threshold: not >
            ("70", 70.0001, True),  # a hair above
            ("70", 69.9999, False),  # a hair below
            ("0", 0.0, False),  # zero threshold, zero value
        ):
            with self.subTest(threshold=value, current=current):
                rule = _rule(">", value, metric="rsi")
                engine = AlertEngine([rule])
                engine.evaluate("frxEURUSD", {"rsi": 1.0}, 1.1, [])
                fired = engine.evaluate("frxEURUSD", {"rsi": current}, 1.1, [])
                self.assertEqual(bool(fired), expect)

    def test_greater_equal_boundaries(self):
        # >= at exactly the threshold fires, including on the first tick
        # (edge-triggered: matched and not previously active).
        rule = _rule(">=", "70", metric="rsi")
        engine = AlertEngine([rule])
        fired = engine.evaluate("frxEURUSD", {"rsi": 70.0}, 1.1, [])
        self.assertEqual(len(fired), 1)
        # Staying at the threshold does not re-fire.
        fired = engine.evaluate("frxEURUSD", {"rsi": 70.0}, 1.1, [])
        self.assertEqual(fired, [])

    def test_less_than_boundaries(self):
        rule = _rule("<", "30", metric="rsi")
        engine = AlertEngine([rule])
        engine.evaluate("frxEURUSD", {"rsi": 50.0}, 1.1, [])
        fired = engine.evaluate("frxEURUSD", {"rsi": 29.9999}, 1.1, [])
        self.assertEqual(len(fired), 1)
        engine.reset()
        engine.evaluate("frxEURUSD", {"rsi": 50.0}, 1.1, [])
        fired = engine.evaluate("frxEURUSD", {"rsi": 30.0}, 1.1, [])
        self.assertEqual(fired, [])  # exactly 30 is not < 30

    def test_equal_uses_tolerance(self):
        rule = _rule("==", "70", metric="rsi")
        engine = AlertEngine([rule])
        engine.evaluate("frxEURUSD", {"rsi": 1.0}, 1.1, [])
        fired = engine.evaluate("frxEURUSD", {"rsi": 70.0 + 1e-12}, 1.1, [])
        self.assertEqual(len(fired), 1)

    def test_crosses_above_needs_prior_tick(self):
        rule = _rule("crosses above", "70", metric="rsi")
        engine = AlertEngine([rule])
        # First ever tick can never fire a crossing rule.
        self.assertEqual(engine.evaluate("frxEURUSD", {"rsi": 80.0}, 1.1), [])
        engine2 = AlertEngine([rule])
        engine2.evaluate("frxEURUSD", {"rsi": 69.0}, 1.1, [])
        fired = engine2.evaluate("frxEURUSD", {"rsi": 71.0}, 1.1, [])
        self.assertEqual(len(fired), 1)

    def test_crosses_above_includes_previous_at_threshold(self):
        # Documented formula: previous <= threshold < current. A previous
        # value sitting exactly on the threshold still counts as a cross.
        rule = _rule("crosses above", "70", metric="rsi")
        engine = AlertEngine([rule])
        engine.evaluate("frxEURUSD", {"rsi": 70.0}, 1.1, [])
        fired = engine.evaluate("frxEURUSD", {"rsi": 71.0}, 1.1, [])
        self.assertEqual(len(fired), 1)
        # But a previous value already above the threshold is no cross.
        engine.reset()
        engine.evaluate("frxEURUSD", {"rsi": 71.0}, 1.1, [])
        fired = engine.evaluate("frxEURUSD", {"rsi": 72.0}, 1.1, [])
        self.assertEqual(fired, [])

    def test_crosses_below_fires_on_descent(self):
        rule = _rule("crosses below", "30", metric="rsi")
        engine = AlertEngine([rule])
        engine.evaluate("frxEURUSD", {"rsi": 31.0}, 1.1, [])
        fired = engine.evaluate("frxEURUSD", {"rsi": 29.0}, 1.1, [])
        self.assertEqual(len(fired), 1)

    def test_signal_metric_matches_case_insensitive(self):
        rule = _rule("==", "buy", metric="signal")
        engine = AlertEngine([rule])
        fired = engine.evaluate("frxEURUSD", {"signal": "BUY"}, 1.1, [])
        self.assertEqual(len(fired), 1)

    def test_pattern_metric_membership(self):
        rule = _rule("==", "bullish engulfing", metric="pattern")
        engine = AlertEngine([rule])
        fired = engine.evaluate(
            "frxEURUSD", {"score": 2}, 1.1, [{"name": "Bullish Engulfing"}]
        )
        self.assertEqual(len(fired), 1)

    def test_symbol_filter_and_disabled_rules(self):
        rule = _rule(">", "1.0")
        engine = AlertEngine([rule])
        self.assertEqual(engine.evaluate("frxGBPUSD", {"score": 1}, 2.0), [])
        disabled = _rule(">", "1.0", enabled=False)
        engine2 = AlertEngine([disabled])
        self.assertEqual(engine2.evaluate("frxEURUSD", {"score": 1}, 2.0), [])

    def test_missing_metric_value_never_fires(self):
        rule = _rule(">", "70", metric="rsi")
        engine = AlertEngine([rule])
        fired = engine.evaluate("frxEURUSD", {"rsi": None}, 1.1, [])
        self.assertEqual(fired, [])

    def test_rule_construction_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            _rule(">", "not-a-number", metric="rsi")
        with self.assertRaises(ValueError):
            _rule("~", "1", metric="rsi")
        with self.assertRaises(ValueError):
            _rule(">", "1", metric="unknown")
        with self.assertRaises(ValueError):
            _rule(">", "")


if __name__ == "__main__":
    unittest.main()
