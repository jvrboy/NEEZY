"""MT5 backend selection and the RPyC terminal client (no real terminal, offline)."""

from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
import types
import unittest
from collections import namedtuple
from unittest import mock

from neezy_backend import mt5_bridge
from neezy_backend.mt5_compat import (
    BACKEND_ENV,
    DEFAULT_RPYC_PORT,
    REMOTE_CONSTANTS,
    RPYC_HOST_ENV,
    RPYC_PORT_ENV,
    RpycMT5,
    _revive,
    current_selection,
    detect_runtime,
    load_mt5_module,
    rpyc_port,
    select_backend,
)

HAS_RPYC = importlib.util.find_spec("rpyc") is not None
HAS_NUMPY = importlib.util.find_spec("numpy") is not None
HAS_MT5LINUX = importlib.util.find_spec("mt5linux") is not None

AccountInfo = namedtuple("AccountInfo", "login server balance equity currency")
Tick = namedtuple("Tick", "bid ask last volume time")
Deal = namedtuple("Deal", "ticket order time symbol type entry volume price")
OrderResult = namedtuple("OrderResult", "retcode order volume price comment")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def build_fake_terminal() -> types.ModuleType:
    """A stand-in for ``MetaTrader5`` as served by mt5server.exe."""
    fake = types.ModuleType("MetaTrader5")
    fake.TIMEFRAME_M5 = 5
    fake.TIMEFRAME_H1 = 16385
    fake.TRADE_RETCODE_DONE = 10009
    fake.REMOTE_ONLY_CONSTANT = 4242  # not in REMOTE_CONSTANTS: fetched remotely
    fake.calls = []
    fake.initialize = lambda *a, **k: (fake.calls.append("initialize"), True)[1]
    fake.shutdown = lambda: fake.calls.append("shutdown")
    fake.last_error = lambda: (1, "Success")
    fake.terminal_info = lambda: {"name": "MetaTrader 5 (fake)"}
    fake.account_info = lambda: AccountInfo(7001, "Demo-Server", 1000.5, 1002.0, "USD")
    fake.symbol_info_tick = lambda symbol: (
        None if symbol == "MISSING" else Tick(1.1, 1.1002, 0.0, 0, 1700000000)
    )
    fake.positions_get = lambda **kwargs: (
        ()
        if kwargs.get("ticket")
        else (Deal(1, 1, 1700000000, "EURUSD", 0, 0, 0.1, 1.1),)
    )
    fake.history_deals_get = lambda start, end: (
        Deal(9, 9, 1700000100, "EURUSD", 1, 1, 0.1, 1.09),
    )
    fake.order_send = lambda request: OrderResult(
        10009, 555, request.get("volume", 0), 1.1, "fake"
    )
    fake.boom = lambda: (_ for _ in ()).throw(RuntimeError("terminal refused"))
    if HAS_NUMPY:
        import numpy as np

        dtype = [
            ("time", "i8"),
            ("open", "f8"),
            ("high", "f8"),
            ("low", "f8"),
            ("close", "f8"),
            ("tick_volume", "u8"),
        ]
        rates = np.array([(1700000000, 1.0, 1.2, 0.9, 1.1, 50)], dtype=dtype)
        fake.copy_rates_from_pos = lambda symbol, tf, start, count: rates
    return fake


