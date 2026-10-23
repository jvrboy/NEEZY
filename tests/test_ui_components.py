"""Advanced UI kit: themes, components, and ASCII-safety guarantees."""

import typing
import unittest

from neezy_backend.ui_style import (
    THEME_DESCRIPTIONS,
    THEME_NAMES,
    THEMES,
    ThemedStyle,
    banner,
    fit_table,
    flatten_panel,
    gauge,
    heatmap,
    histogram,
    kv_grid,
    output_width,
    progress_bar,
    resolve_theme,
    sparkline,
    spinner_frame,
    state_dot,
    strip_ansi,
    tree,
)

_ASCII = set(chr(code) for code in range(32, 127))


def assert_ascii(test: unittest.TestCase, text: str) -> None:
    for character in text:
        test.assertIn(character, _ASCII | {"\n"}, f"non-ASCII {character!r}")


class ThemeTests(unittest.TestCase):
    def test_every_theme_covers_every_role(self):
        roles = {"title", "accent", "bold", "muted", "ok", "warn", "bad", "border"}
        for name, palette in THEMES.items():
            self.assertEqual(set(palette), roles, name)

    def test_theme_names_match_palettes(self):
        self.assertEqual(set(THEME_NAMES), set(THEMES))
        self.assertEqual(set(THEME_NAMES), set(THEME_DESCRIPTIONS))

    def test_resolve_theme_argument_wins(self):
        self.assertEqual(resolve_theme("ocean", {}), "ocean")

    def test_resolve_theme_env_fallback(self):
        self.assertEqual(resolve_theme(None, {"NEEZY_THEME": "sunset"}), "sunset")

    def test_resolve_theme_bad_name_falls_back(self):
        self.assertEqual(resolve_theme("darkroom", {}), "dark")
        self.assertEqual(resolve_theme(None, {}), "dark")

    def test_themed_style_disabled_is_plain(self):
        style = ThemedStyle(False, "ocean")
        self.assertEqual(style("hello", "title"), "hello")

    def test_themed_style_enabled_wraps(self):
        style = ThemedStyle(True, "ocean")
        wrapped = style("hello", "title")
        self.assertTrue(wrapped.startswith("\x1b["))
        self.assertTrue(wrapped.endswith("m"))
        self.assertIn("hello", strip_ansi(wrapped))

    def test_themed_style_unknown_role_plain(self):
        style = ThemedStyle(True, "mono")
        self.assertEqual(style("x", "nope"), "x")


