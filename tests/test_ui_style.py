"""Colour decisions and layout for the CLI menu: plain text stays plain."""

import io
import unittest
from unittest import mock

from neezy_backend.menu import MENU, filter_menu, run_menu, runtime_label
from neezy_backend.ui_style import (
    Style,
    color_enabled,
    panel,
    strip_ansi,
    visible_width,
)


class _Tty(io.StringIO):
    def isatty(self):
        return True


class ColorDecisionTests(unittest.TestCase):
    def test_pipe_and_stringio_are_plain(self):
        self.assertFalse(color_enabled(io.StringIO(), env={}))

    def test_tty_gets_colour(self):
        self.assertTrue(color_enabled(_Tty(), env={}))

    def test_no_color_wins_over_tty_and_force(self):
        env = {"NO_COLOR": "1", "FORCE_COLOR": "1"}
        self.assertFalse(color_enabled(_Tty(), env=env))

    def test_empty_no_color_is_ignored(self):
        self.assertTrue(color_enabled(_Tty(), env={"NO_COLOR": ""}))

    def test_plain_flag_wins_over_tty(self):
        self.assertFalse(color_enabled(_Tty(), plain=True, env={}))

    def test_force_color_enables_on_pipe(self):
        self.assertTrue(color_enabled(io.StringIO(), env={"FORCE_COLOR": "1"}))

    def test_dumb_terminal_is_plain(self):
        self.assertFalse(color_enabled(_Tty(), env={"TERM": "dumb"}))

    def test_windows_vt_failure_automatically_disables_tty_colour(self):
        with mock.patch("neezy_backend.ui_style.enable_windows_vt", return_value=False):
            self.assertFalse(color_enabled(_Tty(), env={}))

    def test_windows_vt_success_enables_tty_colour(self):
        with mock.patch("neezy_backend.ui_style.enable_windows_vt", return_value=True):
            self.assertTrue(color_enabled(_Tty(), env={}))

    def test_force_colour_still_allows_redirected_ansi(self):
        with mock.patch("neezy_backend.ui_style.enable_windows_vt", return_value=False):
            self.assertTrue(color_enabled(io.StringIO(), env={"FORCE_COLOR": "1"}))


class StyleTests(unittest.TestCase):
    def test_disabled_style_returns_text_unchanged(self):
        style = Style(False)
        self.assertEqual(style("hello", "warn"), "hello")
        self.assertEqual(style.badge("exit 0", "ok"), "[exit 0]")

    def test_enabled_style_wraps_and_strips_back(self):
        style = Style(True)
        painted = style("hello", "warn")
        self.assertNotEqual(painted, "hello")
        self.assertEqual(strip_ansi(painted), "hello")
        self.assertEqual(visible_width(painted), 5)

    def test_panel_rows_have_equal_visible_width(self):
        for enabled in (False, True):
            style = Style(enabled)
            text = panel(style, "NEEZY", ["one", style("two bold", "bold")], width=40)
            widths = {visible_width(line) for line in text.splitlines()}
            self.assertEqual(widths, {40}, f"enabled={enabled}")


