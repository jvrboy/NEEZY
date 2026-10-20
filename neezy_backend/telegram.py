"""Telegram Bot API adapter for outbound alerts and allow-listed commands.

Uses the standard library only. Bot tokens are stored separately from normal
settings with owner-only file permissions; incoming commands are ignored unless
the Telegram chat ID was explicitly allow-listed in the desktop settings.
"""

from __future__ import annotations

import json
import queue
import re
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import __version__
from .storage import _atomic_json_write, get_data_dir

_TOKEN_RE = re.compile(r"^[0-9]{5,15}:[A-Za-z0-9_-]{20,}$")
_CHAT_ID_RE = re.compile(r"^-?[0-9]{1,20}$")
_MAX_MESSAGE_LENGTH = 4096


class TelegramAPIError(RuntimeError):
    """A sanitized Telegram API failure; never contains the bot token or URL."""


class TelegramTokenStore:
    """Owner-only local persistence for the Telegram Bot API token."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_data_dir() / "telegram-bot.json"
        self._lock = threading.RLock()

    @staticmethod
    def validate(token: str) -> str:
        cleaned = token.strip()
        if not _TOKEN_RE.fullmatch(cleaned):
            raise ValueError("paste a valid Telegram BotFather token (number:secret)")
        return cleaned

    def load(self) -> str | None:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        token = document.get("token") if isinstance(document, dict) else None
        if isinstance(token, str) and _TOKEN_RE.fullmatch(token):
            return token
        return None

    def save(self, token: str) -> None:
        secret = self.validate(token)
        with self._lock:
            _atomic_json_write(self.path, {"token": secret})
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    @property
    def configured(self) -> bool:
        return self.load() is not None


def parse_chat_ids(value: str | Iterable[str | int]) -> tuple[str, ...]:
    """Parse a comma-separated list of numeric Telegram chat IDs safely."""
    if isinstance(value, str):
        parts = value.replace("\n", ",").split(",")
    else:
        parts = [str(item) for item in value]
    ids: list[str] = []
    for part in parts:
        chat_id = str(part).strip()
        if not chat_id:
            continue
        if not _CHAT_ID_RE.fullmatch(chat_id) or int(chat_id) == 0:
            raise ValueError(f"invalid Telegram chat id: {chat_id!r}")
        if chat_id not in ids:
            ids.append(chat_id)
    if len(ids) > 20:
        raise ValueError("at most 20 Telegram chats can be allow-listed")
    return tuple(ids)


def _api_call(
    token: str,
    method: str,
    payload: dict[str, Any],
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    if not _TOKEN_RE.fullmatch(token):
        raise TelegramAPIError("Telegram bot token is not configured")
    url = f"https://api.telegram.org/bot{token}/{method}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"NEEZY/{__version__}",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(1_000_000)
    except HTTPError as error:
        raise TelegramAPIError(
            f"Telegram {method} request failed (HTTP {error.code})"
        ) from None
    except (URLError, TimeoutError, OSError):
        # URLError messages can embed the request URL, which contains the secret.
        raise TelegramAPIError(
            f"Telegram {method} request could not reach the service"
        ) from None
    try:
        result = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TelegramAPIError(f"Telegram {method} returned invalid JSON") from None
    if not isinstance(result, dict) or not result.get("ok"):
        code = result.get("error_code") if isinstance(result, dict) else None
        suffix = f" (API error {code})" if isinstance(code, int) else ""
        raise TelegramAPIError(f"Telegram {method} was rejected{suffix}")
    return result


def test_bot_token(token: str) -> dict[str, Any]:
    """Test a token with getMe, returning only non-secret bot metadata."""
    secret = TelegramTokenStore.validate(token)
    result = _api_call(secret, "getMe", {}, timeout=10.0).get("result", {})
    if not isinstance(result, dict):
        raise TelegramAPIError("Telegram getMe returned an unexpected result")
    return {
        "id": result.get("id"),
        "username": result.get("username", ""),
        "first_name": result.get("first_name", ""),
    }


class TelegramBotService:
    """Polling bot with a strict chat allow-list and queued outbound messages."""

    def __init__(
        self,
        token: str,
        allowed_chat_ids: Iterable[str | int],
        command_handler: Callable[[str, str], str] | None = None,
        *,
        poll_timeout: int = 10,
    ) -> None:
        self.token = TelegramTokenStore.validate(token)
        self.allowed_chat_ids = frozenset(parse_chat_ids(allowed_chat_ids))
        if not self.allowed_chat_ids:
            raise ValueError("at least one allow-listed Telegram chat ID is required")
        if not 1 <= poll_timeout <= 30:
            raise ValueError("poll_timeout must be between 1 and 30 seconds")
        self.command_handler = command_handler
        self.poll_timeout = poll_timeout
        self._stop_event = threading.Event()
        self._outbound: queue.Queue[tuple[str, str] | None] = queue.Queue(maxsize=200)
        self._poll_thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None
        self._offset = 0
        self._lock = threading.RLock()
        self.last_error = ""
        self.bot_username = ""

    @property
    def running(self) -> bool:
        with self._lock:
            return any(
                thread is not None and thread.is_alive()
                for thread in (self._poll_thread, self._send_thread)
            )

    def start(self) -> None:
        with self._lock:
            if self.running:
                return
            self._stop_event.clear()
            self._send_thread = threading.Thread(
                target=self._send_loop, name="neezy-telegram-send", daemon=True
            )
            self._poll_thread = threading.Thread(
                target=self._poll_loop, name="neezy-telegram-poll", daemon=True
            )
            self._send_thread.start()
            self._poll_thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        try:
            self._outbound.put_nowait(None)
        except queue.Full:
            pass
        with self._lock:
            threads = (self._poll_thread, self._send_thread)
            self._poll_thread = None
            self._send_thread = None
        for thread in threads:
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=max(0.1, timeout))

    def send_message(self, chat_id: str | int, text: str) -> bool:
        """Queue a plain-text message; network I/O never blocks the UI caller."""
        target = str(chat_id).strip()
        if target not in self.allowed_chat_ids:
            return False
        message = str(text).strip()[:_MAX_MESSAGE_LENGTH]
        if not message:
            return False
        try:
            self._outbound.put_nowait((target, message))
        except queue.Full:
            self.last_error = "outbound queue is full"
            return False
        return True

    def notify(self, text: str) -> int:
        return sum(
            self.send_message(chat_id, text) for chat_id in self.allowed_chat_ids
        )

    def _send_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._outbound.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if item is None:
                    return
                chat_id, text = item
                _api_call(
                    self.token,
                    "sendMessage",
                    {
                        "chat_id": chat_id,
                        "text": text,
                        "disable_web_page_preview": True,
                    },
                    timeout=12.0,
                )
                self.last_error = ""
            except TelegramAPIError as error:
                self.last_error = str(error)
            finally:
                self._outbound.task_done()

    def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = _api_call(
                    self.token,
                    "getUpdates",
                    {
                        "offset": self._offset,
                        "timeout": self.poll_timeout,
                        "allowed_updates": ["message"],
                    },
                    timeout=self.poll_timeout + 5,
                )
                self.last_error = ""
                updates = result.get("result", [])
                if isinstance(updates, list):
                    for update in updates:
                        if self._stop_event.is_set():
                            break
                        self._handle_update(update)
            except TelegramAPIError as error:
                self.last_error = str(error)
                self._stop_event.wait(3.0)

    def _handle_update(self, update: Any) -> None:
        if not isinstance(update, dict):
            return
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            self._offset = max(self._offset, update_id + 1)
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        raw_chat_id = chat.get("id")
        chat_id = str(raw_chat_id) if isinstance(raw_chat_id, int) else ""
        if chat_id not in self.allowed_chat_ids:
            return
        text = message.get("text")
        if (
            not isinstance(text, str)
            or not text.strip()
            or self.command_handler is None
        ):
            return
        try:
            response = self.command_handler(text.strip(), chat_id)
        except Exception as error:  # noqa: BLE001 - do not kill the polling thread
            response = f"NEEZY command failed: {str(error)[:350]}"
        if response:
            self.send_message(chat_id, response)
