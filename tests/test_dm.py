"""Unit tests for Direct Messaging and Decision Metrics module."""

import unittest

from neezy_backend.dm import (
    compute_decision_metrics,
    format_signal_dm,
    send_dm_notification,
)


class DirectMessagingTests(unittest.TestCase):
    def test_send_dm_invalid_url(self):
        res = send_dm_notification("", "Title", "Message")
        self.assertFalse(res["success"])

        res_bad = send_dm_notification("invalid_url", "Title", "Message")
        self.assertFalse(res_bad["success"])

    def test_format_signal_dm(self):
        payload = format_signal_dm(
            symbol="frxEURUSD",
            timeframe="15m",
            signal="STRONG BUY",
            score=3.5,
            metrics={"ATR": 0.0012},
        )
        self.assertIn("frxEURUSD", payload["title"])
        self.assertEqual(payload["level"], "warning")
        self.assertEqual(payload["fields"]["Symbol"], "frxEURUSD")

    def test_compute_decision_metrics(self):
        candles = []
        base = 1.0800
        for i in range(100):
            candles.append(
                [
                    1700000000 + i * 300,
                    base + (i * 0.0001),
                    base + (i * 0.0001) + 0.0005,
                    base + (i * 0.0001) - 0.0005,
                    base + (i * 0.0001) + 0.0002,
                    100,
                ]
            )

        metrics = compute_decision_metrics(
            symbol="frxEURUSD",
            timeframe="5m",
            candles=candles,
            balance=10000.0,
            risk_percent=1.0,
        )
        self.assertEqual(metrics["symbol"], "frxEURUSD")
        self.assertIn("decision", metrics)
        self.assertIn("confidence", metrics)
        self.assertIn("rsi", metrics)
        self.assertIn("risk_plan", metrics)
        self.assertTrue(metrics["drawdown_risk_ok"])


if __name__ == "__main__":
    unittest.main()
