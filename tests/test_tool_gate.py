"""Permission gate for agent tools, MT5 read tools, and the MCP catalog."""

import unittest
from unittest import mock

from neezy_backend.agent import AgentPlanner, PlanStep
from neezy_backend.mcp_catalog import (
    MCP_SERVERS,
    client_config,
    get_server,
    warnings_for,
)
from neezy_backend.mt5_bridge import MT5Bridge
from neezy_backend.tools import ToolPermission, ToolRegistry, register_default_tools


class PermissionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []
        self.registry = ToolRegistry()

        def write_tool(text: str) -> str:
            self.calls.append(text)
            return f"wrote {text}"

        def read_tool(text: str) -> str:
            self.calls.append(text)
            return f"read {text}"

        self.registry.register(
            "write_it", "write", write_tool, permission=ToolPermission.WRITE
        )
        self.registry.register(
            "destroy_it",
            "destroy",
            write_tool,
            permission=ToolPermission.DESTRUCTIVE,
        )
        self.registry.register("read_it", "read", read_tool)

    def test_write_tool_refuses_without_confirm(self) -> None:
        with self.assertRaises(PermissionError):
            self.registry.execute("write_it", text="a")
        self.assertEqual(self.calls, [])

    def test_destructive_tool_refuses_without_confirm(self) -> None:
        with self.assertRaises(PermissionError):
            self.registry.execute("destroy_it", text="a")
        self.assertEqual(self.calls, [])

    def test_write_tool_runs_with_confirm(self) -> None:
        result = self.registry.execute("write_it", confirm=True, text="a")
        self.assertEqual(result, "wrote a")
        self.assertEqual(self.calls, ["a"])

    def test_dry_run_never_calls_write_tool(self) -> None:
        res = self.registry.execute("destroy_it", dry_run=True, text="a")
        self.assertEqual(res["status"], "dry_run")
        self.assertEqual(res["permission"], "DESTRUCTIVE")
        self.assertEqual(self.calls, [])

    def test_read_only_tool_needs_no_confirm(self) -> None:
        self.assertEqual(self.registry.execute("read_it", text="x"), "read x")

    def test_confirm_is_not_forwarded_as_a_tool_argument(self) -> None:
        self.assertEqual(
            self.registry.execute("read_it", confirm=True, text="x"), "read x"
        )
        self.assertEqual(self.calls, ["x"])

    def test_agent_plan_step_fails_without_confirm(self) -> None:
        planner = AgentPlanner(registry=self.registry)
        steps = [
            PlanStep(
                step_id=1,
                task="write",
                tool_name="write_it",
                tool_args={"text": "a"},
            )
        ]
        planner.execute_plan(steps)
        self.assertEqual(steps[0].status, "failed")
        self.assertIn("confirm=True", steps[0].error)
        self.assertEqual(self.calls, [])

    def test_agent_plan_step_runs_with_confirm(self) -> None:
        planner = AgentPlanner(registry=self.registry)
        steps = [
            PlanStep(
                step_id=1,
                task="write",
                tool_name="write_it",
                tool_args={"text": "a"},
            )
        ]
        planner.execute_plan(steps, confirm=True)
        self.assertEqual(steps[0].status, "completed")
        self.assertEqual(self.calls, ["a"])