class ComponentTests(unittest.TestCase):
    def test_sparkline_matches_width(self):
        values = [float(index % 17) for index in range(41)]
        line = sparkline(values, width=24)
        self.assertEqual(len(line), 24)
        assert_ascii(self, line)

    def test_sparkline_flat_series(self):
        line = sparkline([5.0, 5.0, 5.0], width=10)
        self.assertEqual(len(line), 10)

    def test_sparkline_empty(self):
        self.assertEqual(sparkline([], width=6), " " * 6)

    def test_sparkline_extremes(self):
        # Width below 4 is clamped; two points pad to the centre.
        line = sparkline([0.0, 100.0], width=4)
        assert_ascii(self, line)
        self.assertEqual(len(line), 4)
        self.assertEqual(line.strip(), "%")  # only the peak is non-blank

    def test_sparkline_min_width_clamp(self):
        self.assertEqual(len(sparkline([1.0, 2.0], width=1)), 4)

    def test_progress_bar_bounds(self):
        self.assertIn("100%", progress_bar(1.2))
        self.assertIn("0%", progress_bar(-3.0))
        assert_ascii(self, progress_bar(0.5, width=12, label="scan"))

    def test_progress_bar_value_error(self):
        self.assertIn("0%", progress_bar(float("nan")))

    def test_spinner_frames_cycle(self):
        frames = [spinner_frame(index) for index in range(8)]
        self.assertEqual(frames[0], frames[4])
        self.assertEqual(len(set(frames[:4])), 4)

    def test_gauge_extremes(self):
        self.assertEqual(gauge(50, 100, width=12).count("|"), 1)
        self.assertEqual(len(gauge(-5, 100, width=12)), 12)
        self.assertEqual(len(gauge(500, 100, width=12)), 12)

    def test_gauge_bad_maximum(self):
        self.assertEqual(len(gauge(10, 0, width=10)), 10)

    def test_histogram_rows_and_ascii(self):
        rows = histogram([1, 2, 2, 3, 3, 3, 9], bins=4, width=40)
        self.assertEqual(len(rows), 4)
        for row in rows:
            assert_ascii(self, row)

    def test_histogram_empty(self):
        self.assertEqual(histogram([]), ["(no data)"])

    def test_heatmap_shape(self):
        rows = heatmap(
            ("EURUSD", "GBPUSD"),
            ("EUR", "GBP"),
            [[1.0, 0.2], [0.2, 1.0]],
        )
        self.assertEqual(len(rows), 3)  # header + two rows
        for row in rows:
            assert_ascii(self, row)

    def test_heatmap_empty(self):
        self.assertEqual(heatmap((), (), ()), ["(no data)"])

    def test_tree_structure(self):
        lines = tree([("root", ["leaf-a", "leaf-b"])])
        self.assertEqual(len(lines), 3)
        assert_ascii(self, "\n".join(lines))

    def test_kv_grid_alignment(self):
        lines = kv_grid([("short", 1), ("a-longer-key", "value")])
        self.assertIn("short", lines[0])
        position = lines[0].index("1")
        self.assertEqual(position, lines[1].index("value"))

    def test_kv_grid_empty(self):
        self.assertEqual(kv_grid(()), ["(empty)"])

    def test_state_dot_categories(self):
        self.assertEqual(state_dot("running"), "[ok]")
        self.assertEqual(state_dot("FAILED"), "[!!]")
        self.assertEqual(state_dot("paused"), "[..]")
        self.assertEqual(state_dot("mysterious"), "[--]")

    def test_banner_exact_width(self):
        self.assertEqual(len(banner("NEEZY", width=40)), 40)

    def test_banner_long_title(self):
        self.assertEqual(banner("x" * 30, width=20), "x" * 30)

    def test_banner_rejects_multichar_rule(self):
        line = banner("NEEZY", width=30, char="==")
        self.assertIn("=", line)


class FitTableTests(unittest.TestCase):
    HEADERS: typing.ClassVar[tuple[str, ...]] = (
        "market",
        "signal",
        "confidence",
        "note",
    )
    ROWS: typing.ClassVar[list[tuple[str, str, str, str]]] = [
        ("frxEURUSD", "BUY", "72", "strong momentum"),
        ("frxGBPUSD", "NEUTRAL", "41", "mixed"),
    ]

    def test_wide_terminal_keeps_all_columns(self):
        lines = fit_table(self.HEADERS, self.ROWS, width=60)
        self.assertIn("confidence", lines[0])
        self.assertIn("note", lines[0])
        self.assertEqual(len(lines), 4)

    def test_narrow_terminal_drops_right_columns(self):
        lines = fit_table(self.HEADERS, self.ROWS, width=28)
        for line in lines:
            self.assertLessEqual(len(line), 32)
        self.assertIn("market", lines[0])
        self.assertNotIn("note", lines[0])

    def test_ascii_only(self):
        for line in fit_table(self.HEADERS, self.ROWS, width=30):
            assert_ascii(self, line)


class DeviceWidthTests(unittest.TestCase):
    def test_columns_env_wins(self):
        self.assertEqual(output_width(env={"COLUMNS": "50"}), 50)

    def test_bounds_applied(self):
        self.assertEqual(output_width(env={"COLUMNS": "5"}), 40)
        self.assertEqual(output_width(env={"COLUMNS": "9999"}), 100)

    def test_garbage_env_falls_back(self):
        width = output_width(env={"COLUMNS": "wide"})
        self.assertGreaterEqual(width, 40)
        self.assertLessEqual(width, 100)


class ScreenReaderTests(unittest.TestCase):
    def test_flatten_panel_keeps_every_line(self):
        flat = flatten_panel("STATUS", ["a", "", "b"])
        self.assertEqual(flat[0], "STATUS:")
        self.assertTrue(any(line.strip() == "a" for line in flat))
        self.assertTrue(all(line.strip() for line in flat))


if __name__ == "__main__":
    unittest.main()
