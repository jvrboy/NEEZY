"""Market panels for the NEEZY desktop window."""

from __future__ import annotations

import logging
import sqlite3
import time
import tkinter as tk
from datetime import datetime

from neezy_backend.brain import predict as predict_brain
from neezy_backend.events import EventBus
from neezy_backend.indicators import analyze, ema
from neezy_backend.markets import (
    SYMBOLS,
    TIMEFRAMES,
    format_price,
)
from neezy_backend.patterns import price_action_summary
from neezy_backend.stream import parse_candle

logger = logging.getLogger(__name__)


class MarketMixin:
    """Methods for the market screen; mixed into App."""

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
        [
            self.watch.insert("end", f"  {n:<22}  {s}")
            for s, n in self.watch_symbols.items()
        ]
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
            self.selected = list(self.watch_symbols)[i[0]]
            self._tab("CHART")
            self.chart_title.config(
                text=f"{SYMBOLS[self.selected]}  ·  {self.tf.get()}"
            )
            self._draw_chart()

    def _subscribe_all(self):
        self.client.send({"forget_all": "candles"})
        self.candles.clear()
        self.results.clear()
        for symbol in self.watch_symbols:
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
            self.command_bridge.process(self._handle_remote_command, limit=25)
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
        result["brain"] = None
        if self.settings.use_brain_model:
            model = self._get_brain_model(symbol, self.tf.get())
            if isinstance(model, dict):
                try:
                    result["brain"] = predict_brain(
                        candles, model, minimum_probability=self.settings.ml_probability
                    )
                except (TypeError, ValueError, KeyError) as error:
                    logger.warning(
                        "Could not apply local brain model for %s: %s", symbol, error
                    )
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
                if abs(result["score"]) >= self.settings.alert_min_score:
                    if self.alerts_enabled.get():
                        self.bell()
                    self._notify_telegram(
                        f"NEEZY signal change · {SYMBOLS[symbol]} {self.tf.get()}\n"
                        f"{previous} → {signal} · score {result['score']:+d}\n"
                        f"Price {self._fmt(symbol, candles[-1][4])}"
                    )
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
        brain = result.get("brain")
        if brain:
            metrics = brain.get("test_metrics") or {}
            balanced = metrics.get("balanced_accuracy")
            validation = (
                f"holdout balanced accuracy {balanced:.1%}"
                if isinstance(balanced, (int, float))
                else "no holdout score"
            )
            lines.append(
                f"Local MLP  {brain.get('direction', 'UNVALIDATED')} · "
                f"up p={brain.get('up_probability', 0):.2f} · {validation} · "
                "research only"
            )
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
