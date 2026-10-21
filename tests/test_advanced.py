"""Tests for NEEZY's advanced analytics, risk, backtest, alert, and CLI tools."""

from __future__ import annotations

import io
import json
import math
import os
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neezy_backend import cli
from neezy_backend.agent import AgentPlanner
from neezy_backend.alerts import AlertEngine, AlertRule, AlertRuleStore
from neezy_backend.analytics import (
    correlation_matrix,
    opportunity_score,
    pearson,
    rank_opportunities,
    strongest_pairs,
)
from neezy_backend.backtest import BacktestConfig, run_backtest
from neezy_backend.database import LocalDatabase
from neezy_backend.indicators import adx, analyze, bollinger, sma, stochastic
from neezy_backend.markets import (
    PUBLIC_WS_URL,
    format_price,
    granularity,
    pip_size,
    ws_urls,
)
from neezy_backend.patterns import detect_patterns, pivot_points, swing_levels
from neezy_backend.risk import atr_levels, position_size
from neezy_backend.storage import SignalHistoryStore
from neezy_backend.stream import (
    BROWSER_HEADERS,
    describe_connection_error,
    fetch_candles,
    parse_candle,
    parse_history_response,
)
from neezy_backend.tools import ToolPermission, ToolRegistry


def random_walk(count: int, *, seed: int = 7, drift: float = 0.0, start=1.1):
    rng = random.Random(seed)
    candles, previous = [], start
    for index in range(count):
        close = max(0.5, previous + drift + rng.gauss(0, 0.0004))
        high = max(previous, close) + abs(rng.gauss(0, 0.0002))
        low = min(previous, close) - abs(rng.gauss(0, 0.0002))
        candles.append((index * 300, previous, high, low, close))
        previous = close
    return candles


class AgentAndMemoryTests(unittest.TestCase):
    def test_database_fts_memory_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite3"
            db = LocalDatabase(db_path)
            db.add_memory(
                "EURUSD trended bullishly after RSI divergence", category="notes"
            )
            db.add_memory(
                "USDJPY showed strong resistance near 150.0", category="notes"
            )

            results = db.search_memory("EURUSD divergence")
            self.assertEqual(len(results), 1)
            self.assertIn("EURUSD", results[0]["content"])

    def test_agent_planner_loop(self) -> None:
        planner = AgentPlanner()
        steps = planner.create_plan("Analyze EURUSD")
        self.assertEqual(len(steps), 1)
        executed_steps = planner.execute_plan(steps, dry_run=True)
        self.assertEqual(executed_steps[0].status, "completed")
        self.assertEqual(executed_steps[0].result["status"], "dry_run")
        from neezy_backend.markets import SYMBOLS

        symbol = steps[0].tool_args["symbol"]
        self.assertIn(symbol, SYMBOLS)


def _drift_candles(count: int) -> list[tuple[int, float, float, float, float]]:
    candles, previous = [], 1.1
    for index in range(count):
        close = previous + 0.00001
        candles.append(
            (
                index * 900,
                previous,
                max(previous, close) + 0.0004,
                min(previous, close) - 0.0004,
                close,
            )
        )
        previous = close
    return candles


class DefaultToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = mock.patch.dict(os.environ, {"NEEZY_HOME": self._tmp.name})
        env.start()
        self.addCleanup(env.stop)

    def _registry(self):
        from neezy_backend.tools import ToolRegistry, register_default_tools

        registry = ToolRegistry()
        register_default_tools(registry)
        return registry

    def test_new_tools_carry_the_right_permissions(self) -> None:
        permissions = {
            tool["name"]: tool["permission"] for tool in self._registry().list_tools()
        }
        self.assertEqual(permissions["scan_strategies"], "READ_ONLY")
        self.assertEqual(permissions["plan_risk"], "READ_ONLY")
        self.assertEqual(permissions["search_memory"], "READ_ONLY")
        self.assertEqual(permissions["recent_signals"], "READ_ONLY")
        self.assertEqual(permissions["add_memory"], "WRITE")

    def test_scan_strategies_reports_consensus_for_fetched_candles(self) -> None:
        with mock.patch(
            "neezy_backend.stream.fetch_candles", return_value=_drift_candles(120)
        ) as fetch:
            # The tool binds fetch_candles at registration, so register inside
            # the patch.
            output = self._registry().execute("scan_strategies", dry_run=False)
        self.assertEqual(fetch.call_args.args, ("frxEURUSD", 900, 300))
        self.assertIn("Market: frxEURUSD (15m)", output)
        self.assertIn("Consensus:", output)

    def test_scan_strategies_rejects_unknown_market(self) -> None:
        with self.assertRaises(ValueError):
            self._registry().execute("scan_strategies", symbol="NOPE")

    def test_plan_risk_accepts_string_arguments_from_the_agent(self) -> None:
        output = self._registry().execute(
            "plan_risk",
            dry_run=False,
            symbol="frxEURUSD",
            balance="10000",
            risk_percent="1",
            entry="1.1000",
            stop="1.0950",
        )
        self.assertTrue(output.startswith("BUY frxEURUSD lots="))
        self.assertIn("target=1.11", output)

    def test_plan_risk_rejects_stop_equal_to_entry(self) -> None:
        with self.assertRaises(ValueError):
            self._registry().execute(
                "plan_risk",
                dry_run=False,
                symbol="frxEURUSD",
                balance=10000,
                risk_percent=1,
                entry=1.1,
                stop=1.1,
            )

    def test_memory_round_trip_through_the_local_database(self) -> None:
        registry = self._registry()
        saved = registry.execute(
            "add_memory",
            dry_run=False,
            confirm=True,
            content="Volatility spike after news",
            category="notes",
        )
        self.assertEqual(saved, "Memory saved as #1")
        found = registry.execute("search_memory", dry_run=False, query="volatility")
        self.assertIn("#1 [notes] Volatility spike after news", found)
        self.assertEqual(
            registry.execute("search_memory", dry_run=False, query="unrelated"),
            "No matching memory.",
        )

    def test_add_memory_rejects_blank_content(self) -> None:
        with self.assertRaises(ValueError):
            self._registry().execute(
                "add_memory", dry_run=False, confirm=True, content="   "
            )

    def test_recent_signals_lists_saved_rows_newest_first(self) -> None:
        from neezy_backend.database import LocalDatabase

        registry = self._registry()
        self.assertEqual(
            registry.execute("recent_signals", dry_run=False), "No saved signals."
        )
        with LocalDatabase() as database:
            database.save_signal(
                symbol="frxEURUSD", timeframe="15m", signal="BUY", score=3.0
            )
            database.save_signal(
                symbol="frxGBPUSD", timeframe="1h", signal="SELL", score=-2.0
            )
        lines = registry.execute(
            "recent_signals", dry_run=False, limit="5"
        ).splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("frxGBPUSD 1h SELL", lines[0])
        only_eur = registry.execute("recent_signals", dry_run=False, symbol="frxEURUSD")
        self.assertEqual(len(only_eur.splitlines()), 1)


class ToolRegistryTests(unittest.TestCase):
    def test_registry_registration_and_dry_run(self) -> None:
        registry = ToolRegistry()

        def sample_tool(text: str) -> str:
            return f"Processed: {text}"

        registry.register(
            "sample",
            "A sample tool",
            sample_tool,
            permission=ToolPermission.WRITE,
        )

        tools = registry.list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "sample")
        self.assertEqual(tools[0]["permission"], "WRITE")

        # Dry run test
        dry_res = registry.execute("sample", dry_run=True, text="hello")
        self.assertEqual(dry_res["status"], "dry_run")
        self.assertEqual(dry_res["kwargs"], {"text": "hello"})

        # Normal execution test
        res = registry.execute("sample", dry_run=False, confirm=True, text="hello")
        self.assertEqual(res, "Processed: hello")

    def test_read_market_tool_uses_real_granularity_and_market_keys(self) -> None:
        from neezy_backend.tools import register_default_tools

        candles, previous = [], 1.1
        for index in range(120):
            close = previous + 0.00001
            candles.append(
                (
                    index * 900,
                    previous,
                    max(previous, close) + 0.0004,
                    min(previous, close) - 0.0004,
                    close,
                )
            )
            previous = close
        registry = ToolRegistry()
        with mock.patch(
            "neezy_backend.stream.fetch_candles", return_value=candles
        ) as fetch:
            # Register inside the patch: the tool binds fetch_candles at registration.
            register_default_tools(registry)
            default_output = registry.execute("read_market", dry_run=False)
            registry.execute(
                "read_market",
                dry_run=False,
                symbol="frxGBPUSD",
                timeframe="1h",
            )
        self.assertIn("Market: EUR/USD (15m)", default_output)
        self.assertEqual(fetch.call_args_list[0].args, ("frxEURUSD", 900, 100))
        self.assertEqual(fetch.call_args_list[1].args, ("frxGBPUSD", 3600, 100))

        with self.assertRaisesRegex(ValueError, "Unknown market"):
            registry.execute("read_market", dry_run=False, symbol="EURUSD")
        with self.assertRaisesRegex(ValueError, "Unknown timeframe"):
            registry.execute("read_market", dry_run=False, timeframe="7m")


