from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from neezy_backend.status_api import StatusServer, StatusState


class StatusApiTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        self.state = StatusState(clock=lambda: self.now)
        self.server = StatusServer(self.state, "127.0.0.1", 0)
        self.server.start()
        host, port = self.server.address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.server.stop()

    def read(self, path):
        with urllib.request.urlopen(self.base + path, timeout=3) as response:
            return response.status, json.loads(response.read())

    def test_status_is_read_only_and_contains_equity(self):
        self.state.update(account={"equity": 10_000}, broker={"connected": True})
        self.state.record_equity(10_000, force=True)
        self.state.heartbeat("ok", [])
        status, document = self.read("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(document["account"]["equity"], 10_000)
        self.assertEqual(len(document["equity_history"]), 1)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(
                urllib.request.Request(self.base + "/api/status", method="POST"),
                timeout=3,
            )
        self.assertEqual(caught.exception.code, 405)

    def test_research_catalog_is_read_only_and_advisory(self):
        status, document = self.read("/api/capabilities")
        self.assertEqual(status, 200)
        self.assertTrue(document["advisory_only"])
        self.assertEqual(len(document["engines"]), 4)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(
                urllib.request.Request(self.base + "/api/capabilities", method="POST"),
                timeout=3,
            )
        self.assertEqual(caught.exception.code, 405)

    def test_health_computes_heartbeat_age(self):
        self.state.heartbeat("ok", [])
        self.now += timedelta(seconds=12)
        _status, document = self.read("/health")
        self.assertTrue(document["ok"])
        self.assertEqual(document["heartbeat_age_seconds"], 12)

    def test_unknown_route_is_not_a_broker_action(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.read("/api/trade")
        self.assertEqual(caught.exception.code, 404)

    def test_equity_history_survives_a_service_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            state = StatusState(clock=lambda: self.now, persistence_path=path)
            state.record_equity(10_000, force=True)
            self.now += timedelta(minutes=1)
            state.record_equity(10_025.5, force=True)
            restored = StatusState(clock=lambda: self.now, persistence_path=path)
            history = restored.snapshot()["equity_history"]
            self.assertEqual(
                [sample["equity"] for sample in history], [10_000, 10_025.5]
            )

    def test_corrupt_equity_history_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaises(ValueError):
                StatusState(clock=lambda: self.now, persistence_path=path)

    def test_public_bind_is_refused(self):
        with self.assertRaises(ValueError):
            StatusServer(self.state, "0.0.0.0", 0)


if __name__ == "__main__":
    unittest.main()
