import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from neezy_backend.diagnostics import REDACTED, build_bundle, redact, redact_text


class RedactTest(unittest.TestCase):
    def test_masks_secret_keys_but_not_token_counts(self):
        data = {
            "ai_api_key": "abc",
            "access_token": "xyz",
            "ai_max_tokens": 512,
            "nested": {"password": "p", "theme": "dark"},
            "empty_secret": "",
        }
        clean = redact(data)
        self.assertEqual(clean["ai_api_key"], REDACTED)
        self.assertEqual(clean["access_token"], REDACTED)
        self.assertEqual(clean["ai_max_tokens"], 512)
        self.assertEqual(clean["nested"], {"password": REDACTED, "theme": "dark"})
        self.assertEqual(clean["empty_secret"], "")

    def test_masks_log_assignments_and_known_key_shapes(self):
        text = "api_key=hunter2 ok Authorization: Bearer1 sk-abcdefghijklmnopqrst"
        clean = redact_text(text)
        self.assertNotIn("hunter2", clean)
        self.assertNotIn("sk-abcdefghijklmnopqrst", clean)
        self.assertIn("ok", clean)


class BundleTest(unittest.TestCase):
    def test_bundle_contents_are_redacted(self):
        with tempfile.TemporaryDirectory() as folder:
            data = Path(folder) / "data"
            data.mkdir()
            (data / "neezy.log").write_text("start\napi_key=topsecret\n")
            out = Path(folder) / "out" / "bundle.zip"
            build_bundle(
                out,
                data_dir=data,
                settings={"ai_api_key": "topsecret", "theme": "dark"},
                db_stats={"counts": {"signals": 3}},
            )
            with zipfile.ZipFile(out) as bundle:
                names = set(bundle.namelist())
                blob = "".join(bundle.read(name).decode() for name in names)
                settings = json.loads(bundle.read("settings.json"))
            self.assertLessEqual(
                {"system.json", "settings.json", "database.json", "logs/neezy.log"},
                names,
            )
            self.assertNotIn("topsecret", blob)
            self.assertEqual(settings["theme"], "dark")


if __name__ == "__main__":
    unittest.main()
