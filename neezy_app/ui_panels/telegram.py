"""Telegram panels for the NEEZY desktop window."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

from neezy_backend.telegram import (
    TelegramAPIError,
    TelegramBotService,
    parse_chat_ids,
    test_bot_token,
)


class TelegramMixin:
    """Methods for the telegram screen; mixed into App."""

    def _telegram_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "TELEGRAM")
        self._label(left, "TELEGRAM BOT", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self._check_row(left, "Enable Telegram bot", self.telegram_enabled_var)
        self._check_row(
            left,
            "Send alert-rule and signal-transition notifications",
            self.telegram_alerts_var,
        )
        self._check_row(
            left,
            "Allow authorized chats to change settings, alerts, and memory",
            self.telegram_commands_var,
        )
        self._entry_row(
            left,
            "Allowed Telegram chat IDs (comma-separated)",
            self.telegram_chat_ids_var,
        )
        self._label(
            left,
            "Commands are restricted to the chat IDs above. Read commands are always "
            "available; write commands require the separate permission checkbox.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        ).pack(anchor="w", padx=16, pady=(6, 10))
        self._label(right, "BOT TOKEN · STORED LOCALLY", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self.telegram_token_entry = tk.Entry(
            right,
            textvariable=self.telegram_token_var,
            show="•",
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
        )
        self.telegram_token_entry.pack(fill="x", padx=16, pady=(4, 8), ipady=5)
        token_buttons = tk.Frame(right, bg=self.PANEL)
        token_buttons.pack(fill="x", padx=16, pady=(0, 8))
        for text, command in [
            ("Save token", self._telegram_save_token),
            ("Remove token", self._telegram_remove_token),
            ("Test bot", self._telegram_test_bot),
        ]:
            tk.Button(
                token_buttons,
                text=text,
                command=command,
                bg=self.PANEL2,
                fg=self.TEXT,
                relief="flat",
                padx=8,
                pady=5,
            ).pack(side="left", padx=(0, 5))
        self.telegram_status = self._label(
            right,
            "No bot token stored."
            if not self.telegram_token_store.configured
            else "Bot token stored securely.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        )
        self.telegram_status.pack(anchor="w", padx=16, pady=(0, 6))
        self._label(
            right,
            "Create a bot with @BotFather, then message it. Use @userinfobot to "
            "find your numeric chat ID and add it to the allow-list. Start the bot "
            "with /start. Supported commands: /help, /status, /markets, /signals, "
            "/analyze, /scan, /ask, /alerts; optional writes: /alert, /remember, "
            "/set, /delete-alert. Telegram handles messages sent through the bot; "
            "allow-list only chats you trust.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        ).pack(anchor="w", padx=16, pady=(0, 10))

    def _stop_telegram_service(self):
        if self.telegram_service is not None:
            self.telegram_service.stop()
        self.telegram_service = None
        self._telegram_service_signature = None

    def _sync_telegram_service(self):
        if not hasattr(self, "telegram_status"):
            return
        if not self.settings.telegram_enabled:
            self._stop_telegram_service()
            configured = self.telegram_token_store.configured
            self.telegram_status.config(
                text="Bot disabled · token stored securely"
                if configured
                else "Bot disabled · no token stored",
                fg=self.MUTED,
            )
            return
        token = self.telegram_token_store.load()
        if not token:
            self._stop_telegram_service()
            self.telegram_status.config(
                text="Save a valid BotFather token to start the bot.", fg=self.RED
            )
            return
        try:
            chat_ids = parse_chat_ids(self.settings.telegram_chat_ids)
        except ValueError as error:
            self._stop_telegram_service()
            self.telegram_status.config(text=str(error), fg=self.RED)
            return
        if not chat_ids:
            self._stop_telegram_service()
            self.telegram_status.config(
                text="Add at least one authorized chat ID.", fg=self.RED
            )
            return
        signature = (token, chat_ids)
        if (
            self.telegram_service is not None
            and self._telegram_service_signature == signature
            and self.telegram_service.running
        ):
            status = (
                self.telegram_service.last_error
                or "Polling for authorized Telegram commands."
            )
            self.telegram_status.config(
                text=f"Running · {status}",
                fg=self.RED if self.telegram_service.last_error else self.GREEN,
            )
            return
        if self.telegram_service is not None:
            self.telegram_service.stop()
        try:
            self.telegram_service = TelegramBotService(
                token,
                chat_ids,
                command_handler=self._telegram_command,
            )
            self.telegram_service.start()
            self._telegram_service_signature = signature
            self.telegram_status.config(
                text=f"Running · {len(chat_ids)} authorized chat(s).", fg=self.GREEN
            )
        except (ValueError, OSError) as error:
            self.telegram_service = None
            self._telegram_service_signature = None
            self.telegram_status.config(
                text=f"Telegram bot failed: {error}", fg=self.RED
            )

    def _telegram_save_token(self):
        token = self.telegram_token_var.get().strip()
        try:
            self.telegram_token_store.save(token)
        except (ValueError, OSError) as error:
            self.telegram_status.config(text=str(error), fg=self.RED)
            return
        self.telegram_token_var.set("")
        self._sync_telegram_service()
        self.telegram_status.config(text="Bot token saved securely.", fg=self.GREEN)

    def _telegram_remove_token(self):
        if not messagebox.askyesno(
            "Remove Telegram token", "Stop the bot and remove its local token?"
        ):
            return
        if self.telegram_service is not None:
            self.telegram_service.stop()
        self.telegram_service = None
        self._telegram_service_signature = None
        self.telegram_token_store.clear()
        self.telegram_status.config(text="Telegram token removed.", fg=self.MUTED)

    def _telegram_test_bot(self):
        if self._telegram_testing:
            return
        token = (
            self.telegram_token_var.get().strip() or self.telegram_token_store.load()
        )
        if not token:
            self.telegram_status.config(
                text="Save or paste a bot token first.", fg=self.RED
            )
            return
        self._telegram_testing = True
        self.telegram_status.config(text="Testing Telegram bot…", fg=self.MUTED)

        def work():
            try:
                bot = test_bot_token(token)
                message = f"Connected to @{bot['username']} (ID {bot['id']})."
                color = self.GREEN
            except (TelegramAPIError, ValueError) as error:
                message, color = str(error), self.RED
            self.after(0, lambda: self._finish_telegram_test(message, color))

        threading.Thread(target=work, name="neezy-telegram-test", daemon=True).start()

    def _finish_telegram_test(self, message, color):
        self._telegram_testing = False
        self.telegram_status.config(text=message, fg=color)
