"""Offline tests for market regime, correlation snapshot, and their CLI, tool,
and MCP surfaces. Every series is generated from a fixed seed."""

from __future__ import annotations

import io
import json
import math
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neezy_backend import cli, menu
from neezy_backend.analytics import correlation_snapshot
from neezy_backend.database import LocalDatabase
from neezy_backend.mcp_tools import PUBLIC_READ_ONLY_TOOLS, register_app_tools
from neezy_backend.regime import market_regime
from neezy_backend.remote import AppCommandBridge
from neezy_backend.tools import ToolPermission, ToolRegistry, register_default_tools

REGIMES = {"trend_up", "trend_down", "range", "squeeze", "unknown"}


def walk(
    count: int,
    seed: int,
    *,
    drift: float = 0.0,
    vol: float = 0.001,
    quiet_tail: int = 0,
) -> list[tuple[int, float, float, float, float]]:
    """Random walk with optional quiet final bars. Oldest first."""
    rng = random.Random(seed)
    price, rows = 1.1, []
    for index in range(count):
        scale = 0.00005 if index >= count - quiet_tail else vol
        open_ = price
        close = open_ * (1 + drift + rng.gauss(0.0, scale))
        high = max(open_, close) * (1 + abs(rng.gauss(0, scale / 3)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, scale / 3)))
        rows.append((index * 60, open_, high, low, close))
        price = close
    return rows


def zigzag(count: int) -> list[tuple[int, float, float, float, float]]:
    """Closes alternate around 1.1, so up and down movement balance out."""
    rows, price = [], 1.1
    for index in range(count):
        close = 1.1 + (0.0008 if index % 2 else -0.0008)
        close += 0.00003 * math.sin(index)
        open_ = price
        high = max(open_, close) + 0.0002
        low = min(open_, close) - 0.0002
        rows.append((index * 60, open_, high, low, close))
        price = close
    return rows


class MarketRegimeTests(unittest.TestCase):
    def test_strong_uptrend_reads_trend_up(self) -> None:
        result = market_regime(walk(200, 1, drift=0.002, vol=0.0003))
        self.assertEqual(result["regime"], "trend_up")
        self.assertGreater(result["plus_di"], result["minus_di"])
        self.assertGreaterEqual(result["adx"], 25.0)

    def test_strong_downtrend_reads_trend_down(self) -> None:
        result = market_regime(walk(200, 1, drift=-0.002, vol=0.0003))
        self.assertEqual(result["regime"], "trend_down")
        self.assertGreater(result["minus_di"], result["plus_di"])

    def test_balanced_oscillation_reads_range(self) -> None:
        result = market_regime(zigzag(200))
        self.assertEqual(result["regime"], "range")
        self.assertLess(result["adx"], 25.0)

    def test_quiet_tail_after_volatility_reads_squeeze(self) -> None:
        result = market_regime(walk(200, 6, quiet_tail=15))
        self.assertEqual(result["regime"], "squeeze")
        self.assertLessEqual(result["bandwidth_percentile"], 20.0)
        self.assertEqual(result["volatility"], "contracting")
        self.assertIn("Squeeze", result["summary"])

    def test_short_history_is_unknown_not_guessed(self) -> None:
        result = market_regime(walk(30, 2))
        self.assertEqual(result["regime"], "unknown")
        self.assertEqual(result["candles_used"], 29)

    def test_sixty_rows_is_still_unknown_because_last_bar_is_dropped(self) -> None:
        self.assertEqual(market_regime(walk(60, 2))["regime"], "unknown")
        self.assertNotEqual(market_regime(walk(61, 2))["regime"], "unknown")

    def test_forming_last_candle_does_not_change_the_read(self) -> None:
        rows = walk(200, 6, quiet_tail=15)
        changed = [*rows[:-1], (rows[-1][0], 1.0, 9.0, 0.1, 1.0)]
        self.assertEqual(market_regime(rows), market_regime(changed))

    def test_malformed_row_is_rejected(self) -> None:
        rows = walk(100, 3)
        rows[10] = (rows[10][0], 1.0, 1.0)
        with self.assertRaises(ValueError):
            market_regime(rows)

    def test_non_finite_value_is_rejected(self) -> None:
        rows = walk(100, 3)
        rows[10] = (rows[10][0], 1.0, math.nan, 1.0, 1.0)
        with self.assertRaises(ValueError):
            market_regime(rows)

    def test_every_result_uses_a_known_regime(self) -> None:
        for rows in (walk(200, 4), zigzag(200), walk(30, 1)):
            self.assertIn(market_regime(rows)["regime"], REGIMES)


