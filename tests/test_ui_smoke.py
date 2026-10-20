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
        self.options = dict(kwargs)
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "winfo_children":
                return []
            if name == "curselection":
                return ()
            if name == "get":
                return self.options.get("text", "")
            return None

        return method

    def cget(self, key):
        return self.options.get(key, "#000000")

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
    tk.StringVar = FakeStringVar
    tk.IntVar = FakeIntVar
    tk.DoubleVar = FakeDoubleVar
    tk.BooleanVar = FakeBooleanVar
    tk.TclError = type("TclError", (Exception,), {})

    ttk = types.ModuleType("tkinter.ttk")
    ttk.Notebook = FakeWidget
    ttk.Combobox = FakeWidget
    ttk.Treeview = FakeWidget
    ttk.Style = FakeStyle
    tk.ttk = ttk

    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.asksaveasfilename = lambda **_kwargs: ""
    filedialog.askopenfilename = lambda **_kwargs: ""
    messagebox = types.ModuleType("tkinter.messagebox")
    messagebox.showerror = lambda *_args, **_kwargs: None
    messagebox.showinfo = lambda *_args, **_kwargs: None
    messagebox.showwarning = lambda *_args, **_kwargs: None
    tk.filedialog = filedialog
    tk.messagebox = messagebox

    sys.modules["tkinter"] = tk
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.messagebox"] = messagebox


install_fake_tkinter()

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

    def test_app_builds_with_every_settings_tab(self) -> None:
        added = [
            call[2]["text"]
            for call in self.app.settings_notebook.calls
            if call[0] == "add"
        ]
        for name in ("WORKSPACE", "ENGINE", "LOCAL DATA", "AI PROVIDERS"):
            self.assertIn(name, added)
        self.assertTrue(hasattr(self.app, "ai_model_combo"))
        self.assertTrue(hasattr(self.app, "db_stats_label"))
        self.assertTrue(hasattr(self.app, "ai_keys_list"))
        self.assertIsNotNone(self.app.db)
        self.assertIsInstance(self.app.db, LocalDatabase)

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
        self.assertFalse(self.app.db.store_candles)

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
            mock.patch.object(ui.threading, "Thread", side_effect=make_thread),
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
        with mock.patch.object(
            ui.filedialog, "asksaveasfilename", return_value=str(destination)
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