class FakeTerminalServer:
    """Serve ``build_fake_terminal()`` over the RPyC classic protocol, in-process."""

    def __enter__(self) -> FakeTerminalServer:
        from rpyc.utils.classic import ClassicService
        from rpyc.utils.server import ThreadedServer

        self.module = build_fake_terminal()
        self._saved = sys.modules.get("MetaTrader5")
        sys.modules["MetaTrader5"] = self.module
        self.port = free_port()
        self.server = ThreadedServer(
            ClassicService,
            hostname="127.0.0.1",
            port=self.port,
            protocol_config={
                "allow_all_attrs": True,
                "allow_pickle": True,
                "allow_public_attrs": True,
            },
            logger=None,
        )
        thread = threading.Thread(target=self.server.start, daemon=True)
        thread.start()
        # ``active`` flips once the listener is up. Polling it avoids probe
        # connections, which the server would log as errors.
        deadline = time.monotonic() + 5
        while not self.server.active:
            if time.monotonic() > deadline:
                raise RuntimeError("in-process RPyC server did not start")
            time.sleep(0.01)
        return self

    def __exit__(self, *exc_info) -> None:
        self.server.close()
        if self._saved is None:
            sys.modules.pop("MetaTrader5", None)
        else:
            sys.modules["MetaTrader5"] = self._saved


class RuntimeDetectionTests(unittest.TestCase):
    def test_termux_detected_by_version_or_prefix_before_linux(self):
        self.assertEqual(
            detect_runtime({"TERMUX_VERSION": "0.118"}, platform="linux"), "termux"
        )
        self.assertEqual(
            detect_runtime(
                {"PREFIX": "/data/data/com.termux/files/usr"}, platform="linux"
            ),
            "termux",
        )

    def test_codespaces_and_actions_win_over_plain_linux(self):
        self.assertEqual(
            detect_runtime({"CODESPACES": "true"}, platform="linux"), "codespaces"
        )
        self.assertEqual(
            detect_runtime({"GITHUB_ACTIONS": "true"}, platform="linux"),
            "github_actions",
        )

    def test_flag_values_must_match_exactly(self):
        self.assertEqual(
            detect_runtime({"CODESPACES": "false"}, platform="linux"), "linux"
        )
        self.assertEqual(
            detect_runtime({"GITHUB_ACTIONS": "1"}, platform="linux"), "linux"
        )

    def test_colab_by_release_tag_or_gpu_variable(self):
        self.assertEqual(
            detect_runtime({"COLAB_RELEASE_TAG": "release-2024"}, platform="linux"),
            "colab",
        )
        self.assertEqual(detect_runtime({"COLAB_GPU": "0"}, platform="linux"), "colab")

    def test_desktop_platforms(self):
        self.assertEqual(detect_runtime({}, platform="win32"), "windows")
        self.assertEqual(detect_runtime({}, platform="darwin"), "macos")
        self.assertEqual(detect_runtime({}, platform="linux"), "linux")
        self.assertEqual(detect_runtime({}, platform="freebsd13"), "other")


