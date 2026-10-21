"""Settings panels for the NEEZY desktop window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from neezy_app.ui_panels.constants import RESEARCH_CONTROLS
from neezy_backend.markets import (
    APP_ID,
    TIMEFRAMES,
)
from neezy_backend.strategies import (
    STRATEGIES,
)


class SettingsMixin:
    """Methods for the settings screen; mixed into App."""

    def _settings_page(self):
        page = self.pages["SETTINGS"]
        self._label(page, "Workspace settings", 16).pack(anchor="w", pady=(5, 4))
        self._label(
            page,
            "Tune the engine, local storage, and AI providers.",
            10,
            self.MUTED,
        ).pack(anchor="w", pady=(0, 10))
        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True)
        self.settings_notebook = notebook
        self._workspace_settings_tab(notebook)
        self._data_provider_settings_tab(notebook)
        self._engine_settings_tab(notebook)
        self._research_settings_tab(notebook, "ML RESEARCH")
        self._research_settings_tab(notebook, "PAIR RESEARCH")
        self._local_settings_tab(notebook)
        self._ai_settings_tab(notebook)
        self._local_model_settings_tab(notebook)
        self._mcp_settings_tab(notebook)
        self._telegram_settings_tab(notebook)
        self._mt5_settings_tab(notebook)
        self._dm_settings_tab(notebook)
        self.settings_status = self._label(
            page, "Settings are saved locally", 10, self.GREEN
        )
        self.settings_status.pack(anchor="w", padx=4, pady=(8, 0))

    def _research_settings_tab(self, notebook, title):
        _tab, left, right = self._settings_tab(notebook, title)
        controls = [row for row in RESEARCH_CONTROLS if row[-1] == title]
        middle = (len(controls) + 1) // 2
        for index, (name, label, low, high, step, _group) in enumerate(controls):
            self._spin_row(
                left if index < middle else right,
                label,
                self.research_vars[name],
                low,
                high,
                step,
            )
        self._label(
            right,
            "Research only. Pair thresholds require exit < entry < stop; "
            "overlap must be at least 3 lookback windows.",
            9,
            self.MUTED,
            wraplength=300,
        ).pack(anchor="w", padx=16, pady=12)

    def _settings_tab(self, notebook, title):
        tab = tk.Frame(notebook, bg=self.BG)
        notebook.add(tab, text=title)
        body = tk.Frame(tab, bg=self.BG)
        body.pack(fill="both", expand=True, padx=4, pady=8)
        left, right = self._panel(body), self._panel(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))
        return tab, left, right

    def _check_row(self, parent, text, variable):
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=self.PANEL,
            fg=self.TEXT,
            activebackground=self.PANEL,
            activeforeground=self.TEXT,
            selectcolor=self.PANEL2,
            anchor="w",
            font=("Helvetica", 10),
            command=self._settings_changed,
        ).pack(fill="x", padx=12, pady=5)

    def _spin_row(self, parent, label, variable, low, high, step=1):
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.pack(fill="x", padx=16, pady=4)
        self._label(row, label, 10, self.MUTED).pack(side="left")
        box = tk.Spinbox(
            row,
            from_=low,
            to=high,
            increment=step,
            width=8,
            textvariable=variable,
            bg=self.PANEL2,
            fg=self.TEXT,
            buttonbackground=self.PANEL2,
            relief="flat",
            command=self._settings_changed,
        )
        self._bind_commit(box)
        box.pack(side="right")
        return box

    def _entry_row(self, parent, label, variable, show=None):
        self._label(parent, label, 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(6, 3)
        )
        entry = tk.Entry(
            parent,
            textvariable=variable,
            show=show,
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
        )
        entry.pack(fill="x", padx=16, pady=(0, 4), ipady=4)
        entry.bind("<Return>", lambda _: self._settings_changed())
        entry.bind("<FocusOut>", lambda _: self._settings_changed())
        return entry

    def _combo_row(self, parent, label, variable, values, on_change=None):
        self._label(parent, label, 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(6, 3)
        )
        combo = ttk.Combobox(
            parent, textvariable=variable, values=values, state="readonly"
        )
        combo.pack(fill="x", padx=16, pady=(0, 4))
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _: (on_change or self._settings_changed)(),
        )
        return combo

    def _workspace_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "WORKSPACE")
        self._label(left, "LIVE WORKSPACE", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self._check_row(left, "Auto-refresh signal feed", self.auto_refresh)
        self._check_row(left, "Desktop signal alerts", self.alerts_enabled)
        self._check_row(left, "Compact data density", self.compact_mode)
        self._combo_row(
            left,
            "Theme preset",
            self.theme_var,
            ["Liquid dark", "Midnight blue", "High contrast"],
        )
        self._spin_row(left, "UI poll interval (ms)", self.polling_var, 50, 2000, 50)
        self._spin_row(
            left, "Max candles in memory", self.candle_limit_var, 60, 1000, 20
        )
        self._spin_row(left, "Alert score threshold", self.alert_min_score_var, 1, 4, 1)
        self._combo_row(
            left,
            "Startup timeframe",
            self.default_tf_var,
            list(TIMEFRAMES),
        )
        self._spin_row(
            left,
            "History candles per market",
            self.history_var,
            60,
            1000,
            20,
        )
        self._entry_row(
            left, "Extra markets (comma-separated, blank = default)", self.watchlist_var
        )

        self._label(right, "ENGINE & CONNECTION", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        self._label(right, "Market data connection", 12).pack(
            anchor="w", padx=16, pady=(2, 2)
        )
        self.connection_detail = self._label(
            right, f"App ID {APP_ID} · awaiting connection", 10, self.MUTED
        )
        self.connection_detail.pack(anchor="w", padx=16, pady=(0, 4))
        self._entry_row(
            right, "Custom WebSocket URL (blank = automatic)", self.endpoint_var
        )
        self._spin_row(
            right, "First reconnect delay (s)", self.reconnect_var, 0.5, 60, 0.5
        )
        self._spin_row(
            right, "Max reconnect delay (s)", self.max_reconnect_var, 1, 600, 1
        )
        self._label(
            right,
            "Connection and watchlist fields apply after you restart NEEZY.",
            9,
            self.MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 10))
        self._label(right, "Signal engine", 12).pack(anchor="w", padx=16, pady=(2, 2))
        self._label(
            right,
            "EMA 9/21/50 · RSI 14 · ATR 14 · MACD\n"
            "Bollinger · Stochastic · ADX · Supertrend\n"
            "RSI/MACD divergence · correlation divergence",
            10,
            self.MUTED,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 12))
        tk.Button(
            right,
            text="Export signal history as CSV",
            command=self._export_history,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=12,
            pady=7,
        ).pack(anchor="w", padx=16, pady=(2, 6))
        tk.Button(
            right,
            text="Clear local signal history",
            command=self._clear_history,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=12,
            pady=7,
        ).pack(anchor="w", padx=16, pady=(2, 6))

    def _engine_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "ENGINE")
        self._label(left, "STRATEGY ENGINE", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self._combo_row(
            left,
            "Active strategy",
            self.strategy_var,
            [f"{spec.name} · {spec.label}" for spec in STRATEGIES.values()],
            self._strategy_changed,
        )
        self._spin_row(left, "Supertrend period", self.st_period_var, 2, 100, 1)
        self._spin_row(left, "Supertrend multiplier", self.st_mult_var, 0.5, 10.0, 0.5)
        self._spin_row(
            left, "Divergence lookback (bars)", self.div_lookback_var, 1, 30, 1
        )
        self._spin_row(left, "Correlation window", self.corr_window_var, 10, 500, 10)
        self._spin_row(
            left, "Correlation baseline", self.corr_baseline_var, 20, 2000, 20
        )
        self._check_row(left, "Show strategy overlay on chart", self.overlay_var)
        self._check_row(
            left,
            "Include the local neural research model in context",
            self.use_brain_var,
        )

        self._label(right, "MULTI-STRATEGY SCAN", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self.strategy_help = self._label(
            right,
            self._strategy_description(),
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        )
        self.strategy_help.pack(anchor="w", padx=16, pady=(0, 8))
        tk.Button(
            right,
            text="Scan selected market",
            command=self._scan_strategies,
            bg=self.CYAN,
            fg=self.BG,
            relief="flat",
            font=("Helvetica", 10, "bold"),
            padx=12,
            pady=7,
        ).pack(anchor="w", padx=16, pady=(0, 8))
        brain_row = tk.Frame(right, bg=self.PANEL)
        brain_row.pack(fill="x", padx=16, pady=(0, 5))
        tk.Button(
            brain_row,
            text="Train local brain on saved candles",
            command=self._train_brain,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=6,
        ).pack(side="left")
        self.brain_status_label = self._label(
            right,
            "Local neural model is optional and never changes the core signal score.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        )
        self.brain_status_label.pack(anchor="w", padx=16, pady=(0, 6))
        self.engine_out = tk.Text(
            right,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            wrap="word",
            font=("Courier", 9),
            height=10,
            padx=8,
            pady=6,
        )
        self.engine_out.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.engine_out.insert("end", "Run a scan to score every strategy.")
        self.engine_out.config(state="disabled")

    def _local_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "LOCAL DATA")
        self._label(left, "ON-DEVICE STORAGE", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self._check_row(
            left, "Save candles to the local database", self.store_candles_var
        )
        self._check_row(left, "Save analysis snapshots", self.snapshots_var)
        self._spin_row(left, "Keep history (days)", self.retention_var, 1, 3650, 5)
        self._label(
            left,
            "Local data stays on this PC in your NEEZY data folder.\n"
            "Enabled AI/Telegram integrations send selected data externally; "
            "an MCP client may forward results to its provider. "
            "Use NEEZY_HOME to relocate local storage.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        ).pack(anchor="w", padx=16, pady=(10, 6))

        self._label(right, "DATABASE", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self.db_stats_label = self._label(
            right,
            "Reading local database…",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        )
        self.db_stats_label.pack(anchor="w", padx=16, pady=(0, 8))
        for text, command in [
            ("Refresh database stats", self._refresh_db_stats),
            ("Export database to JSON", self._export_database),
            ("Reclaim disk space (VACUUM)", self._vacuum_db),
            ("Apply retention now", self._prune_db),
        ]:
            tk.Button(
                right,
                text=text,
                command=command,
                bg=self.PANEL2,
                fg=self.TEXT,
                relief="flat",
                padx=12,
                pady=6,
            ).pack(anchor="w", padx=16, pady=3)
        self._refresh_db_stats()
