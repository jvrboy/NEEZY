"""Read-only MT5 preflight: uses a fake MetaTrader5 module, never a real terminal."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from neezy_backend import cli, mt5_bridge
from neezy_backend.config import AppSettings
from neezy_backend.mt5_preflight import FAIL, OK, WARN, has_failures, run_preflight


class _Record(SimpleNamespace):
    def _asdict(self):
        return dict(vars(self))


class FakeMT5:
    """Stands in for the MetaTrader5 module; records every call made to it."""

    def __init__(
        self,
        *,
        init_ok=True,
        login=424242,
        trade_mode=0,
        account_trade=True,
        terminal_trade=True,
        known_symbols=("EURUSD",),
        account_none=False,
    ):
        self.init_ok = init_ok
        self.login = login
        self.trade_mode = trade_mode
        self.account_trade = account_trade
        self.terminal_trade = terminal_trade
        self.known_symbols = set(known_symbols)
        self.account_none = account_none
        self.calls: list[str] = []

    def initialize(self, **kwargs):
        self.calls.append("initialize")
        return self.init_ok

    def last_error(self):
        return (-10003, "IPC initialize failed")

    def account_info(self):
        self.calls.append("account_info")
        if self.account_none:
            return None
        return _Record(
            login=self.login,
            server="Broker-Demo",
            trade_mode=self.trade_mode,
            trade_allowed=self.account_trade,
        )

    def terminal_info(self):
        self.calls.append("terminal_info")
        return _Record(trade_allowed=self.terminal_trade)

    def symbol_info(self, name):
        self.calls.append(f"symbol_info:{name}")
        return _Record(name=name) if name in self.known_symbols else None

    def symbol_select(self, *args, **kwargs):  # must never be called
        raise AssertionError("preflight must not change Market Watch")

    def order_send(self, *args, **kwargs):  # must never be called
        raise AssertionError("preflight must never send orders")


GOOD = {
    "mt5_login": 424242,
    "mt5_password": "hunter2",
    "mt5_server": "Broker-Demo",
    "mt5_symbol_map": "frxEURUSD=EURUSD",
}


class PreflightTests(unittest.TestCase):
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

    def _checks(self, fake, **overrides):
        settings = AppSettings(**{**GOOD, **overrides})
        if fake is None:
            with mock.patch.object(mt5_bridge, "mt5", None):
                return run_preflight(settings)
        with mock.patch.object(mt5_bridge, "mt5", fake):
            return run_preflight(settings)

    def _by_name(self, checks):
        return {check.name: check for check in checks}

    def test_missing_package_fails_and_never_connects(self):
        checks = self._checks(None)
        names = self._by_name(checks)
        self.assertEqual(names["MetaTrader5 package"].status, FAIL)
        self.assertEqual(names["connection"].status, WARN)
        self.assertTrue(has_failures(checks))

    def test_ready_demo_account_has_no_failures(self):
        fake = FakeMT5()
        checks = self._checks(fake)
        self.assertFalse(has_failures(checks), [c for c in checks if c.status == FAIL])
        names = self._by_name(checks)
        self.assertEqual(names["connection"].status, OK)
        self.assertEqual(names["account type"].status, OK)
        self.assertIn("DEMO", names["account type"].detail)
        self.assertEqual(names["trading allowed"].status, OK)
        self.assertEqual(names["symbol EURUSD"].status, OK)

    def test_real_account_is_flagged_as_live(self):
        checks = self._checks(FakeMT5(trade_mode=2))
        names = self._by_name(checks)
        self.assertEqual(names["account type"].status, WARN)
        self.assertIn("real money", names["account type"].detail)

    def test_trading_blocked_on_account_fails(self):
        checks = self._checks(FakeMT5(account_trade=False))
        self.assertEqual(self._by_name(checks)["trading allowed"].status, FAIL)
        self.assertTrue(has_failures(checks))

    def test_trading_blocked_in_terminal_fails(self):
        checks = self._checks(FakeMT5(terminal_trade=False))
        self.assertEqual(self._by_name(checks)["trading allowed"].status, FAIL)

    def test_failed_initialize_reports_connection_failure(self):
        checks = self._checks(FakeMT5(init_ok=False))
        names = self._by_name(checks)
        self.assertEqual(names["connection"].status, FAIL)
        self.assertIn("initialize", names["connection"].detail)
        self.assertNotIn("account type", names)

    def test_unreadable_account_fails(self):
        checks = self._checks(FakeMT5(account_none=True))
        self.assertEqual(self._by_name(checks)["account"].status, FAIL)

    def test_login_mismatch_warns(self):
        checks = self._checks(FakeMT5(login=999))
        self.assertEqual(self._by_name(checks)["account match"].status, WARN)

    def test_missing_symbol_warns(self):
        checks = self._checks(FakeMT5(known_symbols=()))
        self.assertEqual(self._by_name(checks)["symbol EURUSD"].status, WARN)

    def test_missing_login_and_server_warns_and_still_connects(self):
        fake = FakeMT5()
        checks = self._checks(fake, mt5_login=0, mt5_server="")
        self.assertEqual(self._by_name(checks)["login and server"].status, WARN)
        self.assertIn("initialize", fake.calls)

    def test_login_without_server_fails_before_connecting(self):
        fake = FakeMT5()
        checks = self._checks(fake, mt5_login=424242, mt5_server="")
        self.assertEqual(self._by_name(checks)["login and server"].status, FAIL)
        self.assertNotIn("initialize", fake.calls)

    def test_missing_terminal_path_fails(self):
        checks = self._checks(FakeMT5(), mt5_path="C:/does/not/exist/terminal64.exe")
        self.assertEqual(self._by_name(checks)["terminal path"].status, FAIL)

    def test_password_is_never_printed(self):
        checks = self._checks(FakeMT5(init_ok=False))
        self.assertTrue(all("hunter2" not in c.detail for c in checks))
        checks = self._checks(FakeMT5())
        self.assertTrue(all("hunter2" not in c.detail for c in checks))

    def test_preflight_uses_only_read_calls(self):
        fake = FakeMT5()
        self._checks(fake)
        allowed = {"initialize", "account_info", "terminal_info"}
        for call in fake.calls:
            self.assertTrue(call in allowed or call.startswith("symbol_info:"), call)

    def test_reads_saved_settings_from_disk(self):
        (self.home / "settings.json").write_text(
            json.dumps({"mt5_login": 1, "mt5_server": ""}), encoding="utf-8"
        )
        with mock.patch.object(mt5_bridge, "mt5", FakeMT5()):
            checks = run_preflight()
        self.assertEqual(self._by_name(checks)["login and server"].status, FAIL)


class PreflightCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"NEEZY_HOME": self._tmp.name})
        self._env.start()
        mt5_bridge._GLOBAL_BRIDGE = None
        mt5_bridge._GLOBAL_KEY = None

    def tearDown(self) -> None:
        mt5_bridge._GLOBAL_BRIDGE = None
        mt5_bridge._GLOBAL_KEY = None
        self._env.stop()
        self._tmp.cleanup()

    def test_unconfigured_machine_exits_nonzero(self):
        out = io.StringIO()
        code = cli.main(["mt5", "preflight"], out=out)
        self.assertEqual(code, 1)
        self.assertIn("NOT READY", out.getvalue())

    def test_json_output_lists_checks(self):
        out = io.StringIO()
        cli.main(["mt5", "preflight", "--json"], out=out)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertTrue(
            any(c["name"] == "MetaTrader5 package" for c in payload["checks"])
        )


if __name__ == "__main__":
    unittest.main()
