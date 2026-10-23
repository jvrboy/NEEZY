from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from neezy_backend.executor_config import ExecutorConfig
from neezy_backend.executor_service import ExecutorService
from neezy_backend.status_api import StatusState
from tests.cloud_fixtures import candles, model_and_manifest


class FakeBridge:
    def __init__(self, *, trade_mode=0, connected=True):
        self.trade_mode = trade_mode
        self.connected = connected
        self.mock = False
        self.magic = 123
        self.orders = []
        self.rows = [
            {
                "time": int(row[0]),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
            }
            for row in candles()
        ]

    def connect(self):
        return {
            "success": self.connected,
            "connected": self.connected,
            "mock": False,
            "error": None if self.connected else "terminal offline",
        }

    def disconnect(self):
        pass

    def get_account_info(self):
        return {
            "balance": 10_000.0,
            "equity": 10_000.0,
            "currency": "USD",
            "trade_mode": self.trade_mode,
            "mock": False,
        }

    def get_positions(self):
        return []

    def get_account_history(self, days=1, limit=500):
        del days, limit
        return []

    def fetch_candles(self, _symbol, timeframe="15m", count=400):
        del timeframe
        return self.rows[-count:]

    def get_quote(self, _symbol):
        return {"bid": 1.1000, "ask": 1.1002, "mock": False}

    def place_order(self, symbol, direction, volume, **kwargs):
        self.orders.append((symbol, direction, volume, kwargs))
        return {"success": True, "ticket": 987, "mock": False}


class FakeManager:
    def __init__(self):
        self.model, self.content, self.manifest = model_and_manifest()

    def load_active(self):
        return {
            "model": self.model,
            "content": self.content,
            "manifest": self.manifest,
        }

    def status(self):
        return {"active": True, "model_id": self.manifest["model_id"]}

    def check_for_update(self):
        return {"status": "unchanged", "model_id": self.manifest["model_id"]}


class ExecutorServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = mock.patch.dict(
            os.environ, {"NEEZY_HOME": self.temporary.name}
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def service(self, bridge, enabled):
        return ExecutorService(
            ExecutorConfig(execution_enabled=enabled),
            bridge=bridge,
            managers={"frxEURUSD": FakeManager()},
            state=StatusState(),
        )

    def test_observer_reads_and_predicts_without_sending(self):
        bridge = FakeBridge()
        snapshot = self.service(bridge, False).run_once()
        self.assertEqual(snapshot["status"], "ok")
        self.assertEqual(len(bridge.orders), 0)
        prediction = snapshot["models"]["frxEURUSD"]["last_prediction"]
        self.assertEqual(prediction["direction"], "BUY")
        self.assertEqual(snapshot["account"]["trade_mode"], "DEMO")

    def test_demo_execution_sends_once_with_broker_side_levels(self):
        bridge = FakeBridge()
        service = self.service(bridge, True)
        first = service.run_once()
        second = service.run_once()
        self.assertEqual(first["status"], "ok")
        self.assertEqual(len(bridge.orders), 1)
        self.assertEqual(len(bridge.orders), 1)
        _symbol, _direction, volume, kwargs = bridge.orders[0]
        self.assertGreater(volume, 0)
        self.assertLessEqual(volume, 0.1)
        self.assertGreater(kwargs["sl"], 0)
        self.assertGreater(kwargs["tp"], 0)
        self.assertTrue(second["last_order"]["success"])
        self.assertEqual(second["risk"]["trades_today"], 1)

    def test_paper_mode_never_sends_or_activates_production_models(self):
        bridge = FakeBridge()
        model, content, manifest = model_and_manifest(paper=False)
        config = ExecutorConfig(
            hf_repo_id="owner/models",
            paper_candidate="manifests/candidate.json",
            paper_spread=0.0001,
        )
        with mock.patch(
            "neezy_backend.executor_service.load_paper_candidate",
            return_value={"model": model, "content": content, "manifest": manifest},
        ) as loader:
            service = ExecutorService(
                config,
                bridge=bridge,
                managers={"frxEURUSD": object()},
                state=StatusState(),
            )
            snapshot = service.run_once()
            service.run_once()
        self.assertEqual(loader.call_count, 1)
        self.assertEqual(snapshot["execution"]["mode"], "paper-validation")
        self.assertFalse(snapshot["execution"]["enabled"])
        self.assertEqual(snapshot["paper_validation"]["model_id"], manifest["model_id"])
        self.assertTrue(snapshot["paper_validation"]["open_simulation"])
        self.assertEqual(bridge.orders, [])

    def test_real_account_is_never_auto_traded(self):
        bridge = FakeBridge(trade_mode=2)
        snapshot = self.service(bridge, True).run_once()
        self.assertEqual(snapshot["status"], "critical")
        self.assertEqual(len(bridge.orders), 0)
        self.assertTrue(
            any(
                issue["code"] == "demo_account_required" for issue in snapshot["issues"]
            )
        )

    def test_offline_broker_does_not_fabricate_account_or_positions(self):
        bridge = FakeBridge(connected=False)
        snapshot = self.service(bridge, False).run_once()
        self.assertEqual(snapshot["status"], "critical")
        self.assertEqual(snapshot["account"], {})
        self.assertEqual(snapshot["open_trades"], [])
        self.assertEqual(len(bridge.orders), 0)


if __name__ == "__main__":
    unittest.main()
