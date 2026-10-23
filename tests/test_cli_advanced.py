"""CLI-level tests for the advanced commands: sessions, indicators, btoken,
ui, bots, and agents - all offline through the standard fetcher seam."""

import io
import json
import math
import unittest

from neezy_backend import cli


def make_fetch(symbols=None):
    symbols = symbols or {"frxEURUSD", "frxGBPUSD", "frxXAUUSD", "cryBTCUSD"}
    offset = {
        "frxEURUSD": 1.10,
        "frxGBPUSD": 1.27,
        "frxXAUUSD": 2300.0,
        "cryBTCUSD": 67000.0,
    }

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
            high = max(open_, close) + abs(drift) * 0.4 + 0.0002
            low = min(open_, close) - abs(drift) * 0.4 - 0.0002
            price = close
            candles.append((1700000000 + index * seconds, open_, high, low, close))
        return candles

    return fetch


class SessionCommandTests(unittest.TestCase):
    def test_plain_output_lists_sessions(self):
        out = io.StringIO()
        code = cli.main(
            ["sessions", "--now", "2026-10-23T13:30"], fetch=make_fetch(), out=out
        )
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("London", text)
        self.assertIn("New York", text)

    def test_json_output_schema(self):
        out = io.StringIO()
        code = cli.main(
            ["sessions", "--json", "--now", "2026-10-23T13:30"],
            fetch=make_fetch(),
            out=out,
        )
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertIn("sessions", report)
        self.assertIn("next_event", report)
        names = [session["name"] for session in report["sessions"]]
        self.assertEqual(names, ["Sydney", "Tokyo", "London", "New York"])

    def test_bad_timestamp_rejected(self):
        out = io.StringIO()
        code = cli.main(
            ["sessions", "--now", "not-a-time"], fetch=make_fetch(), out=out
        )
        self.assertEqual(code, 2)

    def test_dashless_equals_form(self):
        out = io.StringIO()
        code = cli.main(
            "sessions,now=2026-10-23T13:30".split(","),
            fetch=make_fetch(),
            out=out,
        )
        self.assertEqual(code, 0)
        self.assertIn("London", out.getvalue())


class IndicatorCommandTests(unittest.TestCase):
    def test_plain_output(self):
        out = io.StringIO()
        code = cli.main(["indicators", "frxEURUSD"], fetch=make_fetch(), out=out)
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("advanced indicator suite", text)
        self.assertIn("cci", text)
        self.assertIn("choppiness", text)

    def test_json_output(self):
        out = io.StringIO()
        code = cli.main(
            ["indicators", "frxEURUSD", "--json"], fetch=make_fetch(), out=out
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["symbol"], "frxEURUSD")
        self.assertEqual(len(payload["advanced"]), 12)
        self.assertFalse(payload["warmup"])

    def test_short_history_rejected(self):
        out = io.StringIO()
        code = cli.main(["indicators", "frxEURUSD"], fetch=lambda *_a: [], out=out)
        self.assertEqual(code, 2)

    def test_lowercase_symbol_resolved(self):
        out = io.StringIO()
        code = cli.main(["indicators", "eurusd"], fetch=make_fetch(), out=out)
        self.assertEqual(code, 0)


class BtokenCommandTests(unittest.TestCase):
    def test_list_plain_and_json(self):
        for argv in (["btoken", "list"], ["btoken", "list", "--json"]):
            out = io.StringIO()
            code = cli.main(argv, fetch=make_fetch(), out=out)
            self.assertEqual(code, 0)
            self.assertTrue(out.getvalue())

    def test_translate_action(self):
        out = io.StringIO()
        code = cli.main(
            ["btoken", "translate", "bt:space bt:enter"],
            fetch=make_fetch(),
            out=out,
        )
        self.assertEqual(code, 0)
        self.assertIn("SPACE", out.getvalue())

    def test_translate_no_tokens_fails_cleanly(self):
        out = io.StringIO()
        code = cli.main(
            ["btoken", "translate", "nothing here"], fetch=make_fetch(), out=out
        )
        self.assertEqual(code, 1)

    def test_stuck_action(self):
        out = io.StringIO()
        code = cli.main(["btoken", "stuck", "space"], fetch=make_fetch(), out=out)
        self.assertEqual(code, 0)
        self.assertIn("NEEZY_BTOKEN", out.getvalue())

    def test_rewrite_action(self):
        out = io.StringIO()
        code = cli.main(
            ["btoken", "rewrite", "analyze", "frxEURUSD", "timeframe=15m"],
            fetch=make_fetch(),
            out=out,
        )
        self.assertEqual(code, 0)
        self.assertIn("--timeframe", out.getvalue())


