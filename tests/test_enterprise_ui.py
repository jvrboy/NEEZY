"""Headless tests for the pure helpers in the enterprise UI layer."""

import unittest

try:
    from neezy_app.enterprise import GLYPHS, PAGE_TITLES, filter_commands
    from neezy_app.ui import NAV
except ModuleNotFoundError as error:  # Tk or optional deps missing
    raise unittest.SkipTest(str(error)) from error


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


if __name__ == "__main__":
    unittest.main()