class SelectionTests(unittest.TestCase):
    def select(self, env, *, native=False, rpyc=True, runtime="linux"):
        return select_backend(
            env, native_importable=native, rpyc_importable=rpyc, runtime=runtime
        )

    def test_default_without_mt5_stays_simulated(self):
        choice = self.select({}, native=False, rpyc=True)
        self.assertEqual(choice.backend, "none")
        self.assertIn(RPYC_HOST_ENV, choice.reason)

    def test_native_package_preferred_in_auto(self):
        env = {RPYC_HOST_ENV: "10.0.0.5"}
        choice = self.select(env, native=True)
        self.assertEqual(choice.backend, "native")

    def test_auto_uses_rpyc_only_when_host_configured(self):
        choice = self.select({RPYC_HOST_ENV: "10.0.0.5"})
        self.assertEqual(choice.backend, "rpyc")
        self.assertEqual(choice.rpyc_host, "10.0.0.5")
        self.assertEqual(choice.rpyc_port, DEFAULT_RPYC_PORT)

    def test_auto_without_rpyc_package_explains_install(self):
        choice = self.select({RPYC_HOST_ENV: "10.0.0.5"}, rpyc=False)
        self.assertEqual(choice.backend, "none")
        self.assertIn("mt5-remote", choice.reason)

    def test_forced_native_fails_closed_when_missing(self):
        choice = self.select({BACKEND_ENV: "native"}, native=False)
        self.assertEqual(choice.backend, "none")
        self.assertIn("not importable", choice.reason)

    def test_forced_rpyc_requires_host(self):
        choice = self.select({BACKEND_ENV: "rpyc"}, native=True)
        self.assertEqual(choice.backend, "none")
        self.assertIn(RPYC_HOST_ENV, choice.reason)

    def test_forced_rpyc_ignores_native_package(self):
        env = {BACKEND_ENV: "rpyc", RPYC_HOST_ENV: "wine.lan"}
        self.assertEqual(self.select(env, native=True).backend, "rpyc")

    def test_none_disables_everything(self):
        env = {BACKEND_ENV: "none", RPYC_HOST_ENV: "wine.lan"}
        choice = self.select(env, native=True)
        self.assertEqual(choice.backend, "none")

    def test_unknown_backend_name_fails_closed(self):
        choice = self.select({BACKEND_ENV: "wine"}, native=True)
        self.assertEqual(choice.backend, "none")
        self.assertIn("not one of", choice.reason)

    def test_backend_name_is_case_and_space_insensitive(self):
        env = {BACKEND_ENV: "  RPYC ", RPYC_HOST_ENV: "wine.lan"}
        self.assertEqual(self.select(env).backend, "rpyc")

    def test_invalid_port_fails_closed(self):
        env = {RPYC_HOST_ENV: "wine.lan", RPYC_PORT_ENV: "70000"}
        choice = self.select(env)
        self.assertEqual(choice.backend, "none")
        self.assertIn("1-65535", choice.reason)

    def test_port_parsing(self):
        self.assertEqual(rpyc_port({}), DEFAULT_RPYC_PORT)
        self.assertEqual(rpyc_port({RPYC_PORT_ENV: " 18900 "}), 18900)
        with self.assertRaises(ValueError):
            rpyc_port({RPYC_PORT_ENV: "abc"})

    @unittest.skipUnless(HAS_RPYC, "rpyc not installed")
    def test_current_selection_reads_environment_without_connecting(self):
        env = {BACKEND_ENV: "rpyc", RPYC_HOST_ENV: "wine.lan"}
        with mock.patch.dict("os.environ", env, clear=False):
            selection = current_selection()
        self.assertEqual(selection.backend, "rpyc")
        self.assertEqual(selection.rpyc_host, "wine.lan")

    def test_load_returns_lazy_client_and_never_connects(self):
        env = {BACKEND_ENV: "rpyc", RPYC_HOST_ENV: "127.0.0.1", RPYC_PORT_ENV: "1"}
        module = load_mt5_module(env)
        self.assertIsInstance(module, RpycMT5)
        self.assertIsNone(module._conn)

    def test_load_returns_none_without_backend(self):
        self.assertIsNone(load_mt5_module({BACKEND_ENV: "none"}))


@unittest.skipUnless(HAS_MT5LINUX, "mt5linux not installed; cross-check skipped")
class ConstantsAgainstMt5linuxTests(unittest.TestCase):
    def test_embedded_constants_match_upstream(self):
        from mt5linux.constants import Constants

        for name, value in REMOTE_CONSTANTS.items():
            self.assertEqual(getattr(Constants, name), value, name)


class RevivalTests(unittest.TestCase):
    def test_records_support_attribute_and_asdict_access(self):
        record = _revive(
            {"__record__": True, "fields": ["bid", "ask"], "values": [1.1, 1.2]}
        )
        self.assertEqual(record.ask, 1.2)
        self.assertEqual(record._asdict(), {"bid": 1.1, "ask": 1.2})

    def test_unsafe_field_names_are_renamed_not_rejected(self):
        record = _revive(
            {"__record__": True, "fields": ["class", "1x"], "values": [1, 2]}
        )
        self.assertEqual(record[0], 1)

    def test_plain_values_pass_through(self):
        self.assertEqual(_revive([1, {"a": "b"}, None]), [1, {"a": "b"}, None])


