"""MT5 bridge must use the connection saved in settings.json, not defaults."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from neezy_backend import cli, mt5_bridge
from neezy_backend.mt5_bridge import MT5Bridge, get_global_mt5_bridge


class _IsolatedHome(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self._env = mock.patch.dict(os.environ, {"NEEZY_HOME": str(self.home)})
        self._env.start()
        mt5_bridge._GLOBAL_BRIDGE = None
        mt5_bridge._GLOBAL_KEY = None

    def tearDown(self) -> None:
        mt5_bridge._GLOBAL_BRIDGE = None
        mt5_bridge._GLOBAL_KEY = None
        self._env.stop()
        self._tmp.cleanup()

    def _save(self, **fields) -> None:
        (self.home / "settings.json").write_text(json.dumps(fields), encoding="utf-8")


class GlobalBridgeSettingsTests(_IsolatedHome):
    def test_no_arguments_uses_saved_mt5_settings(self):
        self._save(
            mt5_login=424242,
            mt5_password="secret",
            mt5_server="Broker-Demo",
            mt5_path="C:/MT5/terminal64.exe",
            mt5_magic=77,
            mt5_symbol_map="frxEURUSD=EURUSD",
        )
        bridge = get_global_mt5_bridge()
        self.assertEqual(bridge.login, 424242)
        self.assertEqual(bridge.password, "secret")
        self.assertEqual(bridge.server, "Broker-Demo")
        self.assertEqual(bridge.path, "C:/MT5/terminal64.exe")
        self.assertEqual(bridge.magic, 77)
        self.assertEqual(bridge.symbol_map_str, "frxEURUSD=EURUSD")

    def test_missing_settings_file_gives_defaults(self):
        bridge = get_global_mt5_bridge()
        self.assertEqual(bridge.login, 0)
        self.assertEqual(bridge.server, "")
        self.assertEqual(bridge.magic, 123456)

    def test_corrupt_settings_file_does_not_crash(self):
        (self.home / "settings.json").write_text("{not json", encoding="utf-8")
        bridge = get_global_mt5_bridge()
        self.assertEqual(bridge.login, 0)

    def test_same_settings_reuse_connected_bridge(self):
        self._save(mt5_login=1, mt5_server="S")
        first = get_global_mt5_bridge()
        first.connected = True
        self.assertIs(get_global_mt5_bridge(), first)
        self.assertTrue(get_global_mt5_bridge().connected)

    def test_changed_settings_rebuild_bridge(self):
        self._save(mt5_login=1, mt5_server="S")
        first = get_global_mt5_bridge()
        self._save(mt5_login=2, mt5_server="S2")
        second = get_global_mt5_bridge()
        self.assertIsNot(first, second)
        self.assertEqual(second.login, 2)
        self.assertEqual(second.server, "S2")

    def test_explicit_arguments_override_saved_settings(self):
        self._save(mt5_login=1, mt5_server="Saved")
        bridge = get_global_mt5_bridge(login=9, server="Explicit")
        self.assertEqual(bridge.login, 9)
        self.assertEqual(bridge.server, "Explicit")
        self.assertEqual(bridge.password, "")

    def test_bridge_from_settings_accepts_explicit_settings(self):
        from neezy_backend.config import AppSettings

        bridge = mt5_bridge.bridge_from_settings(
            AppSettings(mt5_login=5, mt5_server="X")
        )
        self.assertIsInstance(bridge, MT5Bridge)
        self.assertEqual(bridge.login, 5)
        self.assertEqual(bridge.server, "X")


class CliMt5ReadRefusalTests(_IsolatedHome):
    def _run(self, argv):
        out = io.StringIO()
        code = cli.main(argv, out=out)
        return code, out.getvalue()

    def _simulated_bridge(self):
        # Simulate a machine without the MetaTrader5 package: bridge is mock.
        return mock.patch(
            "neezy_backend.mt5_bridge.get_global_mt5_bridge",
            return_value=MT5Bridge(mock=True),
        )

    def test_account_refuses_simulated_data(self):
        with self._simulated_bridge():
            code, out = self._run(["mt5", "account"])
        self.assertNotEqual(code, 0)
        self.assertNotIn("MT5 Account Info", out)

    def test_quote_refuses_simulated_data(self):
        with self._simulated_bridge():
            code, out = self._run(["mt5", "quote", "frxEURUSD"])
        self.assertNotEqual(code, 0)
        self.assertNotIn("MT5 Quote", out)

    def test_candles_refuses_simulated_data(self):
        with self._simulated_bridge():
            code, out = self._run(["mt5", "candles", "frxEURUSD"])
        self.assertNotEqual(code, 0)
        self.assertNotIn("fetched", out)

    def test_disconnected_real_bridge_refuses(self):
        bridge = MT5Bridge(mock=False)
        with (
            mock.patch.object(
                bridge,
                "connect",
                return_value={"success": False, "error": "terminal not running"},
            ),
            mock.patch(
                "neezy_backend.mt5_bridge.get_global_mt5_bridge", return_value=bridge
            ),
        ):
            code, out = self._run(["mt5", "account"])
        self.assertNotEqual(code, 0)
        self.assertNotIn("MT5 Account Info", out)


if __name__ == "__main__":
    unittest.main()
