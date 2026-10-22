"""Integrations panels for the NEEZY desktop window."""

from __future__ import annotations

import tkinter as tk

from neezy_backend.config import DM_WEBHOOK_FORMATS, MT5_FILLING_MODES


class IntegrationsMixin:
    """Methods for the integrations screen; mixed into App."""

    def _mt5_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "MT5 BRIDGE")
        self._label(left, "METATRADER 5 BRIDGE", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._check_row(left, "Enable MetaTrader 5 local bridge", self.mt5_enabled_var)
        self._check_row(
            left, "Auto-sync account & quotes from MT5", self.mt5_auto_sync_var
        )
        self._spin_row(
            left,
            "Auto-sync interval (seconds)",
            self.extra_vars["mt5_sync_interval_seconds"],
            1,
            300,
            1,
        )
        self._entry_row(left, "MT5 Server", self.mt5_server_var)
        self._spin_row(
            left, "MT5 Account Login ID", self.mt5_login_var, 0, 2147483647, 1
        )
        self._entry_row(left, "MT5 Account Password", self.mt5_password_var, show="•")
        self._spin_row(left, "Magic Number", self.mt5_magic_var, 1, 2147483647, 1)

        self._label(right, "EXECUTION FILLING, SLIPPAGE & MAPPING", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._combo_row(
            right,
            "Broker order filling policy",
            self.extra_vars["mt5_filling_mode"],
            sorted(MT5_FILLING_MODES),
        )
        self._spin_row(
            right,
            "Max order slippage / deviation (points)",
            self.extra_vars["mt5_order_deviation_points"],
            0,
            200,
            5,
        )
        self._entry_row(right, "Terminal Executable Path (Optional)", self.mt5_path_var)
        self._entry_row(
            right,
            "Symbol Map (e.g. frxEURUSD=EURUSD,frxGBPUSD=GBPUSD.m)",
            self.mt5_symbol_map_var,
        )
        btn_frame = tk.Frame(right, bg=self.PANEL)
        btn_frame.pack(fill="x", padx=16, pady=(10, 6))
        tk.Button(
            btn_frame,
            text="Test MT5 Connection",
            command=self._test_mt5_connection,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=6,
        ).pack(side="left")
        self.mt5_status_label = self._label(
            right, "MT5 Bridge status: idle", 9, self.MUTED, wraplength=330
        )
        self.mt5_status_label.pack(anchor="w", padx=16, pady=(4, 10))

    def _test_mt5_connection(self):
        from neezy_backend.mt5_bridge import MT5Bridge

        bridge = MT5Bridge(
            login=int(self.mt5_login_var.get()),
            password=self.mt5_password_var.get(),
            server=self.mt5_server_var.get().strip(),
            path=self.mt5_path_var.get().strip(),
            magic=int(self.mt5_magic_var.get()),
            symbol_map=self.mt5_symbol_map_var.get().strip(),
        )
        res = bridge.connect()
        if res.get("success"):
            acc = res.get("account")
            srv = res.get("server", "N/A")
            self.mt5_status_label.config(
                text=f"Connected! Account: {acc} | Server: {srv}",
                fg=self.GREEN,
            )
        else:
            self.mt5_status_label.config(
                text=f"Connection failed: {res.get('error')}", fg=self.RED
            )

    def _dm_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "DIRECT MESSAGING")
        self._label(left, "WEBHOOK DIRECT MESSAGING", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._check_row(
            left, "Enable Direct Message Notifications", self.dm_enabled_var
        )
        self._check_row(
            left, "Notify on Signal Transitions", self.dm_notify_signals_var
        )
        self._check_row(left, "Notify on Alert Triggers", self.dm_notify_alerts_var)
        self._check_row(
            left,
            "Enforce HTTPS-only webhook URLs",
            self.extra_vars["dm_https_only"],
        )
        self._entry_row(
            left, "Webhook URL (Discord / Slack / Custom HTTP)", self.dm_webhook_url_var
        )
        self._combo_row(
            left,
            "Webhook payload format",
            self.extra_vars["dm_webhook_format"],
            sorted(DM_WEBHOOK_FORMATS),
        )
        self._spin_row(left, "Min Signal Score to Send", self.dm_min_score_var, 1, 4, 1)

        self._label(right, "DECISION METRICS & DELIVERY TEST", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        self._spin_row(
            right,
            "Default Account Risk %",
            self.default_risk_percent_var,
            0.1,
            100.0,
            0.5,
        )
        self._spin_row(
            right, "Max Drawdown Limit %", self.max_drawdown_limit_var, 0.1, 100.0, 1.0
        )
        btn_frame = tk.Frame(right, bg=self.PANEL)
        btn_frame.pack(fill="x", padx=16, pady=(12, 6))
        tk.Button(
            btn_frame,
            text="Send Test Direct Message",
            command=self._test_dm_webhook,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=6,
        ).pack(side="left")
        self.dm_status_label = self._label(
            right, "Direct messaging status: idle", 9, self.MUTED, wraplength=330
        )
        self.dm_status_label.pack(anchor="w", padx=16, pady=(6, 10))

    def _test_dm_webhook(self):
        from neezy_backend.dm import send_dm_notification

        url = self.dm_webhook_url_var.get().strip()
        if not url:
            self.dm_status_label.config(
                text="Please enter a Webhook URL first.", fg=self.RED
            )
            return
        res = send_dm_notification(
            url,
            "NEEZY Direct Message Test",
            "This is a test notification from your NEEZY desktop workspace.",
            level="info",
            fields={"App": "NEEZY", "Version": "1.5.0", "Status": "Active"},
            webhook_format=str(self.extra_vars["dm_webhook_format"].get()),
            https_only=bool(self.extra_vars["dm_https_only"].get()),
        )
        if res.get("success"):
            self.dm_status_label.config(
                text="Test message sent successfully!", fg=self.GREEN
            )
        else:
            self.dm_status_label.config(text=f"Failed: {res.get('error')}", fg=self.RED)
