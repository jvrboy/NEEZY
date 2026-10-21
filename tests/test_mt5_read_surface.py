"""Read-only MT5 surface: account history, MCP tools, and the agent tool.

Every read must refuse when the terminal is not connected and must label
simulated output. None of these tests may reach order_send.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from neezy_backend import mt5_bridge
from neezy_backend.database import LocalDatabase
from neezy_backend.mcp_tools import PUBLIC_READ_ONLY_TOOLS, register_app_tools
from neezy_backend.mt5_bridge import MT5Bridge
from neezy_backend.remote import AppCommandBridge
from neezy_backend.tools import ToolRegistry, register_default_tools

MT5_TOOLS = ("mt5_positions", "mt5_candles", "mt5_account_history")


def _real_bridge(fake_mt5: mock.Mock | None = None) -> MT5Bridge:
    """Build a non-simulated bridge. The MetaTrader5 package is absent here,
    and MT5Bridge forces mock mode when ``mt5`` is None, so patch a stand-in
    module in before construction."""
    fake = fake_mt5 if fake_mt5 is not None else mock.Mock()
    with mock.patch.object(mt5_bridge, "mt5", fake):
        return MT5Bridge(mock=False)


def _disconnected_bridge(mock_mode: bool = False) -> MT5Bridge:
    bridge = MT5Bridge(mock=mock_mode)
    bridge.connect = mock.Mock(return_value={"success": False, "error": "no terminal"})
    return bridge


class AccountHistoryBridgeTests(unittest.TestCase):
    def test_mock_history_is_labelled_simulated(self) -> None:
        deals = MT5Bridge(mock=True).get_account_history(days=3)
        self.assertEqual(len(deals), 1)
        self.assertTrue(deals[0]["mock"])
        self.assertEqual(deals[0]["entry"], "OUT")

    def test_disconnected_real_bridge_returns_no_deals(self) -> None:
        bridge = _real_bridge()
        self.assertFalse(bridge.connected)
        self.assertEqual(bridge.get_account_history(days=7), [])

    def test_real_history_maps_codes_and_keeps_newest(self) -> None:
        def deal(ticket: int, time: int, kind: int, entry: int) -> SimpleNamespace:
            row = {
                "ticket": ticket,
                "order": ticket + 100,
                "time": time,
                "symbol": "EURUSD",
                "type": kind,
                "entry": entry,
                "volume": 0.1,
                "price": 1.085,
                "profit": 4.2,
                "commission": -0.5,
                "swap": 0.0,
                "comment": "",
            }
            return SimpleNamespace(time=time, _asdict=lambda: row)

        deals = [deal(1, 100, 0, 0), deal(2, 300, 1, 1), deal(3, 200, 0, 3)]
        fake_mt5 = mock.Mock()
        fake_mt5.history_deals_get.return_value = deals

        bridge = _real_bridge(fake_mt5)
        bridge.connected = True
        with mock.patch.object(mt5_bridge, "mt5", fake_mt5):
            rows = bridge.get_account_history(days=2, limit=2)

        start, end = fake_mt5.history_deals_get.call_args.args
        self.assertEqual(end - start, 2 * 86400)
        # Sorted by time, then the last `limit` rows: tickets 3 and 2.
        self.assertEqual([r["ticket"] for r in rows], [3, 2])
        self.assertEqual(rows[0]["type"], "BUY")
        self.assertEqual(rows[0]["entry"], "OUT_BY")
        self.assertEqual(rows[1]["type"], "SELL")
        self.assertEqual(rows[1]["entry"], "OUT")
        self.assertFalse(any(r["mock"] for r in rows))

    def test_real_history_with_no_deals_is_empty(self) -> None:
        fake_mt5 = mock.Mock()
        fake_mt5.history_deals_get.return_value = None
        bridge = _real_bridge(fake_mt5)
        bridge.connected = True
        with mock.patch.object(mt5_bridge, "mt5", fake_mt5):
            self.assertEqual(bridge.get_account_history(days=7), [])

    def test_ready_bridge_reports_disconnect(self) -> None:
        bridge = _disconnected_bridge()
        with mock.patch.object(
            mt5_bridge, "get_global_mt5_bridge", return_value=bridge
        ):
            got, error = mt5_bridge.ready_bridge()
        self.assertIs(got, bridge)
        self.assertIn("MT5 not connected", error)
        self.assertIn("no terminal", error)


class McpMt5ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        db = LocalDatabase(Path(self._dir.name) / "test.db")
        self.addCleanup(db.close)
        self.registry = register_app_tools(ToolRegistry(), db, AppCommandBridge())

    def _run(self, bridge: MT5Bridge, tool: str, **kwargs):
        with mock.patch.object(
            mt5_bridge, "get_global_mt5_bridge", return_value=bridge
        ):
            return self.registry.execute(tool, **kwargs)

    def test_positions_refuse_when_disconnected(self) -> None:
        out = self._run(_disconnected_bridge(), "mt5_positions")
        self.assertIn("error", out)
        self.assertNotIn("positions", out)

    def test_positions_mock_is_flagged(self) -> None:
        out = self._run(MT5Bridge(mock=True), "mt5_positions")
        self.assertTrue(out["mock"])
        self.assertIn("positions", out)

    def test_candles_refuse_when_disconnected(self) -> None:
        out = self._run(_disconnected_bridge(), "mt5_candles", symbol="frxEURUSD")
        self.assertIn("error", out)
        self.assertNotIn("candles", out)

    def test_candles_reject_unknown_timeframe_before_connecting(self) -> None:
        bridge = _disconnected_bridge()
        with self.assertRaises(ValueError) as ctx:
            self._run(bridge, "mt5_candles", symbol="frxEURUSD", timeframe="7m")
        self.assertIn("unknown timeframe", str(ctx.exception))
        bridge.connect.assert_not_called()

    def test_candles_mock_returns_bounded_rows(self) -> None:
        out = self._run(
            MT5Bridge(mock=True),
            "mt5_candles",
            symbol="frxEURUSD",
            timeframe="1h",
            count=5000,
        )
        self.assertTrue(out["mock"])
        self.assertEqual(out["timeframe"], "1h")
        self.assertLessEqual(len(out["candles"]), 1000)

    def test_account_history_refuses_when_disconnected(self) -> None:
        out = self._run(_disconnected_bridge(), "mt5_account_history", days=7)
        self.assertIn("error", out)
        self.assertNotIn("deals", out)

    def test_account_history_clamps_days_and_flags_mock(self) -> None:
        out = self._run(MT5Bridge(mock=True), "mt5_account_history", days=500)
        self.assertEqual(out["days"], 90)
        self.assertTrue(out["mock"])
        self.assertEqual(len(out["deals"]), 1)

    def test_mt5_tools_are_not_public(self) -> None:
        self.assertFalse(set(MT5_TOOLS) & PUBLIC_READ_ONLY_TOOLS)


class AgentMt5HistoryToolTests(unittest.TestCase):
    def _tools(self) -> ToolRegistry:
        registry = ToolRegistry()
        register_default_tools(registry)
        return registry

    def test_history_refuses_when_disconnected(self) -> None:
        with mock.patch.object(
            mt5_bridge, "get_global_mt5_bridge", return_value=_disconnected_bridge()
        ):
            out = self._tools().execute("mt5_history")
        self.assertTrue(out.startswith("MT5 not connected"))

    def test_history_mock_is_labelled_simulated(self) -> None:
        with mock.patch.object(
            mt5_bridge,
            "get_global_mt5_bridge",
            return_value=MT5Bridge(mock=True),
        ):
            out = self._tools().execute("mt5_history", days="3")
        self.assertIn("SIMULATED", out)
        self.assertIn("last 3 days", out)

    def test_history_is_read_only(self) -> None:
        tools = {t["name"]: t["permission"] for t in self._tools().list_tools()}
        self.assertEqual(tools["mt5_history"], "READ_ONLY")


if __name__ == "__main__":
    unittest.main()
