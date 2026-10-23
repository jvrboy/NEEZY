"""Multi-agent team: blackboard, messages, and deterministic briefings."""

import math
import unittest

from neezy_backend.agents import (
    Agent,
    AgentMessage,
    AgentTeam,
    Blackboard,
    TeamContext,
)
from neezy_backend.bots import WATCHLIST  # watchlist constant shared by bots


def make_fetch(symbols=None):
    symbols = symbols or {"frxEURUSD", "frxXAUUSD"}
    offset = {"frxEURUSD": 1.10, "frxXAUUSD": 2300.0}

    def fetch(symbol, seconds, count):
        if symbol not in symbols:
            raise RuntimeError(f"unknown symbol {symbol}")
        base = offset.get(symbol, 1.1)
        candles = []
        price = base
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


class BlackboardTests(unittest.TestCase):
    def test_post_and_read_sections(self):
        board = Blackboard()
        board.post("facts", "goal", "review EURUSD")
        self.assertEqual(board.section("facts")["goal"], "review EURUSD")
        self.assertEqual(board.section("missing"), {})

    def test_section_returns_copy(self):
        board = Blackboard()
        board.post("facts", "x", 1)
        snapshot = board.section("facts")
        snapshot["x"] = 99
        self.assertEqual(board.section("facts")["x"], 1)

    def test_messages_routed_to_inbox(self):
        board = Blackboard()
        board.send(AgentMessage("scout", "analyst", "request", "go"))
        board.send(AgentMessage("analyst", "*", "finding", "done"))
        self.assertEqual(len(board.inbox("analyst")), 2)
        self.assertEqual(len(board.inbox("reporter")), 1)

    def test_sections_snapshot_is_nested_copy(self):
        board = Blackboard()
        board.post("a", "k", [1])
        snapshot = board.sections()
        snapshot["a"]["k"].append(2)
        self.assertEqual(board.section("a")["k"], [1])


class SymbolExtractionTests(unittest.TestCase):
    def test_alias_extraction(self):
        from neezy_backend.agents import _extract_symbols

        self.assertEqual(
            _extract_symbols("review EURUSD and GOLD", ()), ("frxEURUSD", "frxXAUUSD")
        )
        self.assertEqual(_extract_symbols("btc mood", ()), ("cryBTCUSD",))
        self.assertEqual(
            _extract_symbols("nothing here", ("frxGBPUSD",)), ("frxGBPUSD",)
        )
        self.assertEqual(_extract_symbols("", ()), ("frxEURUSD",))


class TeamRunTests(unittest.TestCase):
    def test_default_roster(self):
        roster = AgentTeam().roster()
        roles = [agent["role"] for agent in roster]
        self.assertEqual(roles, ["scout", "analyst", "risk", "archivist", "reporter"])

    def test_run_produces_report(self):
        team = AgentTeam()
        result = team.run(TeamContext(goal="review EURUSD", fetch=make_fetch()))
        self.assertIn("Team briefing", result["report"])
        self.assertIn("frxEURUSD", result["report"])
        self.assertEqual(result["facts"]["symbols"], ["frxEURUSD"])
        self.assertTrue(result["metrics"])

    def test_run_with_ai_polish(self):
        team = AgentTeam()
        result = team.run(
            TeamContext(
                goal="review EURUSD",
                fetch=make_fetch(),
                ai_client=lambda _prompt: "AI summary line",
            )
        )
        self.assertEqual(result["report"], "AI summary line")

    def test_ai_failure_falls_back_to_rule_report(self):
        def broken(_prompt):
            raise RuntimeError("model offline")

        team = AgentTeam()
        result = team.run(
            TeamContext(goal="review EURUSD", fetch=make_fetch(), ai_client=broken)
        )
        self.assertIn("Team briefing", result["report"])

    def test_offline_fetch_reports_unavailable(self):
        team = AgentTeam()
        result = team.run(
            TeamContext(goal="review EURUSD", fetch=None, symbols=("frxEURUSD",))
        )
        self.assertIn("unavailable", result["report"])
        self.assertIn("error", result["metrics"]["frxEURUSD"])

    def test_risk_section_populated(self):
        team = AgentTeam()
        result = team.run(
            TeamContext(
                goal="review EURUSD",
                fetch=make_fetch(),
                symbols=("frxEURUSD",),
                balance=2000.0,
                risk_percent=2.0,
            )
        )
        self.assertIn("frxEURUSD", result["risks"])
        self.assertIn("ATR stop", result["risks"]["frxEURUSD"])

    def test_messages_flow_between_agents(self):
        team = AgentTeam()
        result = team.run(TeamContext(goal="review EURUSD", fetch=make_fetch()))
        senders = [message["from"] for message in result["messages"]]
        self.assertIn("scout", senders)
        self.assertIn("reporter", senders)

    def test_custom_team_shares_blackboard(self):
        seen: list[str] = []

        def first(board: Blackboard, _context: TeamContext) -> None:
            board.post("facts", "order", "first")
            board.send(AgentMessage("first", "second", "request", "go"))

        def second(board: Blackboard, _context: TeamContext) -> None:
            seen.append(board.section("facts").get("order", "missing"))
            seen.append(board.inbox("second")[0].payload)

        team = AgentTeam(
            [
                Agent("first", "scout", "writes", first),
                Agent("second", "analyst", "reads", second),
            ]
        )
        team.run(TeamContext(goal="pipeline test"))
        self.assertEqual(seen, ["first", "go"])

    def test_watchlist_constant_available_for_agents(self):
        self.assertIn("frxEURUSD", WATCHLIST)


if __name__ == "__main__":
    unittest.main()
