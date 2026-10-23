"""Tests for MT5Bridge state machine transitions."""

from __future__ import annotations

import unittest
from unittest import mock

from neezy_backend.mt5_bridge import MT5Bridge, MT5ConnectionState


class MT5StateMachineTests(unittest.TestCase):
    def test_initial_state_is_disconnected(self) -> None:
        bridge = MT5Bridge(mock=True)
        self.assertEqual(bridge.state, MT5ConnectionState.DISCONNECTED)
        self.assertFalse(bridge.connected)

    def test_successful_connection_transitions_to_connected(self) -> None:
        bridge = MT5Bridge(mock=True)
        res = bridge.connect()
        self.assertTrue(res["success"])
        self.assertEqual(bridge.state, MT5ConnectionState.CONNECTED)
        self.assertTrue(bridge.connected)

    def test_disconnect_transitions_to_disconnected(self) -> None:
        bridge = MT5Bridge(mock=True)
        bridge.connect()
        self.assertEqual(bridge.state, MT5ConnectionState.CONNECTED)
        bridge.disconnect()
        self.assertEqual(bridge.state, MT5ConnectionState.DISCONNECTED)
        self.assertFalse(bridge.connected)

    def test_failed_connection_transitions_to_failed(self) -> None:
        fake_mt5 = mock.Mock()
        fake_mt5.initialize.return_value = False
        fake_mt5.last_error.return_value = "IPC connect failed"
        with mock.patch("neezy_backend.mt5_bridge.mt5", fake_mt5):
            bridge = MT5Bridge(mock=False)
            res = bridge.connect()
            self.assertFalse(res["success"])
            self.assertEqual(bridge.state, MT5ConnectionState.FAILED)
            self.assertFalse(bridge.connected)

    def test_connecting_guard_rejects_concurrent_connect(self) -> None:
        bridge = MT5Bridge(mock=True)
        bridge.state = MT5ConnectionState.CONNECTING
        res = bridge.connect()
        self.assertFalse(res["success"])
        self.assertIn("Cannot connect while state is CONNECTING", res["error"])

    def test_already_connected_returns_success(self) -> None:
        bridge = MT5Bridge(mock=True)
        bridge.connect()
        res = bridge.connect()
        self.assertTrue(res["success"])
        self.assertEqual(bridge.state, MT5ConnectionState.CONNECTED)


if __name__ == "__main__":
    unittest.main()