class IndicatorExtensionTests(unittest.TestCase):
    def test_sma_warms_up_then_averages(self) -> None:
        self.assertEqual(sma([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_bollinger_flat_and_wide(self) -> None:
        flat = bollinger([1.0] * 20)
        self.assertEqual(flat["upper"], flat["lower"])
        self.assertEqual(flat["percent_b"], 0.5)
        bands = bollinger([float(i) for i in range(1, 21)])
        self.assertGreater(bands["percent_b"], 0.8)
        self.assertIsNone(bollinger([1.0] * 5))

    def test_stochastic_extremes(self) -> None:
        highs = [float(i + 1) for i in range(20)]
        lows = [float(i) for i in range(20)]
        closes = [float(i + 1) for i in range(20)]
        result = stochastic(highs, lows, closes)
        self.assertAlmostEqual(result["k"], 100.0)
        self.assertIsNone(stochastic(highs[:5], lows[:5], closes[:5]))

    def test_adx_strong_for_trend_and_bounded(self) -> None:
        candles = random_walk(150, drift=0.0006)
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]
        closes = [c[4] for c in candles]
        result = adx(highs, lows, closes)
        self.assertGreater(result["adx"], 25)
        self.assertGreater(result["plus_di"], result["minus_di"])
        self.assertTrue(0 <= result["adx"] <= 100)
        self.assertIsNone(adx(highs[:10], lows[:10], closes[:10]))

    def test_analysis_includes_context_without_changing_score_range(self) -> None:
        result = analyze(random_walk(200, seed=3))
        for key in ("bollinger", "stochastic", "adx", "regime"):
            self.assertIn(key, result)
        self.assertIn(result["regime"], {"Trending", "Ranging", "Squeeze"})
        self.assertTrue(-4 <= result["score"] <= 4)


class PatternTests(unittest.TestCase):
    def test_engulfing_and_hammer(self) -> None:
        bullish = [(0, 1.10, 1.105, 1.09, 1.095), (1, 1.094, 1.112, 1.093, 1.111)]
        names = {p["name"] for p in detect_patterns(bullish)}
        self.assertIn("Bullish engulfing", names)
        hammer = [(0, 1.100, 1.1035, 1.092, 1.103)]
        self.assertEqual(detect_patterns(hammer)[0]["name"], "Hammer")
        doji = [(0, 1.1, 1.11, 1.09, 1.1001)]
        self.assertEqual(detect_patterns(doji)[0]["name"], "Doji")
        self.assertEqual(detect_patterns([]), [])

    def test_pivots_and_swing_levels(self) -> None:
        pivots = pivot_points((0, 1.0, 2.0, 1.0, 1.5))
        self.assertAlmostEqual(pivots["pivot"], 1.5)
        self.assertGreater(pivots["r1"], pivots["pivot"])
        self.assertLess(pivots["s1"], pivots["pivot"])
        candles = random_walk(120, seed=11)
        levels = swing_levels(candles)
        last = candles[-1][4]
        self.assertTrue(all(level > last for level in levels["resistance"]))
        self.assertTrue(all(level < last for level in levels["support"]))


class RiskTests(unittest.TestCase):
    def test_position_size_respects_risk_budget(self) -> None:
        plan = position_size(
            symbol="frxEURUSD", balance=10_000, risk_percent=1, entry=1.1, stop=1.098
        )
        self.assertEqual(plan.direction, "BUY")
        self.assertAlmostEqual(plan.stop_pips, 20.0)
        self.assertAlmostEqual(plan.lots, 0.5)
        self.assertLessEqual(plan.risk_amount, 100.0 + 1e-9)
        self.assertAlmostEqual(plan.target, 1.104)

    def test_short_jpy_and_rounding_down(self) -> None:
        plan = position_size(
            symbol="frxUSDJPY",
            balance=5_000,
            risk_percent=0.7,
            entry=150.0,
            stop=150.33,
            pip_value_per_lot=6.7,
        )
        self.assertEqual(plan.direction, "SELL")
        self.assertAlmostEqual(plan.stop_pips, 33.0)
        self.assertLessEqual(plan.risk_amount, 35.0)
        self.assertLess(plan.target, plan.entry)

    def test_invalid_risk_inputs(self) -> None:
        with self.assertRaises(ValueError):
            position_size(
                symbol="frxEURUSD", balance=1000, risk_percent=1, entry=1.1, stop=1.1
            )
        with self.assertRaises(ValueError):
            position_size(
                symbol="frxEURUSD", balance=-1, risk_percent=1, entry=1.1, stop=1.0
            )
        with self.assertRaises(ValueError):
            atr_levels("HOLD", 1.1, 0.001)

    def test_atr_levels(self) -> None:
        stop, target = atr_levels("BUY", 1.1, 0.001, 2, 3)
        self.assertAlmostEqual(stop, 1.098)
        self.assertAlmostEqual(target, 1.106)
        stop, target = atr_levels("sell", 1.1, 0.001)
        self.assertGreater(stop, 1.1)
        self.assertLess(target, 1.1)


class BacktestTests(unittest.TestCase):
    def test_trending_market_produces_profitable_longs(self) -> None:
        result = run_backtest(random_walk(600, drift=0.0004, seed=5))
        stats = result.stats
        self.assertGreater(stats["trades"], 0)
        self.assertGreater(stats["long_trades"], stats["short_trades"])
        self.assertGreater(stats["total_r"], 0)
        self.assertEqual(len(result.equity_curve), stats["trades"])

    def test_no_lookahead_future_candles_do_not_change_past_trades(self) -> None:
        candles = random_walk(500, seed=9)
        short = run_backtest(candles[:300])
        long = run_backtest(candles)
        closed_short = [t for t in short.trades if t.reason != "end of data"]
        self.assertEqual(
            [(t.entry_time, t.exit_time, t.r_multiple) for t in closed_short],
            [(t.entry_time, t.exit_time, t.r_multiple) for t in long.trades][
                : len(closed_short)
            ],
        )

    def test_stop_and_target_bound_losses(self) -> None:
        result = run_backtest(
            random_walk(500, seed=2),
            BacktestConfig(exit_on_opposite=False, reward_to_risk=1.5),
        )
        for trade in result.trades:
            if trade.reason == "stop":
                self.assertAlmostEqual(trade.r_multiple, -1.0)
            if trade.reason == "target":
                self.assertAlmostEqual(trade.r_multiple, 1.5)

    def test_short_history_and_invalid_config(self) -> None:
        self.assertEqual(run_backtest(random_walk(50)).stats["trades"], 0)
        with self.assertRaises(ValueError):
            BacktestConfig(min_score=0)
        with self.assertRaises(ValueError):
            BacktestConfig(spread=-1)

    def test_result_serialises_to_json(self) -> None:
        payload = run_backtest(random_walk(300, seed=4)).to_dict()
        json.dumps(cli._finite(payload))


class AnalyticsTests(unittest.TestCase):
    def test_pearson_and_matrix(self) -> None:
        self.assertAlmostEqual(pearson([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)
        self.assertAlmostEqual(pearson([1, 2, 3, 4], [8, 6, 4, 2]), -1.0)
        self.assertIsNone(pearson([1, 1, 1], [1, 2, 3]))
        base = [c[4] for c in random_walk(120, seed=1)]
        mirror = [2.2 - value for value in base]
        other = [c[4] for c in random_walk(120, seed=99)]
        matrix = correlation_matrix({"A": base, "B": mirror, "C": other})
        self.assertLess(matrix["A"]["B"], -0.9)
        self.assertEqual(matrix["A"]["A"], 1.0)
        top = strongest_pairs(matrix, limit=1)[0]
        self.assertEqual({top[0], top[1]}, {"A", "B"})

    def test_opportunity_ranking(self) -> None:
        strong = {"signal": "STRONG BUY", "score": 4, "rsi": 55, "adx": {"adx": 40}}
        weak = {"signal": "BUY", "score": 2, "rsi": 70, "adx": {"adx": 10}}
        neutral = {"signal": "NEUTRAL", "score": 0, "rsi": 50, "adx": None}
        self.assertGreater(opportunity_score(strong), opportunity_score(weak))
        ranked = rank_opportunities({"s": strong, "w": weak, "n": neutral})
        self.assertEqual([item["symbol"] for item in ranked], ["s", "w"])
        self.assertTrue(0 <= opportunity_score(strong) <= 100)


class AlertTests(unittest.TestCase):
    def test_rules_validate(self) -> None:
        with self.assertRaises(ValueError):
            AlertRule("frxEURUSD", "rsi", ">", "abc")
        with self.assertRaises(ValueError):
            AlertRule("frxEURUSD", "signal", ">", "BUY")
        with self.assertRaises(ValueError):
            AlertRule("frxEURUSD", "volume", ">", "1")

    def test_edge_triggered_threshold_and_cross(self) -> None:
        engine = AlertEngine(
            [
                AlertRule("frxEURUSD", "rsi", ">", "70", rule_id="hot"),
                AlertRule("*", "price", "crosses above", "1.2", rule_id="cross"),
                AlertRule("frxEURUSD", "pattern", "==", "doji", rule_id="doji"),
            ]
        )

        def fire(rsi, price, patterns=()):
            rules = engine.evaluate(
                "frxEURUSD", {"rsi": rsi}, price, [{"name": p} for p in patterns]
            )
            return {rule.rule_id for rule in rules}

        self.assertEqual(fire(60, 1.19), set())
        self.assertEqual(fire(75, 1.21), {"hot", "cross"})
        self.assertEqual(fire(76, 1.22), set())
        self.assertEqual(fire(50, 1.18, ["Doji"]), {"doji"})
        self.assertEqual(fire(71, 1.25), {"hot", "cross"})

    def test_store_round_trip_skips_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.json"
            store = AlertRuleStore(path)
            rule = AlertRule("frxEURUSD", "score", ">=", "3", note="momentum")
            store.save([rule])
            self.assertEqual(store.load(), [rule])
            path.write_text(
                json.dumps({"rules": [{"symbol": "x", "metric": "bad"}]}),
                encoding="utf-8",
            )
            self.assertEqual(store.load(), [])
            path.write_text("{oops", encoding="utf-8")
            self.assertEqual(store.load(), [])


class MarketAndParsingTests(unittest.TestCase):
    def test_market_helpers(self) -> None:
        self.assertEqual(format_price("frxUSDJPY", 150.12345), "150.123")
        self.assertEqual(format_price("R_100", 1234.567), "1234.57")
        self.assertEqual(format_price("frxEURUSD", None), "—")
        self.assertEqual(pip_size("frxEURUSD"), 0.0001)
        self.assertEqual(granularity("1h"), 3600)
        with self.assertRaises(ValueError):
            granularity("2m")

    def test_history_response_parsing(self) -> None:
        rows = [
            {"epoch": 60, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15},
            {"epoch": 0, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1},
        ]
        parsed = parse_history_response({"candles": rows})
        self.assertEqual([row[0] for row in parsed], [0, 60])
        with self.assertRaisesRegex(RuntimeError, "rate"):
            parse_history_response({"error": {"message": "rate limited"}})
        with self.assertRaises(ValueError):
            parse_candle({"epoch": 1, "open": 1, "high": 0.5, "low": 1, "close": 1})


class EndpointTests(unittest.TestCase):
    def test_default_endpoints_prefer_public_api_then_legacy_hosts(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEEZY_WS_URL", None)
            os.environ.pop("NEEZY_APP_ID", None)
            urls = ws_urls()
        self.assertEqual(urls[0], PUBLIC_WS_URL)
        self.assertTrue(urls[0].startswith("wss://api.derivws.com/"))
        legacy = urls[1:]
        self.assertGreaterEqual(len(legacy), 2)
        self.assertTrue(all("app_id=1089" in url for url in legacy))
        self.assertEqual(len(set(urls)), len(urls))

    def test_settings_endpoint_pins_one_url_and_env_wins(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(ws_urls("wss://proxy.local/v3"), ("wss://proxy.local/v3",))
            self.assertEqual(ws_urls("  "), ws_urls(""))
        with mock.patch.dict(os.environ, {"NEEZY_WS_URL": "wss://env.local"}):
            self.assertEqual(ws_urls("wss://proxy.local/v3"), ("wss://env.local",))

    def test_endpoint_and_app_id_can_be_overridden(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"NEEZY_WS_URL": "wss://proxy.internal/v3", "NEEZY_APP_ID": "12345"},
            clear=False,
        ):
            self.assertEqual(ws_urls(), ("wss://proxy.internal/v3",))
            os.environ.pop("NEEZY_WS_URL")
            self.assertTrue(all("app_id=12345" in url for url in ws_urls()[1:]))

    def test_cloudflare_520_becomes_one_readable_line(self) -> None:
        raw = (
            "Handshake status 520 <none> -+-+- {'date': 'Tue, 20 Oct 2026', "
            "'content-type': 'text/plain; charset=UTF-8', 'server': 'cloudflare', "
            "'cf-ray': 'a4d8ee17eb4f3419-JNB'} -+-+- error code: 520"
        )
        message = describe_connection_error(raw)
        self.assertIn("520", message)
        self.assertIn("down or refused", message)
        self.assertNotIn("cf-ray", message)
        self.assertNotIn("content-type", message)
        self.assertLess(len(message), 200)

    def test_stream_client_accepts_a_candidate_list(self) -> None:
        from neezy_backend.events import EventBus
        from neezy_backend.stream import DerivStreamClient

        client = DerivStreamClient(
            ("wss://a.invalid/v3", "wss://b.invalid/v3"), EventBus()
        )
        self.assertEqual(client.url, "wss://a.invalid/v3")
        self.assertEqual(len(client.urls), 2)
        self.assertEqual(client.headers, BROWSER_HEADERS)
        with self.assertRaises(ValueError):
            DerivStreamClient((), EventBus())


class FetchTests(unittest.TestCase):
    def test_fetch_fails_over_to_the_next_endpoint(self) -> None:
        import websocket

        connection = mock.Mock()
        connection.recv.return_value = json.dumps(
            {
                "msg_type": "candles",
                "candles": [
                    {"epoch": 0, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1}
                ],
            }
        )
        blocked = websocket.WebSocketBadStatusException("x", 520)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NEEZY_WS_URL", None)
            targets = ws_urls()
            with mock.patch.object(
                websocket,
                "create_connection",
                mock.Mock(side_effect=[blocked, connection]),
            ) as connect:
                rows = fetch_candles("frxEURUSD", 60, 10)
            self.assertEqual(connect.call_count, 2)
            self.assertEqual(connect.call_args_list[1].args[0], targets[1])
        self.assertEqual(rows, [(0, 1.1, 1.2, 1.0, 1.1)])

    def test_connection_failures_become_connection_errors(self) -> None:
        import websocket

        failing = mock.Mock(side_effect=websocket.WebSocketBadStatusException("x", 520))
        with mock.patch.object(websocket, "create_connection", failing):
            with self.assertRaises(ConnectionError):
                fetch_candles("frxEURUSD", 60, 10, url="wss://example.invalid")

    def test_fetch_parses_response_and_closes(self) -> None:
        import websocket

        connection = mock.Mock()
        connection.recv.return_value = json.dumps(
            {
                "msg_type": "candles",
                "candles": [
                    {"epoch": 0, "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1}
                ],
            }
        )
        with mock.patch.object(websocket, "create_connection", return_value=connection):
            rows = fetch_candles("frxEURUSD", 60, 10, url="wss://example.invalid")
        self.assertEqual(rows, [(0, 1.1, 1.2, 1.0, 1.1)])
        connection.close.assert_called_once()
        with self.assertRaises(ValueError):
            fetch_candles("frxEURUSD", 60, 0, url="wss://example.invalid")


class HistoryCompactionTests(unittest.TestCase):
    def test_auto_compaction_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SignalHistoryStore(
                Path(directory) / "h.jsonl", max_bytes=2000, keep_records=5
            )
            for index in range(40):
                store.append(
                    symbol="frxEURUSD",
                    previous="BUY",
                    current="SELL" if index % 2 else "BUY",
                    price=1.1,
                    score=-2,
                )
            self.assertLessEqual(len(store.read()), 25)
            self.assertEqual(store.compact(3), 3)
            summary = store.summary()
            self.assertEqual(summary["total"], 3)
            self.assertEqual(summary["by_symbol"], {"frxEURUSD": 3})


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"NEEZY_HOME": self.directory.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.directory.cleanup)

    @staticmethod
    def fake_fetch(symbol, seconds, count):
        seed = sum(map(ord, symbol))
        return random_walk(max(count, 300), seed=seed, drift=0.0002)[-count:]

    def run_cli(self, *argv):
        out = io.StringIO()
        code = cli.main(list(argv), fetch=self.fake_fetch, out=out)
        return code, out.getvalue()

    def test_scan_json_and_table(self) -> None:
        code, text = self.run_cli("scan", "EURUSD", "gbp/usd", "--json")
        self.assertEqual(code, 0)
        data = json.loads(text)
        self.assertEqual(
            {item["symbol"] for item in data["ranked"]}, {"frxEURUSD", "frxGBPUSD"}
        )
        code, text = self.run_cli("scan", "-t", "1h")
        self.assertEqual(code, 0)
        self.assertIn("EUR/USD", text)

    def test_analyze_backtest_risk_correlation(self) -> None:
        code, text = self.run_cli("analyze", "frxEURUSD")
        self.assertEqual(code, 0)
        self.assertIn("Pivots", text)
        code, text = self.run_cli("backtest", "EURUSD", "-n", "600", "--json")
        self.assertEqual(code, 0)
        self.assertIn("stats", json.loads(text))
        code, text = self.run_cli(
            "risk", "EURUSD", "--balance", "1000", "--entry", "1.1", "--stop", "1.099"
        )
        self.assertEqual(code, 0)
        self.assertIn("lots", text)
        code, text = self.run_cli("correlation", "EURUSD", "GBPUSD", "USDJPY")
        self.assertEqual(code, 0)
        self.assertIn("CORRELATION", text)

    def test_local_model_management_is_available_headlessly(self) -> None:
        model_path = Path(self.directory.name) / "small.gguf"
        model_path.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + bytes(64))
        code, text = self.run_cli("local-model", "add", str(model_path), "--json")
        self.assertEqual(code, 0)
        model = json.loads(text)
        self.assertEqual(model["format"], "gguf")
        code, text = self.run_cli("local-model", "list", "--json")
        self.assertEqual(json.loads(text)[0]["model_id"], model["model_id"])
        code, text = self.run_cli("local-model", "remove", model["model_id"], "--json")
        self.assertEqual(code, 0)
        self.assertTrue(model_path.exists())
        code, text = self.run_cli("local-model", "runtime", "--json")
        self.assertEqual(code, 0)
        self.assertIn("llama_cpp", json.loads(text))

    def test_alert_and_history_commands(self) -> None:
        code, text = self.run_cli("alerts", "add", "EURUSD", "rsi", ">", "70")
        self.assertEqual(code, 0)
        rule_id = text.split()[1].rstrip(":")
        code, text = self.run_cli("alerts", "--json")
        self.assertEqual(json.loads(text)[0]["rule_id"], rule_id)
        self.assertEqual(self.run_cli("alerts", "remove", rule_id)[0], 0)
        self.assertEqual(self.run_cli("alerts", "remove", "missing")[0], 1)
        code, text = self.run_cli("history", "--summary", "--json")
        self.assertEqual(json.loads(text)["total"], 0)

    def test_unknown_market_is_rejected(self) -> None:
        with self.assertRaises(SystemExit), mock.patch("sys.stderr", io.StringIO()):
            self.run_cli("analyze", "NOTAPAIR")

    def test_non_finite_values_are_json_safe(self) -> None:
        self.assertEqual(cli._finite({"pf": math.inf}), {"pf": "inf"})


if __name__ == "__main__":
    unittest.main()
