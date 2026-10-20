"""Local, offline tests for Telegram token storage and chat allow-listing."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import URLError

from neezy_backend.telegram import (
    TelegramAPIError,
    TelegramBotService,
    TelegramTokenStore,
    _api_call,
    parse_chat_ids,
)

VALID_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"


class TelegramTokenStoreTest(unittest.TestCase):
    def test_save_load_clear_and_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "telegram-bot.json"
            store = TelegramTokenStore(path)
            store.save(VALID_TOKEN)
            self.assertEqual(store.load(), VALID_TOKEN)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            store.clear()
            self.assertIsNone(store.load())

    def test_invalid_tokens_are_rejected(self):
        store = TelegramTokenStore(Path("/tmp/not-written.json"))
        with self.assertRaises(ValueError):
            store.save("not-a-token")

    def test_chat_id_parser_deduplicates_and_checks_numeric_ids(self):
        self.assertEqual(parse_chat_ids("123, -456,123"), ("123", "-456"))
        self.assertEqual(parse_chat_ids([]), ())
        with self.assertRaises(ValueError):
            parse_chat_ids("123abc")
        with self.assertRaises(ValueError):
            parse_chat_ids(",".join(str(i) for i in range(1, 22)))


class TelegramBotServiceTest(unittest.TestCase):
    def test_only_allow_listed_chats_reach_the_command_handler(self):
        seen = []
        service = TelegramBotService(
            VALID_TOKEN,
            ["123"],
            command_handler=lambda text, chat_id: seen.append((text, chat_id)) or "ok",
        )
        sent = []
        service.send_message = lambda chat_id, text: (
            sent.append((chat_id, text)) or True
        )
        service._handle_update(
            {
                "update_id": 4,
                "message": {"chat": {"id": 999}, "text": "/status"},
            }
        )
        self.assertEqual(seen, [])
        service._handle_update(
            {
                "update_id": 5,
                "message": {"chat": {"id": 123}, "text": "/status"},
            }
        )
        self.assertEqual(seen, [("/status", "123")])
        self.assertEqual(sent, [("123", "ok")])
        self.assertEqual(service._offset, 6)

    def test_unauthorized_send_is_rejected(self):
        service = TelegramBotService(VALID_TOKEN, ["123"])
        self.assertFalse(service.send_message("999", "private"))
        self.assertEqual(service.notify("alert"), 1)
        self.assertEqual(service._outbound.get_nowait(), ("123", "alert"))

    def test_network_error_does_not_leak_bot_token(self):
        with mock.patch(
            "neezy_backend.telegram.urlopen", side_effect=URLError("offline")
        ):
            with self.assertRaises(TelegramAPIError) as error:
                _api_call(VALID_TOKEN, "getMe", {})
        self.assertNotIn(VALID_TOKEN, str(error.exception))

    def test_api_success_parses_json(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"ok": True, "result": {"username": "neezy_bot"}}
        ).encode()
        with mock.patch("neezy_backend.telegram.urlopen", return_value=response):
            self.assertEqual(
                _api_call(VALID_TOKEN, "getMe", {})["result"]["username"],
                "neezy_bot",
            )


if __name__ == "__main__":
    unittest.main()
