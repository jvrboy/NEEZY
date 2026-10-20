#!/usr/bin/env python3
"""NEEZY native trading workspace; live prices are supplied by Deriv's public API.

The application displays educational technical-analysis summaries only. It does
not place trades, and its signals are not investment advice.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from neezy_backend.ai import (
    PROVIDERS,
    AIClient,
    AIError,
    AIKeyStore,
    free_models,
)
from neezy_backend.alerts import (
    METRICS,
    OPERATORS,
    AlertEngine,
    AlertRule,
    AlertRuleStore,
)
from neezy_backend.analytics import (
    correlation_matrix,
    rank_opportunities,
    strongest_pairs,
)
from neezy_backend.backtest import BacktestConfig, run_backtest
from neezy_backend.config import AppSettings
from neezy_backend.context import chat_messages, format_context, market_snapshot
from neezy_backend.database import LocalDatabase
from neezy_backend.events import EventBus
from neezy_backend.indicators import analyze, ema
from neezy_backend.markets import (
    APP_ID,
    SYMBOLS,
    TIMEFRAMES,
    format_price,
    ws_urls,
)
from neezy_backend.patterns import price_action_summary
from neezy_backend.risk import atr_levels, position_size
from neezy_backend.storage import SettingsStore, SignalHistoryStore
from neezy_backend.strategies import (
    STRATEGIES,
    consensus,
    run_all,
)
from neezy_backend.stream import DerivStreamClient, fetch_candles, parse_candle

logger = logging.getLogger(__name__)
NAV = ["CHAT", "SYMBOLS", "CHART", "SIGNALS", "TOOLS", "ALERTS", "HISTORY", "SETTINGS"]


class App(tk.Tk):
    BG = "#08111f"
    PANEL = "#101d30"
    PANEL2 = "#14253b"
    TEXT = "#e6f0ff"
    MUTED = "#8ea4bd"
    CYAN = "#55d6ff"
    GREEN = "#48e6a1"
    RED = "#ff718c"
    BORDER = "#203754"

    def __init__(self):
        super().__init__()
        self.title("NEEZY / Market Intelligence")
        self.geometry("1280x800")
        self.minsize(1050, 650)
        self.settings_store = SettingsStore()
        self.history_store = SignalHistoryStore()
        self.settings = self.settings_store.load()
        self.db = self._open_database()
        self.ai_keys = AIKeyStore()
        self.ai_client = AIClient(
            self.ai_keys,
            recorder=self.db.record_ai_call if self.db is not None else None,
        )
        self._snapshot_at = {}
        self._ai_key_rows = []
        self.bus = EventBus(subscriber_queue_size=2500)
        self.inbox = self.bus.subscribe()
        self.client = DerivStreamClient(
            ws_urls(self.settings.deriv_endpoint),
            self.bus,
            reconnect_seconds=self.settings.reconnect_seconds,
            max_reconnect_seconds=self.settings.max_reconnect_seconds,
        )
        self.alert_store = AlertRuleStore()
        self.alert_engine = AlertEngine(self.alert_store.load())
        self.gran = TIMEFRAMES[self.settings.default_timeframe]
        self.candles = {}
        self.results = {}
        self.price_action = {}
        self._backtest_running = False
        self.last_signal = {}
        self.selected = "frxEURUSD"
        self.history = self.history_store.read(limit=1000)
        self.auto_refresh = tk.BooleanVar(value=self.settings.auto_refresh)
        self.compact_mode = tk.BooleanVar(value=self.settings.compact_mode)
        self.alerts_enabled = tk.BooleanVar(value=self.settings.alerts_enabled)
        self.theme_var = tk.StringVar(value=self.settings.theme)
        self.polling_var = tk.IntVar(value=self.settings.polling_ms)
        self.candle_limit_var = tk.IntVar(value=self.settings.candle_limit)
        self.alert_min_score_var = tk.IntVar(value=self.settings.alert_min_score)
        self.default_tf_var = tk.StringVar(value=self.settings.default_timeframe)
        self.history_var = tk.IntVar(value=self.settings.history_candles)
        self.endpoint_var = tk.StringVar(value=self.settings.deriv_endpoint)
        self.reconnect_var = tk.DoubleVar(value=self.settings.reconnect_seconds)
        self.max_reconnect_var = tk.DoubleVar(value=self.settings.max_reconnect_seconds)
        self.strategy_var = tk.StringVar(value=self.settings.strategy)
        self.st_period_var = tk.IntVar(value=self.settings.supertrend_period)
        self.st_mult_var = tk.DoubleVar(value=self.settings.supertrend_multiplier)
        self.div_lookback_var = tk.IntVar(value=self.settings.divergence_lookback)
        self.corr_window_var = tk.IntVar(value=self.settings.correlation_window)
        self.corr_baseline_var = tk.IntVar(value=self.settings.correlation_baseline)
        self.overlay_var = tk.BooleanVar(value=self.settings.show_strategy_overlay)
        self.store_candles_var = tk.BooleanVar(value=self.settings.store_candles)
        self.retention_var = tk.IntVar(value=self.settings.retention_days)
        self.snapshots_var = tk.BooleanVar(value=self.settings.save_snapshots)
        self.ai_enabled_var = tk.BooleanVar(value=self.settings.ai_enabled)
        self._provider_labels = {
            f"{spec.label} ({spec.key})": spec.key for spec in PROVIDERS.values()
        }
        self.ai_provider_var = tk.StringVar(
            value=self._provider_label(self.settings.ai_provider)
        )
        self.ai_model_var = tk.StringVar(
            value=self.settings.ai_model or free_models(self.settings.ai_provider)[0]
        )
        self.ai_base_var = tk.StringVar(value=self.settings.ai_base_url)
        self.ai_temp_var = tk.DoubleVar(value=self.settings.ai_temperature)
        self.ai_tokens_var = tk.IntVar(value=self.settings.ai_max_tokens)
        self.ai_timeout_var = tk.DoubleVar(value=self.settings.ai_timeout)
        self.ai_system_var = tk.StringVar(value=self.settings.ai_system_prompt)
        self._ai_testing = False
        self.status_var = tk.StringVar(value="Ready")
        self.last_message_at = None
        self._apply_theme()
        self._style()
        self._build()
        self._render_history()
        self.client.start()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "TCombobox",
            fieldbackground=self.PANEL2,
            background=self.PANEL2,
            foreground=self.TEXT,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", self.PANEL2)],
            foreground=[("readonly", self.TEXT)],
            selectbackground=[("readonly", self.PANEL2)],
            selectforeground=[("readonly", self.TEXT)],
        )
        style.configure(
            "Treeview",
            background=self.PANEL,
            fieldbackground=self.PANEL,
            foreground=self.TEXT,
            rowheight=28 if self.settings.compact_mode else 34,
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", "#204467")])
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background=self.PANEL,
            foreground=self.MUTED,
            padding=(18, 10),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.PANEL2)],
            foreground=[("selected", self.CYAN)],
        )

    def _apply_theme(self):
        palettes = {
            "Liquid dark": {
                "BG": "#08111f",
                "PANEL": "#101d30",
                "PANEL2": "#14253b",
                "TEXT": "#e6f0ff",
                "MUTED": "#8ea4bd",
                "CYAN": "#55d6ff",
                "GREEN": "#48e6a1",
                "RED": "#ff718c",
                "BORDER": "#203754",
            },
            "Midnight blue": {
                "BG": "#071522",
                "PANEL": "#10263a",
                "PANEL2": "#17354e",
                "TEXT": "#e7f5ff",
                "MUTED": "#9bb8ca",
                "CYAN": "#64e1ff",
                "GREEN": "#5ce8b2",
                "RED": "#ff8299",
                "BORDER": "#29506b",
            },
            "High contrast": {
                "BG": "#000000",
                "PANEL": "#111111",
                "PANEL2": "#222222",
                "TEXT": "#ffffff",
                "MUTED": "#d2d2d2",
                "CYAN": "#00e5ff",
                "GREEN": "#00ff76",
                "RED": "#ff647c",
                "BORDER": "#777777",
            },
        }
        palette = palettes.get(
            getattr(self, "settings", AppSettings()).theme, palettes["Liquid dark"]
        )
        old = getattr(self, "_active_palette", {})
        for key, value in palette.items():
            setattr(self, key, value)
        if old and hasattr(self, "main"):
            swaps = {old[key]: palette[key] for key in old}
            for widget in self._walk_widgets(self):
                for option in (
                    "background",
                    "foreground",
                    "activebackground",
                    "activeforeground",
                    "selectcolor",
                    "insertbackground",
                ):
                    try:
                        current = widget.cget(option)
                        if current in swaps:
                            widget.configure(**{option: swaps[current]})
                    except (tk.TclError, TypeError):
                        pass
            self.canvas.configure(
                bg="#0c192b" if self.theme_var.get() != "High contrast" else "#050505"
            )
        self._active_palette = palette
        self.configure(bg=self.BG)
        if hasattr(self, "main"):
            self._style()

    @staticmethod
    def _walk_widgets(parent):
        for child in parent.winfo_children():
            yield child
            yield from App._walk_widgets(child)

    def _label(self, p, text, size=10, color=None, **kw):
        return tk.Label(
            p,
            text=text,
            bg=p.cget("bg"),
            fg=color or self.TEXT,
            font=("Helvetica", size),
            **kw,
        )

    def _panel(self, p):
        return tk.Frame(
            p, bg=self.PANEL, highlightbackground=self.BORDER, highlightthickness=1
        )

    def _build(self):
        self._sidebar()
        self.main = tk.Frame(self, bg=self.BG)
        self.main.pack(side="left", fill="both", expand=True)
        self._header()
        self._tabs()

    def _sidebar(self):
        side = tk.Frame(self, bg=self.BG, width=220)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(
            side,
            text="N",
            bg=self.CYAN,
            fg=self.BG,
            font=("Helvetica", 20, "bold"),
            width=2,
            height=1,
        ).pack(anchor="w", padx=22, pady=(25, 8))
        tk.Label(
            side,
            text="NEEZY",
            bg=side.cget("bg"),
            fg=self.TEXT,
            font=("Helvetica", 16, "bold"),
        ).pack(anchor="w", padx=22)
        tk.Label(
            side,
            text="MARKET INTELLIGENCE",
            bg=side.cget("bg"),
            fg=self.MUTED,
            font=("Helvetica", 8),
        ).pack(anchor="w", padx=23, pady=(0, 35))
        self.nav = {}
        for name in NAV:
            b = tk.Button(
                side,
                text="  " + name,
                anchor="w",
                command=lambda n=name: self._tab(n),
                bg=side.cget("bg"),
                fg=self.MUTED,
                activebackground=self.PANEL2,
                activeforeground=self.CYAN,
                relief="flat",
                bd=0,
                font=("Helvetica", 10, "bold"),
                padx=18,
                pady=9,
            )
            b.pack(fill="x", padx=10, pady=1)
            self.nav[name] = b
        self.nav["SIGNALS"].configure(fg=self.CYAN, bg=self.PANEL2)
        tk.Label(
            side,
            text="LIVE FEED",
            bg=side.cget("bg"),
            fg=self.MUTED,
            font=("Helvetica", 8, "bold"),
        ).pack(anchor="w", padx=23, pady=(28, 8))
        self.conn = tk.Label(
            side,
            text="●  Connecting",
            bg=side.cget("bg"),
            fg="#f0bd62",
            font=("Helvetica", 10),
        )
        self.conn.pack(anchor="w", padx=23)
        tk.Label(
            side,
            text="Educational tool · not financial advice",
            wraplength=170,
            justify="left",
            bg=side.cget("bg"),
            fg="#577089",
            font=("Helvetica", 8),
        ).pack(side="bottom", anchor="w", padx=23, pady=25)

    def _header(self):
        h = tk.Frame(self.main, bg=self.BG)
        h.pack(fill="x", padx=28, pady=(25, 18))
        self._label(h, "SIGNALS OVERVIEW", 19, "#ffffff").pack(side="left")
        self._label(h, "  Live market workspace", 10, self.MUTED).pack(
            side="left", pady=5
        )
        self.status = self._label(h, "●  Connecting", 10, "#f0bd62")
        self.status.pack(side="right")

    def _tabs(self):
        self.nb = ttk.Notebook(self.main)
        self.nb.pack(fill="both", expand=True, padx=28, pady=(0, 28))
        self.pages = {}
        for name in NAV:
            page = tk.Frame(self.nb, bg=self.BG)
            self.nb.add(page, text=name)
            self.pages[name] = page
        self._signals_page()
        self._symbols_page()
        self._chart_page()
        self._chat_page()
        self._tools_page()
        self._alerts_page()
        self._history_page()
        self._settings_page()
        self.nb.select(self.pages["SIGNALS"])

    def _tab(self, name):
        self.nb.select(self.pages[name])
        for button in self.nav.values():
            button.configure(fg=self.MUTED, bg=self.BG)
        self.nav[name].configure(fg=self.CYAN, bg=self.PANEL2)

    def _signals_page(self):
        p = self.pages["SIGNALS"]
        top = tk.Frame(p, bg=self.BG)
        top.pack(fill="x", pady=(0, 12))
        self._label(top, "Signal monitor", 12, "#ffffff").pack(side="left")
        self._label(
            top, "  Closed-candle confirmation · no repainting", 9, self.MUTED
        ).pack(side="left", pady=2)
        self.signal_cards = tk.Frame(p, bg=self.BG)
        self.signal_cards.pack(fill="x", pady=(0, 12))
        self.card_values = {}
        for key, title, accent in [
            ("active", "ACTIVE SETUPS", self.CYAN),
            ("buy", "BUY BIAS", self.GREEN),
            ("sell", "SELL BIAS", self.RED),
            ("confidence", "AVG SCORE", self.MUTED),
        ]:
            card = self._panel(self.signal_cards)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            self._label(card, title, 8, self.MUTED).pack(
                anchor="w", padx=14, pady=(10, 2)
            )
            v = self._label(card, "—", 18, accent)
            v.pack(anchor="w", padx=14, pady=(0, 10))
            self.card_values[key] = v
        self.tf = ttk.Combobox(top, values=list(TIMEFRAMES), width=7, state="readonly")
        self.tf.set(self.settings.default_timeframe)
        self.tf.pack(side="right")
        self.tf.bind("<<ComboboxSelected>>", lambda e: self._tf_changed())
        body = tk.Frame(p, bg=self.BG)
        body.pack(fill="both", expand=True)
        left = self._panel(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 12))
        right = self._panel(body)
        right.pack(side="right", fill="both", expand=False)
        right.configure(width=320)
        right.pack_propagate(False)
        cols = ("pair", "price", "signal", "score", "rsi", "regime", "updated")
        self.tree = ttk.Treeview(left, columns=cols, show="headings")
        for c, t, w in [
            ("pair", "MARKET", 170),
            ("price", "PRICE", 100),
            ("signal", "BIAS", 120),
            ("score", "SCORE", 65),
            ("rsi", "RSI", 60),
            ("regime", "REGIME", 90),
            ("updated", "UPDATED", 80),
        ]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="center" if c != "pair" else "w")
        self.tree.tag_configure("buy", foreground=self.GREEN)
        self.tree.tag_configure("sell", foreground=self.RED)
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._select())
        for s, n in SYMBOLS.items():
            self.tree.insert(
                "", "end", iid=s, values=(n, "—", "Loading", "—", "—", "—", "—")
            )
        self.detail = tk.Text(
            right,
            bg=self.PANEL,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
            wrap="word",
            font=("Helvetica", 10),
            padx=18,
            pady=18,
        )
        self.detail.tag_configure("big", font=("Helvetica", 22, "bold"))
        self.detail.tag_configure("buy", foreground=self.GREEN)
        self.detail.tag_configure("sell", foreground=self.RED)
        self.detail.pack(fill="both", expand=True)

    def _symbols_page(self):
        p = self.pages["SYMBOLS"]
        self._label(p, "Market watchlist", 16).pack(anchor="w", pady=(5, 16))
        self._label(
            p, "Select a market to focus the chart and signal detail.", 10, self.MUTED
        ).pack(anchor="w", pady=(0, 18))
        self.watch = tk.Listbox(
            p,
            bg=self.PANEL,
            fg=self.TEXT,
            selectbackground="#204467",
            relief="flat",
            font=("Helvetica", 12),
            height=15,
        )
        self.watch.pack(fill="both", expand=True)
        [self.watch.insert("end", f"  {n:<22}  {s}") for s, n in SYMBOLS.items()]
        self.watch.bind("<<ListboxSelect>>", lambda e: self._watch_select())

    def _chart_page(self):
        p = self.pages["CHART"]
        bar = tk.Frame(p, bg=self.BG)
        bar.pack(fill="x", pady=(5, 12))
        self.chart_title = self._label(bar, "EUR/USD  ·  5m", 16)
        self.chart_title.pack(side="left")
        self._label(bar, "TradingView-style canvas", 9, self.MUTED).pack(
            side="left", padx=12
        )
        self.canvas = tk.Canvas(
            p, bg="#0c192b", highlightthickness=1, highlightbackground=self.BORDER
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw_chart())

    def _chat_page(self):
        p = self.pages["CHAT"]
        self._label(p, "Market copilot", 16).pack(anchor="w", pady=(5, 4))
        self._label(
            p, "Ask for a concise read on the active market.", 10, self.MUTED
        ).pack(anchor="w", pady=(0, 15))
        self.chat = tk.Text(
            p,
            bg=self.PANEL,
            fg=self.TEXT,
            relief="flat",
            font=("Helvetica", 11),
            padx=18,
            pady=15,
        )
        self.chat.pack(fill="both", expand=True)
        self.chat.insert(
            "end",
            "NEEZY  ·  Copilot\n\nSelect a market and ask a question below. "
            "I'll use the live signal context.\n",
            ("intro",),
        )
        self.chat.tag_configure("intro", foreground=self.MUTED)
        row = tk.Frame(p, bg=self.BG)
        row.pack(fill="x", pady=(12, 0))
        self.prompt = tk.Entry(
            row,
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
            font=("Helvetica", 11),
        )
        self.prompt.pack(side="left", fill="x", expand=True, ipady=10)
        self.prompt.bind("<Return>", self._on_prompt_key)
        tk.Button(
            row,
            text="Ask",
            command=self._ask,
            bg=self.CYAN,
            fg=self.BG,
            relief="flat",
            font=("Helvetica", 10, "bold"),
            padx=22,
            pady=9,
        ).pack(side="right", padx=(10, 0))

    def _field(self, parent, label, variable, width=10):
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.pack(fill="x", padx=16, pady=3)
        self._label(row, label, 9, self.MUTED).pack(side="left")
        tk.Entry(
            row,
            textvariable=variable,
            width=width,
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
            justify="right",
        ).pack(side="right", ipady=3)
        return row

    def _output(self, parent, height=12):
        text = tk.Text(
            parent,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            wrap="word",
            font=("Courier", 9),
            padx=10,
            pady=8,
            height=height,
            width=28,
        )
        text.pack(fill="both", expand=True, padx=16, pady=(8, 16))
        text.insert("end", "—")
        text.config(state="disabled")
        return text

    @staticmethod
    def _write(widget, content):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", content)
        widget.config(state="disabled")

    def _action_button(self, parent, text, command):
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bg=self.CYAN,
            fg=self.BG,
            activebackground=self.PANEL2,
            relief="flat",
            font=("Helvetica", 9, "bold"),
            padx=12,
            pady=6,
        )
        button.pack(anchor="w", padx=16, pady=(8, 0))
        return button

    def _tools_page(self):
        page = self.pages["TOOLS"]
        self._label(page, "Trader toolkit", 16).pack(anchor="w", pady=(5, 4))
        self._label(
            page,
            "Risk planning, walk-forward backtests, and cross-market ranking "
            "for the selected market.",
            10,
            self.MUTED,
        ).pack(anchor="w", pady=(0, 14))
        grid = tk.Frame(page, bg=self.BG)
        grid.pack(fill="both", expand=True)
        risk, test, rank = self._panel(grid), self._panel(grid), self._panel(grid)
        for index, panel in enumerate((risk, test, rank)):
            panel.pack(
                side="left", fill="both", expand=True, padx=(0 if index == 0 else 6, 0)
            )

        self._label(risk, "RISK PLANNER", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        self.risk_vars = {
            "balance": tk.StringVar(value="10000"),
            "risk": tk.StringVar(value="1.0"),
            "stop_atr": tk.StringVar(value="1.5"),
            "reward": tk.StringVar(value="2.0"),
            "pip_value": tk.StringVar(value="10"),
        }
        for key, label in [
            ("balance", "Account balance"),
            ("risk", "Risk per trade (%)"),
            ("stop_atr", "Stop distance (x ATR)"),
            ("reward", "Reward : risk"),
            ("pip_value", "Pip value / lot"),
        ]:
            self._field(risk, label, self.risk_vars[key])
        self._action_button(risk, "Plan selected market", self._plan_risk)
        self.risk_out = self._output(risk)

        self._label(test, "BACKTEST", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        self.test_vars = {
            "min_score": tk.StringVar(value="2"),
            "stop_atr": tk.StringVar(value="1.5"),
            "reward": tk.StringVar(value="2.0"),
            "count": tk.StringVar(value="2000"),
        }
        for key, label in [
            ("min_score", "Min score (1-4)"),
            ("stop_atr", "Stop (x ATR)"),
            ("reward", "Reward : risk"),
            ("count", "History candles"),
        ]:
            self._field(test, label, self.test_vars[key])
        buttons = tk.Frame(test, bg=test.cget("bg"))
        buttons.pack(fill="x")
        self._action_button(buttons, "Run on live buffer", self._backtest_buffer)
        self.fetch_button = self._action_button(
            buttons, "Fetch history & run", self._backtest_fetch
        )
        self.test_out = self._output(test)

        self._label(rank, "MARKET RANKING", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        self._action_button(rank, "Refresh ranking", self._refresh_ranking)
        self.rank_out = self._output(rank, height=20)

    def _float_var(self, variables, key, label):
        try:
            return float(variables[key].get())
        except ValueError:
            raise ValueError(f"{label} must be a number") from None

    def _plan_risk(self):
        symbol, result = self.selected, self.results.get(self.selected)
        candles = self.candles.get(symbol, [])
        if not result or not candles or not result.get("atr"):
            self._write(self.risk_out, "Waiting for enough closed candles…")
            return
        try:
            direction = "SELL" if "SELL" in result["signal"] else "BUY"
            entry = candles[-1][4]
            stop, _target = atr_levels(
                direction,
                entry,
                result["atr"],
                self._float_var(self.risk_vars, "stop_atr", "Stop multiple"),
            )
            plan = position_size(
                symbol=symbol,
                balance=self._float_var(self.risk_vars, "balance", "Balance"),
                risk_percent=self._float_var(self.risk_vars, "risk", "Risk"),
                entry=entry,
                stop=stop,
                reward_to_risk=self._float_var(self.risk_vars, "reward", "Reward"),
                pip_value_per_lot=self._float_var(
                    self.risk_vars, "pip_value", "Pip value"
                ),
            )
        except ValueError as error:
            self._write(self.risk_out, f"Check inputs: {error}")
            return
        f = lambda price: self._fmt(symbol, price)  # noqa: E731
        bias = "" if result["signal"] != "NEUTRAL" else " (neutral bias, long shown)"
        self._write(
            self.risk_out,
            f"{SYMBOLS[symbol]} · {plan.direction}{bias}\n\n"
            f"Entry   {f(plan.entry)}\n"
            f"Stop    {f(plan.stop)}  ({plan.stop_pips:.1f} pips)\n"
            f"Target  {f(plan.target)}  ({plan.target_pips:.1f} pips)\n\n"
            f"Size    {plan.lots:.2f} lots\n"
            f"Units   {plan.units:,}\n"
            f"Risk    {plan.risk_amount:,.2f}\n"
            f"Reward  {plan.reward_amount:,.2f}\n\n"
            "Planning aid only; verify with your broker.",
        )

    def _backtest_config(self):
        return BacktestConfig(
            min_score=int(self._float_var(self.test_vars, "min_score", "Min score")),
            stop_atr_multiple=self._float_var(self.test_vars, "stop_atr", "Stop"),
            reward_to_risk=self._float_var(self.test_vars, "reward", "Reward"),
        )

    def _backtest_buffer(self):
        candles = self.candles.get(self.selected, [])[:-1]
        try:
            result = run_backtest(candles, self._backtest_config())
        except ValueError as error:
            self._write(self.test_out, f"Check inputs: {error}")
            return
        self._show_backtest(self.selected, self.tf.get(), result)

    def _backtest_fetch(self):
        if self._backtest_running:
            return
        try:
            config = self._backtest_config()
            count = int(self._float_var(self.test_vars, "count", "Candles"))
            if not 100 <= count <= 5000:
                raise ValueError("History candles must be between 100 and 5000")
        except ValueError as error:
            self._write(self.test_out, f"Check inputs: {error}")
            return
        symbol, timeframe, seconds = self.selected, self.tf.get(), self.gran
        endpoints = ws_urls(self.settings.deriv_endpoint)
        self._backtest_running = True
        self.fetch_button.config(state="disabled")
        self._write(self.test_out, f"Fetching {count} {timeframe} candles…")

        def work():
            try:
                candles = fetch_candles(symbol, seconds, count, url=endpoints)
                result = run_backtest(candles[:-1], config)
                self.bus.publish("backtest", (symbol, timeframe, result))
            except (OSError, RuntimeError, ValueError) as error:
                self.bus.publish("backtest_error", str(error))
            except Exception as error:
                logger.exception("Backtest worker failed")
                self.bus.publish("backtest_error", str(error))

        threading.Thread(target=work, name="neezy-backtest", daemon=True).start()

    def _show_backtest(self, symbol, timeframe, result):
        stats = result.stats
        if not stats["trades"]:
            self._write(
                self.test_out,
                f"No trades in {stats['candles_tested']} candles. Load more "
                "history or lower the minimum score.",
            )
            return
        pf = stats["profit_factor"]
        recent = "\n".join(
            f"  {t.direction:<4} {t.reason:<15} {t.r_multiple:+.2f}R"
            for t in result.trades[-6:]
        )
        self._write(
            self.test_out,
            f"{SYMBOLS[symbol]} · {timeframe} · {stats['candles_tested']} candles\n\n"
            f"Trades        {stats['trades']} "
            f"({stats['long_trades']}L/{stats['short_trades']}S)\n"
            f"Win rate      {stats['win_rate']:.1f}%\n"
            f"Total         {stats['total_r']:+.2f} R\n"
            f"Expectancy    {stats['expectancy_r']:+.3f} R\n"
            f"Profit factor {'inf' if pf == float('inf') else f'{pf:.2f}'}\n"
            f"Max drawdown  {stats['max_drawdown_r']:.2f} R\n"
            f"Sharpe/trade  {stats['sharpe_per_trade']:.2f}\n\n"
            f"Recent trades\n{recent}\n\n"
            "Simulated; past results do not predict future results.",
        )

    def _refresh_ranking(self):
        if not self.results:
            self._write(self.rank_out, "Collecting live candles…")
            return
        lines = ["TOP SETUPS"]
        for item in rank_opportunities(self.results, include_neutral=True):
            lines.append(
                f"  {SYMBOLS[item['symbol']]:<15}{item['signal']:<12}"
                f"{item['opportunity']:>5.1f}"
            )
        closes = {s: [row[4] for row in c[:-1]] for s, c in self.candles.items()}
        pairs = strongest_pairs(correlation_matrix(closes, window=100), limit=6)
        lines.append("\nSTRONGEST CORRELATIONS")
        lines.extend(
            f"  {SYMBOLS[a]} / {SYMBOLS[b]}  {value:+.2f}" for a, b, value in pairs
        )
        lines.append("\nRank 0-100 blends score, ADX, and RSI room.")
        self._write(self.rank_out, "\n".join(lines))

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
            self.rules_list.insert(
                "end", f"{market:<15} {rule.metric} {rule.operator} {rule.value}"
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
        fired = self.alert_engine.evaluate(symbol, result, price, patterns)
        if not fired:
            return
        if self.alert_log.get(0) == "Triggered alerts appear here":
            self.alert_log.delete(0)
        stamp = datetime.now().strftime("%H:%M:%S")
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
        if self.alerts_enabled.get():
            self.bell()

    def _history_page(self):
        page = self.pages["HISTORY"]
        bar = tk.Frame(page, bg=self.BG)
        bar.pack(fill="x", pady=(5, 12))
        self._label(bar, "Signal history", 16).pack(side="left")
        tk.Button(
            bar,
            text="Export CSV",
            command=self._export_history,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=14,
            pady=7,
        ).pack(side="right")
        self.hist = tk.Listbox(
            page, bg=self.PANEL, fg=self.TEXT, relief="flat", font=("Courier", 10)
        )
        self.hist.pack(fill="both", expand=True)

    def _render_history(self):
        if not hasattr(self, "hist"):
            return
        self.hist.delete(0, "end")
        for record in reversed(self.history):
            stamp = record.get("timestamp", "")
            market = SYMBOLS.get(record.get("symbol"), record.get("symbol", "?"))
            self.hist.insert(
                "end",
                f"{stamp[:19]:<19}  {market:<18} "
                f"{record.get('previous', '?')} → {record.get('current', '?')}  "
                f"@ {record.get('price', 0):g}  [{record.get('score', 0):+d}]",
            )

    def _export_history(self):
        destination = filedialog.asksaveasfilename(
            title="Export signal history",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="neezy-signal-history.csv",
        )
        if not destination:
            return
        try:
            count = self.history_store.export_csv(Path(destination))
            self.settings_status.config(text=f"Exported {count} records", fg=self.GREEN)
            messagebox.showinfo(
                "History exported", f"Exported {count} signal-history records."
            )
        except OSError as error:
            logger.exception("Could not export signal history")
            messagebox.showerror("Export failed", str(error))

    def _open_database(self):
        try:
            return LocalDatabase(
                retention_days=self.settings.retention_days,
                store_candles=self.settings.store_candles,
            )
        except (OSError, sqlite3.Error) as error:
            logger.warning("Local database unavailable: %s", error)
            return None

    @staticmethod
    def _provider_label(key):
        for spec in PROVIDERS.values():
            if spec.key == key:
                return f"{spec.label} ({spec.key})"
        return "OpenRouter (openrouter)"

    def _ai_provider_key(self):
        return self._provider_labels.get(self.ai_provider_var.get(), "openrouter")

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
        self._engine_settings_tab(notebook)
        self._local_settings_tab(notebook)
        self._ai_settings_tab(notebook)
        self.settings_status = self._label(
            page, "Settings are saved locally", 10, self.GREEN
        )
        self.settings_status.pack(anchor="w", padx=4, pady=(8, 0))

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
            "Connection fields apply after you restart NEEZY.",
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
            "Everything stays on this PC in %APPDATA%\\NEEZY.\n"
            "Nothing is uploaded. Use NEEZY_HOME to relocate it.",
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

    def _ai_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "AI PROVIDERS")
        self._label(left, "BRING YOUR OWN KEY", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self._check_row(left, "Enable AI answers in CHAT", self.ai_enabled_var)
        self._combo_row(
            left,
            "Provider",
            self.ai_provider_var,
            list(self._provider_labels),
            self._ai_provider_changed,
        )
        self._label(left, "Model (free models only)", 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(6, 3)
        )
        self.ai_model_combo = ttk.Combobox(
            left,
            textvariable=self.ai_model_var,
            values=free_models(self.settings.ai_provider),
            state="readonly",
        )
        self.ai_model_combo.pack(fill="x", padx=16, pady=(0, 4))
        self.ai_model_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._settings_changed()
        )
        self._entry_row(left, "Base URL (blank = provider default)", self.ai_base_var)
        self._spin_row(left, "Temperature x10", self.ai_temp_var, 0.0, 2.0, 0.1)
        self._spin_row(left, "Max reply tokens", self.ai_tokens_var, 64, 8192, 64)
        self._spin_row(left, "Timeout (seconds)", self.ai_timeout_var, 5.0, 300.0, 5.0)
        self._entry_row(left, "System prompt (blank = built-in)", self.ai_system_var)

        self._label(right, "KEY POOL", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self.ai_provider_help = self._label(
            right, "", 9, self.MUTED, justify="left", wraplength=330
        )
        self.ai_provider_help.pack(anchor="w", padx=16, pady=(0, 6))
        self.ai_keys_list = tk.Listbox(
            right,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            height=6,
            selectbackground="#204467",
            font=("Courier", 9),
        )
        self.ai_keys_list.pack(fill="both", expand=True, padx=16, pady=(0, 6))
        row = tk.Frame(right, bg=self.PANEL)
        row.pack(fill="x", padx=16, pady=(0, 4))
        self.ai_key_entry = tk.Entry(
            row,
            show="*",
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
        )
        self.ai_key_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.ai_key_name = tk.Entry(
            row,
            width=12,
            bg=self.PANEL2,
            fg=self.TEXT,
            insertbackground=self.TEXT,
            relief="flat",
        )
        self.ai_key_name.pack(side="right", padx=(6, 0), ipady=4)
        self.ai_key_name.insert(0, "label")
        buttons = tk.Frame(right, bg=self.PANEL)
        buttons.pack(fill="x", padx=16, pady=(0, 4))
        for text, command in [
            ("Add key", self._ai_add_key),
            ("Remove", self._ai_remove_key),
            ("Reset", self._ai_reset_keys),
            ("Test", self._ai_test),
        ]:
            tk.Button(
                buttons,
                text=text,
                command=command,
                bg=self.PANEL2,
                fg=self.TEXT,
                relief="flat",
                padx=10,
                pady=5,
            ).pack(side="left", padx=(0, 6))
        self.ai_status = self._label(
            right,
            "Keys are stored only on this PC.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        )
        self.ai_status.pack(anchor="w", padx=16, pady=(0, 10))
        self._ai_provider_changed(save=False)

    def _strategy_name(self):
        raw = self.strategy_var.get()
        return raw.split("·")[0].strip() or "SUPERTREND"

    def _strategy_description(self):
        spec = STRATEGIES.get(self._strategy_name())
        if spec is None:
            return ""
        return f"{spec.label}: {spec.description}"

    def _strategy_changed(self):
        if hasattr(self, "strategy_help"):
            self.strategy_help.config(text=self._strategy_description())
        self._settings_changed()

    def _scan_strategies(self):
        candles = self.candles.get(self.selected, [])
        if len(candles) < 40:
            self._write(
                self.engine_out,
                f"{SYMBOLS[self.selected]} is still collecting closed candles.",
            )
            return
        signals = run_all(candles)
        verdict = consensus(signals)
        lines = [
            f"{SYMBOLS[self.selected]} · {self.tf.get()} · {len(candles)} candles",
            "",
        ]
        for signal in signals:
            lines.append(
                f"{signal.strategy:<14} {signal.label:<8} "
                f"{signal.confidence:>5.0f}%  {signal.summary}"
            )
        lines.append("")
        lines.append(
            f"Consensus {verdict['label']} ({verdict['confidence']:.0f}%) "
            f"- buy {verdict['votes']['buy']}, sell {verdict['votes']['sell']}, "
            f"neutral {verdict['votes']['neutral']}"
        )
        self._write(self.engine_out, "\n".join(lines))

    def _refresh_db_stats(self):
        if self.db is None:
            if hasattr(self, "db_stats_label"):
                self.db_stats_label.config(
                    text="Local database unavailable (check permissions)."
                )
            return
        try:
            stats = self.db.stats()
        except sqlite3.Error as error:
            self.db_stats_label.config(text=f"Database error: {error}")
            return
        counts = stats["counts"]
        self.db_stats_label.config(
            text=(
                f"{stats['path']}\n"
                f"{stats['size_mb']} MB · {stats['journal_mode']} journal\n"
                f"candles {counts['candles']} · signals {counts['signals']} · "
                f"snapshots {counts['snapshots']} · AI calls {counts['ai_calls']}"
            )
        )

    def _export_database(self):
        if self.db is None:
            self.settings_status.config(text="No local database to export", fg=self.RED)
            return
        destination = filedialog.asksaveasfilename(
            title="Export NEEZY database",
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if not destination:
            return
        try:
            counts = self.db.export_json(destination)
        except (OSError, sqlite3.Error) as error:
            logger.exception("Database export failed")
            messagebox.showerror("Export failed", str(error))
            return
        self.settings_status.config(
            text=f"Exported {sum(counts.values())} rows to {destination}", fg=self.GREEN
        )

    def _vacuum_db(self):
        if self.db is None:
            return
        try:
            self.db.vacuum()
        except sqlite3.Error as error:
            self.settings_status.config(text=f"Vacuum failed: {error}", fg=self.RED)
            return
        self._refresh_db_stats()
        self.settings_status.config(text="Database vacuumed", fg=self.GREEN)

    def _prune_db(self):
        if self.db is None:
            return
        try:
            removed = self.db.prune()
        except (sqlite3.Error, ValueError) as error:
            self.settings_status.config(text=f"Prune failed: {error}", fg=self.RED)
            return
        self._refresh_db_stats()
        self.settings_status.config(
            text="Pruned "
            + ", ".join(f"{key} {value}" for key, value in removed.items()),
            fg=self.GREEN,
        )

    def _ai_provider_changed(self, save=True):
        provider_key = self._ai_provider_key()
        spec = PROVIDERS[provider_key]
        models = free_models(provider_key)
        if hasattr(self, "ai_model_combo"):
            self.ai_model_combo.config(values=models)
        if self.ai_model_var.get() not in models:
            self.ai_model_var.set(models[0])
        if hasattr(self, "ai_provider_help"):
            self.ai_provider_help.config(
                text=(
                    f"{spec.label} · free models only\n"
                    f"Get a key: {spec.key_url}\n{spec.notes}"
                )
            )
        self._refresh_ai_keys()
        if save:
            self._settings_changed()

    def _refresh_ai_keys(self):
        if not hasattr(self, "ai_keys_list"):
            return
        provider_key = self._ai_provider_key()
        statuses = self.ai_keys.statuses(provider_key)
        self._ai_key_rows = [(provider_key, status.id) for status in statuses]
        self.ai_keys_list.delete(0, "end")
        if not statuses:
            self.ai_keys_list.insert(
                "end", "No keys yet - paste one below and press Add key"
            )
        for status in statuses:
            state = "ready" if status.usable() else "cooling"
            self.ai_keys_list.insert(
                "end",
                f"{status.label[:14]:<14} {status.hint:<16} "
                f"{state:<8} uses {status.uses}",
            )
        if hasattr(self, "ai_status"):
            usable = sum(1 for status in statuses if status.usable())
            self.ai_status.config(
                text=(
                    f"{len(statuses)} key(s) for {PROVIDERS[provider_key].label}; "
                    f"{usable} usable right now. Rotation is automatic when a key hits "
                    "its quota."
                ),
                fg=self.GREEN if usable else self.MUTED,
            )

    def _ai_add_key(self):
        provider_key = self._ai_provider_key()
        secret = self.ai_key_entry.get().strip()
        label = self.ai_key_name.get().strip()
        if label == "label":
            label = ""
        try:
            status = self.ai_keys.add(provider_key, secret, label)
        except ValueError as error:
            self.ai_status.config(text=str(error), fg=self.RED)
            return
        self.ai_key_entry.delete(0, "end")
        self._refresh_ai_keys()
        self.ai_status.config(
            text=f"Added {status.label} ({status.hint}).", fg=self.GREEN
        )

    def _ai_remove_key(self):
        selection = self.ai_keys_list.curselection()
        if not selection or selection[0] >= len(self._ai_key_rows):
            self.ai_status.config(text="Select a stored key first.", fg=self.RED)
            return
        provider_key, key_id = self._ai_key_rows[selection[0]]
        if self.ai_keys.remove(provider_key, key_id):
            self._refresh_ai_keys()
            self.ai_status.config(text="Key removed.", fg=self.GREEN)

    def _ai_reset_keys(self):
        changed = self.ai_keys.reset(self._ai_provider_key())
        self._refresh_ai_keys()
        self.ai_status.config(
            text=f"Cleared cooldowns on {changed} key(s).", fg=self.GREEN
        )

    def _ai_test(self):
        if self._ai_testing:
            return
        provider_key = self._ai_provider_key()
        if not self.ai_keys.secrets(provider_key):
            self.ai_status.config(
                text="Add at least one key for this provider first.", fg=self.RED
            )
            return
        self._ai_testing = True
        self.ai_status.config(text="Testing provider…", fg=self.MUTED)
        model = self.ai_model_var.get() or None
        base_url = self.ai_base_var.get().strip() or None
        settings = self.settings

        def work():
            try:
                result = self.ai_client.chat(
                    provider_key,
                    [{"role": "user", "content": "Reply with the single word OK."}],
                    model=model,
                    temperature=0.0,
                    max_tokens=16,
                    timeout=min(settings.ai_timeout, 30.0),
                    base_url=base_url,
                    system_prompt="You are a connectivity test. Reply OK.",
                )
                message = (
                    f"OK via {result.key_label} · {result.model} · "
                    f"{result.latency_ms} ms"
                )
                color = self.GREEN
            except (AIError, OSError, ValueError) as error:
                message, color = f"Test failed: {error}", self.RED
            self.after(0, lambda: self._finish_ai_test(message, color))

        threading.Thread(target=work, name="neezy-ai-test", daemon=True).start()

    def _finish_ai_test(self, message, color):
        self._ai_testing = False
        self._refresh_ai_keys()
        self.ai_status.config(text=message, fg=color)

    def _bind_commit(self, widget):
        """Persist typed values too, not only arrow-button changes."""
        widget.bind("<Return>", lambda _: self._settings_changed())
        widget.bind("<FocusOut>", lambda _: self._settings_changed())

    def _update_signal_cards(self):
        vals = list(self.results.values())
        active = [r for r in vals if r["signal"] != "NEUTRAL"]
        buys = sum("BUY" in r["signal"] for r in vals)
        sells = sum("SELL" in r["signal"] for r in vals)
        avg = (sum(abs(r["score"]) for r in vals) / len(vals)) if vals else 0
        for key, value in [
            ("active", str(len(active))),
            ("buy", str(buys)),
            ("sell", str(sells)),
            ("confidence", f"{avg:.1f} / 4"),
        ]:
            self.card_values[key].config(text=value)

    def _settings_changed(self):
        try:
            candidate = self.settings.updated(
                auto_refresh=self.auto_refresh.get(),
                alerts_enabled=self.alerts_enabled.get(),
                compact_mode=self.compact_mode.get(),
                theme=self.theme_var.get(),
                polling_ms=int(self.polling_var.get()),
                candle_limit=int(self.candle_limit_var.get()),
                alert_min_score=int(self.alert_min_score_var.get()),
                default_timeframe=self.default_tf_var.get(),
                history_candles=int(self.history_var.get()),
                deriv_endpoint=self.endpoint_var.get().strip(),
                reconnect_seconds=float(self.reconnect_var.get()),
                max_reconnect_seconds=float(self.max_reconnect_var.get()),
                strategy=self._strategy_name(),
                supertrend_period=int(self.st_period_var.get()),
                supertrend_multiplier=float(self.st_mult_var.get()),
                divergence_lookback=int(self.div_lookback_var.get()),
                correlation_window=int(self.corr_window_var.get()),
                correlation_baseline=int(self.corr_baseline_var.get()),
                show_strategy_overlay=self.overlay_var.get(),
                store_candles=self.store_candles_var.get(),
                retention_days=int(self.retention_var.get()),
                save_snapshots=self.snapshots_var.get(),
                ai_enabled=self.ai_enabled_var.get(),
                ai_provider=self._ai_provider_key(),
                ai_model=self.ai_model_var.get().strip(),
                ai_base_url=self.ai_base_var.get().strip(),
                ai_temperature=float(self.ai_temp_var.get()),
                ai_max_tokens=int(self.ai_tokens_var.get()),
                ai_timeout=float(self.ai_timeout_var.get()),
                ai_system_prompt=self.ai_system_var.get().strip(),
            )
            self.settings_store.save(candidate)
        except (ValueError, tk.TclError, OSError) as error:
            self.settings_status.config(text=str(error), fg=self.RED)
            return
        if self.db is not None:
            self.db.retention_days = candidate.retention_days
            self.db.store_candles = candidate.store_candles
        should_refresh = not self.settings.auto_refresh and candidate.auto_refresh
        restart_needed = (
            candidate.deriv_endpoint,
            candidate.reconnect_seconds,
            candidate.max_reconnect_seconds,
        ) != (
            self.settings.deriv_endpoint,
            self.settings.reconnect_seconds,
            self.settings.max_reconnect_seconds,
        )
        self.settings = candidate
        self._apply_theme()
        if should_refresh:
            for symbol in list(self.candles):
                try:
                    self._refresh(symbol)
                except ValueError as error:
                    logger.warning("Could not refresh %s: %s", symbol, error)
        self.status_var.set("Settings saved")
        summary = (
            f"Saved · {candidate.polling_ms} ms · {candidate.candle_limit} candles"
        )
        if restart_needed:
            summary += " · connection changes apply after restart"
        self.settings_status.config(text=summary, fg=self.GREEN)

    def _clear_history(self):
        try:
            self.history_store.clear()
            self.history.clear()
            self._render_history()
            self.settings_status.config(
                text="Local signal history cleared", fg=self.GREEN
            )
        except OSError as error:
            logger.exception("Could not clear signal history")
            self.settings_status.config(
                text=f"History clear failed: {error}", fg=self.RED
            )

    def _tf_changed(self):
        self.gran = TIMEFRAMES[self.tf.get()]
        self.last_signal.clear()
        self.price_action.clear()
        self.alert_engine.reset()
        self._subscribe_all()
        self.chart_title.config(text=f"{SYMBOLS[self.selected]}  ·  {self.tf.get()}")

    def _select(self):
        s = self.tree.selection()
        if s:
            self.selected = s[0]
            self.chart_title.config(
                text=f"{SYMBOLS[self.selected]}  ·  {self.tf.get()}"
            )
            self._show_detail()
            self._draw_chart()

    def _set_selected(self, symbol):
        self.selected = symbol
        self.chart_title.config(text=f"{SYMBOLS[symbol]}  ·  {self.tf.get()}")
        self._show_detail()
        self._draw_chart()

    def _watch_select(self):
        i = self.watch.curselection()
        if i:
            self.selected = list(SYMBOLS)[i[0]]
            self._tab("CHART")
            self.chart_title.config(
                text=f"{SYMBOLS[self.selected]}  ·  {self.tf.get()}"
            )
            self._draw_chart()

    def _subscribe_all(self):
        self.client.send({"forget_all": "candles"})
        self.candles.clear()
        self.results.clear()
        for symbol in SYMBOLS:
            sent = self.client.send(
                {
                    "ticks_history": symbol,
                    "adjust_start_time": 1,
                    "count": self.settings.history_candles,
                    "end": "latest",
                    "granularity": self.gran,
                    "style": "candles",
                    "subscribe": 1,
                }
            )
            if not sent:
                logger.debug("Subscription queued for next connection: %s", symbol)

    def _poll(self):
        try:
            for event in EventBus.drain(self.inbox, limit=300):
                if event.kind == "connected":
                    self.status.config(text="●  Connected", fg=self.GREEN)
                    self.conn.config(text="●  Live feed", fg=self.GREEN)
                    seen_at = self.last_message_at or "waiting for first update"
                    self.connection_detail.config(text=f"Connected · {seen_at}")
                    self._subscribe_all()
                elif event.kind in {"error", "closed", "reconnecting"}:
                    detail = (
                        event.payload
                        if isinstance(event.payload, str)
                        else event.kind.title()
                    )
                    label = (
                        "Reconnecting…"
                        if event.kind == "reconnecting"
                        else f"●  {detail}"
                    )
                    self.status.config(
                        text=label,
                        fg="#f0bd62" if event.kind == "reconnecting" else self.RED,
                    )
                    self.conn.config(
                        text="●  Reconnecting"
                        if event.kind == "reconnecting"
                        else "●  Offline",
                        fg="#f0bd62" if event.kind == "reconnecting" else self.RED,
                    )
                    self.connection_detail.config(text=str(detail)[:120])
                    if event.kind == "error":
                        logger.warning("Market stream error: %s", detail)
                elif event.kind in {"backtest", "backtest_error"}:
                    self._backtest_running = False
                    self.fetch_button.config(state="normal")
                    if event.kind == "backtest":
                        self._show_backtest(*event.payload)
                    else:
                        self._write(self.test_out, f"Backtest failed: {event.payload}")
                elif event.kind == "message":
                    self.last_message_at = datetime.now().strftime("%H:%M:%S")
                    self._handle(event.payload)
        except tk.TclError:
            return
        if self.winfo_exists():
            self.after(self.settings.polling_ms, self._poll)

    def _handle(self, msg):
        if not isinstance(msg, dict):
            logger.warning(
                "Ignoring unexpected market payload type: %s", type(msg).__name__
            )
            return
        if msg.get("error"):
            error = msg["error"]
            logger.warning("Market API error: %s", error)
            if isinstance(error, dict):
                self.status.config(
                    text=f"API: {error.get('message', 'request failed')}", fg=self.RED
                )
            return
        request = msg.get("echo_req", {})
        if not isinstance(request, dict):
            request = {}
        ohlc = msg.get("ohlc", {})
        symbol = request.get("ticks_history") or (
            ohlc.get("symbol") if isinstance(ohlc, dict) else None
        )
        if symbol not in SYMBOLS:
            return
        # Drop late updates from a previous timeframe's subscription.
        message_gran = (
            ohlc.get("granularity")
            if msg.get("msg_type") == "ohlc" and isinstance(ohlc, dict)
            else request.get("granularity")
        )
        if message_gran is not None and int(message_gran) != self.gran:
            return
        try:
            if msg.get("msg_type") == "candles":
                rows = msg.get("candles", [])
                self.candles[symbol] = [parse_candle(candle) for candle in rows]
                self.candles[symbol] = self.candles[symbol][
                    -self.settings.candle_limit :
                ]
                self._persist_candles(symbol)
                if self.settings.auto_refresh:
                    self._refresh(symbol)
            elif msg.get("msg_type") == "ohlc" and isinstance(ohlc, dict):
                row = parse_candle(ohlc, time_key="open_time")
                current = self.candles.setdefault(symbol, [])
                if current and current[-1][0] == row[0]:
                    current[-1] = row
                else:
                    current.append(row)
                del current[: -self.settings.candle_limit]
                self._persist_candles(symbol)
                if self.settings.auto_refresh:
                    self._refresh(symbol)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            logger.warning("Ignoring invalid candle payload for %s: %s", symbol, error)

    def _persist_candles(self, symbol):
        if self.db is None or not self.settings.store_candles:
            return
        try:
            self.db.save_candles(symbol, self.tf.get(), self.candles.get(symbol, []))
        except (OSError, sqlite3.Error) as error:
            logger.warning("Could not persist candles for %s: %s", symbol, error)

    def _persist_snapshot(self, symbol, result):
        if self.db is None or not self.settings.save_snapshots:
            return
        now = time.monotonic()
        last = self._snapshot_at.get(symbol)
        # monotonic() can be under 60 s on a freshly booted machine, so a
        # symbol with no previous snapshot must not be compared against zero.
        if last is not None and now - last < 60.0:
            return
        self._snapshot_at[symbol] = now
        try:
            self.db.save_snapshot(symbol=symbol, timeframe=self.tf.get(), result=result)
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            logger.warning("Could not persist snapshot for %s: %s", symbol, error)

    def _persist_signal(self, symbol, signal, result, price):
        if self.db is None:
            return
        try:
            strategy = self.settings.strategy
            self.db.save_signal(
                symbol=symbol,
                timeframe=self.tf.get(),
                signal=signal,
                score=result["score"],
                price=price,
                strategy=strategy,
                direction=1 if "BUY" in signal else -1 if "SELL" in signal else 0,
                confidence=abs(result["score"]) / 4.0 * 100.0,
                payload={"regime": result.get("regime"), "rsi": result.get("rsi")},
            )
        except (OSError, sqlite3.Error, TypeError, ValueError) as error:
            logger.warning("Could not persist signal for %s: %s", symbol, error)

    def _fmt(self, s, p):
        return format_price(s, p)

    def _refresh(self, symbol):
        candles = self.candles.get(symbol, [])
        result = analyze(candles)
        if not result:
            return
        self.results[symbol] = result
        self._persist_snapshot(symbol, result)
        action = price_action_summary(candles[:-1])
        self.price_action[symbol] = action
        self._evaluate_alerts(symbol, result, candles[-1][4], action["patterns"])
        signal = result["signal"]
        tag = "buy" if "BUY" in signal else "sell" if "SELL" in signal else ""
        previous = self.last_signal.get(symbol)
        if previous and previous != signal:
            try:
                record = self.history_store.append(
                    symbol=symbol,
                    previous=previous,
                    current=signal,
                    price=candles[-1][4],
                    score=result["score"],
                )
                self._persist_signal(symbol, signal, result, candles[-1][4])
                self.history.append(record)
                self.history = self.history[-1000:]
                self._render_history()
                if (
                    self.alerts_enabled.get()
                    and abs(result["score"]) >= self.settings.alert_min_score
                ):
                    self.bell()
            except OSError as error:
                logger.exception("Could not persist signal transition")
                self.status.config(text=f"History write error: {error}", fg=self.RED)
        self.last_signal[symbol] = signal
        self.tree.item(
            symbol,
            values=(
                SYMBOLS[symbol],
                self._fmt(symbol, candles[-1][4]),
                signal,
                f"{result['score']:+d}",
                f"{result['rsi']:.0f}" if result["rsi"] is not None else "—",
                result.get("regime", "—"),
                datetime.now().strftime("%H:%M:%S"),
            ),
            tags=(tag,) if tag else (),
        )
        self._update_signal_cards()
        if symbol == self.selected:
            self._show_detail()
            self._draw_chart()

    def _show_detail(self):
        symbol = self.selected
        result = self.results.get(symbol)
        candles = self.candles.get(symbol, [])
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        if not result or not candles:
            self.detail.insert("end", "Collecting live candles…")
        else:
            signal = result["signal"]
            tag = "buy" if "BUY" in signal else "sell" if "SELL" in signal else ""
            self.detail.insert("end", f"{SYMBOLS[symbol]}\n")
            self.detail.insert("end", f"{signal}\n", ("big", tag) if tag else ("big",))
            self.detail.insert(
                "end",
                f"Score {result['score']:+d} / 4     "
                f"Price {self._fmt(symbol, candles[-1][4])}\n",
            )
            self.detail.insert(
                "end",
                f"Trend {result['trend']}     "
                f"ATR {self._fmt(symbol, result['atr'])} "
                f"({result['atr_pct']:.2f}%)\n\nWhy this signal\n",
            )
            self.detail.insert(
                "end", "\n".join("  · " + reason for reason in result["why"])
            )
            self.detail.insert(
                "end",
                f"\n\nEMA 9    {self._fmt(symbol, result['ema9'])}\n"
                f"EMA 21   {self._fmt(symbol, result['ema21'])}\n"
                f"EMA 50   {self._fmt(symbol, result['ema50'])}\n"
                f"RSI 14   {result['rsi']:.1f}\n"
                f"MACD hist {result['macd_histogram']:.6f}\n",
            )
            self.detail.insert("end", self._context_text(symbol, result))
            self.detail.insert(
                "end",
                f"Closed candles {result['closed_candles']}\n\n"
                "Educational summary only — not financial advice.",
            )
        self.detail.config(state="disabled")

    def _context_text(self, symbol, result):
        lines = [f"Regime   {result.get('regime', 'Unknown')}"]
        if result.get("adx"):
            d = result["adx"]
            lines.append(
                f"ADX 14   {d['adx']:.1f} (+DI {d['plus_di']:.0f} / -DI "
                f"{d['minus_di']:.0f})"
            )
        if result.get("stochastic"):
            k = result["stochastic"]
            lines.append(f"Stoch    %K {k['k']:.0f} · %D {k['d']:.0f}")
        if result.get("bollinger"):
            b = result["bollinger"]
            lines.append(
                f"Bands    {self._fmt(symbol, b['lower'])} to "
                f"{self._fmt(symbol, b['upper'])} (%B {b['percent_b']:.2f})"
            )
        action = self.price_action.get(symbol) or {}
        if action.get("pivots"):
            p = action["pivots"]
            lines.append(
                f"Pivots   S1 {self._fmt(symbol, p['s1'])} · P "
                f"{self._fmt(symbol, p['pivot'])} · R1 {self._fmt(symbol, p['r1'])}"
            )
        levels = action.get("levels") or {}
        if levels.get("support"):
            lines.append(f"Support  {self._fmt(symbol, levels['support'][0])}")
        if levels.get("resistance"):
            lines.append(f"Resist.  {self._fmt(symbol, levels['resistance'][0])}")
        patterns = action.get("patterns") or []
        if patterns:
            lines.append(
                "Pattern  " + ", ".join(f"{p['name']} ({p['bias']})" for p in patterns)
            )
        return "\n".join(lines) + "\n"

    def _draw_chart(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        visible = 80
        all_candles = self.candles.get(self.selected, [])
        cs = all_candles[-visible:]
        if len(cs) < 2:
            self.canvas.create_text(
                200,
                100,
                text="Waiting for live chart data…",
                fill=self.MUTED,
                anchor="w",
            )
            return
        w = max(self.canvas.winfo_width(), 500)
        h = max(self.canvas.winfo_height(), 300)
        plot_w = w - 70
        closes = [row[4] for row in all_candles]
        ema21 = ema(closes, 21)[-len(cs) :]
        bands = self._band_series(closes, len(cs))
        lo = min([x[3] for x in cs] + [b[1] for b in bands if b])
        hi = max([x[2] for x in cs] + [b[0] for b in bands if b])
        span = hi - lo or 1

        def y_of(price):
            return h - 30 - (price - lo) / span * (h - 60)

        for i in range(5):
            y = 30 + i * (h - 60) / 4
            self.canvas.create_line(0, y, plot_w, y, fill="#19304b")
            self.canvas.create_text(
                w - 8,
                y,
                text=self._fmt(self.selected, hi - (span * i / 4)),
                fill=self.MUTED,
                anchor="e",
                font=("Helvetica", 8),
            )
        step = plot_w / len(cs)
        action = self.price_action.get(self.selected) or {}
        levels = action.get("levels") or {}
        for price, colour in [
            *((level, self.GREEN) for level in levels.get("support", [])[:1]),
            *((level, self.RED) for level in levels.get("resistance", [])[:1]),
        ]:
            if lo <= price <= hi:
                self.canvas.create_line(
                    0, y_of(price), plot_w, y_of(price), fill=colour, dash=(2, 6)
                )
        upper = [(step * i + step / 2, y_of(b[0])) for i, b in enumerate(bands) if b]
        lower = [(step * i + step / 2, y_of(b[1])) for i, b in enumerate(bands) if b]
        for points in (upper, lower):
            if len(points) > 1:
                self.canvas.create_line(
                    *[c for point in points for c in point], fill="#36597d", dash=(4, 3)
                )
        for i, (_timestamp, o, high, low, c) in enumerate(cs):
            x = step * i + step / 2
            yo, yc = y_of(o), y_of(c)
            col = self.GREEN if c >= o else self.RED
            self.canvas.create_line(x, y_of(high), x, y_of(low), fill=col)
            half = max(1.5, min(4.0, step * 0.35))
            self.canvas.create_rectangle(
                x - half, min(yo, yc), x + half, max(yo, yc) + 1, fill=col, outline=col
            )
        ema_points = [
            coordinate
            for i, value in enumerate(ema21)
            for coordinate in (step * i + step / 2, y_of(value))
        ]
        self.canvas.create_line(*ema_points, fill=self.CYAN, width=2, smooth=True)
        last = cs[-1][4]
        self.canvas.create_line(0, y_of(last), plot_w, y_of(last), fill="#f0bd62")
        self.canvas.create_rectangle(
            plot_w, y_of(last) - 9, w, y_of(last) + 9, fill="#f0bd62", outline=""
        )
        self.canvas.create_text(
            w - 6,
            y_of(last),
            text=self._fmt(self.selected, last),
            fill=self.BG,
            anchor="e",
            font=("Helvetica", 8, "bold"),
        )
        self.canvas.create_text(
            10,
            12,
            text="EMA 21   ·   Bollinger 20/2   ·   nearest support / resistance",
            fill=self.MUTED,
            anchor="w",
            font=("Helvetica", 8),
        )

    @staticmethod
    def _band_series(closes, count, period=20, deviations=2.0):
        """Rolling Bollinger (upper, lower) aligned with the last ``count`` bars."""
        series = []
        for end in range(len(closes) - count + 1, len(closes) + 1):
            window = closes[max(0, end - period) : end]
            if len(window) < period:
                series.append(None)
                continue
            mean = sum(window) / period
            spread = (sum((v - mean) ** 2 for v in window) / period) ** 0.5
            series.append((mean + deviations * spread, mean - deviations * spread))
        return series

    def _ask(self):
        question = self.prompt.get().strip()
        if not question:
            return
        self.prompt.delete(0, "end")
        self.chat.insert("end", f"\nYOU\n{question}\n\nNEEZY\n")
        self.chat.see("end")
        if not self.settings.ai_enabled:
            self.chat.insert("end", self._answer(question) + "\n")
            self.chat.see("end")
            return
        provider = self.settings.ai_provider
        if not self.ai_keys.secrets(provider):
            self.chat.insert(
                "end",
                f"No {provider} key is stored yet, so here is the local read. "
                "Add a key in SETTINGS → AI PROVIDERS.\n"
                + self._answer(question)
                + "\n",
            )
            self.chat.see("end")
            return
        snapshot = market_snapshot(
            self.candles.get(self.selected, []),
            symbol=self.selected,
            timeframe=self.tf.get(),
            strategy=self.settings.strategy,
            supertrend_period=self.settings.supertrend_period,
            supertrend_multiplier=self.settings.supertrend_multiplier,
            divergence_lookback=self.settings.divergence_lookback,
        )
        context = format_context(snapshot) if snapshot else "No live context yet."
        messages = chat_messages(question, context)
        self.status_var.set(f"Asking {provider}…")
        settings = self.settings

        def work():
            # Worker thread: no Tk calls here. The local fallback touches
            # widgets (_answer may select a market), so it runs on the main thread.
            try:
                result = self.ai_client.chat(
                    provider,
                    messages,
                    model=settings.ai_model or None,
                    temperature=settings.ai_temperature,
                    max_tokens=settings.ai_max_tokens,
                    timeout=settings.ai_timeout,
                    base_url=settings.ai_base_url or None,
                    system_prompt=settings.ai_system_prompt or None,
                )
                text = (
                    f"{result.text}\n[{result.provider} · {result.model} · "
                    f"key {result.key_label} · {result.latency_ms} ms]"
                )
            except (AIError, OSError, ValueError) as error:
                reason = str(error)
                self.after(
                    0,
                    lambda: self._append_ai(
                        f"AI unavailable ({reason}). Local read instead:\n"
                        f"{self._answer(question)}"
                    ),
                )
                return
            except Exception as error:
                logger.exception("AI request failed")
                text = f"AI request failed: {error}"
            self.after(0, lambda: self._append_ai(text))

        threading.Thread(target=work, name="neezy-ai-chat", daemon=True).start()

    def _append_ai(self, text):
        self.chat.insert("end", text + "\n")
        self.chat.see("end")
        self.status_var.set("AI answer ready")

    def _answer(self, question):
        """Rule-based copilot: route the question to the matching live context."""
        text = question.lower()
        for symbol, name in SYMBOLS.items():
            plain = name.lower().replace("/", "")
            if name.lower() in text or plain in text.replace("/", ""):
                self._set_selected(symbol)
                break
        name = SYMBOLS[self.selected]
        result = self.results.get(self.selected)
        if any(word in text for word in ("best", "rank", "top", "strongest")):
            ranked = rank_opportunities(self.results)[:3]
            if not ranked:
                return "No market has a directional bias right now."
            return "Strongest current setups: " + "; ".join(
                f"{SYMBOLS[i['symbol']]} {i['signal']} (rank {i['opportunity']:.0f})"
                for i in ranked
            )
        if not result:
            return f"{name} is still collecting enough closed candles for analysis."
        action = self.price_action.get(self.selected) or {}
        if any(word in text for word in ("risk", "size", "lot", "stop")):
            self._plan_risk()
            return (
                f"I've planned a {name} position in TOOLS → Risk planner using "
                "an ATR stop. " + self.risk_out.get("1.0", "end").strip()
            )
        if any(word in text for word in ("level", "support", "resist", "pivot")):
            levels = action.get("levels") or {}
            pivots = action.get("pivots") or {}
            sup = ", ".join(
                self._fmt(self.selected, v) for v in levels.get("support", [])
            )
            res = ", ".join(
                self._fmt(self.selected, v) for v in levels.get("resistance", [])
            )
            pivot = self._fmt(self.selected, pivots.get("pivot"))
            return (
                f"{name} swing support: {sup or 'none nearby'}; resistance: "
                f"{res or 'none nearby'}; last-bar pivot {pivot}."
            )
        if "pattern" in text or "candle" in text:
            patterns = action.get("patterns") or []
            if not patterns:
                return f"No notable candlestick pattern on the last closed {name} bar."
            return f"{name} last closed bar: " + ", ".join(
                f"{p['name']} ({p['bias'].lower()})" for p in patterns
            )
        if any(word in text for word in ("trend", "adx", "regime", "volatil")):
            d = result.get("adx") or {}
            return (
                f"{name} regime is {result.get('regime', 'unknown').lower()} with "
                f"ADX {d.get('adx', 0):.1f}; ATR is {result['atr_pct']:.2f}% of "
                f"price and the EMA trend reads {result['trend'].lower()}."
            )
        return (
            f"{name} is currently {result['signal']} "
            f"(score {result['score']:+d}/4, {result['trend'].lower()} trend, "
            f"{result.get('regime', 'unknown').lower()} regime, "
            f"RSI {result['rsi']:.1f}, ATR {result['atr_pct']:.2f}%). "
            f"The signal uses {', '.join(result['why'])}. "
            "Try asking about risk, levels, patterns, trend, or the best setups. "
            "Treat this as an educational indicator summary, not a forecast or "
            "recommendation."
        )

    def _on_prompt_key(self, event):
        if event.keysym == "Return":
            self._ask()
            return "break"
        return None

    def _close(self):
        self.client.stop()
        self.bus.unsubscribe(self.inbox)
        if self.db is not None:
            try:
                self.db.close()
            except sqlite3.Error:
                logger.warning("Could not close the local database cleanly")
        self.destroy()


def main() -> None:
    """Start the desktop event loop."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        app = App()
    except tk.TclError as error:
        raise SystemExit(
            f"NEEZY requires a graphical desktop session: {error}"
        ) from error
    app.mainloop()


if __name__ == "__main__":
    main()