class UiCommandTests(unittest.TestCase):
    def test_theme_list(self):
        out = io.StringIO()
        code = cli.main(["ui", "theme", "list"], fetch=make_fetch(), out=out)
        self.assertEqual(code, 0)
        for name in ("dark", "contrast", "ocean"):
            self.assertIn(name, out.getvalue())

    def test_theme_show(self):
        out = io.StringIO()
        code = cli.main(["ui", "theme", "show", "sunset"], fetch=make_fetch(), out=out)
        self.assertEqual(code, 0)
        self.assertIn("sunset", out.getvalue())

    def test_demo_is_ascii(self):
        out = io.StringIO()
        code = cli.main(["ui", "demo"], fetch=make_fetch(), out=out)
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertTrue(text.isascii())

    def test_capabilities_json(self):
        out = io.StringIO()
        code = cli.main(["ui", "capabilities", "--json"], fetch=make_fetch(), out=out)
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertIn("backend_features", report)
        self.assertIn("btoken_mode", report)


class BotsCommandTests(unittest.TestCase):
    def test_list_and_status(self):
        for argv in (["bots", "list"], ["bots", "status"]):
            out = io.StringIO()
            code = cli.main(argv, fetch=make_fetch(), out=out)
            self.assertEqual(code, 0)
            self.assertIn("scanner", out.getvalue())

    def test_run_sessions_bot_offline(self):
        out = io.StringIO()
        code = cli.main(
            ["bots", "run", "--bot", "sessions", "--ticks", "1"],
            fetch=make_fetch(),
            out=out,
        )
        self.assertEqual(code, 0)
        self.assertIn("UTC", out.getvalue())

    def test_run_json(self):
        out = io.StringIO()
        code = cli.main(
            ["bots", "run", "--bot", "momentum", "--ticks", "1", "--json"],
            fetch=make_fetch(),
            out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["bot"], "momentum")
        self.assertEqual(len(payload["decisions"]), 1)

    def test_unknown_bot_rejected(self):
        out = io.StringIO()
        code = cli.main(["bots", "run", "--bot", "warp"], fetch=make_fetch(), out=out)
        self.assertEqual(code, 2)


class AgentsCommandTests(unittest.TestCase):
    def test_list(self):
        out = io.StringIO()
        code = cli.main(["agents", "list"], fetch=make_fetch(), out=out)
        self.assertEqual(code, 0)
        self.assertIn("scout", out.getvalue())
        self.assertIn("reporter", out.getvalue())

    def test_run_plain(self):
        out = io.StringIO()
        code = cli.main(
            ["agents", "run", "review EURUSD and GOLD", "--symbol", "EURUSD"],
            fetch=make_fetch(),
            out=out,
        )
        self.assertEqual(code, 0)
        self.assertIn("frxEURUSD", out.getvalue())

    def test_run_json(self):
        out = io.StringIO()
        code = cli.main(
            ["agents", "run", "review EURUSD", "--json"],
            fetch=make_fetch(),
            out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertIn("report", payload)
        self.assertEqual(payload["facts"]["symbols"], ["frxEURUSD"])

    def test_missing_goal_rejected(self):
        out = io.StringIO()
        code = cli.main(["agents", "run", ""], fetch=make_fetch(), out=out)
        self.assertEqual(code, 2)


class AccessibilityIntegrationTests(unittest.TestCase):
    """A user with broken SPACE, DASH, and SHIFT keys can drive everything."""

    def test_full_dashless_session_flow(self):
        fetch = make_fetch()
        argv = "sessions,now=2026-10-23T13:30".split(",")
        out = io.StringIO()
        self.assertEqual(cli.main(argv, fetch=fetch, out=out), 0)
        self.assertIn("London", out.getvalue())

    def test_full_dashless_indicators_flow(self):
        fetch = make_fetch()
        argv = "indicators,frxEURUSD,json=1".split(",")
        out = io.StringIO()
        self.assertEqual(cli.main(argv, fetch=fetch, out=out), 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["symbol"], "frxEURUSD")

    def test_bare_flag_words_with_env(self):
        import os

        fetch = make_fetch()
        argv = "sessions,json".split(",")
        out = io.StringIO()
        os.environ["NEEZY_BTOKEN"] = "1"
        try:
            self.assertEqual(cli.main(argv, fetch=fetch, out=out), 0)
            payload = json.loads(out.getvalue())
            self.assertIn("sessions", payload)
        finally:
            del os.environ["NEEZY_BTOKEN"]

    def test_standard_commands_unaffected(self):
        fetch = make_fetch()
        out = io.StringIO()
        code = cli.main(
            [
                "risk",
                "EURUSD",
                "--balance",
                "10000",
                "--entry",
                "1.1",
                "--stop",
                "1.098",
            ],
            fetch=fetch,
            out=out,
        )
        self.assertEqual(code, 0)

    def test_help_lists_new_commands(self):
        from neezy_backend.cli.parser import build_parser

        text = build_parser().format_help()
        for command in ("sessions", "indicators", "btoken", "ui", "bots", "agents"):
            self.assertIn(command, text)
        self.assertIn("--btoken", text)
        self.assertIn("--theme", text)


if __name__ == "__main__":
    unittest.main()
