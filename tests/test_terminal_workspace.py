"""State, content, and responsive rendering for the seven CLI tabs."""

import unittest

from neezy_backend.terminal_workspace import (
    SETTINGS_TABS,
    TABS,
    WorkspaceState,
    refresh_argv,
    render_tab,
    render_tabs,
    symbol_rows,
)
from neezy_backend.ui_style import Style, visible_width


class WorkspaceStateTests(unittest.TestCase):
    def test_tabs_cycle_and_aliases(self):
        state = WorkspaceState()
        self.assertTrue(state.select_tab("markets"))
        self.assertEqual(state.tab, "SYMBOLS")
        state.cycle_tab(1)
        self.assertEqual(state.tab, "CHART")
        state.cycle_tab(-2)
        self.assertEqual(state.tab, "CHAT")
        state.cycle_tab(-1)
        self.assertEqual(state.tab, "SETTINGS")
        self.assertFalse(state.select_tab("unknown"))

    def test_shared_symbol_and_timeframe_are_validated(self):
        state = WorkspaceState()
        self.assertTrue(state.select_symbol("GBP/USD"))
        self.assertEqual(state.symbol, "frxGBPUSD")
        self.assertTrue(state.select_timeframe("15m"))
        self.assertEqual(state.timeframe, "15m")
        self.assertFalse(state.select_symbol("not-a-market"))
        self.assertFalse(state.select_timeframe("7m"))
        self.assertEqual(state.symbol, "frxGBPUSD")
        self.assertEqual(state.timeframe, "15m")

    def test_symbol_search_uses_real_catalog(self):
        self.assertTrue(symbol_rows())
        rows = symbol_rows("volatility 100")
        self.assertEqual([row[0] for row in rows], ["1HZ100V", "R_100"])
        self.assertEqual([row[0] for row in symbol_rows("R_100")], ["R_100"])
        self.assertEqual(symbol_rows("no-such-market"), [])

    def test_settings_subtabs_and_reset(self):
        state = WorkspaceState()
        self.assertTrue(state.select_settings_tab("ui"))
        self.assertEqual(state.settings_tab, "APPEARANCE")
        state.cycle_settings_tab(1)
        self.assertEqual(state.settings_tab, "DATA")
        state.cycle_settings_tab(-2)
        self.assertEqual(state.settings_tab, "GENERAL")
        self.assertFalse(state.select_settings_tab("unknown"))
        state.set_option("chart-count", "240")
        state.set_option("hints", "off")
        state.reset_preferences()
        self.assertEqual(state.chart_count, 120)
        self.assertTrue(state.hints)
        self.assertEqual(state.settings_tab, "GENERAL")

    def test_functional_options_are_validated(self):
        state = WorkspaceState()
        state.set_option("width", "44")
        self.assertEqual(state.view_width(84), 44)
        self.assertEqual(state.view_width(32), 32)
        state.set_option("width", "auto")
        self.assertEqual(state.view_width(72), 72)
        state.set_option("temperature", "0.7")
        state.set_option("max-tokens", "900")
        state.set_option("provider", "gemini")
        self.assertEqual(
            state.apply_ai_preferences(["ai", "chat", "hello"]),
            [
                "ai",
                "chat",
                "hello",
                "--provider",
                "gemini",
                "--temperature",
                "0.7",
                "--max-tokens",
                "900",
            ],
        )
        explicit = ["ai", "chat", "hello", "--provider", "grok"]
        self.assertNotIn("gemini", state.apply_ai_preferences(explicit))
        for name, value in (
            ("width", "20"),
            ("temperature", "nan"),
            ("max-tokens", "2"),
            ("provider", "unknown"),
            ("live-orders", "on"),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                state.set_option(name, value)


class WorkspaceRenderTests(unittest.TestCase):
    def test_every_tab_fits_narrow_wide_plain_and_coloured_screens(self):
        for enabled in (False, True):
            for width in (28, 44, 60, 72, 84):
                for tab in TABS:
                    with self.subTest(enabled=enabled, width=width, tab=tab):
                        state = WorkspaceState(tab=tab)
                        style = Style(enabled)
                        text = (
                            render_tabs(style, state, width)
                            + "\n"
                            + render_tab(style, state, width, runtime="Test OS")
                        )
                        self.assertIn(f"[{tab}]", text)
                        for line in text.splitlines():
                            self.assertLessEqual(visible_width(line), width, repr(line))
                            self.assertTrue(all(ord(char) < 128 for char in line))

    def test_refresh_actions_are_read_only_and_use_shared_context(self):
        state = WorkspaceState(symbol="frxGBPUSD", timeframe="15m")
        expected = {
            "CHART": "chart",
            "SIGNALS": "scan",
            "HISTORY": "history",
            "BOT": "bot",
        }
        for tab, command in expected.items():
            with self.subTest(tab=tab):
                state.tab = tab
                action = refresh_argv(state, 44)
                self.assertIsNotNone(action)
                argv, _label = action
                self.assertEqual(argv[0], command)
                self.assertNotIn("order", argv)
                self.assertNotIn("--confirm", argv)
        for tab in ("CHAT", "SYMBOLS", "SETTINGS"):
            state.tab = tab
            self.assertIsNone(refresh_argv(state, 44))

        state.tab = "CHART"
        argv, _ = refresh_argv(state, 44)
        self.assertIn("frxGBPUSD", argv)
        self.assertIn("15m", argv)
        self.assertIn("44", argv)

    def test_every_settings_subtab_is_responsive_and_ascii(self):
        for width in (28, 44, 72):
            for settings_tab in SETTINGS_TABS:
                with self.subTest(width=width, settings_tab=settings_tab):
                    state = WorkspaceState(tab="SETTINGS", settings_tab=settings_tab)
                    text = render_tab(Style(False), state, width, runtime="Test OS")
                    self.assertIn(f"[{settings_tab}]", text)
                    for line in text.splitlines():
                        self.assertLessEqual(visible_width(line), width, repr(line))
                        self.assertTrue(all(ord(char) < 128 for char in line))

    def test_refresh_honours_functional_data_and_performance_options(self):
        state = WorkspaceState(
            symbol="frxGBPUSD",
            timeframe="15m",
            chart_count=240,
            chart_height=18,
            scan_count=500,
            history_limit=5,
            bot_timeout=1.5,
        )
        state.tab = "CHART"
        chart, _ = refresh_argv(state, 44)
        self.assertEqual(chart[-4:], ["--width", "44", "--height", "18"])
        self.assertEqual(chart[chart.index("-n") + 1], "240")
        state.tab = "SIGNALS"
        scan, _ = refresh_argv(state, 44)
        self.assertEqual(scan[-2:], ["-n", "500"])
        state.tab = "HISTORY"
        history, _ = refresh_argv(state, 44)
        self.assertEqual(history, ["history", "--limit", "5"])
        state.tab = "BOT"
        bot, _ = refresh_argv(state, 44)
        self.assertEqual(bot, ["bot", "status", "--timeout", "1.5"])
        state.tab = "SETTINGS"
        state.settings_tab = "PERFORMANCE"
        kernels, _ = refresh_argv(state, 44)
        self.assertEqual(kernels, ["kernels", "status"])


if __name__ == "__main__":
    unittest.main()