class MenuRenderTests(unittest.TestCase):
    def _run(self, answers, *, color=False, echo_prompts=False):
        feed = iter(answers)
        out = io.StringIO()
        calls: list[list[str]] = []

        def fake_run(argv):
            calls.append(argv)
            return 0

        def ask(prompt):
            if echo_prompts:
                out.write(prompt)
            return next(feed)

        code = run_menu(
            out,
            input_fn=ask,
            run=fake_run,
            color=color,
        )
        return code, calls, out.getvalue()

    def test_plain_output_has_no_escape_codes(self):
        _, calls, out = self._run(["2", "0"])
        self.assertEqual(calls, [["mt5", "status"]])
        self.assertNotIn("\x1b", out)

    def test_coloured_output_has_escape_codes(self):
        _, _, out = self._run(["0"], color=True)
        self.assertIn("\x1b[", out)

    def test_screen_is_ascii_only(self):
        _, _, out = self._run(["?", "0"])
        self.assertTrue(all(ord(ch) < 128 for ch in out), "non-ASCII glyph in menu")

    def test_palette_keys_are_unique(self):
        keys = [item[0] for item in MENU]
        self.assertEqual(len(keys), len(set(keys)))

    def test_filter_narrows_palette_without_running(self):
        keys = [item[0] for item in filter_menu("mt5 order")]
        self.assertEqual(keys, ["6", "7"])
        _, calls, out = self._run(["/mt5 order", "0"])
        self.assertEqual(calls, [])
        self.assertIn("DRY RUN", out)

    def test_filter_empty_query_returns_everything(self):
        self.assertEqual(filter_menu(""), MENU)
        self.assertEqual(filter_menu("   "), MENU)

    def test_filter_no_match_says_so(self):
        _, calls, out = self._run(["/zzzz", "0"])
        self.assertEqual(calls, [])
        self.assertIn("No matches", out)

    def test_plain_text_is_routed_to_ai_chat(self):
        _, calls, out = self._run(["x", "0"])
        self.assertEqual(calls, [["ai", "chat", "x"]])
        self.assertIn("AI assistant", out)

    def test_default_workspace_hides_command_palette(self):
        _, calls, out = self._run(["0"])
        self.assertEqual(calls, [])
        self.assertIn("NEEZY", out)
        self.assertIn("CHAT", out)
        self.assertNotIn("COMMAND PALETTE", out)
        self.assertNotIn("Market data connectivity check", out)

    def test_slash_opens_and_close_hides_palette(self):
        _, calls, out = self._run(["/", "/close", "0"])
        self.assertEqual(calls, [])
        self.assertEqual(out.count("COMMAND PALETTE"), 1)
        self.assertIn("DRY RUN", out)
        self.assertEqual(out.count("| CHAT"), 2)

    def test_palette_shows_real_commands_only_when_requested(self):
        _, _, default = self._run(["0"])
        self.assertNotIn("doctor", default.lower())
        self.assertNotIn("analyze", default.lower())
        _, calls, palette = self._run(["/", "0"])
        self.assertEqual(calls, [])
        self.assertIn("[1] doctor", palette)
        self.assertIn("[a] analyze", palette)
        self.assertIn("MT5 ORDERS / 2", palette)

    def test_wide_header_places_status_beside_banner(self):
        with mock.patch("neezy_backend.menu.terminal_width", return_value=76):
            _, _, out = self._run(["0"])
        self.assertTrue(
            any(
                "#   #" in line and "INTELLIGENT MARKET WORKSPACE" in line
                for line in out.splitlines()
            )
        )
        self.assertIn("LIVE needs SEND", out)

    def test_natural_market_request_uses_existing_cli(self):
        _, calls, out = self._run(["analyse EURUSD on 15m", "0"])
        self.assertEqual(calls, [["analyze", "frxEURUSD", "-t", "15m"]])
        self.assertIn("Market analysis", out)

    def test_natural_trade_intent_never_dispatches_order(self):
        _, calls, out = self._run(["buy EURUSD now", "0"])
        self.assertEqual(calls, [])
        self.assertIn("not available through natural language", out)
        self.assertIn("SEND", out)

    def test_narrow_terminal_wraps_palette(self):
        with mock.patch("neezy_backend.menu.terminal_width", return_value=44):
            _, _, out = self._run(["/very-long-" + "x" * 70, "/", "0"])
        for line in out.splitlines():
            self.assertLessEqual(visible_width(line), 44, repr(line))

    def test_tiny_terminal_wraps_header_palette_and_messages(self):
        with mock.patch("neezy_backend.menu.terminal_width", return_value=28):
            _, _, out = self._run(["/", "?", "buy EURUSD now", "0"])
        for line in out.splitlines():
            self.assertLessEqual(visible_width(line), 28, repr(line))
        self.assertIn("NEEZY", out)
        self.assertIn("COMMAND PALETTE", out)

    def test_piped_prompts_never_join_panels_or_overflow(self):
        with mock.patch("neezy_backend.menu.terminal_width", return_value=28):
            _, _, out = self._run(
                [
                    ":symbols",
                    "GBPUSD",
                    ":chart",
                    ":refresh",
                    "/",
                    ":does-not-exist",
                    "0",
                ],
                echo_prompts=True,
            )
        for line in out.splitlines():
            self.assertLessEqual(visible_width(line), 28, repr(line))

    def test_runtime_labels_cover_supported_terminal_families(self):
        self.assertEqual(runtime_label({}, "win32"), "Windows")
        self.assertEqual(runtime_label({}, "linux"), "Linux")
        self.assertEqual(
            runtime_label({"TERMUX_VERSION": "1"}, "linux"), "Termux / Android"
        )
        self.assertEqual(
            runtime_label({"CODESPACES": "true"}, "linux"), "GitHub Codespaces"
        )

    def test_tab_navigation_and_chart_refresh_use_shared_context(self):
        with mock.patch("neezy_backend.menu.terminal_width", return_value=44):
            _, calls, out = self._run(
                [
                    ":symbols",
                    "GBPUSD",
                    ":timeframe 15m",
                    ":chart",
                    ":refresh",
                    "0",
                ]
            )
        self.assertEqual(
            calls,
            [
                [
                    "chart",
                    "frxGBPUSD",
                    "-t",
                    "15m",
                    "-n",
                    "120",
                    "--width",
                    "44",
                    "--height",
                    "14",
                ]
            ],
        )
        self.assertIn("[CHART]", out)
        self.assertIn("Closed-candle chart", out)

    def test_signal_history_and_bot_tabs_refresh_read_only_commands(self):
        _, calls, _ = self._run(
            [":signals", ":refresh", ":history", ":refresh", ":bot", ":refresh", "0"]
        )
        self.assertEqual(
            calls,
            [
                ["scan", "frxEURUSD", "-t", "5m"],
                ["history", "--limit", "12"],
                ["bot", "status"],
            ],
        )

    def test_tab_switching_and_settings_do_not_run_commands(self):
        _, calls, out = self._run(
            [":next", ":prev", ":settings", ":color off", "0"], color=True
        )
        self.assertEqual(calls, [])
        plain = strip_ansi(out)
        for tab in (
            "CHAT",
            "SYMBOLS",
            "CHART",
            "SIGNALS",
            "HISTORY",
            "BOT",
            "SETTINGS",
        ):
            self.assertIn(tab, plain)
        self.assertIn("colour | plain", plain)

    def test_unknown_tab_command_is_reported_without_running(self):
        _, calls, out = self._run([":does-not-exist", "0"])
        self.assertEqual(calls, [])
        self.assertIn("unknown tab command", out)

    def test_eof_exits_cleanly(self):
        def eof(_prompt):
            raise EOFError

        out = io.StringIO()
        code = run_menu(out, input_fn=eof, run=lambda argv: 0, color=False)
        self.assertEqual(code, 0)
        self.assertIn("bye", out.getvalue())

    def test_ctrl_c_exits_cleanly(self):
        def interrupt(_prompt):
            raise KeyboardInterrupt

        out = io.StringIO()
        self.assertEqual(
            run_menu(out, input_fn=interrupt, run=lambda a: 0, color=False), 0
        )

    def test_eof_mid_order_prompt_exits_cleanly(self):
        feed = iter(["6", "frxEURUSD"])

        def ask(_prompt):
            try:
                return next(feed)
            except StopIteration:
                raise EOFError from None

        out = io.StringIO()
        calls = []
        code = run_menu(
            out, input_fn=ask, run=lambda a: calls.append(a) or 0, color=False
        )
        self.assertEqual(code, 0)
        self.assertEqual(calls, [])

    def test_exit_code_is_shown_after_a_run(self):
        out = io.StringIO()
        feed = iter(["2", "0"])
        run_menu(out, input_fn=lambda _p: next(feed), run=lambda argv: 3, color=False)
        self.assertIn("[exit 3]", out.getvalue())

    def test_cli_menu_plain_flag_runs_without_colour(self):
        from neezy_backend.cli import main

        out = io.StringIO()
        with mock.patch("builtins.input", side_effect=["0"]):
            code = main(["menu", "--plain"], out=out)
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b", out.getvalue())
        self.assertIn("NEEZY", out.getvalue())

    def test_menu_reads_input_late_so_patch_applies(self):
        """run_menu must resolve `input` at call time, not import time.

        Regression: binding the default at import time made
        mock.patch("builtins.input") ineffective and hung interactive
        stdin environments in a prompt loop.
        """
        out = io.StringIO()
        prompts: list[str] = []

        def fake_input(prompt: str) -> str:
            prompts.append(prompt)
            return "0"

        with mock.patch("builtins.input", new=fake_input):
            code = run_menu(out, color=False)
        self.assertEqual(code, 0)
        self.assertTrue(prompts, "run_menu should read through builtins.input")


if __name__ == "__main__":
    unittest.main()
