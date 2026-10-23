"""Read-only, loopback-only executor status used by the BOT tab."""

import io
import json
import unittest
from types import SimpleNamespace
from unittest import mock
from urllib.error import URLError

from neezy_backend.cli import main
from neezy_backend.cli.bot import _read_status


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class BotStatusTests(unittest.TestCase):
    def test_human_status_is_read_only_and_sanitised(self):
        document = {
            "service": "neezy-light-executor",
            "status": "degraded",
            "heartbeat_utc": "2026-10-23T12:00:00+00:00",
            "execution": {"enabled": False, "mode": "demo-only"},
            "open_trades": [],
            "models": {"frxEURUSD": {"active": True}},
            "paper_validation": {"status": "running"},
            "issues": [{"message": "demo offline \u2014 retrying"}],
        }
        out = io.StringIO()
        with mock.patch("neezy_backend.cli.bot._read_status", return_value=document):
            code = main(["bot", "status"], out=out)
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("Status: degraded", text)
        self.assertIn("Execution: disabled / observer", text)
        self.assertIn("Models: 1 active / 1 configured", text)
        self.assertIn("Paper validation: running", text)
        self.assertIn("Read-only status", text)
        self.assertTrue(all(ord(char) < 128 for char in text))

    def test_offline_status_is_clean_and_sends_nothing(self):
        out = io.StringIO()
        with mock.patch(
            "neezy_backend.cli.bot._read_status", side_effect=URLError("offline")
        ):
            code = main(["bot", "status"], out=out)
        self.assertEqual(code, 1)
        self.assertIn("Executor offline", out.getvalue())
        self.assertIn("No executor action or order was attempted", out.getvalue())

    def test_json_status_preserves_document(self):
        out = io.StringIO()
        with mock.patch(
            "neezy_backend.cli.bot._read_status", return_value={"status": "ok"}
        ):
            code = main(["bot", "status", "--json"], out=out)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), {"status": "ok"})

    def test_reader_uses_validated_loopback_config_and_bounded_timeout(self):
        config = SimpleNamespace(status_host="127.0.0.1", status_port=8787)
        response = _Response(b'{"status":"ok"}')
        with (
            mock.patch(
                "neezy_backend.executor_config.load_executor_config",
                return_value=config,
            ),
            mock.patch("neezy_backend.cli.bot.urlopen", return_value=response) as open_,
        ):
            document = _read_status(0.5)
        self.assertEqual(document, {"status": "ok"})
        request = open_.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8787/api/status")
        self.assertEqual(open_.call_args.kwargs["timeout"], 0.5)

    def test_reader_rejects_oversized_response(self):
        config = SimpleNamespace(status_host="localhost", status_port=8787)
        response = _Response(b" " * 256_001)
        with (
            mock.patch(
                "neezy_backend.executor_config.load_executor_config",
                return_value=config,
            ),
            mock.patch("neezy_backend.cli.bot.urlopen", return_value=response),
        ):
            with self.assertRaisesRegex(ValueError, "size limit"):
                _read_status(0.5)


if __name__ == "__main__":
    unittest.main()
