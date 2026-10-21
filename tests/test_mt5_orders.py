"""Gate tests for live MT5 orders shared by the CLI and the desktop ORDERS page.

MetaTrader5 is not installed in CI. The live path is exercised with a fake
``mt5`` module patched in before the bridge is built, so no order can reach a
real terminal from these tests.
"""

import math
import unittest
from types import SimpleNamespace
from unittest import mock

from neezy_backend import mt5_bridge
from neezy_backend.mt5_bridge import MT5Bridge
from neezy_backend.mt5_orders import (
    check_live_terminal,
    confirmation_lines,
    parse_order_form,
    send_live_order,
)


def _fake_mt5(initialize_ok=True):
    fake = mock.Mock()
    fake.TRADE_ACTION_DEAL = 1
    fake.ORDER_TYPE_BUY = 0
    fake.ORDER_TYPE_SELL = 1
    fake.ORDER_TIME_GTC = 0
    fake.ORDER_FILLING_IOC = 1
    fake.TRADE_RETCODE_DONE = 10009
    fake.initialize.return_value = initialize_ok
    fake.last_error.return_value = (1, "terminal not found")
    fake.account_info.return_value = SimpleNamespace(
        _asdict=lambda: {"login": 555, "server": "Broker-Demo", "balance": 1000.0}
    )
    fake.symbol_info_tick.return_value = SimpleNamespace(ask=1.085, bid=1.0848)
    fake.order_send.return_value = SimpleNamespace(
        _asdict=lambda: {"retcode": 10009, "order": 77, "price": 1.085}
    )
    return fake


class _FakeTerminalCase(unittest.TestCase):
    """Patch ``mt5`` for the whole test: ``connect()`` reads it at call time."""

    def setUp(self):
        self.fake = _fake_mt5()
        patcher = mock.patch.object(mt5_bridge, "mt5", self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def live_bridge(self):
        return MT5Bridge(login=555, server="Broker-Demo", mock=False)


class ParseOrderFormTests(unittest.TestCase):
    def test_valid_ticket_is_normalised(self):
        order = parse_order_form("frxEURUSD", " buy ", "0.10", "1.080", "1.095")
        self.assertEqual(order["order_type"], "BUY")
        self.assertEqual(order["volume"], 0.1)
        self.assertEqual(order["sl"], 1.08)
        self.assertEqual(order["tp"], 1.095)

    def test_blank_stop_and_target_mean_none(self):
        order = parse_order_form("frxEURUSD", "SELL", "1", "", "  ")
        self.assertEqual((order["sl"], order["tp"]), (0.0, 0.0))

    def test_rejects_bad_input(self):
        cases = [
            (("", "BUY", "0.1"), "Choose a symbol"),
            (("frxEURUSD", "HOLD", "0.1"), "BUY or SELL"),
            (("frxEURUSD", "BUY", "0"), "greater than zero"),
            (("frxEURUSD", "BUY", "abc"), "must be a number"),
            (("frxEURUSD", "BUY", "nan"), "finite"),
            (("frxEURUSD", "BUY", "inf"), "finite"),
            (("frxEURUSD", "BUY", "0.1", "-1"), "must not be negative"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                with self.assertRaisesRegex(ValueError, message):
                    parse_order_form(*args)
        self.assertTrue(math.isfinite(parse_order_form("x", "BUY", "1")["volume"]))


class LiveTerminalGateTests(_FakeTerminalCase):
    def test_simulated_bridge_is_refused(self):
        gate = check_live_terminal(MT5Bridge(mock=True))
        self.assertFalse(gate["ok"])
        self.assertIn("MT5 not connected", gate["reason"])

    def test_failed_initialize_is_refused(self):
        self.fake.initialize.return_value = False
        gate = check_live_terminal(self.live_bridge())
        self.assertFalse(gate["ok"])
        self.assertIn("initialize failed", gate["reason"])

    def test_connected_terminal_reports_account(self):
        gate = check_live_terminal(self.live_bridge())
        self.assertTrue(gate["ok"])
        self.assertEqual(gate["account"], 555)
        self.assertEqual(gate["server"], "Broker-Demo")


SAMPLE_ORDER = {
    "symbol": "frxEURUSD",
    "order_type": "BUY",
    "volume": 0.1,
    "sl": 1.08,
    "tp": 0.0,
}


class SendLiveOrderTests(_FakeTerminalCase):
    def test_nothing_is_sent_without_confirmation(self):
        res = send_live_order(self.live_bridge(), confirmed=False, **SAMPLE_ORDER)
        self.assertFalse(res["success"])
        self.assertFalse(res["sent"])
        self.fake.order_send.assert_not_called()

    def test_simulated_bridge_is_refused_even_when_confirmed(self):
        res = send_live_order(MT5Bridge(mock=True), confirmed=True, **SAMPLE_ORDER)
        self.assertFalse(res["success"])
        self.assertIn("live order refused", res["error"])

    def test_disconnected_terminal_is_refused_even_when_confirmed(self):
        self.fake.initialize.return_value = False
        res = send_live_order(self.live_bridge(), confirmed=True, **SAMPLE_ORDER)
        self.assertFalse(res["success"])
        self.assertIn("live order refused", res["error"])
        self.fake.order_send.assert_not_called()

    def test_confirmed_order_on_live_terminal_is_sent_once(self):
        res = send_live_order(self.live_bridge(), confirmed=True, **SAMPLE_ORDER)
        self.assertTrue(res["success"])
        self.assertEqual(res["ticket"], 77)
        self.assertEqual(self.fake.order_send.call_count, 1)
        request = self.fake.order_send.call_args.args[0]
        self.assertEqual(request["symbol"], "EURUSD")
        self.assertEqual(request["volume"], 0.1)
        self.assertEqual(request["sl"], 1.08)


class ConfirmationTextTests(unittest.TestCase):
    def test_lists_what_will_be_sent(self):
        order = parse_order_form("frxEURUSD", "buy", "0.25", "1.08", "")
        order["mt5_symbol"] = "EURUSD"
        lines = confirmation_lines(
            order, {"ok": True, "account": 555, "server": "Broker-Demo"}
        )
        text = "\n".join(lines)
        self.assertIn("Symbol: frxEURUSD (MT5: EURUSD)", text)
        self.assertIn("Side: BUY at market", text)
        self.assertIn("Volume: 0.25 lots", text)
        self.assertIn("Stop loss: 1.08", text)
        self.assertIn("Take profit: none", text)
        self.assertIn("Account: 555 on Broker-Demo", text)

    def test_preview_without_account_says_it_is_checked_later(self):
        order = parse_order_form("frxEURUSD", "SELL", "0.1")
        order["mt5_symbol"] = "EURUSD"
        text = "\n".join(confirmation_lines(order, {}))
        self.assertIn("checked when the order is placed", text)
        self.assertNotIn("None", text)


if __name__ == "__main__":
    unittest.main()
