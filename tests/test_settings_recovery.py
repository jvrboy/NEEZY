"""Settings file corruption recovery tests (roadmap update #62).

A corrupt, empty, wrong-type, or hostile settings.json must never prevent
startup; the app falls back to defaults.
"""

import tempfile
import unittest
from pathlib import Path

from neezy_backend.config import AppSettings
from neezy_backend.storage import SettingsStore


class SettingsRecoveryTests(unittest.TestCase):
    def _load_from_content(self, content: str) -> AppSettings:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(content, encoding="utf-8")
            return SettingsStore(path).load()

    def test_truncated_json_falls_back_to_defaults(self):
        self.assertEqual(self._load_from_content('{"polling_ms": 250'), AppSettings())

    def test_empty_file_falls_back_to_defaults(self):
        self.assertEqual(self._load_from_content(""), AppSettings())

    def test_json_array_is_rejected_gently(self):
        # A top-level list is valid JSON but not a settings object.
        self.assertEqual(self._load_from_content("[1, 2, 3]"), AppSettings())

    def test_scalar_json_is_rejected_gently(self):
        self.assertEqual(self._load_from_content("42"), AppSettings())

    def test_wrong_field_types_fall_back_to_defaults(self):
        # from_dict with type-violating values must not raise past the loader.
        settings = self._load_from_content('{"polling_ms": "very fast"}')
        self.assertEqual(settings, AppSettings())

    def test_out_of_range_values_fall_back_to_defaults(self):
        settings = self._load_from_content('{"polling_ms": 999999999}')
        self.assertEqual(settings, AppSettings())

    def test_hostile_but_valid_values_still_validate(self):
        # Fields that parse but violate cross-field rules reset everything.
        settings = self._load_from_content(
            '{"max_reconnect_seconds": 1, "reconnect_seconds": 500}'
        )
        self.assertEqual(settings, AppSettings())

    def test_missing_file_returns_defaults_without_creating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "absent.json"
            self.assertEqual(SettingsStore(path).load(), AppSettings())
            self.assertFalse(path.exists())

    def test_valid_partial_file_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            expected = AppSettings().updated(polling_ms=250, compact_mode=True)
            store.save(expected)
            self.assertEqual(store.load(), expected)


if __name__ == "__main__":
    unittest.main()


class SettingsLoadWarningTests(unittest.TestCase):
    """Roadmap #90: invalid settings fall back loudly, not silently."""

    def test_corrupt_file_logs_a_warning(self):

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertLogs("neezy.settings", level="WARNING") as captured:
                SettingsStore(path).load()
        self.assertTrue(any("falling back" in line for line in captured.output))

    def test_unknown_fields_log_a_warning(self):

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                '{"polling_ms": 250, "future_option": true}', encoding="utf-8"
            )
            with self.assertLogs("neezy.settings", level="WARNING") as captured:
                settings = SettingsStore(path).load()
        self.assertEqual(settings.polling_ms, 250)
        self.assertTrue(any("future_option" in line for line in captured.output))

    def test_clean_file_emits_no_warning(self):
        import logging

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            SettingsStore(path).save(AppSettings())
            logger = logging.getLogger("neezy.settings")
            records: list[logging.LogRecord] = []
            handler = logging.Handler()
            handler.emit = records.append  # type: ignore[method-assign]
            logger.addHandler(handler)
            try:
                SettingsStore(path).load()
            finally:
                logger.removeHandler(handler)
        self.assertFalse(records, "clean settings must not warn")
