"""BTOKEN keyboard-accessibility layer: tokens and dashless argv rewriting."""

import unittest

from neezy_backend.btoken import (
    BTOKENS,
    KeyEvent,
    btoken_enabled,
    describe_mode,
    normalize_argv,
    reset_parser_cache,
    stuck_key_help,
    tokens_by_category,
    translate,
)


class TokenRegistryTests(unittest.TestCase):
    def test_every_token_is_prefixed_and_typeable(self):
        for token in BTOKENS:
            self.assertTrue(token.startswith("bt:"))
            body = token[3:]
            self.assertTrue(body.replace("-", "").isalnum(), token)
            self.assertEqual(body, body.lower())

    def test_translate_mixes_words_and_tokens(self):
        events = translate("please bt:space then BT:ENTER and bt:nope")
        self.assertEqual([event.key for event in events], ["SPACE", "ENTER"])

    def test_translate_rejects_unknown_tokens(self):
        self.assertEqual(translate("bt:warp-speed"), [])

    def test_tokens_grouped_by_category(self):
        grouped = tokens_by_category()
        self.assertIn("confirm", grouped)
        self.assertIn("cancel", grouped)
        self.assertIn("editing", grouped)
        for events in grouped.values():
            self.assertIsInstance(events[0], KeyEvent)

    def test_stuck_key_help_is_actionable(self):
        for key in ("space", "ctrl", "SHIFT", "dash", "del", "esc", "arrows"):
            lines = stuck_key_help(key)
            self.assertTrue(lines, key)
            self.assertGreaterEqual(len(lines), 2, key)

    def test_stuck_key_help_unknown_suggests_known(self):
        lines = stuck_key_help("f13")
        self.assertTrue(any("space" in line for line in lines))

    def test_mode_description_reflects_env(self):
        self.assertIn("standard", describe_mode({}))
        self.assertIn("full", describe_mode({"NEEZY_BTOKEN": "1"}))

    def test_btoken_enabled_reads_env(self):
        self.assertFalse(btoken_enabled({}))
        self.assertTrue(btoken_enabled({"NEEZY_BTOKEN": "1"}))


class NormalizeArgvTests(unittest.TestCase):
    def setUp(self):
        reset_parser_cache()

    def test_standard_argv_untouched(self):
        prepared, full = normalize_argv(
            ["scan", "--json", "-t", "5m", "frxEURUSD"], mode="safe"
        )
        self.assertEqual(prepared, ["scan", "--json", "-t", "5m", "frxEURUSD"])
        self.assertFalse(full)

    def test_equals_form_becomes_long_flag(self):
        prepared, _ = normalize_argv(
            ["analyze", "frxEURUSD", "timeframe=15m"], mode="safe"
        )
        self.assertEqual(prepared, ["analyze", "frxEURUSD", "--timeframe", "15m"])

    def test_short_alias_resolves(self):
        prepared, _ = normalize_argv(
            ["chart", "frxXAUUSD", "t=15m", "n=200"], mode="safe"
        )
        self.assertEqual(
            prepared,
            ["chart", "frxXAUUSD", "--timeframe", "15m", "--count", "200"],
        )

    def test_boolean_true_word_becomes_flag(self):
        prepared, _ = normalize_argv(["scan", "json=1", "debug=true"], mode="safe")
        self.assertIn("--json", prepared)
        self.assertIn("--debug", prepared)

    def test_boolean_false_word_drops_flag(self):
        prepared, _ = normalize_argv(["scan", "json=0"], mode="safe")
        self.assertNotIn("--json", prepared)
        self.assertNotIn("json=0", prepared)

    def test_unknown_equals_token_stays_literal(self):
        prepared, _ = normalize_argv(["scan", "banana=split"], mode="safe")
        self.assertIn("banana=split", prepared)

    def test_full_mode_comma_separator(self):
        prepared, full = normalize_argv(
            "analyze,frxEURUSD,json,timeframe=15m".split(","),
            mode="full",
        )
        self.assertTrue(full)
        self.assertEqual(
            prepared, ["analyze", "frxEURUSD", "--json", "--timeframe", "15m"]
        )

    def test_full_mode_bare_flag_word(self):
        prepared, _ = normalize_argv(["scan", "json"], mode="full")
        self.assertEqual(prepared, ["scan", "--json"])

    def test_safe_mode_never_rewrites_bare_words(self):
        prepared, _ = normalize_argv(["scan", "json"], mode="safe")
        self.assertEqual(prepared, ["scan", "json"])

    def test_auto_mode_uses_env(self):
        prepared, full = normalize_argv(
            "scan,json".split(","),
            mode="auto",
            env={"NEEZY_BTOKEN": "1"},
        )
        self.assertTrue(full)
        self.assertEqual(prepared, ["scan", "--json"])

    def test_auto_mode_detects_btoken_flag(self):
        prepared, full = normalize_argv(
            ["--btoken", "scan", "json"], mode="auto", env={}
        )
        self.assertTrue(full)
        self.assertIn("--json", prepared)

    def test_free_text_positional_keeps_equals(self):
        # dm send url title message: the message must keep literal equals.
        prepared, _ = normalize_argv(
            ["dm", "send", "https://hook", "title", "a=b=c"], mode="safe"
        )
        self.assertEqual(prepared[-1], "a=b=c")

    def test_config_set_value_keeps_equals(self):
        prepared, _ = normalize_argv(
            ["config", "set", "polling_ms", "250"], mode="safe"
        )
        self.assertEqual(prepared, ["config", "set", "polling_ms", "250"])

    def test_constrained_positional_allows_rewrite(self):
        # scan takes _symbol-validated positionals; an equals token can
        # never be a market name, so rewriting is safe there.
        prepared, _ = normalize_argv(["scan", "timeframe=15m"], mode="safe")
        self.assertEqual(prepared, ["scan", "--timeframe", "15m"])

    def test_global_equals_form(self):
        prepared, _ = normalize_argv(["btoken=1", "scan"], mode="safe")
        self.assertEqual(prepared[0], "--btoken")

    def test_nested_subcommand_options(self):
        prepared, _ = normalize_argv(
            ["mt5", "candles", "frxEURUSD", "count=200"], mode="safe"
        )
        self.assertIn("--count", prepared)
        self.assertIn("200", prepared)


class CliIntegrationTests(unittest.TestCase):
    def test_prepare_argv_wiring(self):
        from neezy_backend.cli import _prepare_argv

        prepared, full = _prepare_argv(["analyze", "frxEURUSD", "json=1"])
        self.assertFalse(full)
        self.assertIn("--json", prepared)

    def test_menu_btoken_quit(self):
        import io

        from neezy_backend.menu import run_menu

        calls: list[list[str]] = []
        feed = iter(["bt:ctrl-c"])
        out = io.StringIO()
        code = run_menu(
            out,
            input_fn=lambda _prompt: next(feed),
            run=lambda argv: calls.append(argv) or 0,
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