class CorrelationSnapshotTests(unittest.TestCase):
    def test_identical_series_correlate_perfectly_and_rank_first(self) -> None:
        base = [row[4] for row in walk(120, 5)]
        other = [row[4] for row in walk(120, 9)]
        result = correlation_snapshot(
            {"a": base, "b": list(base), "c": other}, window=100
        )
        top = result["strongest"][0]
        self.assertEqual({top["first"], top["second"]}, {"a", "b"})
        self.assertAlmostEqual(top["correlation"], 1.0, places=3)
        self.assertEqual(result["matrix"]["a"]["a"], 1.0)
        self.assertEqual(result["symbols"], ["a", "b", "c"])

    def test_values_are_rounded_to_three_places(self) -> None:
        closes = {
            "a": [row[4] for row in walk(120, 5)],
            "b": [row[4] for row in walk(120, 9)],
        }
        result = correlation_snapshot(closes, window=100)
        value = result["matrix"]["a"]["b"]
        self.assertEqual(value, round(value, 3))


class RegimeCliTests(unittest.TestCase):
    @staticmethod
    def fake_fetch(symbol, seconds, count):
        if symbol == "frxGBPUSD":
            raise ConnectionError("Could not reach any market data endpoint")
        return walk(count, seed=sum(map(ord, symbol)), drift=0.002, vol=0.0003)

    def run_cli(self, *argv):
        out = io.StringIO()
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            code = cli.main(list(argv), fetch=self.fake_fetch, out=out)
        return code, out.getvalue(), err.getvalue()

    def test_json_output_carries_regime_and_market(self) -> None:
        code, text, _ = self.run_cli("regime", "frxEURUSD", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(text)
        self.assertEqual(payload["symbol"], "frxEURUSD")
        self.assertEqual(payload["timeframe"], "5m")
        self.assertIn(payload["regime"], REGIMES)

    def test_text_output_is_plain_and_has_disclaimer(self) -> None:
        code, text, _ = self.run_cli("regime", "frxEURUSD", "-t", "15m")
        self.assertEqual(code, 0)
        self.assertIn("Regime", text)
        self.assertIn("Volatility", text)
        self.assertIn("not financial advice", text)
        self.assertNotIn("\x1b[", text)

    def test_fetch_failure_exits_two_with_message(self) -> None:
        code, text, err = self.run_cli("regime", "frxGBPUSD")
        self.assertEqual(code, 2)
        self.assertEqual(text, "")
        self.assertIn("Could not reach", err)

    def test_menu_key_r_runs_regime_for_the_typed_symbol(self) -> None:
        calls: list[list[str]] = []
        feed = iter(["r", "frxEURUSD", "0"])
        menu.run_menu(
            io.StringIO(),
            input_fn=lambda _prompt: next(feed),
            run=lambda argv: calls.append(argv) or 0,
            color=False,
        )
        self.assertEqual(calls, [["regime", "frxEURUSD"]])


class RegimeToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.fetched: list[str] = []

        def fake_fetch(symbol, seconds, count):
            self.fetched.append(symbol)
            if symbol == "frxGBPUSD":
                raise ConnectionError("offline")
            return walk(count, seed=sum(map(ord, symbol)), drift=0.002, vol=0.0003)

        patcher = mock.patch("neezy_backend.stream.fetch_candles", new=fake_fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        register_default_tools(self.registry)

    def test_both_tools_are_read_only(self) -> None:
        for name in ("market_regime", "correlation_snapshot"):
            with self.subTest(tool=name):
                self.assertIs(
                    self.registry.get(name).permission, ToolPermission.READ_ONLY
                )

    def test_regime_tool_reports_one_market(self) -> None:
        text = self.registry.execute("market_regime", symbol="frxEURUSD")
        self.assertIn("Market: frxEURUSD", text)
        self.assertIn("Regime:", text)

    def test_regime_tool_rejects_unknown_market(self) -> None:
        with self.assertRaises(ValueError):
            self.registry.execute("market_regime", symbol="NOPE")

    def test_snapshot_defaults_to_forex_majors(self) -> None:
        text = self.registry.execute("correlation_snapshot")
        self.assertIn("Correlation", text)
        self.assertIn("frxEURUSD", self.fetched)
        self.assertIn("frxUSDCHF", self.fetched)

    def test_snapshot_reports_unavailable_markets(self) -> None:
        text = self.registry.execute(
            "correlation_snapshot", symbols="frxEURUSD,frxGBPUSD,frxUSDJPY"
        )
        self.assertIn("Unavailable: frxGBPUSD", text)

    def test_snapshot_caps_market_count(self) -> None:
        names = ",".join(
            ["frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD", "frxUSDCHF"] * 2
            + ["frxEURGBP", "frxEURJPY"]
        )
        with self.assertRaises(ValueError):
            self.registry.execute("correlation_snapshot", symbols=names)


class RegimeMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = LocalDatabase(Path(directory.name) / "test.db")
        self.addCleanup(self.db.close)
        self.registry = register_app_tools(ToolRegistry(), self.db, AppCommandBridge())

    def _tool(self, name):
        tool = self.registry.get(name)
        self.assertIsNotNone(tool)
        return tool.func

    def test_new_tools_stay_off_the_public_tunnel(self) -> None:
        self.assertNotIn("get_market_regime", PUBLIC_READ_ONLY_TOOLS)
        self.assertNotIn("get_correlation_snapshot", PUBLIC_READ_ONLY_TOOLS)

    def test_regime_reads_stored_candles(self) -> None:
        self.db.save_candles("frxEURUSD", "5m", walk(200, 1, drift=0.002, vol=0.0003))
        result = self._tool("get_market_regime")("frxEURUSD", "5m")
        self.assertEqual(result["symbol"], "frxEURUSD")
        self.assertEqual(result["regime"], "trend_up")

    def test_regime_rejects_unknown_market_and_timeframe(self) -> None:
        func = self._tool("get_market_regime")
        with self.assertRaises(ValueError):
            func("NOPE", "5m")
        with self.assertRaises(ValueError):
            func("frxEURUSD", "7m")

    def test_snapshot_aligns_markets_by_timestamp(self) -> None:
        shared = walk(150, 4)
        self.db.save_candles("frxEURUSD", "5m", shared)
        # Starts 20 bars later: only the shared timestamps may be correlated.
        self.db.save_candles("frxGBPUSD", "5m", shared[20:])
        self.db.save_candles("frxUSDJPY", "5m", walk(150, 8))
        result = self._tool("get_correlation_snapshot")(
            "frxEURUSD,frxGBPUSD,frxUSDJPY", "5m", 100
        )
        self.assertEqual(result["observations"], 100)
        pair = result["strongest"][0]
        self.assertEqual({pair["first"], pair["second"]}, {"frxEURUSD", "frxGBPUSD"})
        self.assertAlmostEqual(pair["correlation"], 1.0, places=3)

    def test_snapshot_needs_shared_history(self) -> None:
        self.db.save_candles("frxEURUSD", "5m", walk(8, 1))
        self.db.save_candles("frxGBPUSD", "5m", walk(8, 2))
        with self.assertRaises(ValueError):
            self._tool("get_correlation_snapshot")("frxEURUSD,frxGBPUSD")


if __name__ == "__main__":
    unittest.main()
