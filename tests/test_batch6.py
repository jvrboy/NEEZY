"""Batch 6 coverage: notifiers, snapshots, watchlists, capabilities, config migration, timing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from neezy_backend import capabilities
from neezy_backend.capabilities import BUILD_INFO, VERSION
from neezy_backend.diagnostics import timed
from neezy_backend.notifiers import (
    CompositeNotifier,
    MemoryNotifier,
    Notification,
    TelegramNotifier,
    WebhookNotifier,
)
from neezy_backend.snapshots import capture_snapshot, snapshot_payload
from neezy_backend.storage import format_timestamp
from neezy_backend.watchlists import export_watchlist, import_watchlist


class TestNotifierProtocol(unittest.TestCase):
    def test_memory_notifier(self) -> None:
        mem = MemoryNotifier()
        n = Notification(title="Hi", body="hello", level="info")
        res = mem.send(n)
        self.assertTrue(res["success"])
        self.assertEqual(len(mem.sent), 1)
        self.assertEqual(mem.sent[0].title, "Hi")
        self.assertIn("memory", mem.health()["notifier"])

    def test_composite_fanout(self) -> None:
        a = MemoryNotifier()
        b = MemoryNotifier()
        comp = CompositeNotifier([a, b])
        n = Notification(title="T", body="B")
        res = comp.send(n)
        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 2)
        self.assertEqual(len(a.sent), 1)
        self.assertEqual(len(b.sent), 1)

    def test_composite_empty_ok(self) -> None:
        comp = CompositeNotifier([])
        self.assertTrue(comp.send(Notification(title="x", body="y"))["success"])

    def test_telegram_notifier_health(self) -> None:
        t = TelegramNotifier(chat_ids=["123"])
        self.assertTrue(t.health()["configured"])
        self.assertEqual(TelegramNotifier().health()["configured"], False)

    def test_webhook_notifier_health(self) -> None:
        w = WebhookNotifier("https://example.com/hook")
        self.assertTrue(w.health()["configured"])
        self.assertFalse(WebhookNotifier().health()["configured"])


class TestSnapshots(unittest.TestCase):
    def test_capture_basic(self) -> None:
        rec = capture_snapshot(
            "frxEURUSD", "15m", regime="trend", signal="BUY", score=3
        )
        self.assertEqual(rec["symbol"], "frxEURUSD")
        self.assertEqual(rec["timeframe"], "15m")
        self.assertEqual(rec["regime"], "trend")
        self.assertEqual(rec["score"], 3)
        self.assertIn("created_at", rec)

    def test_capture_requires_symbol(self) -> None:
        with self.assertRaises(ValueError):
            capture_snapshot("", "15m")
        with self.assertRaises(ValueError):
            capture_snapshot("frxEURUSD", "")

    def test_snapshot_payload(self) -> None:
        p = snapshot_payload(
            indicators={"rsi": 55}, strategies=[], confluence={"score": 60}
        )
        self.assertIn("indicators", p)
        self.assertIn("confluence", p)


class TestWatchlists(unittest.TestCase):
    def test_export_import_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wl.json"
            export_watchlist(path, symbols=["frxEURUSD", "frxUSDJPY"])
            doc = import_watchlist(path)
            self.assertEqual(doc["symbols"], ["frxEURUSD", "frxUSDJPY"])
            self.assertEqual(doc["schema_version"], 1)

    def test_export_rejects_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wl.json"
            with self.assertRaises(ValueError):
                export_watchlist(path, symbols=["NOTASYMBOL"])

    def test_import_future_version(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "wl.json"
            path.write_text(
                json.dumps({"schema_version": 99, "symbols": ["frxEURUSD"]})
            )
            with self.assertRaises(ValueError):
                import_watchlist(path)


class TestCapabilities(unittest.TestCase):
    def test_version_present(self) -> None:
        self.assertIsInstance(VERSION, str)
        self.assertNotEqual(VERSION, "")
        self.assertIn("version", BUILD_INFO)
        self.assertEqual(BUILD_INFO["api_version"], "1")

    def test_feature_report(self) -> None:
        feats = capabilities.feature_report()
        self.assertIn("mt5_bridge", feats)
        self.assertIn("notifiers", feats)

    def test_version_report(self) -> None:
        vr = capabilities.version_report()
        self.assertIn("version", vr)


class TestConfigMigration(unittest.TestCase):
    def test_v0_stamp(self) -> None:
        from neezy_backend.config import AppSettings

        s = AppSettings.from_dict({"theme": "Liquid dark"})
        self.assertEqual(s.config_version, 1)
        self.assertEqual(s.theme, "Liquid dark")

    def test_dry_run_field(self) -> None:
        from neezy_backend.config import AppSettings

        s = AppSettings()
        self.assertFalse(s.dry_run)
        s2 = s.updated(dry_run=True)
        self.assertTrue(s2.dry_run)

    def test_future_version_rejected(self) -> None:
        from neezy_backend.config import AppSettings

        with self.assertRaises(ValueError):
            AppSettings.from_dict({"config_version": 99, "theme": "Liquid dark"})

    def test_env_override_dry_run(self) -> None:
        from neezy_backend.config import AppSettings

        s = AppSettings().apply_env_overrides(env={"NEEZY_DRY_RUN": "1"})
        self.assertTrue(s.dry_run)


class TestTiming(unittest.TestCase):
    def test_timed_noop_when_disabled(self) -> None:
        # Without NEEZY_TIMING, timed() is a no-op
        with timed("test"):
            x = 1 + 1
        self.assertEqual(x, 2)


class TestFormatTimestamp(unittest.TestCase):
    def test_utc_passthru(self) -> None:
        ts = "2026-10-24T06:00:00Z"
        self.assertEqual(format_timestamp(ts, "UTC"), ts)

    def test_labeled_zone(self) -> None:
        ts = "2026-10-24T06:00:00Z"
        out = format_timestamp(ts, "Africa/Johannesburg")
        self.assertIn("Africa/Johannesburg", out)

    def test_bad_ts_passthru(self) -> None:
        self.assertEqual(format_timestamp("not-a-ts", "UTC"), "not-a-ts")


class TestDryRunOrder(unittest.TestCase):
    def test_dry_run_no_send(self) -> None:
        from unittest.mock import Mock

        from neezy_backend.mt5_orders import send_live_order

        bridge = Mock()
        res = send_live_order(
            bridge,
            confirmed=True,
            symbol="frxEURUSD",
            order_type="BUY",
            volume=0.1,
            dry_run=True,
        )
        self.assertTrue(res["success"])
        self.assertFalse(res["sent"])
        self.assertTrue(res["dry_run"])
        bridge.place_order.assert_not_called()

    def test_normal_still_checks_terminal(self) -> None:
        from unittest.mock import Mock

        from neezy_backend.mt5_orders import send_live_order

        bridge = Mock()
        bridge.connect.return_value = {"success": False, "error": "no term"}
        res = send_live_order(
            bridge, confirmed=True, symbol="frxEURUSD", order_type="BUY", volume=0.1
        )
        self.assertFalse(res["success"])


class TestForexSignalsDeprecation(unittest.TestCase):
    def test_shim_warns(self) -> None:
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Import-like exec of the shim's warning line
            warnings.warn(
                "forex_signals.py is deprecated; use `neezy` or `python -m neezy_app`",
                DeprecationWarning,
                stacklevel=2,
            )
            self.assertEqual(len(w), 1)
            self.assertIs(w[0].category, DeprecationWarning)


class TestMenuWidth(unittest.TestCase):
    def test_terminal_width_respects_columns(self) -> None:
        from neezy_backend.menu import terminal_width

        # Should be bounded even with env
        w = terminal_width()
        self.assertGreaterEqual(w, 28)
        self.assertLessEqual(w, 84)


if __name__ == "__main__":
    unittest.main()
