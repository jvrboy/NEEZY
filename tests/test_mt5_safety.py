"""Safety tests for MT5 order paths: no fake success, dry-run, and --confirm."""

import io
import unittest
from unittest import mock

from neezy_backend import cli
from neezy_backend.mt5_bridge import MT5Bridge


class BridgeOrderSafetyTests(unittest.TestCase):
    def test_unconnected_bridge_refuses_order(self):
        bridge = MT5Bridge(mock=True)
        res = bridge.place_order("frxEURUSD", "BUY", 0.1)
        self.assertFalse(res["success"])
        self.assertIn("not connected", res["error"])

    def test_unconnected_bridge_refuses_close(self):
        bridge = MT5Bridge(mock=True)
        res = bridge.close_position(42)
        self.assertFalse(res["success"])

    def test_invalid_order_rejected(self):
        bridge = MT5Bridge(mock=True)
        bridge.connect()
        self.assertFalse(bridge.place_order("frxEURUSD", "HOLD", 0.1)["success"])
        self.assertFalse(bridge.place_order("frxEURUSD", "BUY", 0)["success"])

    def test_preview_never_sends(self):
        bridge = MT5Bridge(mock=True)
        preview = bridge.preview_order("frxEURUSD", "buy", 0.2, sl=1.0, tp=1.2)
        self.assertEqual(preview["status"], "dry_run")
        self.assertFalse(preview["sent"])
        self.assertTrue(preview["valid"])
        self.assertEqual(preview["order_type"], "BUY")
        self.assertEqual(preview["mt5_symbol"], "EURUSD")

    def test_preview_reports_errors(self):
        preview = MT5Bridge(mock=True).preview_order("frxEURUSD", "HOLD", -1)
        self.assertFalse(preview["valid"])
        self.assertEqual(len(preview["errors"]), 2)


class CliOrderSafetyTests(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        code = cli.main(argv, out=out)
        return code, out.getvalue()

    def test_order_without_confirm_is_refused(self):
        with mock.patch.object(cli, "_default_fetch", side_effect=AssertionError):
            code, _ = self._run(
                ["mt5", "order", "frxEURUSD", "--type", "BUY", "--volume", "0.1"]
            )
        self.assertNotEqual(code, 0)

    def test_confirm_without_terminal_is_refused_not_faked(self):
        # MetaTrader5 is not installed in CI, so the bridge is simulated.
        code, out = self._run(
            [
                "mt5",
                "order",
                "frxEURUSD",
                "--type",
                "BUY",
                "--volume",
                "0.1",
                "--confirm",
            ]
        )
        self.assertNotEqual(code, 0)
        self.assertNotIn("Order placed", out)

    def test_dry_run_prints_preview_and_exits_zero(self):
        code, out = self._run(
            [
                "mt5",
                "order",
                "frxEURUSD",
                "--type",
                "SELL",
                "--volume",
                "0.05",
                "--dry-run",
                "--json",
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn('"sent": false', out)

    def test_dry_run_invalid_volume_fails(self):
        code, _ = self._run(
            [
                "mt5",
                "order",
                "frxEURUSD",
                "--type",
                "BUY",
                "--volume",
                "0",
                "--dry-run",
            ]
        )
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
