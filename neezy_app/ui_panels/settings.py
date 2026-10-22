"""Settings panels for the NEEZY desktop window (16 searchable sub-tabs)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from neezy_app.ui_panels.constants import NAV, RESEARCH_CONTROLS
from neezy_backend.config import (
    ACCOUNT_CURRENCIES,
    ALERT_SOUND_MODES,
    CHART_STYLES,
    CHART_SUBPANE_OSCILLATORS,
    CSV_DELIMITERS,
    DISPLAY_TIMEZONES,
    LIVE_SIGNAL_SOURCES,
    LOG_LEVELS,
    ML_ARCHITECTURES,
    SETTINGS_PROFILE_NAMES,
)
from neezy_backend.markets import (
    APP_ID,
    SYMBOLS,
    TIMEFRAMES,
)
from neezy_backend.strategies import (
    STRATEGIES,
)


class SettingsMixin:
    """Methods for the settings screen; mixed into App."""

    def _settings_page(self):
        page = self.pages["SETTINGS"]
        self._settings_tabs: dict[str, tk.Frame] = {}
        self._settings_search_index: list[tuple[str, str]] = []
        self._active_build_tab = "WORKSPACE"

        top_bar = tk.Frame(page, bg=self.BG)
        top_bar.pack(fill="x", pady=(5, 4))
        self._label(top_bar, "Workspace settings", 16).pack(side="left")

        search_wrap = tk.Frame(top_bar, bg=self.BG)
        search_wrap.pack(side="right")
        self._label(search_wrap, "Find setting:", 9, self.MUTED).pack(
            side="left", padx=(0, 6)
        )
        self.settings_search_var = tk.StringVar()
        self.settings_search_entry = tk.Entry(
            search_wrap,
            textvariable=self.settings_search_var,
            width=26,
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
        )
        self.settings_search_entry.pack(side="left", ipady=3, padx=(0, 6))
        self.settings_jump_var = tk.StringVar(value="")
        self.settings_jump_combo = ttk.Combobox(
            search_wrap,
            textvariable=self.settings_jump_var,
            width=30,
            state="readonly",
            values=(),
        )
        self.settings_jump_combo.pack(side="left")
        self.settings_jump_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._jump_to_searched_setting()
        )
        self.settings_search_entry.bind(
            "<KeyRelease>", lambda _e: self._filter_settings_search()
        )

        self._label(
            page,
            "Tune the engine, charts, risk guardrails, alerts, local storage, "
            "AI copilot, and broker bridges. All changes validate & apply live.",
            10,
            self.MUTED,
        ).pack(anchor="w", pady=(0, 8))

        notebook = ttk.Notebook(page)
        notebook.pack(fill="both", expand=True)
        self.settings_notebook = notebook
        self._workspace_settings_tab(notebook)
        self._chart_settings_tab(notebook)
        self._data_provider_settings_tab(notebook)
        self._engine_settings_tab(notebook)
        self._risk_safety_settings_tab(notebook)
        self._alerts_settings_tab(notebook)
        self._research_settings_tab(notebook, "ML RESEARCH")
        self._research_settings_tab(notebook, "PAIR RESEARCH")
        self._local_settings_tab(notebook)
        self._ai_settings_tab(notebook)
        self._local_model_settings_tab(notebook)
        self._mcp_settings_tab(notebook)
        self._telegram_settings_tab(notebook)
        self._mt5_settings_tab(notebook)
        self._dm_settings_tab(notebook)
        self._profiles_diagnostics_tab(notebook)

        footer = tk.Frame(page, bg=self.BG)
        footer.pack(fill="x", pady=(8, 0))
        self.settings_status = self._label(
            footer, "Settings are saved locally", 10, self.GREEN
        )
        self.settings_status.pack(side="left", padx=4)
        for text, cmd in (
            ("Reset Defaults", self._reset_settings_to_defaults),
            ("Undo Last Save", self._rollback_previous_settings),
            ("Import JSON", self._import_settings_json),
            ("Export JSON", self._export_settings_json),
        ):
            tk.Button(
                footer,
                text=text,
                command=cmd,
                bg=self.PANEL2,
                fg=self.TEXT,
                relief="flat",
                padx=9,
                pady=4,
            ).pack(side="right", padx=(6, 0))
        self._filter_settings_search()

    def _filter_settings_search(self) -> None:
        query = self.settings_search_var.get().strip().lower()
        tokens = query.split()
        matches = [
            f"{tab}  ->  {label}"
            for tab, label in self._settings_search_index
            if not tokens or all(tok in f"{tab} {label}".lower() for tok in tokens)
        ]
        self.settings_jump_combo.configure(values=matches[:60])
        if query and matches:
            self.settings_jump_var.set(matches[0])

    def _jump_to_searched_setting(self) -> None:
        picked = self.settings_jump_var.get()
        if "->" not in picked:
            return
        tab_name = picked.split("->", 1)[0].strip()
        tab_widget = self._settings_tabs.get(tab_name)
        if tab_widget is not None:
            self.settings_notebook.select(tab_widget)

    def _index_setting(self, label: str) -> None:
        if hasattr(self, "_settings_search_index"):
            self._settings_search_index.append((self._active_build_tab, label))

    def _settings_tab(self, notebook, title):
        self._active_build_tab = title
        tab = tk.Frame(notebook, bg=self.BG)
        notebook.add(tab, text=title)
        if hasattr(self, "_settings_tabs"):
            self._settings_tabs[title] = tab
        body = tk.Frame(tab, bg=self.BG)
        body.pack(fill="both", expand=True, padx=4, pady=8)
        left, right = self._panel(body), self._panel(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))
        return tab, left, right

    def _check_row(self, parent, text, variable):
        self._index_setting(text)
        btn = tk.Checkbutton(
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
        )
        btn.pack(fill="x", padx=12, pady=4)
        return btn

    def _spin_row(self, parent, label, variable, low, high, step=1):
        self._index_setting(label)
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.pack(fill="x", padx=16, pady=3)
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
        self._index_setting(label)
        self._label(parent, label, 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(5, 2)
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
        entry.pack(fill="x", padx=16, pady=(0, 3), ipady=4)
        entry.bind("<Return>", lambda _: self._settings_changed())
        entry.bind("<FocusOut>", lambda _: self._settings_changed())
        return entry

    def _combo_row(self, parent, label, variable, values, on_change=None):
        self._index_setting(label)
        self._label(parent, label, 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(5, 2)
        )
        combo = ttk.Combobox(
            parent, textvariable=variable, values=values, state="readonly"
        )
        combo.pack(fill="x", padx=16, pady=(0, 3))
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _: (on_change or self._settings_changed)(),
        )
        return combo

    def _workspace_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "WORKSPACE")
        self._label(left, "LIVE WORKSPACE & APPEARANCE", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._check_row(left, "Auto-refresh signal feed", self.auto_refresh)
        self._check_row(left, "Desktop signal alerts", self.alerts_enabled)
        self._check_row(left, "Compact data density", self.compact_mode)
        self._check_row(
            left,
            "Colorblind-safe cyan / amber palette",
            self.extra_vars["colorblind_palette"],
        )
        self._check_row(
            left,
            "Reduced motion (disable pulse animations)",
            self.extra_vars["reduced_motion"],
        )
        self._check_row(
            left,
            "Flash watchlist rows on live ticks",
            self.extra_vars["price_flash_on_tick"],
        )
        self._check_row(
            left,
            "Confirm before closing NEEZY window",
            self.extra_vars["confirm_on_exit"],
        )
        self._combo_row(
            left,
            "Theme preset",
            self.theme_var,
            ["Liquid dark", "Midnight blue", "High contrast"],
        )
        self._spin_row(
            left,
            "UI DPI scale (%)",
            self.extra_vars["ui_scale_percent"],
            75,
            200,
            5,
        )
        self._spin_row(
            left,
            "Font size offset (pt)",
            self.extra_vars["font_size_offset"],
            -2,
            6,
            1,
        )
        self._spin_row(left, "UI poll interval (ms)", self.polling_var, 50, 2000, 50)
        self._spin_row(
            left, "Max candles in memory", self.candle_limit_var, 60, 1000, 20
        )
        self._spin_row(left, "Alert score threshold", self.alert_min_score_var, 1, 4, 1)

        self._label(right, "STARTUP & LIVE STREAM CONNECTION", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self.connection_detail = self._label(
            right, f"App ID {APP_ID} · awaiting connection", 10, self.MUTED
        )
        self.connection_detail.pack(anchor="w", padx=16, pady=(0, 4))
        self._combo_row(
            right,
            "Default startup screen",
            self.extra_vars["startup_page"],
            list(NAV),
        )
        self._combo_row(
            right,
            "Default startup symbol",
            self.extra_vars["startup_symbol"],
            list(SYMBOLS),
        )
        self._combo_row(
            right,
            "Startup timeframe",
            self.default_tf_var,
            list(TIMEFRAMES),
        )
        self._combo_row(
            right,
            "Display clock timezone",
            self.extra_vars["display_timezone"],
            sorted(DISPLAY_TIMEZONES),
        )
        self._spin_row(
            right,
            "History candles per market",
            self.history_var,
            60,
            1000,
            20,
        )
        self._entry_row(
            right,
            "Extra markets (comma-separated, blank = default)",
            self.watchlist_var,
        )
        self._entry_row(
            right, "Custom WebSocket URL (blank = automatic)", self.endpoint_var
        )
        self._spin_row(
            right, "First reconnect delay (s)", self.reconnect_var, 0.5, 60, 0.5
        )
        self._spin_row(
            right, "Max reconnect delay (s)", self.max_reconnect_var, 1, 600, 1
        )
        self._spin_row(
            right,
            "Stale tick warning threshold (s)",
            self.extra_vars["stale_tick_timeout_seconds"],
            10,
            600,
            10,
        )
        btn_row = tk.Frame(right, bg=self.PANEL)
        btn_row.pack(fill="x", padx=16, pady=(8, 8))
        tk.Button(
            btn_row,
            text="Export signal history CSV",
            command=self._export_history,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=6,
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            btn_row,
            text="Clear local history",
            command=self._clear_history,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=6,
        ).pack(side="left")

    def _chart_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "CHART & VISUALS")
        self._label(left, "CANDLES & MOVING AVERAGES", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._combo_row(
            left,
            "Chart rendering style",
            self.extra_vars["chart_style"],
            sorted(CHART_STYLES),
        )
        self._spin_row(
            left,
            "Visible candles on chart",
            self.extra_vars["chart_visible_candles"],
            30,
            500,
            10,
        )
        self._check_row(
            left, "Show fast EMA overlay", self.extra_vars["chart_show_ema_fast"]
        )
        self._spin_row(
            left,
            "Fast EMA period",
            self.extra_vars["chart_ema_fast_period"],
            2,
            200,
            1,
        )
        self._check_row(
            left, "Show medium EMA overlay", self.extra_vars["chart_show_ema_slow"]
        )
        self._spin_row(
            left,
            "Medium EMA period",
            self.extra_vars["chart_ema_slow_period"],
            2,
            200,
            1,
        )
        self._check_row(
            left, "Show slow trend EMA overlay", self.extra_vars["chart_show_ema_trend"]
        )
        self._spin_row(
            left,
            "Slow trend EMA period",
            self.extra_vars["chart_ema_trend_period"],
            5,
            500,
            5,
        )
        self._check_row(
            left, "Show Bollinger Bands", self.extra_vars["chart_show_bollinger"]
        )

        self._label(right, "STRUCTURE LEVELS, HUD & SUBPANES", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._check_row(
            right,
            "Draw horizontal Support / Resistance lines",
            self.extra_vars["chart_show_sr_levels"],
        )
        self._spin_row(
            right,
            "S/R levels per side",
            self.extra_vars["chart_sr_count"],
            1,
            5,
            1,
        )
        self._check_row(
            right,
            "Draw classic Floor Pivots (P / R1 / S1)",
            self.extra_vars["chart_show_pivots"],
        )
        self._check_row(
            right,
            "Draw ATR Entry / Stop-Loss / Take-Profit guide lines",
            self.extra_vars["chart_show_entry_sl_tp"],
        )
        self._check_row(
            right,
            "Shade London / New York session windows",
            self.extra_vars["chart_show_session_boxes"],
        )
        self._combo_row(
            right,
            "Lower oscillator subpane",
            self.extra_vars["chart_subpane_oscillator"],
            ["None", *sorted(CHART_SUBPANE_OSCILLATORS - {"None"})],
        )
        self._check_row(
            right,
            "Interactive mouse crosshair & OHLC HUD",
            self.extra_vars["chart_show_crosshair"],
        )
        self._check_row(
            right, "Show horizontal price grid", self.extra_vars["chart_show_grid"]
        )
        self._check_row(
            right,
            "Mark missing timestamp gaps",
            self.extra_vars["chart_mark_candle_gaps"],
        )

    def _engine_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "ENGINE")
        self._label(left, "STRATEGY & INDICATOR ENGINE", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._combo_row(
            left,
            "Active strategy",
            self.strategy_var,
            [f"{spec.name} · {spec.label}" for spec in STRATEGIES.values()],
            self._strategy_changed,
        )
        self._combo_row(
            left,
            "Live watchlist signal source",
            self.extra_vars["live_signal_source"],
            sorted(LIVE_SIGNAL_SOURCES),
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
        self._spin_row(
            left,
            "ADX trend regime threshold",
            self.extra_vars["indicator_adx_trend_threshold"],
            10.0,
            50.0,
            1.0,
        )
        self._spin_row(
            left,
            "Donchian channel period",
            self.extra_vars["donchian_period"],
            5,
            200,
            5,
        )
        self._spin_row(
            left,
            "Keltner channel period",
            self.extra_vars["keltner_period"],
            5,
            200,
            5,
        )
        self._spin_row(
            left,
            "Consensus vote threshold",
            self.extra_vars["consensus_net_threshold"],
            0.05,
            0.80,
            0.05,
        )
        self._check_row(left, "Show strategy overlay on chart", self.overlay_var)
        self._check_row(
            left,
            "Include the local neural research model in context",
            self.use_brain_var,
        )

        self._label(right, "MULTI-STRATEGY SCAN", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
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

    def _risk_safety_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "RISK & SAFETY")
        self._label(left, "POSITION SIZING DEFAULTS", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._spin_row(
            left,
            "Default account balance",
            self.extra_vars["account_balance_default"],
            10.0,
            10000000.0,
            500.0,
        )
        self._combo_row(
            left,
            "Account display currency",
            self.extra_vars["account_currency"],
            sorted(ACCOUNT_CURRENCIES),
        )
        self._spin_row(
            left,
            "Default risk per trade (%)",
            self.default_risk_percent_var,
            0.1,
            100.0,
            0.25,
        )
        self._spin_row(
            left,
            "Forex risk override (%)",
            self.extra_vars["fx_risk_percent"],
            0.1,
            20.0,
            0.25,
        )
        self._spin_row(
            left,
            "Synthetic index risk (%)",
            self.extra_vars["synthetic_risk_percent"],
            0.1,
            20.0,
            0.25,
        )
        self._spin_row(
            left,
            "Crypto risk override (%)",
            self.extra_vars["crypto_risk_percent"],
            0.1,
            20.0,
            0.25,
        )
        self._spin_row(
            left,
            "Default Reward : Risk target",
            self.extra_vars["default_reward_to_risk"],
            0.5,
            10.0,
            0.5,
        )
        self._spin_row(
            left,
            "Default pip value / standard lot",
            self.extra_vars["default_pip_value_per_lot"],
            0.1,
            1000.0,
            1.0,
        )
        self._spin_row(
            left,
            "Max account drawdown alert (%)",
            self.max_drawdown_limit_var,
            0.1,
            100.0,
            0.5,
        )

        self._label(right, "LIVE ORDER SAFETY CIRCUIT BREAKERS", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._check_row(
            right,
            "Hard dry-run / paper lock (block live broker orders)",
            self.extra_vars["order_dry_run_mode"],
        )
        self._check_row(
            right,
            "Require Stop-Loss price on all live orders",
            self.extra_vars["require_stop_loss_on_live_orders"],
        )
        self._check_row(
            right,
            "Require pre-trade checklist confirmation before order",
            self.extra_vars["pre_trade_checklist_enabled"],
        )
        self._spin_row(
            right,
            "Max lot size per ticket cap",
            self.extra_vars["max_lot_size_cap"],
            0.01,
            100.0,
            0.1,
        )
        self._spin_row(
            right,
            "Max simultaneous open positions",
            self.extra_vars["max_open_positions"],
            1,
            50,
            1,
        )
        self._spin_row(
            right,
            "Daily max loss circuit breaker (%)",
            self.extra_vars["daily_max_loss_percent"],
            0.5,
            50.0,
            0.5,
        )
        self._spin_row(
            right,
            "Daily max live orders",
            self.extra_vars["daily_max_trades"],
            1,
            100,
            1,
        )
        self._spin_row(
            right,
            "Minimum R:R when SL & TP set",
            self.extra_vars["min_rr_for_live_order"],
            0.1,
            10.0,
            0.25,
        )
        self._entry_row(
            right,
            "Pre-trade checklist items (semicolon-separated)",
            self.extra_vars["pre_trade_checklist_items"],
        )

    def _alerts_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "ALERTS & QUIET HOURS")
        self._label(left, "DESKTOP TOASTS, BELL & COOLDOWNS", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._combo_row(
            left,
            "Alert sound mode",
            self.extra_vars["alert_sound_mode"],
            sorted(ALERT_SOUND_MODES),
        )
        self._spin_row(
            left,
            "Per-rule alert cooldown (seconds)",
            self.extra_vars["alert_cooldown_seconds"],
            0,
            86400,
            30,
        )
        self._check_row(
            left,
            "Show sliding desktop toast notifications",
            self.extra_vars["toast_notifications_enabled"],
        )
        self._spin_row(
            left,
            "Toast display duration (ms)",
            self.extra_vars["toast_duration_ms"],
            1500,
            30000,
            500,
        )
        self._check_row(
            left,
            "Auto-disable price cross rules after first trigger",
            self.extra_vars["auto_disable_one_shot_price_alerts"],
        )

        self._label(right, "QUIET HOURS & WATCHDOG ALERTS", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._check_row(
            right,
            "Enable quiet hours (mute bell & outbound webhooks/bots)",
            self.extra_vars["quiet_hours_enabled"],
        )
        self._entry_row(
            right,
            "Quiet hours start (UTC HH:MM)",
            self.extra_vars["quiet_hours_start"],
        )
        self._entry_row(
            right,
            "Quiet hours end (UTC HH:MM)",
            self.extra_vars["quiet_hours_end"],
        )
        self._check_row(
            right,
            "Alert when market stream disconnects",
            self.extra_vars["alert_on_stream_disconnect"],
        )
        self._check_row(
            right,
            "Alert when MT5 equity breaches max drawdown",
            self.extra_vars["alert_on_drawdown_breach"],
        )

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
        if title == "ML RESEARCH":
            self._combo_row(
                right,
                "Neural model architecture",
                self.extra_vars["ml_model_architecture"],
                sorted(ML_ARCHITECTURES),
            )
            self._spin_row(
                right,
                "Ensemble member count",
                self.extra_vars["ml_ensemble_members"],
                2,
                15,
                1,
            )
            self._spin_row(
                right,
                "Sequence lookback window (GRU)",
                self.extra_vars["ml_sequence_window"],
                3,
                60,
                1,
            )
            self._spin_row(
                right,
                "Default backtest spread cost (pips)",
                self.extra_vars["backtest_default_spread_pips"],
                0.0,
                20.0,
                0.2,
            )
            self._spin_row(
                right,
                "Signal outcomes evaluation horizon (bars)",
                self.extra_vars["outcome_eval_horizon"],
                1,
                200,
                1,
            )
        self._label(
            right,
            "Research only. Pair thresholds require exit < entry < stop; "
            "overlap must be at least 3 lookback windows.",
            9,
            self.MUTED,
            wraplength=300,
        ).pack(anchor="w", padx=16, pady=10)

    def _local_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "LOCAL DATA")
        self._label(left, "ON-DEVICE STORAGE & EXPORTS", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._check_row(
            left, "Save candles to the local database", self.store_candles_var
        )
        self._check_row(left, "Save analysis snapshots", self.snapshots_var)
        self._check_row(
            left,
            "Auto-prune expired rows on startup",
            self.extra_vars["auto_prune_on_startup"],
        )
        self._check_row(
            left,
            "Create automatic local zip backup on exit",
            self.extra_vars["auto_backup_enabled"],
        )
        self._spin_row(left, "Keep history (days)", self.retention_var, 1, 3650, 5)
        self._spin_row(
            left,
            "Snapshot throttle interval (seconds)",
            self.extra_vars["snapshot_interval_seconds"],
            15,
            3600,
            15,
        )
        self._spin_row(
            left,
            "Max signal history rows retained",
            self.extra_vars["max_signal_history_rows"],
            100,
            50000,
            500,
        )
        self._spin_row(
            left,
            "Max backup zip files retained",
            self.extra_vars["max_backup_count"],
            1,
            100,
            1,
        )
        self._combo_row(
            left,
            "CSV export delimiter",
            self.extra_vars["csv_delimiter"],
            sorted(CSV_DELIMITERS),
        )

        self._label(right, "DATABASE & BACKUPS", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
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
            ("Create local backup archive (.zip)", self._create_backup_archive),
            ("Restore from local backup (.zip)", self._restore_backup_archive),
        ]:
            tk.Button(
                right,
                text=text,
                command=command,
                bg=self.PANEL2,
                fg=self.TEXT,
                relief="flat",
                padx=12,
                pady=5,
            ).pack(anchor="w", padx=16, pady=2)
        self._refresh_db_stats()

    def _profiles_diagnostics_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "PROFILES & DIAGNOSTICS")
        self._label(left, "WORKSPACE PRESET PROFILES", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._combo_row(
            left,
            "Active workspace preset",
            self.extra_vars["active_settings_profile"],
            list(SETTINGS_PROFILE_NAMES),
            lambda: self._apply_profile_preset(),
        )
        self._label(
            left,
            "Presets tune risk, timeframes, confluence strictness, and UI density "
            "at once while leaving stored API keys, tokens, and broker passwords "
            "untouched.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        ).pack(anchor="w", padx=16, pady=(6, 10))
        for p_name in SETTINGS_PROFILE_NAMES:
            tk.Button(
                left,
                text=f"Apply '{p_name}' preset",
                command=lambda n=p_name: self._apply_profile_preset(n),
                bg=self.PANEL2,
                fg=self.TEXT,
                relief="flat",
                padx=12,
                pady=5,
            ).pack(anchor="w", padx=16, pady=2)

        self._label(right, "LOGGING, PORTABILITY & RECOVERY", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._combo_row(
            right,
            "Runtime log verbosity",
            self.extra_vars["log_level"],
            sorted(LOG_LEVELS),
        )
        for text, cmd in (
            ("Export redacted settings JSON", self._export_settings_json),
            ("Import settings JSON", self._import_settings_json),
            ("Rollback last settings change", self._rollback_previous_settings),
            ("Reset all settings to defaults", self._reset_settings_to_defaults),
        ):
            tk.Button(
                right,
                text=text,
                command=cmd,
                bg=self.PANEL2,
                fg=self.TEXT,
                relief="flat",
                padx=12,
                pady=6,
            ).pack(anchor="w", padx=16, pady=3)
