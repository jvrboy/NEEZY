"""Data providers panels for the NEEZY desktop window."""

from __future__ import annotations

import threading
import tkinter as tk

from neezy_backend.ai import (
    PROVIDERS,
)
from neezy_backend.markets import (
    SYMBOLS,
)
from neezy_backend.providers import (
    PROVIDERS as MARKET_PROVIDERS,
)
from neezy_backend.providers import (
    ProviderError,
    get_candles,
    provider_key_issues,
    resolve_provider,
)


class DataProvidersMixin:
    """Methods for the data providers screen; mixed into App."""

    def _data_provider_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "DATA PROVIDERS")
        self._label(left, "CONFLUENCE ENGINE", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self._spin_row(
            left, "Strict confluence score", self.conf_min_score_var, 0, 100, 5
        )
        self._spin_row(
            left,
            "Search-mode score (relaxed)",
            self.conf_search_score_var,
            0,
            100,
            5,
        )
        self._spin_row(left, "ATR stop multiple", self.conf_stop_var, 0.5, 6.0, 0.1)
        self._spin_row(left, "ATR target multiple", self.conf_tp_var, 0.5, 10.0, 0.1)
        self._spin_row(left, "Outcome horizon (bars)", self.conf_horizon_var, 3, 120, 1)
        self._spin_row(
            left,
            "Minimum win-rate analog samples",
            self.conf_min_analogs_var,
            2,
            100,
            1,
        )
        self._label(
            left,
            "Signals below the strict score are still shown by the ANALYSIS "
            "button in relaxed search mode, so the scan always yields cards.",
            9,
            self.MUTED,
            wraplength=300,
        ).pack(anchor="w", padx=16, pady=12)
        self._label(right, "MARKET DATA PROVIDERS", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        options = [f"{spec.label} ({spec.key})" for spec in MARKET_PROVIDERS.values()]
        current = resolve_provider(self.settings.market_data_provider)
        self.data_provider_var.set(f"{current.label} ({current.key})")
        self._combo_row(right, "Active provider", self.data_provider_var, options)
        self._spin_row(
            right,
            "Fetched candles per market",
            self.provider_count_var,
            60,
            1000,
            20,
        )
        self._entry_row(
            right,
            "API key for the selected provider (stored locally, never logged)",
            self.provider_key_var,
        )
        buttons = tk.Frame(right, bg=right.cget("bg"))
        buttons.pack(anchor="w", padx=16, pady=4)
        tk.Button(
            buttons,
            text="SAVE KEY",
            command=self._save_provider_key,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=12,
            pady=6,
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            buttons,
            text="TEST PROVIDER",
            command=self._test_provider,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=12,
            pady=6,
        ).pack(side="left")
        self.provider_status_label = self._label(
            right, "", 9, self.MUTED, wraplength=300
        )
        self.provider_status_label.pack(anchor="w", padx=16, pady=8)
        self._provider_status(
            "Deriv is the default provider and needs no key. Alpha Vantage, "
            "Finnhub and Twelve Data require one; Binance covers crypto only.",
            self.MUTED,
        )

    def _provider_status(self, message, color):
        if hasattr(self, "provider_status_label"):
            self.provider_status_label.config(text=message, fg=color)

    def _save_provider_key(self):
        provider = self._data_provider_key()
        spec = resolve_provider(provider)
        if not spec.requires_key:
            self._provider_status(f"{spec.label} needs no API key.", self.GREEN)
            return
        key = self.provider_key_var.get().strip()
        try:
            self.provider_keys.set(provider, key)
        except OSError as error:
            self._provider_status(f"Could not save key: {error}", self.RED)
            return
        self.provider_key_var.set("")
        self._settings_changed()
        issue = provider_key_issues(provider, self.provider_keys)
        if issue:
            self._provider_status(issue, self.RED)
        else:
            self._provider_status(
                f"{spec.label} key saved locally ({self.provider_keys.path.name}).",
                self.GREEN,
            )

    def _test_provider(self):
        if getattr(self, "_provider_test_running", False):
            return
        self._provider_test_running = True
        provider = self._data_provider_key()
        issue = provider_key_issues(provider, self.provider_keys)
        if issue:
            self._provider_status(issue, self.RED)
            return
        symbol = next(iter(self.watch_symbols), "frxEURUSD")
        timeframe = self.tf.get()
        spec = resolve_provider(provider)

        def work():
            try:
                rows = get_candles(provider, symbol, timeframe, 60)
                message = (
                    f"{spec.label}: fetched {len(rows)} candles for "
                    f"{SYMBOLS.get(symbol, symbol)}."
                )
                color = self.GREEN
            except (ProviderError, ValueError, ConnectionError, OSError) as error:
                message = f"{spec.label}: {error}"
                color = self.RED
            self.after(
                0,
                lambda sent_message=message, sent_color=color: (
                    self._provider_status(sent_message, sent_color),
                    setattr(self, "_provider_test_running", False),
                ),
            )

        threading.Thread(target=work, name="neezy-provider-test", daemon=True).start()

    @staticmethod
    def _provider_label(key):
        for spec in PROVIDERS.values():
            if spec.key == key:
                return f"{spec.label} ({spec.key})"
        return "OpenRouter (openrouter)"
