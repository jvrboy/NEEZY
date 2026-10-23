"""Bot framework: roster, lifecycle, deterministic ticks, decisions."""

import unittest
from datetime import datetime, timezone

from neezy_backend.bots import (
    FAILED,
    IDLE,
    PAUSED,
    RUNNING,
    STOPPED,
    Bot,
    BotContext,
    BotDecision,
    BotManager,
    default_bots,
)

_DEFAULT_SYMBOLS = {
    "frxEURUSD",
    "frxGBPUSD",
    "frxUSDJPY",
    "frxXAUUSD",
    "cryBTCUSD",
}


def make_fetch(symbols=None):
    symbols = symbols or _DEFAULT_SYMBOLS
    import math

    def fetch(symbol, seconds, count):
        if symbol not in symbols:
            raise RuntimeError(f"unknown symbol {symbol}")
        candles = []
        price = 1.10
        for index in range(count):
            drift = math.sin(index / 9.0) * 0.0015
            open_ = price
            close = price + drift
            high = max(open_, close) + 0.0006
            low = min(open_, close) - 0.0006
            price = close
            candles.append((1700000000 + index * seconds, open_, high, low, close))
        return candles

    return fetch


class RosterTests(unittest.TestCase):
    def test_default_roster_ids_unique(self):
        bots = default_bots()
        ids = [bot.bot_id for bot in bots]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(
            set(ids), {"scanner", "sessions", "risk_guard", "momentum", "scribe"}
        )

    def test_every_bot_described(self):
        for bot in default_bots():
            self.assertTrue(bot.name)
            self.assertTrue(bot.description)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.manager = BotManager(default_bots())

    def test_start_stop_pause_resume(self):
        self.assertEqual(self.manager.get("scanner").state, IDLE)
        self.manager.start("scanner")
        self.assertEqual(self.manager.get("scanner").state, RUNNING)
        self.manager.pause("scanner")
        self.assertEqual(self.manager.get("scanner").state, PAUSED)
        self.manager.resume("scanner")
        self.assertEqual(self.manager.get("scanner").state, RUNNING)
        self.manager.stop("scanner")
        self.assertEqual(self.manager.get("scanner").state, STOPPED)

    def test_pause_requires_running(self):
        with self.assertRaises(ValueError):
            self.manager.pause("scanner")

    def test_unknown_bot_rejected(self):
        with self.assertRaises(KeyError):
            self.manager.start("warp-drive")
        with self.assertRaises(KeyError):
            self.manager.stop("nope")

    def test_duplicate_registration_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.register(default_bots()[0])

    def test_reset_clears_counters(self):
        bot = self.manager.get("sessions")
        self.manager.start("sessions")
        self.manager.run_ticks(2, context=BotContext(fetch=None))
        self.assertGreater(bot.ticks_run, 0)
        self.manager.reset("sessions")
        self.assertEqual(bot.ticks_run, 0)
        self.assertIsNone(bot.last_decision)

    def test_stopped_bots_do_not_tick(self):
        self.manager.start_all()
        self.manager.stop("scribe")
        decisions = self.manager.run_ticks(1, context=BotContext(fetch=None))
        self.assertFalse(any(d.bot_id == "scribe" for d in decisions))

    def test_tick_bounds(self):
        with self.assertRaises(ValueError):
            self.manager.run_ticks(0)
        with self.assertRaises(ValueError):
            self.manager.run_ticks(101)

    def test_status_snapshot_shape(self):
        status = self.manager.status()
        self.assertEqual(status["total"], 5)
        self.assertEqual(status["running"], 0)
        self.assertEqual(status["decisions_logged"], 0)
        self.assertEqual(len(status["bots"]), 5)


class TickTests(unittest.TestCase):
    def test_sessions_bot_offline(self):
        manager = BotManager()
        manager.start("sessions")
        decisions = manager.run_ticks(1, context=BotContext(fetch=None))
        self.assertEqual(len(decisions), 1)
        self.assertIn("UTC", decisions[0].detail)

    def test_scribe_heartbeat_includes_notes(self):
        manager = BotManager()
        manager.start("scribe")
        context = BotContext(fetch=None, notes=["hello"])
        decisions = manager.run_ticks(1, context=context)
        self.assertIn("note: hello", decisions[0].detail)

    def test_scanner_ranks_watchlist(self):
        manager = BotManager()
        manager.start("scanner")
        context = BotContext(fetch=make_fetch(), watchlist=("frxEURUSD",))
        decisions = manager.run_ticks(1, context=context)
        self.assertEqual(decisions[0].action, "scan")
        self.assertIn("frxEURUSD", decisions[0].detail)
        self.assertEqual(decisions[0].data["scanned"], 1)

    def test_scanner_survives_fetch_errors(self):
        def broken(_symbol, _seconds, _count):
            raise OSError("network down")

        manager = BotManager()
        manager.start("scanner")
        decisions = manager.run_ticks(
            1, context=BotContext(fetch=broken, watchlist=("frxEURUSD",))
        )
        self.assertIn("no market", decisions[0].detail)

    def test_risk_guard_advises(self):
        manager = BotManager()
        manager.start("risk_guard")
        context = BotContext(
            fetch=make_fetch(), watchlist=("frxEURUSD",), balance=5000.0
        )
        decisions = manager.run_ticks(1, context=context)
        self.assertEqual(decisions[0].action, "advise")
        self.assertIn("lots=", decisions[0].detail)

    def test_momentum_reads_primary(self):
        manager = BotManager()
        manager.start("momentum")
        decisions = manager.run_ticks(
            1, context=BotContext(fetch=make_fetch(), watchlist=("frxXAUUSD",))
        )
        self.assertEqual(decisions[0].action, "read")
        self.assertIn("RSI", decisions[0].detail)

    def test_failed_bot_records_error(self):
        def exploding(_context):
            raise RuntimeError("kaboom")

        manager = BotManager([Bot("boom", "Boom", "test", "explodes", exploding)])
        manager.start("boom")
        decisions = manager.run_ticks(1, context=BotContext())
        self.assertEqual(decisions[0].action, "error")
        self.assertIn("kaboom", decisions[0].detail)
        self.assertEqual(manager.get("boom").state, FAILED)

    def test_failed_bot_cannot_restart(self):
        def exploding(_context):
            raise RuntimeError("kaboom")

        manager = BotManager([Bot("boom", "Boom", "test", "explodes", exploding)])
        manager.start("boom")
        manager.run_ticks(1, context=BotContext())
        with self.assertRaises(ValueError):
            manager.start("boom")

    def test_run_only_selects_one_bot(self):
        manager = BotManager()
        manager.start_all()
        decisions = manager.run_ticks(
            1, context=BotContext(fetch=None), only="sessions"
        )
        self.assertEqual({d.bot_id for d in decisions}, {"sessions"})

    def test_decision_log_accumulates(self):
        manager = BotManager()
        manager.start("sessions")
        manager.run_ticks(2, context=BotContext(fetch=None))
        self.assertEqual(len(manager.decision_log), 2)

    def test_fixed_clock_for_reproducibility(self):
        manager = BotManager()
        manager.start("sessions")
        moment = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)
        decisions = manager.run_ticks(
            1, context=BotContext(fetch=None, now=lambda: moment)
        )
        self.assertIn("13:30", decisions[0].detail)


class DecisionTests(unittest.TestCase):
    def test_decision_defaults(self):
        decision = BotDecision(bot_id="x", action="a", detail="d")
        self.assertEqual(decision.data, {})


if __name__ == "__main__":
    unittest.main()
