"""Headless tests for the pure helpers and shell in the enterprise UI layer."""

import unittest

import tests.test_ui_smoke  # noqa: F401 - installs headless FakeTk on CI
from neezy_app.enterprise import GLYPHS, PAGE_TITLES, filter_commands
from neezy_app.ui import NAV


def _noop() -> None:
    return None


COMMANDS = [
    ("Go to Chart", _noop),
    ("Go to Settings", _noop),
    ("Open chart · EUR/USD", _noop),
    ("Theme · High contrast", _noop),
]


class EnterpriseHelpersTest(unittest.TestCase):
    def test_filter_empty_query_returns_everything(self):
        self.assertEqual(filter_commands(COMMANDS, ""), COMMANDS)

    def test_filter_is_case_insensitive_and_token_based(self):
        labels = [label for label, _ in filter_commands(COMMANDS, "CHART go")]
        self.assertEqual(labels, ["Go to Chart"])

    def test_filter_no_match(self):
        self.assertEqual(filter_commands(COMMANDS, "zzz"), [])

    def test_every_nav_entry_has_glyph_and_title(self):
        self.assertLessEqual(set(NAV), set(GLYPHS))
        self.assertLessEqual(set(NAV), set(PAGE_TITLES))


class EnterpriseAppSmokeTest(unittest.TestCase):
    """Instantiate the full EnterpriseApp shell headlessly and verify no crashes."""

    def test_enterprise_app_constructs_and_navigates_every_page_and_shortcut(self):
        import os
        import tempfile
        import tkinter as tk
        from unittest import mock

        from neezy_app import ui
        from neezy_app.enterprise import EnterpriseApp

        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.dict(os.environ, {"NEEZY_HOME": home}),
            mock.patch.object(ui.DerivStreamClient, "start"),
        ):
            app = EnterpriseApp()
            try:
                # 1. All 10 pages exist and can be navigated cleanly (including HISTORY)
                for page_name in NAV:
                    app._tab(page_name)
                    self.assertEqual(app._current_tab(), page_name)

                # 2. Ctrl+1..9 and Ctrl+0 shortcuts bind valid <Control-Key-N> events
                for idx, expected_page in enumerate(NAV):
                    key = "0" if idx == 9 else str(idx + 1)
                    binding = f"<Control-Key-{key}>"
                    self.assertIn(binding, app.bound)
                    app.bound[binding](None)
                    self.assertEqual(app._current_tab(), expected_page)

                # 3. _scan_from_palette opens SETTINGS -> ENGINE tab and scans cleanly
                app._scan_from_palette()
                self.assertEqual(app._current_tab(), "SETTINGS")
                self.assertEqual(
                    app.settings_notebook.select(), app._settings_tabs["ENGINE"]
                )

                # 4. Live hot-reload of theme, colorblind mode, and font offset works
                app.theme_var.set("High contrast")
                app.extra_vars["colorblind_palette"].set(True)
                app.extra_vars["font_size_offset"].set("2")
                app._settings_changed()
                self.assertEqual(app.settings.theme, "High contrast")
                self.assertTrue(app.settings.colorblind_palette)
                self.assertEqual(app.settings.font_size_offset, 2)
                self.assertIsInstance(app, tk.Tk)
                self.assertIsInstance(app.hist_canvas, tk.Widget)
            finally:
                app._close()


if __name__ == "__main__":
    unittest.main()
