"""Thread marshalling tests for remote desktop commands."""

from __future__ import annotations

import threading
import unittest

from neezy_backend.remote import AppCommandBridge


class AppCommandBridgeTest(unittest.TestCase):
    def test_worker_request_is_processed_on_owner_thread(self):
        bridge = AppCommandBridge(timeout=2)
        result = {}
        started = threading.Event()

        def worker():
            started.set()
            result["value"] = bridge.call("echo", value=3)

        thread = threading.Thread(target=worker)
        thread.start()
        self.assertTrue(started.wait(1))
        while thread.is_alive():
            bridge.process(lambda action, args: (action, args["value"]))
            thread.join(0.01)
        self.assertEqual(result["value"], ("echo", 3))
        bridge.close()

    def test_ui_thread_cannot_wait_on_its_own_queue(self):
        bridge = AppCommandBridge()
        with self.assertRaisesRegex(RuntimeError, "cannot synchronously call itself"):
            bridge.call("deadlock")
        bridge.close()

    def test_close_rejects_new_calls(self):
        bridge = AppCommandBridge()
        bridge.close()
        with self.assertRaisesRegex(RuntimeError, "shutting down"):
            bridge.call("closed")


if __name__ == "__main__":
    unittest.main()
