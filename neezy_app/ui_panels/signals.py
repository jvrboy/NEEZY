"""Signals panels for the NEEZY desktop window."""

from __future__ import annotations

import sqlite3
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from neezy_backend.confluence import resolve_outcome, scan_candles
from neezy_backend.markets import (
    SYMBOLS,
    TIMEFRAMES,
    format_price,
)
from neezy_backend.providers import (
    ProviderError,
    get_candles,
    resolve_provider,
)
from neezy_backend.stream import fetch_candles


class SignalsMixin:
    """Methods for the signals screen; mixed into App."""

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
        cards_outer = tk.Frame(p, bg=self.BG)
        cards_outer.pack(fill="x", pady=(0, 10))
        self.signal_ticket_canvas = tk.Canvas(
            cards_outer,
            bg=self.BG,
            height=174,
            highlightthickness=0,
        )
        self.signal_ticket_frame = tk.Frame(self.signal_ticket_canvas, bg=self.BG)
        self.signal_ticket_canvas.pack(fill="x", expand=True)
        self.signal_ticket_id = self.signal_ticket_canvas.create_window(
            (0, 0),
            window=self.signal_ticket_frame,
            anchor="nw",
        )
        self.signal_ticket_frame.bind(
            "<Configure>",
            lambda _event, c=self.signal_ticket_canvas, f=self.signal_ticket_frame: (
                c.configure(scrollregion=c.bbox("all"))
            ),
        )
        self.signal_ticket_canvas.bind(
            "<Resize>",
            lambda event, c=self.signal_ticket_canvas, i=self.signal_ticket_id: (
                c.itemconfigure(i, width=event.width - 4)
            ),
        )
        self._render_signal_cards([])
        self.analysis_status = self._label(top, "", 9, self.CYAN)
        self.analysis_status.pack(side="right", padx=(0, 12))
        self.analysis_button = tk.Button(
            top,
            text="ANALYSIS",
            command=self._run_analysis,
            bg=self.CYAN,
            fg="#08111f",
            relief="flat",
            padx=18,
            pady=6,
            font=("Helvetica", 10, "bold"),
        )
        self.analysis_button.pack(side="right")
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
        for s, n in self.watch_symbols.items():
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

    def _data_provider_key(self):
        """Translate the DATA PROVIDERS combo label into a provider key."""
        value = self.data_provider_var.get().strip()
        if "(" in value:
            value = value.rsplit("(", 1)[1].rstrip(")")
        try:
            resolve_provider(value)
            return value
        except ValueError:
            return "deriv"

    def _build_signal_card(self, parent, record):
        """Card fields: INSTRUMENT, BUY/SELL, ENTRY, SL, TP, WIN RATE."""
        symbol = record.get("symbol", "")
        instrument = record.get("instrument") or SYMBOLS.get(symbol, symbol)
        direction = int(record.get("direction", 0) or 0)
        label = "BUY" if direction > 0 else "SELL"
        color = self.GREEN if direction > 0 else self.RED
        card = tk.Frame(
            parent,
            bg=self.PANEL2,
            highlightbackground=self.BORDER,
            highlightthickness=1,
        )
        inner = tk.Frame(card, bg=self.PANEL2)
        inner.pack(fill="both", expand=True, padx=14, pady=10)
        self._label(inner, "INSTRUMENT", 8, self.MUTED).pack(anchor="w")
        self._label(inner, instrument, 13, "#ffffff").pack(anchor="w")
        self._label(inner, label, 17, color).pack(anchor="w")
        rows = tk.Frame(inner, bg=self.PANEL2)
        rows.pack(fill="x", pady=(6, 0))
        values = (
            ("ENTRY", format_price(symbol, record.get("entry"))),
            ("SL", format_price(symbol, record.get("stop_loss"))),
            ("TP", format_price(symbol, record.get("take_profit"))),
            ("WIN RATE", f"{float(record.get('win_rate', 0) or 0):.1f}%"),
        )
        for index, (name, value) in enumerate(values):
            cell = tk.Frame(rows, bg=self.PANEL2)
            cell.grid(row=0, column=index, padx=(0, 14), sticky="w")
            self._label(cell, name, 8, self.MUTED).pack(anchor="w")
            self._label(cell, value, 12, self.TEXT).pack(anchor="w")
        if "outcome" in record:
            outcome = record.get("outcome")
            badge_color = (
                self.GREEN
                if outcome == "TP"
                else self.RED
                if outcome == "SL"
                else self.MUTED
            )
            badge = "—"
            if outcome in ("TP", "SL"):
                badge = f"OUTCOME: {outcome}"
            self._label(inner, badge, 10, badge_color).pack(anchor="w", pady=(8, 0))
        footer = (
            f"{record.get('timeframe', '')} · {record.get('mode', 'strict')}"
            " · educational only"
        ).strip(" ·")
        self._label(inner, footer, 8, self.MUTED).pack(anchor="w", pady=(4, 0))
        return card

    def _render_signal_cards(self, signals):
        """Fill the SIGNALS ticket strip with confluence cards."""
        if not hasattr(self, "signal_ticket_frame"):
            return
        for child in self.signal_ticket_frame.winfo_children():
            child.destroy()
        items = list(signals)
        if not items:
            empty = self._label(
                self.signal_ticket_frame,
                "No confluence cards yet. Press ANALYSIS to scan every market "
                "with the full backend.",
                10,
                self.MUTED,
            )
            empty.pack(anchor="w", padx=12, pady=12)
            return
        for column in range(3):
            self.signal_ticket_frame.grid_columnconfigure(column, weight=1)
        for index, signal in enumerate(items):
            record = signal.to_dict() if hasattr(signal, "to_dict") else signal
            card = self._build_signal_card(self.signal_ticket_frame, record)
            card.grid(
                row=index // 3,
                column=index % 3,
                padx=6,
                pady=6,
                sticky="nsew",
            )

    def _run_analysis(self):
        """ANALYSIS button: scan the watchlist with the whole backend."""
        if self._analysis_running:
            return
        self._analysis_running = True
        self.analysis_button.config(state="disabled")
        self.analysis_status.config(
            text="Running confluence over every market…", fg="#f0bd62"
        )
        timeframe = self.tf.get()
        provider = self._data_provider_key()
        count = int(self.provider_count_var.get())
        symbols = list(self.watch_symbols)
        threading.Thread(
            target=self._analysis_work,
            args=(symbols, timeframe, provider, count),
            name="neezy-analysis",
            daemon=True,
        ).start()

    def _analysis_work(self, symbols, timeframe, provider, count):
        candles_map = {}
        errors = {}
        seconds = TIMEFRAMES.get(timeframe, 300)
        for symbol in symbols:
            buffer = list(self.candles.get(symbol, []))
            if len(buffer) < 90:
                for attempt in (provider, "deriv"):
                    try:
                        if attempt == "deriv":
                            buffer = fetch_candles(
                                symbol,
                                seconds,
                                min(count, 1000),
                                timeout=self.settings.ml_fetch_timeout,
                            )
                        else:
                            buffer = get_candles(attempt, symbol, timeframe, count)
                    except (
                        ProviderError,
                        ValueError,
                        ConnectionError,
                        OSError,
                    ) as error:
                        errors.setdefault(symbol, str(error))
                        continue
                    if buffer:
                        errors.pop(symbol, None)
                        break
            if len(buffer) >= 90:
                candles_map[symbol] = buffer[-900:]
        signals = scan_candles(candles_map, timeframe, self.settings)
        for signal in signals:
            try:
                self.confluence_store.append(signal.as_history_record())
            except (OSError, ValueError):
                pass
        message = f"{len(signals)} signal(s) · provider: {provider}"
        if errors:
            message += f" · {len(errors)} market(s) without history"
        self.after(
            0,
            lambda sent_signals=signals, sent_message=message: self._finish_analysis(
                sent_signals, sent_message
            ),
        )

    def _finish_analysis(self, signals, message):
        self._analysis_running = False
        if self.analysis_button.winfo_exists():
            self.analysis_button.config(state="normal")
        self.analysis_status.config(
            text=message + " · search mode fills gaps so ANALYSIS always "
            "produces signals",
            fg=self.GREEN,
        )
        self._render_signal_cards(signals)
        buys = sum(1 for signal in signals if signal.direction > 0)
        sells = len(signals) - buys
        average = (
            sum(signal.score for signal in signals) / len(signals) if signals else 0
        )
        for key, value, color in [
            ("active", str(len(signals)), self.CYAN),
            ("buy", str(buys), self.GREEN),
            ("sell", str(sells), self.RED),
            ("confidence", f"{average:.0f}", self.MUTED),
        ]:
            self.card_values[key].config(text=value, fg=color)

    def _render_confluence_history(self):
        """History cards identical to SIGNALS plus exactly TP or SL outcome."""
        if not hasattr(self, "hist_frame"):
            return
        for child in self.hist_frame.winfo_children():
            child.destroy()
        records = self.confluence_store.read(limit=60)[:12]
        horizon = self.settings.confluence_horizon
        resolutions = {}
        for record in records:
            if record.get("outcome") is not None:
                continue
            try:
                epoch = datetime.fromisoformat(record["timestamp"]).timestamp()
            except (ValueError, TypeError, OSError):
                continue
            rows = []
            if self.db is not None:
                try:
                    rows = (
                        self.db.load_candles(
                            record["symbol"],
                            record.get("timeframe", "5m"),
                            limit=2 * horizon + 20,
                        )
                        or []
                    )
                except (sqlite3.Error, ValueError, OSError):
                    rows = []
            after = [row for row in rows if row[0] >= epoch]
            outcome = resolve_outcome(
                int(record["direction"]),
                float(record["entry"]),
                float(record["stop_loss"]),
                float(record["take_profit"]),
                after,
                horizon,
            )
            if outcome in ("TP", "SL"):
                resolutions[(record["symbol"], record["timestamp"])] = outcome
        if resolutions:
            try:
                self.confluence_store.update_outcomes(resolutions)
            except (OSError, ValueError):
                pass
            records = self.confluence_store.read(limit=60)[:12]
        if not records:
            self._label(
                self.hist_frame,
                "No confluence signals recorded yet. Every card the ANALYSIS "
                "button produces lands here with its TP or SL outcome.",
                10,
                self.MUTED,
            ).grid(row=0, column=0, padx=12, pady=12, sticky="w")
            return
        for column in range(3):
            self.hist_frame.grid_columnconfigure(column, weight=1)
        for index, record in enumerate(reversed(records)):
            card = self._build_signal_card(self.hist_frame, record)
            card.grid(
                row=index // 3,
                column=index % 3,
                padx=6,
                pady=6,
                sticky="nsew",
            )
