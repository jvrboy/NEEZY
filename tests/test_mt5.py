"""Unit tests for MetaTrader 5 Bridge module."""

import unittest

from neezy_backend.mt5_bridge import MT5Bridge, is_mt5_available


class MT5BridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = MT5Bridge(
            login=123456,
            password="testpassword",
            server="Demo-Server",
            symbol_map="frxEURUSD=EURUSD,frxGBPUSD=GBPUSD.m",
            mock=True,
        )

    def test_symbol_mapping(self):
        self.assertEqual(self.bridge.map_symbol("frxEURUSD"), "EURUSD")
        self.assertEqual(self.bridge.map_symbol("frxGBPUSD"), "GBPUSD.m")
        self.assertEqual(self.bridge.map_symbol("frxUSDJPY"), "USDJPY")

    def test_mock_connect_and_status(self):
        res = self.bridge.connect()
        self.assertTrue(res["success"])
        self.assertTrue(res["connected"])
        self.assertTrue(res["mock"])

        status = self.bridge.get_status()
        self.assertTrue(status["connected"])
        self.assertTrue(status["mock"])

    def test_account_info(self):
        self.bridge.connect()
        acc = self.bridge.get_account_info()
        self.assertEqual(acc["login"], 123456)
        self.assertEqual(acc["server"], "Demo-Server")
        self.assertEqual(acc["balance"], 10000.0)

    def test_quotes_and_candles(self):
        self.bridge.connect()
        quote = self.bridge.get_quote("frxEURUSD")
        self.assertEqual(quote["symbol"], "frxEURUSD")
        self.assertEqual(quote["mt5_symbol"], "EURUSD")
        self.assertIn("bid", quote)
        self.assertIn("ask", quote)

        candles = self.bridge.fetch_candles("frxEURUSD", timeframe="5m", count=20)
        self.assertEqual(len(candles), 20)
        self.assertIn("close", candles[0])

    def test_order_placement_and_close(self):
        self.bridge.connect()
        order_res = self.bridge.place_order(
            symbol="frxEURUSD",
            order_type="BUY",
            volume=0.1,
            sl=1.0750,
            tp=1.0950,
        )
        self.assertTrue(order_res["success"])
        self.assertEqual(order_res["order_type"], "BUY")
        self.assertEqual(order_res["volume"], 0.1)

        ticket = order_res["ticket"]
        close_res = self.bridge.close_position(ticket)
        self.assertTrue(close_res["success"])

    def test_is_mt5_available_boolean(self):
        self.assertIsInstance(is_mt5_available(), bool)


if __name__ == "__main__":
    unittest.main()