class MT5ReadToolTests(unittest.TestCase):
    def _tools(self) -> ToolRegistry:
        registry = ToolRegistry()
        register_default_tools(registry)
        return registry

    def test_positions_refuse_when_not_connected(self) -> None:
        bridge = MT5Bridge(mock=False)
        bridge.connect = mock.Mock(
            return_value={"success": False, "error": "terminal missing"}
        )
        with mock.patch(
            "neezy_backend.mt5_bridge.get_global_mt5_bridge", return_value=bridge
        ):
            out = self._tools().execute("mt5_positions")
        self.assertTrue(out.startswith("MT5 not connected"))
        self.assertNotIn("EURUSD", out)

    def test_candles_refuse_when_not_connected(self) -> None:
        bridge = MT5Bridge(mock=False)
        bridge.connect = mock.Mock(return_value={"success": False, "error": "x"})
        with mock.patch(
            "neezy_backend.mt5_bridge.get_global_mt5_bridge", return_value=bridge
        ):
            out = self._tools().execute("mt5_candles", symbol="frxEURUSD")
        self.assertTrue(out.startswith("MT5 not connected"))

    def test_mock_positions_are_labelled_simulated(self) -> None:
        bridge = MT5Bridge(mock=True)
        with mock.patch(
            "neezy_backend.mt5_bridge.get_global_mt5_bridge", return_value=bridge
        ):
            out = self._tools().execute("mt5_positions")
        self.assertIn("SIMULATED", out)

    def test_mock_candles_are_labelled_and_bounded(self) -> None:
        bridge = MT5Bridge(mock=True)
        with mock.patch(
            "neezy_backend.mt5_bridge.get_global_mt5_bridge", return_value=bridge
        ):
            out = self._tools().execute("mt5_candles", count="5000")
        self.assertIn("SIMULATED", out)
        self.assertIn("1000 fetched", out)

    def test_order_preview_never_sends(self) -> None:
        bridge = MT5Bridge(mock=True)
        bridge.connect()
        with (
            mock.patch(
                "neezy_backend.mt5_bridge.get_global_mt5_bridge", return_value=bridge
            ),
            mock.patch.object(bridge, "place_order") as place,
        ):
            out = self._tools().execute(
                "mt5_order_preview", symbol="frxEURUSD", order_type="BUY", volume=0.01
            )
        place.assert_not_called()
        self.assertIn("NOT SENT", out)
        self.assertIn("'sent': False", out)

    def test_mt5_read_tools_are_read_only(self) -> None:
        tools = {t["name"]: t["permission"] for t in self._tools().list_tools()}
        for name in ("mt5_positions", "mt5_candles", "mt5_order_preview"):
            self.assertEqual(tools[name], "READ_ONLY")


class McpCatalogTests(unittest.TestCase):
    def test_catalog_has_six_unique_servers(self) -> None:
        ids = [server.id for server in MCP_SERVERS]
        self.assertEqual(len(ids), 6)
        self.assertEqual(len(set(ids)), 6)

    def test_unknown_server_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            get_server("nope")

    def test_read_only_profile_is_used_when_safe(self) -> None:
        entry = client_config("desktop-win32")["mcpServers"]["desktop-win32"]
        self.assertEqual(entry["env"], {"WIN32_MCP_SECURITY_PROFILE": "read_only"})

    def test_unsafe_config_drops_the_read_only_profile(self) -> None:
        entry = client_config("desktop-win32", safe=False)["mcpServers"][
            "desktop-win32"
        ]
        self.assertNotIn("env", entry)

    def test_winremote_safe_config_restricts_tools(self) -> None:
        safe = client_config("desktop-winremote")["mcpServers"]["desktop-winremote"]
        unsafe = client_config("desktop-winremote", safe=False)["mcpServers"][
            "desktop-winremote"
        ]
        self.assertIn("--tools", safe["args"])
        self.assertNotIn("--tools", unsafe["args"])

    def test_trading_servers_warn_when_safe(self) -> None:
        messages = warnings_for("mt5-ariadng", safe=True)
        self.assertTrue(any("no read-only mode" in m for m in messages))

    def test_unrestricted_config_warns(self) -> None:
        messages = warnings_for("desktop-win32", safe=False)
        self.assertTrue(any("Unrestricted" in m for m in messages))

    def test_ariadng_config_includes_required_login_flags(self) -> None:
        entry = client_config("mt5-ariadng")["mcpServers"]["mt5-ariadng"]
        for flag in ("--login", "--password", "--server"):
            self.assertIn(flag, entry["args"])

    def test_every_server_warns_about_risk(self) -> None:
        for server in MCP_SERVERS:
            self.assertTrue(warnings_for(server.id), server.id)


if __name__ == "__main__":
    unittest.main()
