from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from neezy_backend.execution_guard import ExecutionGuard
from neezy_backend.executor_config import ExecutorConfig


class ExecutionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "risk.json"
        self.now = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
        self.config = ExecutorConfig(execution_enabled=True)

    def tearDown(self):
        self.temporary.cleanup()

    def guard(self):
        return ExecutionGuard(self.config, self.path, clock=lambda: self.now)

    @staticmethod
    def account(**changes):
        account = {
            "balance": 10_000.0,
            "equity": 10_000.0,
            "trade_mode": 0,
            "mock": False,
        }
        account.update(changes)
        return account

    def refresh(self, guard, **account_changes):
        return guard.refresh(self.account(**account_changes), [], [], bot_magic=123)

    def valid_order(self, guard, risk=None):
        return guard.authorize_order(
            account=self.account(),
            positions=[],
            risk=risk or self.refresh(guard),
            direction="BUY",
            volume=0.1,
            entry=1.1,
            stop=1.09,
            target=1.12,
        )

    def test_valid_demo_order_passes(self):
        guard = self.guard()
        self.assertEqual(self.valid_order(guard), [])

    def test_observer_mode_blocks_order(self):
        self.config = ExecutorConfig(execution_enabled=False)
        guard = self.guard()
        self.assertIn("execution_enabled is false", self.valid_order(guard))

    def test_real_account_and_simulation_are_blocked(self):
        guard = self.guard()
        risk = guard.refresh(self.account(trade_mode=2), [], [], bot_magic=123)
        self.assertFalse(risk["can_trade"])
        reasons = guard.authorize_order(
            account=self.account(trade_mode=2),
            positions=[],
            risk=risk,
            direction="BUY",
            volume=0.1,
            entry=1.1,
            stop=1.09,
            target=1.12,
        )
        self.assertTrue(any("demo" in reason for reason in reasons))

    def test_daily_loss_and_trade_counts_survive_restart(self):
        guard = self.guard()
        self.refresh(guard)
        guard.record_filled_order()
        risk = self.refresh(guard, equity=9_700)
        self.assertFalse(risk["can_trade"])
        self.assertIn("maximum daily loss reached", risk["blockers"])

        reopened = self.guard()
        restored = self.refresh(reopened, equity=9_700)
        self.assertEqual(restored["trades_today"], 1)
        self.assertEqual(restored["day_start_balance"], 10_000)
        self.assertIn("maximum daily loss reached", restored["blockers"])

    def test_first_midday_start_reconstructs_balance_from_realized_deals(self):
        guard = self.guard()
        midnight = datetime(2026, 10, 23, tzinfo=timezone.utc).timestamp()
        risk = guard.refresh(
            self.account(balance=9_900, equity=9_850),
            [],
            [
                {
                    "time": midnight + 100,
                    "profit": -100,
                    "commission": 0,
                    "swap": 0,
                }
            ],
            bot_magic=123,
        )
        self.assertEqual(risk["day_start_balance"], 10_000)
        self.assertEqual(risk["daily_loss_percent"], 1.5)

    def test_new_utc_day_resets_trade_count_not_candle_dedupe(self):
        guard = self.guard()
        self.refresh(guard)
        guard.record_filled_order()
        guard.mark_evaluated("frxEURUSD", 1000)
        self.now += timedelta(days=1)
        risk = self.refresh(guard)
        self.assertEqual(risk["trades_today"], 0)
        self.assertFalse(guard.should_evaluate("frxEURUSD", 1000))
        self.assertTrue(guard.should_evaluate("frxEURUSD", 1001))

    def test_unprotected_bot_position_blocks_new_risk(self):
        guard = self.guard()
        positions = [{"ticket": 77, "magic": 123, "sl": 0.0}]
        risk = guard.refresh(self.account(), positions, [], bot_magic=123)
        self.assertEqual(risk["unprotected_bot_positions"], [77])
        self.assertFalse(risk["can_trade"])

    def test_stop_target_position_and_volume_gates(self):
        guard = self.guard()
        risk = self.refresh(guard)
        base = {
            "account": self.account(),
            "risk": risk,
            "direction": "BUY",
            "entry": 1.1,
            "stop": 1.09,
            "target": 1.12,
            "volume": 0.1,
            "positions": [],
        }
        for changes in (
            {"stop": 0},
            {"target": 1.08},
            {"volume": 0.2},
            {"positions": [{"ticket": 1}]},
        ):
            with self.subTest(changes=changes):
                self.assertTrue(guard.authorize_order(**(base | changes)))

    def test_candle_is_persisted_before_a_restart(self):
        guard = self.guard()
        self.assertTrue(guard.should_evaluate("frxEURUSD", 100))
        guard.mark_evaluated("frxEURUSD", 100)
        self.assertFalse(self.guard().should_evaluate("frxEURUSD", 100))

    def test_corrupt_risk_state_fails_closed(self):
        self.path.write_text("not-json", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "refusing to reset"):
            self.guard()

    def test_malformed_candle_state_also_fails_closed(self):
        self.path.write_text(
            '{"schema":1,"day":null,"day_start_balance":null,'
            '"trades":0,"last_candles":{"frxEURUSD":"invalid"}}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "malformed"):
            self.guard()


if __name__ == "__main__":
    unittest.main()
