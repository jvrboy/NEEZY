"""Alerts panels for the NEEZY desktop window."""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from datetime import datetime
from tkinter import ttk

from neezy_backend.alerts import (
    METRICS,
    OPERATORS,
    AlertRule,
)
from neezy_backend.markets import (
    SYMBOLS,
)


class AlertsMixin:
    """Methods for the alerts screen; mixed into App."""

    def _alerts_page(self):
        page = self.pages["ALERTS"]
        self._label(page, "Alert rules", 16).pack(anchor="w", pady=(5, 4))
        self._label(
            page,
            "Fire a desktop alert when price, RSI, score, ADX, signal, or a "
            "candle pattern matches.",
            10,
            self.MUTED,
        ).pack(anchor="w", pady=(0, 14))
        form = self._panel(page)
        form.pack(fill="x", pady=(0, 12))
        row = tk.Frame(form, bg=self.PANEL)
        row.pack(fill="x", padx=14, pady=12)
        self.rule_symbol = ttk.Combobox(
            row, values=["*", *SYMBOLS.values()], width=14, state="readonly"
        )
        self.rule_symbol.set(SYMBOLS[self.selected])
        self.rule_metric = ttk.Combobox(row, values=METRICS, width=8, state="readonly")
        self.rule_metric.set("rsi")
        self.rule_operator = ttk.Combobox(
            row, values=OPERATORS, width=13, state="readonly"
        )
        self.rule_operator.set(">")
        self.rule_value = tk.Entry(
            row,
            width=12,
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
        )
        self.rule_value.insert(0, "70")
        for widget in (
            self.rule_symbol,
            self.rule_metric,
            self.rule_operator,
            self.rule_value,
        ):
            widget.pack(side="left", padx=(0, 8), ipady=3)
        tk.Button(
            row,
            text="Add rule",
            command=self._add_rule,
            bg=self.CYAN,
            fg=self.BG,
            relief="flat",
            font=("Helvetica", 9, "bold"),
            padx=12,
        ).pack(side="left")
        tk.Button(
            row,
            text="Remove selected",
            command=self._remove_rule,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=12,
        ).pack(side="right")
        self.rule_status = self._label(
            form,
            "Signal / pattern rules use ==, e.g. signal == STRONG BUY",
            9,
            self.MUTED,
        )
        self.rule_status.pack(anchor="w", padx=14, pady=(0, 10))
        body = tk.Frame(page, bg=self.BG)
        body.pack(fill="both", expand=True)
        self.rules_list = tk.Listbox(
            body, bg=self.PANEL, fg=self.TEXT, relief="flat", font=("Courier", 10)
        )
        self.rules_list.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.alert_log = tk.Listbox(
            body, bg=self.PANEL, fg=self.GREEN, relief="flat", font=("Courier", 10)
        )
        self.alert_log.pack(side="left", fill="both", expand=True, padx=(6, 0))
        self.alert_log.insert("end", "Triggered alerts appear here")
        self._render_rules()

    def _render_rules(self):
        self.rules_list.delete(0, "end")
        for rule in self.alert_engine.rules:
            market = SYMBOLS.get(rule.symbol, "All markets")
            state = "" if rule.enabled else " [paused]"
            self.rules_list.insert(
                "end", f"{market:<15} {rule.metric} {rule.operator} {rule.value}{state}"
            )

    def _add_rule(self):
        names = {name: symbol for symbol, name in SYMBOLS.items()}
        try:
            rule = AlertRule(
                symbol=names.get(self.rule_symbol.get(), "*"),
                metric=self.rule_metric.get(),
                operator=self.rule_operator.get(),
                value=self.rule_value.get().strip(),
            )
            rules = [*self.alert_engine.rules, rule]
            self.alert_store.save(rules)
        except (ValueError, TypeError, OSError) as error:
            self.rule_status.config(text=str(error), fg=self.RED)
            return
        self.alert_engine.rules = rules
        self._render_rules()
        self.rule_status.config(text=f"Added: {rule.describe()}", fg=self.GREEN)

    def _remove_rule(self):
        selection = self.rules_list.curselection()
        if not selection:
            return
        rules = [
            rule
            for index, rule in enumerate(self.alert_engine.rules)
            if index != selection[0]
        ]
        try:
            self.alert_store.save(rules)
        except OSError as error:
            self.rule_status.config(text=str(error), fg=self.RED)
            return
        self.alert_engine.rules = rules
        self._render_rules()
        self.rule_status.config(text="Rule removed", fg=self.GREEN)

    def _evaluate_alerts(self, symbol, result, price, patterns):
        fired = self.alert_engine.evaluate(
            symbol,
            result,
            price,
            patterns,
            cooldown_seconds=self.settings.alert_cooldown_seconds,
        )
        if not fired:
            return
        if self.alert_log.get(0) == "Triggered alerts appear here":
            self.alert_log.delete(0)
        stamp = datetime.now().strftime("%H:%M:%S")
        fired_ids = {rule.rule_id for rule in fired if rule.metric == "price"}
        if fired_ids and self.settings.auto_disable_one_shot_price_alerts:
            updated_rules = [
                replace(r, enabled=False) if r.rule_id in fired_ids else r
                for r in self.alert_engine.rules
            ]
            self.alert_engine.rules = updated_rules
            try:
                self.alert_store.save(updated_rules)
            except OSError:
                pass
            self._render_rules()

        for rule in fired:
            self.alert_log.insert(
                0,
                f"{stamp}  {SYMBOLS[symbol]:<14} {rule.metric} {rule.operator} "
                f"{rule.value}  @ {self._fmt(symbol, price)}",
            )
        self.alert_log.delete(500, "end")
        self.status.config(
            text=f"●  Alert · {SYMBOLS[symbol]} {fired[0].metric}", fg="#f0bd62"
        )
        self._ring_alert_bell()
        if not self._in_quiet_hours():
            for rule in fired:
                self._notify_telegram(
                    f"NEEZY alert · {SYMBOLS[symbol]}\n{rule.describe()}\n"
                    f"Price {self._fmt(symbol, price)} · timeframe {self.tf.get()}"
                )
                if self.settings.dm_enabled and self.settings.dm_notify_alerts:
                    self._dispatch_dm_async(
                        f"🔔 NEEZY Alert · {SYMBOLS[symbol]}",
                        rule.describe(),
                        "warning",
                        {
                            "Market": SYMBOLS[symbol],
                            "Price": self._fmt(symbol, price),
                            "Timeframe": self.tf.get(),
                        },
                    )

    def _notify_telegram(self, text):
        if (
            self.settings.telegram_alerts_enabled
            and self.telegram_service is not None
            and self.telegram_service.running
        ):
            self.telegram_service.notify(text)