@unittest.skipUnless(HAS_RPYC, "rpyc not installed")
class RpycTerminalTests(unittest.TestCase):
    def setUp(self):
        self.server_ctx = FakeTerminalServer()
        self.server = self.server_ctx.__enter__()
        self.addCleanup(self.server_ctx.__exit__, None, None, None)
        self.client = RpycMT5("127.0.0.1", self.server.port, timeout=10)
        self.addCleanup(self.client.close)

    def test_constants_come_from_table_without_connecting(self):
        self.assertEqual(self.client.TIMEFRAME_H1, 16385)
        self.assertIsNone(self.client._conn)

    def test_unknown_constant_is_fetched_from_remote(self):
        self.assertEqual(self.client.REMOTE_ONLY_CONSTANT, 4242)

    def test_missing_private_attribute_is_not_forwarded(self):
        with self.assertRaises(AttributeError):
            self.client._definitely_private  # noqa: B018

    def test_account_info_is_a_record_with_asdict(self):
        info = self.client.account_info()
        self.assertEqual(info._asdict()["login"], 7001)
        self.assertEqual(info.server, "Demo-Server")

    def test_initialize_forwards_keyword_arguments(self):
        self.assertTrue(self.client.initialize(login=7001, server="Demo-Server"))
        self.assertIn("initialize", self.server.module.calls)

    def test_order_result_keeps_attribute_access(self):
        result = self.client.order_send({"volume": 0.2, "action": 1})
        self.assertEqual(result.retcode, self.client.TRADE_RETCODE_DONE)
        self.assertEqual(result.order, 555)

    def test_positions_and_history_return_record_sequences(self):
        positions = self.client.positions_get()
        self.assertEqual(positions[0].symbol, "EURUSD")
        self.assertEqual(self.client.positions_get(ticket=99), ())
        deals = self.client.history_deals_get(0, 10)
        self.assertEqual(sorted(d.time for d in deals), [1700000100])

    def test_none_result_survives_the_round_trip(self):
        self.assertIsNone(self.client.symbol_info_tick("MISSING"))

    @unittest.skipUnless(HAS_NUMPY, "numpy not installed")
    def test_rates_arrive_as_rows_indexable_by_name(self):
        rates = self.client.copy_rates_from_pos("EURUSD", 5, 0, 1)
        self.assertEqual(len(rates), 1)
        self.assertEqual(rates[0]["close"], 1.1)
        self.assertIsInstance(rates[0]["tick_volume"], int)

    def test_remote_exception_propagates(self):
        with self.assertRaises(Exception) as ctx:
            self.client.boom()
        self.assertIn("terminal refused", str(ctx.exception))

    def test_shutdown_closes_socket_and_next_call_reconnects(self):
        self.client.account_info()
        self.client.shutdown()
        self.assertIsNone(self.client._conn)
        self.assertIn("shutdown", self.server.module.calls)
        self.assertEqual(self.client.account_info().login, 7001)

    def test_shutdown_is_noop_when_never_connected(self):
        self.client.shutdown()
        self.assertIsNone(self.client._conn)

    def test_bridge_connects_through_rpyc_backend(self):
        with mock.patch.object(mt5_bridge, "mt5", self.client):
            bridge = mt5_bridge.MT5Bridge(login=7001, server="Demo-Server")
            status = bridge.connect()
            self.assertTrue(status["success"], status)
            self.assertFalse(status["mock"])
            self.assertEqual(status["balance"], 1000.5)
            bridge.disconnect()

    def test_bridge_reports_error_when_nothing_listens(self):
        dead = RpycMT5("127.0.0.1", free_port(), timeout=2)
        with mock.patch.object(mt5_bridge, "mt5", dead):
            status = mt5_bridge.MT5Bridge(login=7001).connect()
        self.assertFalse(status["success"])
        self.assertIn("Connection error", status["error"])
        self.assertIsNone(dead._conn)


if __name__ == "__main__":
    unittest.main()
