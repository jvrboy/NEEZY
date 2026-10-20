#!/usr/bin/env python3
"""NEEZY native trading workspace; live prices are supplied by Deriv's public API.

The application displays educational technical-analysis summaries only. It does
not place trades, and its signals are not investment advice.
"""

from __future__ import annotations

import logging
import math
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from neezy_backend.config import AppSettings
from neezy_backend.events import EventBus
from neezy_backend.indicators import analyze
from neezy_backend.storage import SettingsStore, SignalHistoryStore
from neezy_backend.stream import DerivStreamClient

logger = logging.getLogger(__name__)
APP_ID = 1089
WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
SYMBOLS = {
    "frxEURUSD": "EUR/USD",
    "frxGBPUSD": "GBP/USD",
    "frxUSDJPY": "USD/JPY",
    "frxAUDUSD": "AUD/USD",
    "frxUSDCAD": "USD/CAD",
    "frxUSDCHF": "USD/CHF",
    "frxNZDUSD": "NZD/USD",
    "frxEURGBP": "EUR/GBP",
    "frxEURJPY": "EUR/JPY",
    "frxGBPJPY": "GBP/JPY",
    "R_100": "Volatility 100",
}
TIMEFRAMES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}
HISTORY = 300


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
        self.bus = EventBus(subscriber_queue_size=2500)
        self.inbox = self.bus.subscribe()
        self.client = DerivStreamClient(WS_URL, self.bus)
        self.gran = 300
        self.candles = {}
        self.results = {}
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
        for name in ["CHAT", "SYMBOLS", "CHART", "SIGNALS", "HISTORY", "SETTINGS"]:
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
                pady=13,
            )
            b.pack(fill="x", padx=10, pady=2)
            self.nav[name] = b
        self.nav["SIGNALS"].configure(fg=self.CYAN, bg=self.PANEL2)
        tk.Label(
            side,
            text="LIVE FEED",
            bg=side.cget("bg"),
            fg=self.MUTED,
            font=("Helvetica", 8, "bold"),
        ).pack(anchor="w", padx=23, pady=(45, 8))
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
        for name in ["CHAT", "SYMBOLS", "CHART", "SIGNALS", "HISTORY", "SETTINGS"]:
            page = tk.Frame(self.nb, bg=self.BG)
            self.nb.add(page, text=name)
            self.pages[name] = page
        self._signals_page()
        self._symbols_page()
        self._chart_page()
        self._chat_page()
        self._history_page()
        self._settings_page()
        self.nb.select(3)

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
        self.tf.set("5m")
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
        cols = ("pair", "price", "signal", "score", "rsi", "updated")
        self.tree = ttk.Treeview(left, columns=cols, show="headings")
        for c, t, w in [
            ("pair", "MARKET", 170),
            ("price", "PRICE", 100),
            ("signal", "BIAS", 120),
            ("score", "SCORE", 65),
            ("rsi", "RSI", 60),
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
                "", "end", iid=s, values=(n, "—", "Loading", "—", "—", "—")
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

    def _settings_page(self):
        page = self.pages["SETTINGS"]
        self._label(page, "Workspace settings", 16).pack(anchor="w", pady=(5, 4))
        self._label(
            page, "Tune the workspace without leaving your market view.", 10, self.MUTED
        ).pack(anchor="w", pady=(0, 16))
        grid = tk.Frame(page, bg=self.BG)
        grid.pack(fill="both", expand=True)
        left, right = self._panel(grid), self._panel(grid)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        right.pack(side="right", fill="both", expand=True, padx=(10, 0))
        self._label(left, "LIVE WORKSPACE", 9, self.CYAN).pack(
            anchor="w", padx=18, pady=(18, 12)
        )
        for text, variable in [
            ("Auto-refresh signal feed", self.auto_refresh),
            ("Desktop signal alerts", self.alerts_enabled),
            ("Compact data density", self.compact_mode),
        ]:
            tk.Checkbutton(
                left,
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
            ).pack(fill="x", padx=14, pady=7)
        self._label(left, "Theme preset", 10, self.MUTED).pack(
            anchor="w", padx=18, pady=(18, 4)
        )
        theme = ttk.Combobox(
            left,
            textvariable=self.theme_var,
            values=["Liquid dark", "Midnight blue", "High contrast"],
            state="readonly",
        )
        theme.pack(fill="x", padx=18, pady=(0, 18))
        theme.bind("<<ComboboxSelected>>", lambda _: self._settings_changed())
        self._label(left, "STREAM CONTROLS", 9, self.CYAN).pack(
            anchor="w", padx=18, pady=(8, 12)
        )
        self._label(left, "UI poll interval (ms)", 10, self.MUTED).pack(
            anchor="w", padx=18, pady=(0, 4)
        )
        tk.Spinbox(
            left,
            from_=50,
            to=2000,
            increment=50,
            textvariable=self.polling_var,
            bg=self.PANEL2,
            fg=self.TEXT,
            buttonbackground=self.PANEL2,
            relief="flat",
            command=self._settings_changed,
        ).pack(fill="x", padx=18, pady=(0, 10))
        self._label(left, "Max candles in memory", 10, self.MUTED).pack(
            anchor="w", padx=18, pady=(0, 4)
        )
        tk.Spinbox(
            left,
            from_=60,
            to=1000,
            increment=20,
            textvariable=self.candle_limit_var,
            bg=self.PANEL2,
            fg=self.TEXT,
            buttonbackground=self.PANEL2,
            relief="flat",
            command=self._settings_changed,
        ).pack(fill="x", padx=18, pady=(0, 18))
        self._label(left, "Alert score threshold", 10, self.MUTED).pack(
            anchor="w", padx=18, pady=(0, 4)
        )
        tk.Spinbox(
            left,
            from_=1,
            to=4,
            increment=1,
            textvariable=self.alert_min_score_var,
            bg=self.PANEL2,
            fg=self.TEXT,
            buttonbackground=self.PANEL2,
            relief="flat",
            command=self._settings_changed,
        ).pack(fill="x", padx=18, pady=(0, 18))
        self._label(right, "ENGINE & CONNECTION", 9, self.CYAN).pack(
            anchor="w", padx=18, pady=(18, 12)
        )
        self._label(right, "Deriv public WebSocket", 12).pack(
            anchor="w", padx=18, pady=(4, 2)
        )
        self.connection_detail = self._label(
            right, "App ID 1089 · awaiting connection", 10, self.MUTED
        )
        self.connection_detail.pack(anchor="w", padx=18, pady=(0, 18))
        self._label(right, "Signal engine", 12).pack(anchor="w", padx=18, pady=(4, 2))
        self._label(right, "EMA 9/21/50 · RSI 14 · ATR 14 · MACD", 10, self.MUTED).pack(
            anchor="w", padx=18, pady=(0, 18)
        )
        tk.Button(
            right,
            text="Export signal history as CSV",
            command=self._export_history,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=12,
            pady=8,
        ).pack(anchor="w", padx=18, pady=(4, 10))
        tk.Button(
            right,
            text="Clear local signal history",
            command=self._clear_history,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=12,
            pady=8,
        ).pack(anchor="w", padx=18, pady=(4, 10))
        self.settings_status = self._label(
            right, "Settings are saved locally", 10, self.GREEN
        )
        self.settings_status.pack(anchor="w", padx=18, pady=(12, 0))

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
            )
            self.settings_store.save(candidate)
        except (ValueError, tk.TclError, OSError) as error:
            self.settings_status.config(text=str(error), fg=self.RED)
            return
        should_refresh = not self.settings.auto_refresh and candidate.auto_refresh
        self.settings = candidate
        self._apply_theme()
        if should_refresh:
            for symbol in self.candles:
                self._refresh(symbol)
        self.status_var.set("Settings saved")
        self.settings_status.config(
            text=(
                f"Saved · {candidate.polling_ms} ms · {candidate.candle_limit} candles"
            ),
            fg=self.GREEN,
        )

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
                    "count": HISTORY,
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
        try:
            if msg.get("msg_type") == "candles":
                rows = msg.get("candles", [])
                self.candles[symbol] = [self._parse_candle(candle) for candle in rows]
                self.candles[symbol] = self.candles[symbol][
                    -self.settings.candle_limit :
                ]
                if self.settings.auto_refresh:
                    self._refresh(symbol)
            elif msg.get("msg_type") == "ohlc" and isinstance(ohlc, dict):
                row = self._parse_candle(ohlc, time_key="open_time")
                current = self.candles.setdefault(symbol, [])
                if current and current[-1][0] == row[0]:
                    current[-1] = row
                else:
                    current.append(row)
                del current[: -self.settings.candle_limit]
                if self.settings.auto_refresh:
                    self._refresh(symbol)
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            logger.warning("Ignoring invalid candle payload for %s: %s", symbol, error)

    @staticmethod
    def _parse_candle(candle, time_key="epoch"):
        timestamp = int(candle[time_key])
        values = [float(candle[name]) for name in ("open", "high", "low", "close")]
        if not all(math.isfinite(value) and value > 0 for value in values):
            raise ValueError("OHLC prices must be finite positive numbers")
        open_, high, low, close = values
        if high < max(open_, close) or low > min(open_, close) or high < low:
            raise ValueError("inconsistent OHLC values")
        return (timestamp, open_, high, low, close)

    def _fmt(self, s, p):
        return (
            f"{p:.3f}"
            if "JPY" in s
            else f"{p:.2f}"
            if s.startswith("R_")
            else f"{p:.5f}"
        )

    def _refresh(self, symbol):
        candles = self.candles.get(symbol, [])
        result = analyze(candles)
        if not result:
            return
        self.results[symbol] = result
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
                f"MACD hist {result['macd_histogram']:.6f}\n"
                f"Closed candles {result['closed_candles']}\n\n"
                "Educational summary only — not financial advice.",
            )
        self.detail.config(state="disabled")

    def _draw_chart(self):
        if not hasattr(self, "canvas"):
            return
        self.canvas.delete("all")
        cs = self.candles.get(self.selected, [])[-80:]
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
        lo = min(x[3] for x in cs)
        hi = max(x[2] for x in cs)
        span = hi - lo or 1
        for i in range(5):
            y = 30 + i * (h - 60) / 4
            self.canvas.create_line(0, y, w, y, fill="#19304b")
            self.canvas.create_text(
                w - 8,
                y,
                text=f"{hi - (span * i / 4):.4f}",
                fill=self.MUTED,
                anchor="e",
                font=("Helvetica", 8),
            )
        step = w / len(cs)
        for i, (_timestamp, o, high, low, c) in enumerate(cs):
            x = step * i + step / 2
            yo = h - 30 - (o - lo) / span * (h - 60)
            yc = h - 30 - (c - lo) / span * (h - 60)
            yh = h - 30 - (high - lo) / span * (h - 60)
            yl = h - 30 - (low - lo) / span * (h - 60)
            col = self.GREEN if c >= o else self.RED
            self.canvas.create_line(x, yh, x, yl, fill=col)
            self.canvas.create_rectangle(
                x - 3, min(yo, yc), x + 3, max(yo, yc) + 1, fill=col, outline=col
            )

    def _ask(self):
        question = self.prompt.get().strip()
        if not question:
            return
        result = self.results.get(self.selected)
        if result:
            answer = (
                f"{SYMBOLS[self.selected]} is currently {result['signal']} "
                f"(score {result['score']:+d}/4, {result['trend'].lower()} trend, "
                f"RSI {result['rsi']:.1f}, ATR {result['atr_pct']:.2f}%). "
                f"The signal uses {', '.join(result['why'])}. "
                "Treat this as an educational "
                "indicator summary, not a forecast or recommendation."
            )
        else:
            answer = (
                f"{SYMBOLS[self.selected]} is still collecting enough "
                "closed candles for analysis."
            )
        self.chat.insert("end", f"\nYOU\n{question}\n\nNEEZY\n{answer}\n")
        self.chat.see("end")
        self.prompt.delete(0, "end")

    def _on_prompt_key(self, event):
        if event.keysym == "Return":
            self._ask()
            return "break"
        return None

    def _close(self):
        self.client.stop()
        self.bus.unsubscribe(self.inbox)
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
