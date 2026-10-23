"""Natural-language routing for the chat-first terminal workspace."""

import unittest

from neezy_backend.cli_chat import extract_symbol, extract_timeframe, natural_language


class SymbolAndTimeframeTests(unittest.TestCase):
    def test_forex_pair_and_catalog_symbol(self):
        self.assertEqual(extract_symbol("analyse EUR/USD"), "frxEURUSD")
        self.assertEqual(extract_symbol("analyse R_100"), "R_100")
        self.assertEqual(extract_symbol("analyse gold"), "frxXAUUSD")
        self.assertIsNone(extract_symbol("what is market structure?"))

    def test_compact_and_spoken_timeframes(self):
        self.assertEqual(extract_timeframe("EURUSD on 15m"), "15m")
        self.assertEqual(extract_timeframe("EURUSD on 30 minutes"), "30m")
        self.assertEqual(extract_timeframe("EURUSD on 4 hours"), "4h")
        self.assertEqual(extract_timeframe("daily market scan"), "1d")


class NaturalLanguageTests(unittest.TestCase):
    def assertArgv(self, text, expected):
        route = natural_language(text)
        self.assertEqual(route.argv, tuple(expected))
        self.assertEqual(route.message, "")

    def test_analysis_scan_and_research(self):
        self.assertArgv(
            "please analyse EURUSD on 15m",
            ["analyze", "frxEURUSD", "-t", "15m"],
        )
        self.assertArgv("scan the market on 5m", ["scan", "-t", "5m"])
        self.assertArgv("backtest GBPUSD on 1h", ["backtest", "frxGBPUSD", "-t", "1h"])
        self.assertArgv("show the regime for gold", ["regime", "frxXAUUSD"])
        self.assertArgv("chart EURUSD on 15m", ["chart", "frxEURUSD", "-t", "15m"])
        self.assertArgv("show executor status", ["bot", "status"])
        self.assertArgv("check numerical kernel status", ["kernels", "status"])
        self.assertArgv("benchmark the kernels", ["kernels", "benchmark"])
        self.assertArgv("list strategies", ["strategies"])

    def test_mt5_requests_remain_read_only(self):
        self.assertArgv("show MT5 status", ["mt5", "status"])
        self.assertArgv("show the MT5 account balance", ["mt5", "account"])
        self.assertArgv("show MT5 quote for EURUSD", ["mt5", "quote", "frxEURUSD"])
        self.assertArgv(
            "show MT5 candles for EURUSD on 1h",
            ["mt5", "candles", "frxEURUSD", "-t", "1h"],
        )
        self.assertArgv("run the MT5 preflight", ["mt5", "preflight"])

    def test_local_data_and_provider_shortcuts(self):
        self.assertArgv("show supported markets", ["markets"])
        self.assertArgv("show AI providers", ["ai", "providers"])
        self.assertArgv("show database stats", ["db", "stats"])
        self.assertArgv("show recent history", ["history"])
        self.assertArgv("show local knowledge", ["knowledge"])
        self.assertArgv("list datasets", ["datasets"])

    def test_general_question_uses_existing_ai_chat(self):
        self.assertArgv(
            "what is a fair value gap?",
            ["ai", "chat", "what is a fair value gap?"],
        )
        self.assertArgv(
            "ask Gemini what is liquidity?",
            ["ai", "chat", "ask Gemini what is liquidity?", "--provider", "gemini"],
        )

    def test_help_and_missing_symbol_stay_local(self):
        help_route = natural_language("help")
        self.assertEqual(help_route.argv, ())
        self.assertIn("plain language", help_route.message)
        missing = natural_language("analyse the market")
        self.assertEqual(missing.argv, ())
        self.assertIn("Which market", missing.message)

    def test_trade_intent_is_redirected_to_explicit_palette(self):
        for prompt in (
            "buy EURUSD now",
            "sell gold",
            "place a live order for EURUSD",
            "please open a trade on GBPUSD",
            "execute the order",
        ):
            with self.subTest(prompt=prompt):
                route = natural_language(prompt)
                self.assertEqual(route.argv, ())
                self.assertIn("typed SEND confirmation", route.message)

    def test_educational_order_question_still_reaches_ai(self):
        route = natural_language("what is a buy stop order?")
        self.assertEqual(route.argv[:2], ("ai", "chat"))

    def test_educational_questions_are_not_mistaken_for_commands(self):
        for prompt in ("what is market analysis?", "how does backtesting work?"):
            with self.subTest(prompt=prompt):
                route = natural_language(prompt)
                self.assertEqual(route.argv, ("ai", "chat", prompt))


if __name__ == "__main__":
    unittest.main()
