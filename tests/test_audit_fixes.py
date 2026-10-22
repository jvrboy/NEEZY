"""Comprehensive regression tests for the audit bugfixes, 210 AppSettings,
live hot-reload, safety gates, CLI config subcommands, and Android UI tabs.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from neezy_backend.agent import AgentPlanner
from neezy_backend.alerts import AlertEngine, AlertRule, is_quiet_hours_now
from neezy_backend.cli import main as cli_main
from neezy_backend.config import (
    SETTINGS_PROFILES,
    AppSettings,
    apply_profile,
)
from neezy_backend.dm import send_dm_notification
from neezy_backend.mt5_bridge import MT5Bridge
from neezy_backend.providers import ProviderKeyStore
from neezy_backend.storage import (
    ConfluenceHistoryStore,
    SettingsStore,
    SignalHistoryStore,
    create_local_backup,
)
from neezy_backend.tools import ToolRegistry, register_default_tools


class AuditBackendAndSettingsTests(unittest.TestCase):
    def test_settings_field_count_and_docs_one_to_one_sync(self) -> None:
        from scripts.gen_settings_docs import DESCRIPTIONS, render

        fields = {f.name for f in dataclasses.fields(AppSettings)}
        self.assertGreaterEqual(len(fields), 205)
        self.assertEqual(fields, set(DESCRIPTIONS.keys()))
        docs_path = Path(__file__).resolve().parents[1] / "docs" / "SETTINGS.md"
        self.assertEqual(docs_path.read_text(encoding="utf-8"), render())

    def test_all_builtin_profiles_validate_cleanly(self) -> None:
        base = AppSettings()
        for name in SETTINGS_PROFILES:
            updated = apply_profile(base, name)
            self.assertIsInstance(updated, AppSettings)
        with self.assertRaises(ValueError):
            apply_profile(base, "nonexistent_profile")

    def test_env_overrides_and_symbol_risk_helper(self) -> None:
        base = AppSettings(
            default_risk_percent=1.0,
            fx_risk_percent=0.45,
            synthetic_risk_percent=0.8,
        )
        self.assertAlmostEqual(base.risk_percent_for_symbol("frxXAUUSD"), 0.45)
        self.assertAlmostEqual(base.risk_percent_for_symbol("R_100"), 0.8)
        with mock.patch.dict(
            os.environ,
            {
                "NEEZY_THEME": "Midnight blue",
                "NEEZY_POLLING_MS": "250",
                "NEEZY_COMPACT_MODE": "true",
            },
            clear=False,
        ):
            over = base.apply_env_overrides()
            self.assertEqual(over.theme, "Midnight blue")
            self.assertEqual(over.polling_ms, 250)
            self.assertTrue(over.compact_mode)

    def test_alert_cooldown_and_midnight_quiet_hours(self) -> None:
        rule = AlertRule(symbol="frxEURUSD", metric="price", operator=">", value="1.10")
        clock = [1000.0]
        engine = AlertEngine([rule], cooldown_seconds=60, clock=lambda: clock[0])
        self.assertEqual(len(engine.evaluate("frxEURUSD", {}, 1.05)), 0)
        # First upward cross fires
        self.assertEqual(len(engine.evaluate("frxEURUSD", {}, 1.12)), 1)
        # Drop and immediate re-cross inside 60s cooldown is suppressed
        self.assertEqual(len(engine.evaluate("frxEURUSD", {}, 1.05)), 0)
        clock[0] = 1020.0
        self.assertEqual(len(engine.evaluate("frxEURUSD", {}, 1.12)), 0)
        # Re-cross after cooldown expires fires again
        self.assertEqual(len(engine.evaluate("frxEURUSD", {}, 1.05)), 0)
        clock[0] = 1100.0
        self.assertEqual(len(engine.evaluate("frxEURUSD", {}, 1.12)), 1)

        # Midnight-wrapping quiet hours 22:00 -> 06:00
        self.assertTrue(
            is_quiet_hours_now("22:00", "06:00", now=datetime(2026, 10, 22, 23, 30))
        )
        self.assertTrue(
            is_quiet_hours_now("22:00", "06:00", now=datetime(2026, 10, 22, 4, 15))
        )
        self.assertFalse(
            is_quiet_hours_now("22:00", "06:00", now=datetime(2026, 10, 22, 13, 0))
        )

    def test_settings_store_rollback_import_export_and_csv_delimiters(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.dict(os.environ, {"NEEZY_HOME": home}),
        ):
            store = SettingsStore()
            store.save(AppSettings(theme="Liquid dark", polling_ms=100))
            store.save(AppSettings(theme="Midnight blue", polling_ms=250))
            self.assertEqual(store.load().theme, "Midnight blue")
            rolled = store.rollback()
            self.assertIsNotNone(rolled)
            self.assertEqual(rolled.theme, "Liquid dark")

            export_file = Path(home) / "exported_settings.json"
            store.export_json(export_file)
            store.save(AppSettings(theme="High contrast"))
            restored = store.import_json(export_file)
            self.assertEqual(restored.theme, "Liquid dark")

            # ProviderKeyStore writes mode 0o600 on POSIX
            pks = ProviderKeyStore()
            pks.set("finnhub", "test-secret-token")
            if os.name != "nt":
                mode = pks.path.stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)

            # Custom CSV delimiter export on both history stores
            sig_store = SignalHistoryStore()
            sig_store.append(
                symbol="frxEURUSD",
                previous="NEUTRAL",
                current="BUY",
                price=1.085,
                score=3,
            )
            sig_csv = Path(home) / "sig.tsv"
            sig_store.export_csv(sig_csv, delimiter="\t")
            self.assertIn("\t", sig_csv.read_text(encoding="utf-8"))

            conf_store = ConfluenceHistoryStore()
            rec = conf_store.append(
                {
                    "timestamp": "2026-10-22T12:00:00+00:00",
                    "symbol": "frxEURUSD",
                    "instrument": "EUR/USD",
                    "timeframe": "5m",
                    "direction": "BUY",
                    "entry": 1.085,
                    "stop_loss": 1.082,
                    "take_profit": 1.091,
                    "win_rate": 64.0,
                }
            )
            conf_csv = Path(home) / "conf.csv"
            conf_store.export_csv(conf_csv, [rec], delimiter=";")
            self.assertIn(";", conf_csv.read_text(encoding="utf-8"))

            # SQLite safe hot-backup in create_local_backup
            backup_path = create_local_backup()
            self.assertTrue(backup_path.exists())

    def test_mt5_filling_mode_and_dm_https_security(self) -> None:
        bridge = MT5Bridge()
        fake_mt5 = types.SimpleNamespace(
            ORDER_FILLING_FOK=0,
            ORDER_FILLING_IOC=1,
            ORDER_FILLING_RETURN=2,
            symbol_info=lambda _sym: types.SimpleNamespace(filling_mode=2),
        )
        with mock.patch("neezy_backend.mt5_bridge.mt5", fake_mt5):
            self.assertEqual(bridge._resolve_filling_mode("EURUSD", "Auto"), 1)
            self.assertEqual(bridge._resolve_filling_mode("EURUSD", "RETURN"), 2)

        res = send_dm_notification(
            "http://insecure.example.com/hook",
            "Alert",
            "Body",
            https_only=True,
        )
        self.assertFalse(res["success"])
        self.assertIn("https://", res["error"])

    def test_agent_planner_dynamic_symbol_and_timeframe(self) -> None:
        reg = ToolRegistry()
        register_default_tools(reg)
        planner = AgentPlanner(registry=reg, max_steps=5)
        steps = planner.create_plan("Analyze GBPUSD on 1h and rank strongest setups")
        read_steps = [s for s in steps if s.tool_name == "read_market"]
        self.assertEqual(len(read_steps), 1)
        self.assertEqual(read_steps[0].tool_args["symbol"], "frxGBPUSD")
        self.assertEqual(read_steps[0].tool_args["timeframe"], "1h")


class AuditCliAndMobileTests(unittest.TestCase):
    def test_cli_config_list_get_set_diff_profile_and_reset(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.dict(os.environ, {"NEEZY_HOME": home}),
        ):
            buf = io.StringIO()
            self.assertEqual(cli_main(["config", "list", "--json"], out=buf), 0)
            listed = json.loads(buf.getvalue())
            self.assertGreaterEqual(listed["count"], 205)

            buf = io.StringIO()
            self.assertEqual(
                cli_main(["config", "set", "polling_ms", "275", "--json"], out=buf), 0
            )
            buf = io.StringIO()
            self.assertEqual(cli_main(["config", "diff", "--json"], out=buf), 0)
            diff = json.loads(buf.getvalue())
            self.assertEqual(diff["count"], 1)
            self.assertEqual(diff["changes"][0]["value"], 275)

            buf = io.StringIO()
            self.assertEqual(
                cli_main(["config", "profile", "scalper", "--json"], out=buf), 0
            )
            buf = io.StringIO()
            self.assertEqual(
                cli_main(["config", "get", "default_timeframe", "--json"], out=buf), 0
            )
            self.assertEqual(json.loads(buf.getvalue())["value"], "1m")

            # Invalid value exits cleanly with status code 2
            err = io.StringIO()
            with mock.patch("sys.stderr", err):
                code = cli_main(["config", "set", "polling_ms", "999999"], out=buf)
            self.assertEqual(code, 2)

            buf = io.StringIO()
            self.assertEqual(cli_main(["config", "reset", "--json"], out=buf), 0)
            buf = io.StringIO()
            self.assertEqual(cli_main(["config", "diff", "--json"], out=buf), 0)
            self.assertEqual(json.loads(buf.getvalue())["count"], 0)

    def test_desktop_orders_safety_gates_and_settings_search(self) -> None:
        import tests.test_ui_smoke  # noqa: F401
        from neezy_app import ui

        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.dict(os.environ, {"NEEZY_HOME": home}),
            mock.patch.object(ui.DerivStreamClient, "start"),
        ):
            app = ui.App()
            try:
                # Settings search indexes >150 controls and jumps to matching tab
                self.assertGreater(len(app._settings_search_index), 150)
                app.settings_search_var.set("slippage")
                app._filter_settings_search()
                self.assertIn("MT5 BRIDGE", app.settings_jump_var.get())

                # Order safety gates block dry-run lock, missing SL, and oversized lots
                dry_cfg = AppSettings(order_dry_run_mode=True)
                self.assertIn(
                    "Dry-run",
                    app._check_order_safety_gates({"sl": 1.09, "volume": 0.1}, dry_cfg)
                    or "",
                )
                sl_cfg = AppSettings(require_stop_loss_on_live_orders=True)
                self.assertIn(
                    "Stop-Loss",
                    app._check_order_safety_gates({"sl": 0.0, "volume": 0.1}, sl_cfg)
                    or "",
                )
            finally:
                app._close()

    def test_android_mobile_settings_and_chat_tabs_headless(self) -> None:
        import contextlib

        class _KivyWidget:
            def __init__(self, *args, **kw):
                self.children = []
                self.text = kw.get("text", "")
                self.values = kw.get("values", [])
                self.height = kw.get("height", 0)
                self.minimum_height = 0
                self.width = 360
                self.pos = (0, 0)
                self.size = (360, 48)
                self.canvas = types.SimpleNamespace(
                    before=contextlib.nullcontext(),
                    after=contextlib.nullcontext(),
                    clear=lambda: None,
                )

            def add_widget(self, w):
                self.children.append(w)

            def clear_widgets(self):
                self.children.clear()

            def bind(self, **_kw):
                return None

            def setter(self, _name):
                return lambda *_a: None

        kivy_mods = {}
        for mod_name in (
            "kivy",
            "kivy.clock",
            "kivy.graphics",
            "kivy.metrics",
            "kivy.uix",
            "kivy.uix.boxlayout",
            "kivy.uix.button",
            "kivy.uix.gridlayout",
            "kivy.uix.label",
            "kivy.uix.popup",
            "kivy.uix.scrollview",
            "kivy.uix.spinner",
            "kivy.uix.textinput",
            "kivy.uix.widget",
        ):
            mod = types.ModuleType(mod_name)
            if mod_name in {"kivy", "kivy.uix"}:
                mod.__path__ = []  # mark package so submodule imports resolve
            kivy_mods[mod_name] = mod
        kivy_mods["kivy.metrics"].dp = lambda v: v
        kivy_mods["kivy.metrics"].sp = lambda v: v
        kivy_mods["kivy.clock"].Clock = types.SimpleNamespace(
            schedule_once=lambda fn, *_a: fn(0)
        )
        for cls_name in ("Color", "Line", "Rectangle", "RoundedRectangle"):
            setattr(kivy_mods["kivy.graphics"], cls_name, _KivyWidget)
        for mod_key, cls_name in (
            ("kivy.uix.boxlayout", "BoxLayout"),
            ("kivy.uix.button", "Button"),
            ("kivy.uix.gridlayout", "GridLayout"),
            ("kivy.uix.label", "Label"),
            ("kivy.uix.popup", "Popup"),
            ("kivy.uix.scrollview", "ScrollView"),
            ("kivy.uix.spinner", "Spinner"),
            ("kivy.uix.textinput", "TextInput"),
            ("kivy.uix.widget", "Widget"),
        ):
            setattr(kivy_mods[mod_key], cls_name, _KivyWidget)

        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.dict(os.environ, {"NEEZY_HOME": home}),
            mock.patch.dict(sys.modules, kivy_mods),
        ):
            sys.modules.pop("neezy_mobile.widgets", None)
            sys.modules.pop("neezy_mobile.screens", None)
            from neezy_mobile.screens import ChatTab, SettingsTab

            class _FakeMobileService:
                def __init__(self):
                    self.settings = AppSettings()
                    self.selected = "frxEURUSD"
                    self.results = {
                        "frxEURUSD": {
                            "signal": "BUY",
                            "score": 3,
                            "trend": "BULLISH",
                            "rsi": 58.2,
                            "atr_pct": 0.42,
                            "adx": {"adx": 31.0},
                        }
                    }

                def watch_symbols(self):
                    return {"frxEURUSD": "EUR/USD"}

                def save_settings(self, updated: AppSettings):
                    self.settings = updated

            svc = _FakeMobileService()
            mobile_app = types.SimpleNamespace(services=svc)
            settings_tab = SettingsTab(mobile_app)
            settings_tab.on_show()
            settings_tab.profile.text = "conservative"
            settings_tab.risk_pct.text = "0.5"
            settings_tab.save()
            self.assertEqual(settings_tab.status.text, "Saved.")
            self.assertAlmostEqual(svc.settings.default_risk_percent, 0.5)

            chat_tab = ChatTab(mobile_app)
            initial_cards = len(chat_tab.list_box.children)
            chat_tab.prompt.text = "How does EUR/USD look right now?"
            chat_tab.ask()
            self.assertEqual(len(chat_tab.list_box.children), initial_cards + 2)


if __name__ == "__main__":
    unittest.main()
