"""Headless smoke tests for the Tkinter app.

The sandbox and CI runners have no display, so a tiny stand-in ``tkinter``
package is installed before ``neezy_app.ui`` is imported. That exercises the
real widget-building code, the settings wiring, the local database hooks, and
the AI key management without opening a window.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


class FakeWidget:
    """Permissive stand-in: every widget method is a no-op."""

    def __init__(self, *args, **kwargs):
        self.master = args[0] if args else None
        self.options = dict(kwargs)
        self.calls = []
        self._children = []
        self._fake_tabs = []
        self._fake_selected = None
        self.bound = {}
        if args and hasattr(args[0], "_children"):
            args[0]._children.append(self)

    def add(self, child, **kwargs):
        self.calls.append(("add", (child,), kwargs))
        self._fake_tabs.append(child)
        if self._fake_selected is None:
            self._fake_selected = child

    def select(self, tab_id=None):
        self.calls.append(("select", (tab_id,), {}))
        if tab_id is not None:
            self._fake_selected = tab_id
        return self._fake_selected

    def index(self, tab_id):
        if tab_id in self._fake_tabs:
            return self._fake_tabs.index(tab_id)
        return 0

    def bind(self, sequence, func=None, add=None):
        self.calls.append(("bind", (sequence, func, add), {}))
        if callable(func):
            self.bound[sequence] = func
        return "bind_id"

    bind_all = bind

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "winfo_children":
                return list(self._children)
            if name in ("winfo_width", "winfo_reqwidth"):
                return 900
            if name in ("winfo_height", "winfo_reqheight"):
                return 520
            if name == "winfo_exists":
                return 1
            if name == "curselection":
                return ()
            if name == "get":
                return self.options.get("text", "")
            return None

        return method

    def cget(self, key):
        if key in self.options:
            return self.options[key]
        return "" if key == "text" else "#000000"

    __getitem__ = cget

    def configure(self, *args, **kwargs):
        for arg in args:
            if isinstance(arg, dict):
                self.options.update(arg)
        self.options.update(kwargs)

    config = configure


class FakeVar:
    def __init__(self, master=None, value=None, name=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value

    def trace_add(self, *_args, **_kwargs):
        return "trace"


class FakeStringVar(FakeVar):
    def __init__(self, master=None, value=None, name=None):
        super().__init__(master, "" if value is None else value)


class FakeIntVar(FakeVar):
    def __init__(self, master=None, value=None, name=None):
        super().__init__(master, 0 if value is None else int(value))


class FakeDoubleVar(FakeVar):
    def __init__(self, master=None, value=None, name=None):
        super().__init__(master, 0.0 if value is None else float(value))


class FakeBooleanVar(FakeVar):
    def __init__(self, master=None, value=None, name=None):
        super().__init__(master, False if value is None else bool(value))


class FakeTk(FakeWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.destroyed = False

    def destroy(self):
        self.destroyed = True
        self._children.clear()


class FakeStyle(FakeWidget):
    def theme_use(self, *_args, **_kwargs):
        return None


def install_fake_tkinter() -> None:
    tk = types.ModuleType("tkinter")
    tk.Tk = FakeTk
    tk.Frame = FakeWidget
    tk.Label = FakeWidget
    tk.Button = FakeWidget
    tk.Checkbutton = FakeWidget
    tk.Entry = FakeWidget
    tk.Listbox = FakeWidget
    tk.Text = FakeWidget
    tk.Canvas = FakeWidget
    tk.Spinbox = FakeWidget
    tk.Toplevel = FakeTk
    tk.Widget = FakeWidget
    tk.Misc = FakeWidget
    tk.StringVar = FakeStringVar
    tk.IntVar = FakeIntVar
    tk.DoubleVar = FakeDoubleVar
    tk.BooleanVar = FakeBooleanVar
    tk.TclError = type("TclError", (Exception,), {})

    ttk = types.ModuleType("tkinter.ttk")
    ttk.Notebook = FakeWidget
    ttk.Combobox = FakeWidget
    ttk.Treeview = FakeWidget
    ttk.Scrollbar = FakeWidget
    ttk.Style = FakeStyle
    tk.ttk = ttk

    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.asksaveasfilename = lambda **_kwargs: ""
    filedialog.askopenfilename = lambda **_kwargs: ""
    filedialog.askdirectory = lambda **_kwargs: ""
    messagebox = types.ModuleType("tkinter.messagebox")
    messagebox.showerror = lambda *_args, **_kwargs: None
    messagebox.showinfo = lambda *_args, **_kwargs: None
    messagebox.showwarning = lambda *_args, **_kwargs: None
    messagebox.askyesno = lambda *_args, **_kwargs: False
    tk.filedialog = filedialog
    tk.messagebox = messagebox

    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.messagebox"] = messagebox


install_fake_tkinter()

# Other test modules (e.g. ``test_enterprise_ui``) may already have imported
# ``neezy_app.ui`` against the real ``tkinter``. Drop those cached modules so
# the import below is bound to the fake, display-free stand-in.
for _name in [m for m in sys.modules if m == "neezy_app" or m.startswith("neezy_app.")]:
    del sys.modules[_name]

from neezy_app import ui  # noqa: E402
from neezy_backend.database import LocalDatabase  # noqa: E402
from neezy_backend.storage import SettingsStore, get_data_dir  # noqa: E402


def sample_candles(count: int = 220):
    candles, previous = [], 1.10
    for index in range(count):
        close = previous + 0.0008
        candles.append(
            (
                index * 300,
                previous,
                max(previous, close) + 0.0004,
                min(previous, close) - 0.0004,
                close,
            )
        )
        previous = close
    return candles


class AppSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"NEEZY_HOME": self.directory.name})
        self.env.start()
        # UI regression tests must never open real market-data connections.
        stream_start = mock.patch.object(ui.DerivStreamClient, "start")
        stream_start.start()
        self.addCleanup(stream_start.stop)
        self.app = ui.App()
        self.app.tf.get = lambda: "5m"

    def tearDown(self) -> None:
        try:
            self.app.client.stop()
        except Exception:  # noqa: BLE001 - teardown must not mask failures
            pass
        if self.app.db is not None:
            try:
                self.app.db.close()
            except Exception:  # noqa: BLE001
                pass
        self.env.stop()
        self.directory.cleanup()

    def test_research_controls_persist_and_shipped_model_fallback_is_safe(self):
        self.assertEqual(len(self.app.research_vars), 17)
        self.app.research_vars["ml_epochs"].set(12)
        self.app.research_vars["pair_cost_bps"].set(3.5)
        self.app._settings_changed()
        restored = SettingsStore().load()
        self.assertEqual(restored.ml_epochs, 12)
        self.assertEqual(restored.pair_cost_bps, 3.5)
        for name, var in self.app.research_vars.items():
            self.assertEqual(getattr(restored, name), var.get())
        self.assertEqual(self.app._get_brain_model("R_10", "5m")["symbol"], "R_10")
        self.assertIsNone(self.app._get_brain_model("R_10", "1m"))

    def test_invalid_pair_thresholds_do_not_overwrite_saved_settings(self):
        self.app._settings_changed()
        old = SettingsStore().load()
        self.app.research_vars["pair_exit_z"].set(3.0)
        self.app._settings_changed()
        self.assertEqual(SettingsStore().load(), old)
        self.assertIn("exit < entry < stop", self.app.settings_status.options["text"])

    def test_same_pair_and_non_forex_pair_are_rejected(self):
        self.app.selected = "R_10"
        self.app._research_fx_pair()
        self.assertIn("distinct Forex", self.app.research_status_label.options["text"])
        self.app.selected = "frxGBPUSD"
        self.app.pair_reference_var.set("frxGBPUSD")
        self.app._research_fx_pair()
        self.assertIn("distinct Forex", self.app.research_status_label.options["text"])

    def test_research_is_opt_in_and_not_started_at_app_construction(self):
        self.assertFalse(self.app._research_running)
        self.assertFalse(self.app.settings.use_brain_model)
        self.assertEqual(self.app.research_market_var.get(), "frxEURUSD")
        self.assertIn("INSIGHTS", self.app.pages)

    def test_app_builds_with_every_settings_tab(self) -> None:
        added = [
            call[2]["text"]
            for call in self.app.settings_notebook.calls
            if call[0] == "add"
        ]
        for name in (
            "WORKSPACE",
            "ENGINE",
            "ML RESEARCH",
            "PAIR RESEARCH",
            "LOCAL DATA",
            "AI PROVIDERS",
            "LOCAL MODELS",
            "MCP SERVER",
            "TELEGRAM",
        ):
            self.assertIn(name, added)
        self.assertTrue(hasattr(self.app, "ai_model_combo"))
        self.assertTrue(hasattr(self.app, "db_stats_label"))
        self.assertTrue(hasattr(self.app, "ai_keys_list"))
        self.assertIsNotNone(self.app.db)
        self.assertIsInstance(self.app.db, LocalDatabase)

    def test_orders_page_previews_locally_and_refuses_with_bridge_off(self) -> None:
        self.assertIn("ORDERS", self.app.pages)
        self.app.order_vars["volume"].set("0.01")
        self.app.order_vars["side"].set("BUY")
        self.app._order_preview()
        self.assertIn("Preview only", self.app.order_status.options["text"])
        self.app.order_vars["volume"].set("abc")
        self.app._order_preview()
        self.assertIn("Check the ticket", self.app.order_status.options["text"])
        # Verify that _order_place uses the injected self.settings_store handle
        self.app.order_vars["volume"].set("0.01")
        mock_store = mock.Mock()
        mock_store.load.return_value = self.app.settings.updated(mt5_enabled=False)
        self.app.settings_store = mock_store
        self.app._order_place()
        mock_store.load.assert_called_once()
        self.assertIn("bridge is off", self.app.order_status.options["text"])
        self.assertFalse(self.app._order_busy)

    def test_settings_persist_every_new_field(self) -> None:
        self.app.strategy_var.set("DIVERGENCE · RSI/MACD divergence")
        self.app.st_period_var.set(14)
        self.app.st_mult_var.set(2.5)
        self.app.div_lookback_var.set(7)
        self.app.corr_window_var.set(40)
        self.app.corr_baseline_var.set(180)
        self.app.retention_var.set(30)
        self.app.store_candles_var.set(False)
        self.app.snapshots_var.set(True)
        self.app.ai_enabled_var.set(True)
        self.app.ai_model_var.set("deepseek/deepseek-r1:free")
        self.app.ai_base_var.set("https://proxy.local/v1")
        self.app.ai_temp_var.set(0.7)
        self.app.ai_tokens_var.set(512)
        self.app.ai_timeout_var.set(20.0)
        self.app.ai_system_var.set("Answer in three bullets.")
        self.app.overlay_var.set(False)
        self.app.use_knowledge_var.set(True)
        self.app.use_memory_var.set(True)
        self.app.use_brain_var.set(True)
        self.app.local_llm_enabled_var.set(True)
        self.app.local_llm_context_var.set(1024)
        self.app.local_llm_tokens_var.set(64)
        self.app.local_llm_threads_var.set(2)
        self.app.local_llm_batch_var.set(16)
        self.app.local_llm_disk_offload_var.set(True)
        self.app.local_llm_memory_var.set(2048)
        self.app.mcp_port_var.set(9876)
        self.app.mcp_writes_var.set(True)
        self.app.mcp_tunnel_enabled_var.set(True)
        self.app.mcp_tunnel_executable_var.set("/opt/cloudflared")
        self.app.telegram_chat_ids_var.set("123456789")
        self.app._settings_changed()

        saved = SettingsStore(get_data_dir() / "settings.json").load()
        self.assertEqual(saved.strategy, "DIVERGENCE")
        self.assertEqual(saved.supertrend_period, 14)
        self.assertAlmostEqual(saved.supertrend_multiplier, 2.5)
        self.assertEqual(saved.divergence_lookback, 7)
        self.assertEqual(saved.correlation_window, 40)
        self.assertEqual(saved.correlation_baseline, 180)
        self.assertEqual(saved.retention_days, 30)
        self.assertFalse(saved.store_candles)
        self.assertTrue(saved.save_snapshots)
        self.assertTrue(saved.ai_enabled)
        self.assertEqual(saved.ai_model, "deepseek/deepseek-r1:free")
        self.assertEqual(saved.ai_base_url, "https://proxy.local/v1")
        self.assertAlmostEqual(saved.ai_temperature, 0.7)
        self.assertEqual(saved.ai_max_tokens, 512)
        self.assertAlmostEqual(saved.ai_timeout, 20.0)
        self.assertEqual(saved.ai_system_prompt, "Answer in three bullets.")
        self.assertFalse(saved.show_strategy_overlay)
        self.assertTrue(saved.use_knowledge)
        self.assertTrue(saved.use_memory)
        self.assertTrue(saved.use_brain_model)
        self.assertTrue(saved.local_llm_enabled)
        self.assertEqual(saved.local_llm_context_tokens, 1024)
        self.assertEqual(saved.local_llm_max_tokens, 64)
        self.assertEqual(saved.local_llm_threads, 2)
        self.assertEqual(saved.local_llm_batch_size, 16)
        self.assertTrue(saved.local_llm_disk_offload)
        self.assertEqual(saved.local_llm_cpu_memory_mb, 2048)
        self.assertEqual(saved.mcp_port, 9876)
        self.assertTrue(saved.mcp_allow_writes)
        self.assertTrue(saved.mcp_tunnel_enabled)
        self.assertEqual(saved.mcp_tunnel_executable, "/opt/cloudflared")
        self.assertEqual(saved.telegram_chat_ids, "123456789")
        self.assertFalse(self.app.db.store_candles)

    def test_chat_uses_the_selected_local_model_without_a_provider_key(self) -> None:
        model_path = Path(self.directory.name) / "chat.gguf"
        model_path.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + bytes(16))
        self.app._register_local_model(str(model_path))
        self.app.local_llm_enabled_var.set(True)
        self.app._settings_changed()
        self.app.prompt.get = lambda: "Explain this market"
        self.app.after = lambda _delay, callback: callback()

        class ImmediateThread:
            def __init__(self, *, target, **_kwargs):
                self.target = target

            def start(self):
                self.target()

        with (
            mock.patch(
                "neezy_app.ui_panels.chat.generate_chat", return_value="Offline answer"
            ) as generate,
            mock.patch("neezy_app.ui_panels.chat.threading.Thread", ImmediateThread),
        ):
            self.app._ask()

        generate.assert_called_once()
        inserted = " ".join(str(call[1]) for call in self.app.chat.calls)
        self.assertIn("Offline answer", inserted)
        self.assertIn("local", inserted)

    def test_mcp_settings_start_and_stop_the_local_server(self) -> None:
        server = mock.Mock()
        server.url = "http://127.0.0.1:9876/mcp"
        server.running = True
        with mock.patch(
            "neezy_app.ui_panels.mcp.MCPServer", return_value=server
        ) as factory:
            self.app.mcp_enabled_var.set(True)
            self.app.mcp_port_var.set(9876)
            self.app._settings_changed()

            factory.assert_called_once()
            server.start.assert_called_once_with()
            self.assertTrue(self.app.settings.mcp_enabled)
            self.assertEqual(self.app.settings.mcp_port, 9876)
            self.assertEqual(self.app.mcp_url_var.get(), server.url)
            self.assertIn("Running", self.app.mcp_status.options["text"])
            self.assertIsNotNone(self.app.mcp_token_store.load())

            self.app.mcp_enabled_var.set(False)
            self.app._settings_changed()
            server.stop.assert_called_once_with()
            self.assertIsNone(self.app.mcp_server)
            self.assertEqual(
                self.app.mcp_status.options["text"], "MCP server is disabled."
            )

    def test_local_model_import_registers_reference_and_selects_it(self) -> None:
        model_path = Path(self.directory.name) / "offline.gguf"
        model_path.write_bytes(b"GGUF" + (3).to_bytes(4, "little") + bytes(16))
        self.app._register_local_model(str(model_path))
        self.assertEqual(len(self.app._local_model_labels), 1)
        model_id = next(iter(self.app._local_model_labels.values()))
        self.assertEqual(self.app.settings.local_llm_model_id, model_id)
        self.assertTrue(model_path.exists())
        self.assertIn("not copied", self.app.local_model_status.options["text"])

    def test_public_tunnel_uses_separate_read_only_mcp_endpoint(self) -> None:
        local_server = mock.Mock()
        local_server.url = "http://127.0.0.1:9876/mcp"
        local_server.running = True
        public_server = mock.Mock()
        public_server.url = "http://127.0.0.1:45321/mcp"
        public_server.port = 45321
        public_server.running = True
        tunnel = mock.Mock()
        tunnel.running = False
        tunnel.public_url = None
        tunnel.error = ""
        tunnel.start.side_effect = lambda *_args: setattr(tunnel, "running", True)
        self.app.mcp_tunnel_service = tunnel

        with mock.patch(
            "neezy_app.ui_panels.mcp.MCPServer",
            side_effect=[local_server, public_server],
        ) as factory:
            self.app.mcp_enabled_var.set(True)
            self.app.mcp_port_var.set(9876)
            self.app.mcp_tunnel_enabled_var.set(True)
            self.app._settings_changed()

        self.assertEqual(factory.call_count, 2)
        public_call = factory.call_args_list[1]
        public_args = public_call.kwargs
        self.assertIs(public_call.args[0], self.app.public_remote_registry)
        self.assertFalse(public_args["write_enabled"])
        self.assertEqual(public_args["requests_per_minute"], 60)
        self.assertEqual(public_args["port"], 0)
        tunnel.start.assert_called_once_with("cloudflared", 45321)
        self.assertTrue(self.app.mcp_public_token_store.load())
        self.app._stop_mcp_server()
        public_server.stop.assert_called_once_with()
        local_server.stop.assert_called_once_with()
        tunnel.stop.assert_called_once_with()

    def test_telegram_settings_save_token_and_enforce_chat_allow_list(self) -> None:
        token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
        service = mock.Mock()
        service.running = True
        service.last_error = ""
        with mock.patch(
            "neezy_app.ui_panels.telegram.TelegramBotService", return_value=service
        ) as factory:
            self.app.telegram_token_var.set(token)
            self.app._telegram_save_token()
            self.assertEqual(self.app.telegram_token_store.load(), token)
            self.assertEqual(self.app.telegram_token_var.get(), "")

            self.app.telegram_enabled_var.set(True)
            self.app.telegram_chat_ids_var.set("123456789")
            self.app.telegram_alerts_var.set(False)
            self.app.telegram_commands_var.set(True)
            self.app._settings_changed()
            self.assertTrue(self.app.settings.telegram_enabled)
            self.assertFalse(self.app.settings.telegram_alerts_enabled)
            self.assertTrue(self.app.settings.telegram_allow_commands)
            factory.assert_called_once_with(
                token, ("123456789",), command_handler=self.app._telegram_command
            )
            service.start.assert_called_once_with()
            self.assertIn("Running", self.app.telegram_status.options["text"])

            self.app.telegram_chat_ids_var.set("")
            self.app._settings_changed()
            service.stop.assert_called_once_with()
            self.assertIsNone(self.app.telegram_service)
            self.assertEqual(
                self.app.telegram_status.options["text"],
                "Add at least one authorized chat ID.",
            )

    def test_connection_and_workspace_settings_persist(self) -> None:
        self.app.default_tf_var.set("1h")
        self.app.history_var.set(180)
        self.app.endpoint_var.set("  wss://proxy.local/v3  ")
        self.app.reconnect_var.set(3.0)
        self.app.max_reconnect_var.set(45.0)
        self.app._settings_changed()

        saved = SettingsStore(get_data_dir() / "settings.json").load()
        self.assertEqual(saved.default_timeframe, "1h")
        self.assertEqual(saved.history_candles, 180)
        self.assertEqual(saved.deriv_endpoint, "wss://proxy.local/v3")
        self.assertAlmostEqual(saved.reconnect_seconds, 3.0)
        self.assertAlmostEqual(saved.max_reconnect_seconds, 45.0)
        self.assertIn("restart", self.app.settings_status.options["text"])

    def test_saved_endpoint_and_reconnect_reach_the_live_client(self) -> None:
        from neezy_backend.config import AppSettings

        SettingsStore(get_data_dir() / "settings.json").save(
            AppSettings(
                deriv_endpoint="wss://proxy.local/v3",
                reconnect_seconds=4.0,
                max_reconnect_seconds=40.0,
                history_candles=120,
                default_timeframe="15m",
            )
        )
        restarted = ui.App()
        try:
            self.assertEqual(restarted.client.urls, ("wss://proxy.local/v3",))
            self.assertAlmostEqual(restarted.client.reconnect_seconds, 4.0)
            self.assertAlmostEqual(restarted.client.max_reconnect_seconds, 40.0)
            self.assertEqual(restarted.gran, 900)
            self.assertIn(("set", ("15m",), {}), restarted.tf.calls)
        finally:
            restarted.client.stop()
            restarted.db.close()

    def test_invalid_connection_settings_are_rejected(self) -> None:
        self.app.endpoint_var.set("https://api.derivws.com")
        self.app._settings_changed()
        self.assertEqual(
            SettingsStore(get_data_dir() / "settings.json").load().deriv_endpoint,
            "",
        )
        self.assertIn("ws://", self.app.settings_status.options["text"])

        self.app.endpoint_var.set("")
        self.app.reconnect_var.set(10.0)
        self.app.max_reconnect_var.set(5.0)
        self.app._settings_changed()
        saved = SettingsStore(get_data_dir() / "settings.json").load()
        self.assertEqual(saved.reconnect_seconds, 2.0)

    def test_invalid_settings_are_rejected_without_saving(self) -> None:
        self.app.corr_window_var.set(900)
        self.app.corr_baseline_var.set(100)
        self.app._settings_changed()
        self.assertNotEqual(
            SettingsStore(get_data_dir() / "settings.json").load().correlation_window,
            900,
        )

    def test_ai_provider_switch_updates_models(self) -> None:
        self.app.ai_provider_var.set("Ollama Cloud (ollama)")
        self.app._ai_provider_changed()
        values = self.app.ai_model_combo.options["values"]
        self.assertIn("gpt-oss:20b", values)
        self.assertIn(self.app.ai_model_var.get(), values)
        self.assertEqual(self.app.settings.ai_provider, "ollama")

    def test_add_remove_and_reset_ai_keys(self) -> None:
        self.app.ai_provider_var.set("Google Gemini (gemini)")
        self.app._ai_provider_changed()
        self.app.ai_key_entry.get = lambda: "AIzaTESTKEY1111"
        self.app.ai_key_name.get = lambda: "primary"
        self.app._ai_add_key()
        self.assertEqual(self.app.ai_keys.count("gemini"), 1)
        self.assertEqual(len(self.app._ai_key_rows), 1)
        self.assertEqual(self.app._ai_key_rows[0][0], "gemini")

        self.app.ai_keys_list.curselection = lambda: (0,)
        self.app._ai_remove_key()
        self.assertEqual(self.app.ai_keys.count("gemini"), 0)
        self.assertEqual(self.app._ai_key_rows, [])

        self.app.ai_keys.add("gemini", "AIzaTESTKEY2222")
        self.app._ai_reset_keys()
        self.assertIn("Cleared cooldowns", self.app.ai_status.options.get("text", ""))

    def test_ai_test_finish_updates_status(self) -> None:
        self.app._finish_ai_test(
            "OK via primary · gemini-2.5-flash · 120 ms", "#48e6a1"
        )
        self.assertFalse(self.app._ai_testing)
        self.assertIn("OK via", self.app.ai_status.options.get("text", ""))

    def test_scan_strategies_uses_live_candles(self) -> None:
        self.app.candles[self.app.selected] = sample_candles()
        self.app._scan_strategies()
        text = json.dumps([call[1] for call in self.app.engine_out.calls])
        self.assertIn("SUPERTREND", text)
        self.assertIn("Consensus", text)

    def test_scan_without_candles_is_safe(self) -> None:
        self.app.candles.clear()
        self.app._scan_strategies()
        text = json.dumps([call[1] for call in self.app.engine_out.calls])
        self.assertIn("collecting", text)

    def test_local_database_hooks_persist_analysis(self) -> None:
        candidates = sample_candles()
        symbol = self.app.selected
        self.app.candles[symbol] = candidates
        self.app._persist_candles(symbol)
        self.assertGreater(self.app.db.candle_count(symbol), 100)

        result = {
            "signal": "BUY",
            "score": 3,
            "regime": "Trending",
            "rsi": 61.5,
            "atr": 0.0012,
            "atr_pct": 0.11,
            "macd_histogram": 0.0002,
            "trend": "Bullish",
            "why": ["EMA 9 above EMA 21"],
        }
        self.app._persist_snapshot(symbol, result)
        snapshot = self.app.db.latest_snapshot(symbol, "5m")
        self.assertEqual(snapshot["signal"], "BUY")

        self.app._persist_signal(symbol, "BUY", result, candidates[-1][4])
        records = self.app.db.recent_signals(5)
        self.assertEqual(records[0]["signal"], "BUY")
        self.assertEqual(records[0]["strategy"], self.app.settings.strategy)
        self.app._refresh_db_stats()
        self.assertIn("candles", self.app.db_stats_label.options.get("text", ""))

    def test_snapshot_throttle(self) -> None:
        result = {"signal": "BUY", "score": 1, "regime": "Ranging"}
        self.app._persist_snapshot("frxEURUSD", result)
        self.app._persist_snapshot("frxEURUSD", result)
        self.assertEqual(
            self.app.db.connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[
                0
            ],
            1,
        )

    def test_chat_falls_back_to_local_answer_without_ai(self) -> None:
        self.app.ai_enabled_var.set(False)
        self.app._settings_changed()
        self.app.prompt.get = lambda: "what is the trend?"
        self.app.candles[self.app.selected] = sample_candles()
        self.app.results[self.app.selected] = {
            "signal": "BUY",
            "score": 3,
            "trend": "Bullish",
            "regime": "Trending",
            "rsi": 60.0,
            "atr_pct": 0.1,
            "why": ["EMA 9 above EMA 21"],
        }
        self.app._ask()
        inserted = " ".join(str(call[1]) for call in self.app.chat.calls)
        self.assertIn("YOU", inserted)
        self.assertIn("NEEZY", inserted)

    def test_chat_with_ai_enabled_but_no_key_explains_instead_of_calling(self) -> None:
        self.app.ai_enabled_var.set(True)
        self.app._settings_changed()
        self.app.prompt.get = lambda: "anything"
        self.app._ask()
        inserted = " ".join(str(call[1]) for call in self.app.chat.calls)
        self.assertIn("Add a key", inserted)

    def test_ai_failure_fallback_is_built_on_the_main_thread(self) -> None:
        import threading

        self.app.ai_enabled_var.set(True)
        self.app._settings_changed()
        self.app.prompt.get = lambda: "what is the trend?"
        self.app.candles[self.app.selected] = sample_candles()
        self.app.results[self.app.selected] = {
            "signal": "BUY",
            "score": 3,
            "trend": "Bullish",
            "regime": "Trending",
            "rsi": 60.0,
            "atr_pct": 0.1,
            "why": ["EMA 9 above EMA 21"],
        }
        answer_threads = []

        def fake_answer(question):
            answer_threads.append(threading.current_thread())
            return "LOCAL READ"

        self.app._answer = fake_answer
        queued = []
        started = []
        real_thread = threading.Thread

        def make_thread(**kwargs):
            thread = real_thread(**kwargs)
            started.append(thread)
            return thread

        with (
            mock.patch.object(self.app.ai_keys, "secrets", return_value=["key"]),
            mock.patch.object(
                self.app.ai_client, "chat", side_effect=ValueError("offline")
            ),
            mock.patch.object(
                self.app, "after", side_effect=lambda _ms, fn: queued.append(fn)
            ),
            mock.patch.object(threading, "Thread", side_effect=make_thread),
        ):
            self.app._ask()
            for thread in started:
                thread.join(5)

        # The worker must not build the fallback itself; it only queues it.
        self.assertEqual(answer_threads, [])
        self.assertEqual(len(queued), 1)
        queued[0]()
        self.assertEqual(answer_threads, [threading.main_thread()])
        inserted = " ".join(str(call[1]) for call in self.app.chat.calls)
        self.assertIn("Local read instead", inserted)
        self.assertIn("LOCAL READ", inserted)

    def test_append_ai_writes_into_chat(self) -> None:
        self.app._append_ai("Answer text")
        inserted = " ".join(str(call[1]) for call in self.app.chat.calls)
        self.assertIn("Answer text", inserted)

    def test_database_export_and_prune_from_ui(self) -> None:
        symbol = self.app.selected
        self.app.candles[symbol] = sample_candles(30)
        self.app._persist_candles(symbol)
        destination = Path(self.directory.name) / "export.json"
        with mock.patch(
            "neezy_app.ui_panels.database.filedialog.asksaveasfilename",
            return_value=str(destination),
        ):
            self.app._export_database()
        self.assertTrue(destination.exists())
        self.assertIn("Exported", self.app.settings_status.options.get("text", ""))

        self.app._prune_db()
        self.assertIn("Pruned", self.app.settings_status.options.get("text", ""))

    def test_vacuum_from_ui(self) -> None:
        self.app._vacuum_db()
        self.assertIn("vacuumed", self.app.settings_status.options.get("text", ""))

    def test_close_releases_the_database(self) -> None:
        database = self.app.db
        self.app._close()
        self.assertTrue(self.app.destroyed)
        import sqlite3

        with self.assertRaises(sqlite3.ProgrammingError):
            database.connection.execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
