"""Exhaustive bound-checking for AppSettings (roadmap update #50).

Every ranged field is probed one step outside each bound so validation gaps
and misnamed error messages surface immediately.
"""

import unittest

from neezy_backend.config import AI_PROVIDERS, MARKET_DATA_PROVIDERS, AppSettings


def _bounded_int_fields() -> list[tuple[str, int, int]]:
    return [
        ("polling_ms", 50, 2000),
        ("candle_limit", 60, 1000),
        ("alert_min_score", 1, 4),
        ("history_candles", 60, 1000),
        ("provider_candle_count", 60, 1000),
        ("ml_history_candles", 400, 50000),
        ("ml_epochs", 1, 500),
        ("ml_horizon", 1, 100),
        ("ml_min_samples", 60, 10000),
        ("ml_seed", 0, 2147483647),
        ("pair_lookback", 20, 1000),
        ("pair_min_overlap", 100, 20000),
        ("pair_max_holding", 1, 2000),
        ("insights_max_rows", 5, 200),
        ("mt5_login", 0, 2147483647),
        ("mt5_magic", 1, 2147483647),
        ("dm_min_score", 1, 4),
        ("supertrend_period", 2, 100),
        ("divergence_lookback", 1, 30),
        ("correlation_window", 10, 500),
        ("correlation_baseline", 20, 2000),
        ("retention_days", 1, 3650),
        ("mcp_port", 1024, 65535),
        ("local_llm_context_tokens", 128, 32768),
        ("local_llm_max_tokens", 1, 8192),
        ("local_llm_threads", 1, 16),
        ("local_llm_batch_size", 1, 1024),
        ("local_llm_cpu_memory_mb", 256, 262144),
        ("confluence_horizon", 3, 120),
        ("confluence_min_analogs", 2, 100),
        ("ai_max_tokens", 64, 8192),
    ]


class SettingsBoundsTests(unittest.TestCase):
    def test_defaults_construct(self):
        AppSettings()

    def test_int_fields_reject_just_outside_bounds(self):
        for field, low, high in _bounded_int_fields():
            with self.subTest(field=field):
                with self.assertRaises(ValueError, msg=field):
                    AppSettings().updated(**{field: low - 1})
                with self.assertRaises(ValueError, msg=field):
                    AppSettings().updated(**{field: high + 1})

    def test_int_fields_accept_boundaries(self):
        # pair_min_overlap needs >= 3x pair_lookback to be constructible;
        # correlation_baseline >= correlation_window; ml_probability in range.
        for field, low, high in _bounded_int_fields():
            if field == "pair_min_overlap":
                continue
            with self.subTest(field=field):
                try:
                    AppSettings().updated(**{field: low})
                    AppSettings().updated(**{field: high})
                except ValueError as error:
                    # Boundary values that clash with a cross-field rule are
                    # only acceptable when the error names another field.
                    self.assertNotIn(field, str(error))

    def test_float_fields_reject_just_outside_bounds(self):
        cases = [
            ("reconnect_seconds", 0.5, 60.0),
            ("max_reconnect_seconds", 1.0, 600.0),
            ("supertrend_multiplier", 0.5, 10.0),
            ("default_risk_percent", 0.1, 100.0),
            ("max_drawdown_limit", 0.1, 100.0),
            ("ml_deadband_atr", 0.0, 5.0),
            ("ml_probability", 0.51, 0.99),
            ("ml_fetch_timeout", 2.0, 120.0),
            ("ai_temperature", 0.0, 2.0),
            ("ai_timeout", 5.0, 300.0),
            ("confluence_atr_stop_mult", 0.5, 6.0),
            ("confluence_atr_tp_mult", 0.5, 10.0),
        ]
        for field, low, high in cases:
            with self.subTest(field=field):
                with self.assertRaises(ValueError, msg=field):
                    AppSettings().updated(**{field: low - 0.01})
                with self.assertRaises(ValueError, msg=field):
                    AppSettings().updated(**{field: high + 0.01})

    def test_type_errors_name_the_field(self):
        for field, bad in (
            ("polling_ms", "fast"),
            ("alert_min_score", None),
            ("alerts_enabled", 1),
            ("deriv_endpoint", 123),
            ("watchlist_extra", 5),
            ("telegram_chat_ids", []),
            ("mcp_tunnel_executable", None),
        ):
            with self.subTest(field=field, bad=bad):
                with self.assertRaises(TypeError) as raised:
                    AppSettings().updated(**{field: bad})
                self.assertIn(field, str(raised.exception))

    def test_enums_reject_unknown_values(self):
        for field, _allowed in (
            ("theme", {"Liquid dark", "Midnight blue", "High contrast"}),
            ("strategy", {"SUPERTREND", "MACD", "ICHIMOKU"}),
            ("ai_provider", set(AI_PROVIDERS)),
            ("market_data_provider", set(MARKET_DATA_PROVIDERS)),
            ("default_timeframe", {"1m", "5m", "15m", "1h", "4h", "1d"}),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    AppSettings().updated(**{field: "definitely-not-valid"})

    def test_watchlist_extra_validation(self):
        with self.assertRaises(ValueError) as raised:
            AppSettings().updated(watchlist_extra="NOPE,ALSO-NOPE")
        self.assertIn("unknown extra markets", str(raised.exception))
        # Blank entries are tolerated.
        AppSettings().updated(watchlist_extra="frxEURUSD,, frxGBPUSD")

    def test_deriv_endpoint_scheme_rules(self):
        with self.assertRaises(ValueError):
            AppSettings().updated(deriv_endpoint="http://example")
        with self.assertRaises(ValueError):
            AppSettings().updated(deriv_endpoint="wss://bad url")
        AppSettings().updated(deriv_endpoint="wss://ws.derivws.com")

    def test_unknown_from_dict_keys_ignored(self):
        loaded = AppSettings.from_dict({"polling_ms": 999, "from_the_future": True})
        self.assertEqual(loaded.polling_ms, 999)
        self.assertFalse(hasattr(loaded, "from_the_future"))


if __name__ == "__main__":
    unittest.main()
