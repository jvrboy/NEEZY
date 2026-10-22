"""Theme token tests (roadmap update #8).

Palettes must be complete, well-formed, and distinct per theme.
"""

import unittest

from neezy_app.theme import (
    DEFAULT_THEME,
    THEME_CANVAS_BG,
    THEME_PALETTES,
    palette_for,
    validate_palette,
)
from neezy_backend.config import THEMES


class ThemeTests(unittest.TestCase):
    def test_every_config_theme_has_a_palette(self):
        self.assertEqual(set(THEME_PALETTES), set(THEMES))

    def test_every_palette_is_well_formed(self):
        for name, palette in THEME_PALETTES.items():
            with self.subTest(theme=name):
                self.assertEqual(validate_palette(palette), [])

    def test_default_theme_exists(self):
        self.assertIn(DEFAULT_THEME, THEME_PALETTES)

    def test_palette_for_unknown_falls_back_to_default(self):
        self.assertEqual(palette_for("not-a-theme"), THEME_PALETTES[DEFAULT_THEME])
        self.assertEqual(palette_for(None), THEME_PALETTES[DEFAULT_THEME])

    def test_palette_for_returns_a_copy(self):
        first = palette_for("Midnight blue")
        first["BG"] = "#mutated"
        self.assertNotEqual(palette_for("Midnight blue")["BG"], "#mutated")

    def test_themes_are_actually_distinct(self):
        names = list(THEME_PALETTES)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                self.assertNotEqual(THEME_PALETTES[a], THEME_PALETTES[b], f"{a} == {b}")

    def test_canvas_background_defined_for_every_theme(self):
        self.assertEqual(set(THEME_CANVAS_BG), set(THEME_PALETTES))

    def test_validate_palette_reports_missing_tokens(self):
        problems = validate_palette({"BG": "#08111f"})
        self.assertTrue(any("missing tokens" in problem for problem in problems))

    def test_validate_palette_rejects_bad_colors(self):
        problems = validate_palette({**THEME_PALETTES[DEFAULT_THEME], "BG": "blue"})
        self.assertTrue(any("not a #rrggbb" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
