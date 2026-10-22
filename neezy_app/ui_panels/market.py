"""Market panels for the NEEZY desktop window."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import ttk

from neezy_backend.alerts import is_quiet_hours_now
from neezy_backend.brain import predict as predict_brain
from neezy_backend.dm import format_signal_dm, send_dm_notification
from neezy_backend.events import EventBus
from neezy_backend.indicators import (
    analyze,
    ema,
    macd_histogram_series,
    rsi_series,
)
from neezy_backend.markets import (
    SYMBOLS,
    TIMEFRAMES,
    format_price,
)
from neezy_backend.patterns import price_action_summary
from neezy_backend.risk import atr_levels
from neezy_backend.strategies import consensus, run_all
from neezy_backend.strategies import evaluate as eval_strategy
from neezy_backend.stream import parse_candle
from neezy_backend.trend import donchian, keltner, supertrend

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
        self.chart_title = self._label(
            bar, f"{SYMBOLS[self.selected]}  ·  {self.settings.default_timeframe}", 16
        )
        self.chart_title.pack(side="left")
        self.chart_hud_label = self._label(
            bar, "TradingView-style canvas", 9, self.MUTED
        )
        self.chart_hud_label.pack(side="left", padx=12)

        self.chart_tf_combo = ttk.Combobox(
            bar, values=list(TIMEFRAMES), width=7, state="readonly"
        )
        self.chart_tf_combo.set(self.settings.default_timeframe)
        self.chart_tf_combo.pack(side="right")
        self.chart_tf_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: (
                self.tf.set(self.chart_tf_combo.get()),
                self._tf_changed(),
            ),
        )
        self.chart_symbol_var = tk.StringVar(value=self.selected)
        self.chart_symbol_combo = ttk.Combobox(
            bar,
            textvariable=self.chart_symbol_var,
            values=list(self.watch_symbols),
            width=14,
            state="readonly",
        )
        self.chart_symbol_combo.pack(side="right", padx=(0, 8))
        self.chart_symbol_combo.bind(
            "<<ComboboxSelected>>",
            lambda _e: self._set_selected(self.chart_symbol_var.get()),
        )

        self.canvas = tk.Canvas(
            p, bg="#0c192b", highlightthickness=1, highlightbackground=self.BORDER
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw_chart())
        self.canvas.bind("<Motion>", self._on_chart_hover)

    def _on_chart_hover(self, event):
        if not getattr(self.settings, "chart_show_crosshair", True):
            return
        candles = self.candles.get(self.selected, [])
        visible = self.settings.chart_visible_candles
        cs = candles[-visible:]
        if len(cs) < 2 or not hasattr(self, "chart_hud_label"):
            return
        plot_w = max(self.canvas.winfo_width(), 500) - 70
        idx = int(max(0, min(len(cs) - 1, event.x / max(plot_w, 1) * len(cs))))
        ts, o, hi, lo, c = cs[idx]
        stamp = datetime.utcfromtimestamp(ts).strftime("%m-%d %H:%M")
        self.chart_hud_label.config(
            text=(
                f"{stamp}  O {self._fmt(self.selected, o)}  "
                f"H {self._fmt(self.selected, hi)}  "
                f"L {self._fmt(self.selected, lo)}  "
                f"C {self._fmt(self.selected, c)}"
            )
        )

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
        if hasattr(self, "chart_tf_combo"):
            self.chart_tf_combo.set(self.tf.get())
        self.last_signal.clear()
        self.price_action.clear()
        self.alert_engine.reset()
        self._subscribe_all()
        self.chart_title.config(text=f"{SYMBOLS[self.selected]}  ·  {self.tf.get()}")

    def _select(self):
        s = self.tree.selection()
        if s:
            self.selected = s[0]
            if hasattr(self, "chart_symbol_var"):
                self.chart_symbol_var.set(self.selected)
            self.chart_title.config(
                text=f"{SYMBOLS[self.selected]}  ·  {self.tf.get()}"
            )
            self._show_detail()
            self._draw_chart()

    def _set_selected(self, symbol):
        self.selected = symbol
        if hasattr(self, "chart_symbol_var"):
            self.chart_symbol_var.set(symbol)
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

    def _in_quiet_hours(self) -> bool:
        return bool(
            self.settings.quiet_hours_enabled
            and is_quiet_hours_now(
                self.settings.quiet_hours_start,
                self.settings.quiet_hours_end,
            )
        )

    def _ring_alert_bell(self) -> None:
        if (
            self.alerts_enabled.get()
            and self.settings.alert_sound_mode != "Muted"
            and not self._in_quiet_hours()
        ):
            self.bell()

    def _dispatch_dm_async(
        self, title: str, message: str, level: str = "info", fields: dict | None = None
    ) -> None:
        if not self.settings.dm_enabled or self._in_quiet_hours():
            return
        url = self.settings.dm_webhook_url.strip()
        if not url:
            return
        fmt = self.settings.dm_webhook_format
        https_only = self.settings.dm_https_only
        threading.Thread(
            target=send_dm_notification,
            args=(url, title, message, level, fields),
            kwargs={"webhook_format": fmt, "https_only": https_only},
            name="neezy-dm-dispatch",
            daemon=True,
        ).start()

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
                    if (
                        event.kind == "closed"
                        and self.settings.alert_on_stream_disconnect
                    ):
                        self._ring_alert_bell()
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
        interval = float(getattr(self.settings, "snapshot_interval_seconds", 60))
        if last is not None and now - last < interval:
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

    def _strategy_kwargs(self) -> dict[str, float | int]:
        return {
            "period": self.settings.supertrend_period,
            "multiplier": self.settings.supertrend_multiplier,
            "lookback": self.settings.divergence_lookback,
        }

    def _refresh(self, symbol):
        candles = self.candles.get(symbol, [])
        result = analyze(candles)
        if not result:
            return
        source = getattr(self.settings, "live_signal_source", "core")
        if source == "active_strategy" and len(candles) >= 40:
            try:
                strat_sig = eval_strategy(
                    self.settings.strategy, candles, **self._strategy_kwargs()
                )
                result = dict(result)
                result["signal"] = strat_sig.label
                result["score"] = round(
                    strat_sig.direction * max(1, strat_sig.confidence / 25.0)
                )
            except Exception as error:  # noqa: BLE001
                logger.debug("Strategy signal fallback for %s: %s", symbol, error)
        elif source == "consensus" and len(candles) >= 40:
            try:
                all_sigs = run_all(candles)
                verdict = consensus(all_sigs)
                result = dict(result)
                result["signal"] = verdict["label"]
                direction = (
                    1
                    if "BUY" in verdict["label"]
                    else -1
                    if "SELL" in verdict["label"]
                    else 0
                )
                result["score"] = round(
                    direction * max(1, verdict["confidence"] / 25.0)
                )
            except Exception as error:  # noqa: BLE001
                logger.debug("Consensus signal fallback for %s: %s", symbol, error)

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
                    self._ring_alert_bell()
                if (
                    abs(result["score"]) >= self.settings.telegram_min_signal_score
                    and not self._in_quiet_hours()
                ):
                    msg_lines = [
                        f"NEEZY signal change · {SYMBOLS[symbol]} {self.tf.get()}",
                        f"{previous} → {signal} · score {result['score']:+d}",
                        f"Price {self._fmt(symbol, candles[-1][4])}",
                    ]
                    if (
                        self.settings.telegram_include_sl_tp_levels
                        and result.get("atr")
                        and signal != "NEUTRAL"
                    ):
                        side = "SELL" if "SELL" in signal else "BUY"
                        sl_p, tp_p = atr_levels(
                            side,
                            candles[-1][4],
                            result["atr"],
                            self.settings.confluence_atr_stop_mult,
                            self.settings.default_reward_to_risk,
                        )
                        sl_s = self._fmt(symbol, sl_p)
                        tp_s = self._fmt(symbol, tp_p)
                        msg_lines.append(f"ATR SL {sl_s} · TP {tp_s}")
                    self._notify_telegram("\n".join(msg_lines))
                if (
                    self.settings.dm_enabled
                    and self.settings.dm_notify_signals
                    and abs(result["score"]) >= self.settings.dm_min_score
                ):
                    dm_payload = format_signal_dm(
                        symbol=SYMBOLS[symbol],
                        timeframe=self.tf.get(),
                        signal=signal,
                        score=float(abs(result["score"])),
                        metrics={
                            "Previous": previous,
                            "Price": self._fmt(symbol, candles[-1][4]),
                            "Regime": result.get("regime", "—"),
                        },
                    )
                    self._dispatch_dm_async(
                        dm_payload["title"],
                        dm_payload["message"],
                        dm_payload["level"],
                        dm_payload["fields"],
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
        visible = self.settings.chart_visible_candles
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
        subpane = self.settings.chart_subpane_oscillator
        main_h = int(h * 0.76) if subpane != "None" else h
        plot_w = w - 70
        closes = [row[4] for row in all_candles]
        bands = (
            self._band_series(
                closes,
                len(cs),
                period=self.settings.bollinger_period,
                deviations=self.settings.bollinger_std,
            )
            if self.settings.chart_show_bollinger
            else []
        )
        lo = min([x[3] for x in cs] + [b[1] for b in bands if b])
        hi = max([x[2] for x in cs] + [b[0] for b in bands if b])
        span = hi - lo or 1

        def y_of(price):
            return main_h - 30 - (price - lo) / span * (main_h - 60)

        if self.settings.chart_show_grid:
            for i in range(5):
                y = 30 + i * (main_h - 60) / 4
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
        if self.settings.chart_show_sr_levels:
            levels = action.get("levels") or {}
            sr_n = self.settings.chart_sr_count
            for price, colour in [
                *((level, self.GREEN) for level in levels.get("support", [])[:sr_n]),
                *((level, self.RED) for level in levels.get("resistance", [])[:sr_n]),
            ]:
                if lo <= price <= hi:
                    self.canvas.create_line(
                        0, y_of(price), plot_w, y_of(price), fill=colour, dash=(2, 6)
                    )
        if self.settings.chart_show_pivots and action.get("pivots"):
            piv = action["pivots"]
            for p_key, col in (
                ("pivot", "#f0bd62"),
                ("r1", self.RED),
                ("s1", self.GREEN),
            ):
                p_val = piv.get(p_key)
                if isinstance(p_val, (int, float)) and lo <= p_val <= hi:
                    self.canvas.create_line(
                        0, y_of(p_val), plot_w, y_of(p_val), fill=col, dash=(5, 4)
                    )
        if bands:
            upper = [
                (step * i + step / 2, y_of(b[0])) for i, b in enumerate(bands) if b
            ]
            lower = [
                (step * i + step / 2, y_of(b[1])) for i, b in enumerate(bands) if b
            ]
            for points in (upper, lower):
                if len(points) > 1:
                    self.canvas.create_line(
                        *[c for point in points for c in point],
                        fill="#36597d",
                        dash=(4, 3),
                    )

        # Strategy overlay (Supertrend / Donchian / Keltner)
        overlay_tags: list[str] = []
        if self.settings.show_strategy_overlay and len(all_candles) >= 25:
            strat = self.settings.strategy
            if strat == "DONCHIAN":
                dc = donchian(all_candles, period=self.settings.donchian_period)
                if dc:
                    for key, col in (("upper", self.GREEN), ("lower", self.RED)):
                        val = dc.get(key)
                        if isinstance(val, (int, float)) and lo <= val <= hi:
                            self.canvas.create_line(
                                0, y_of(val), plot_w, y_of(val), fill=col, dash=(6, 2)
                            )
                    overlay_tags.append(f"Donchian {self.settings.donchian_period}")
            elif strat == "KELTNER":
                kc = keltner(all_candles, period=self.settings.keltner_period)
                if kc:
                    for key in ("upper", "lower"):
                        val = kc.get(key)
                        if isinstance(val, (int, float)) and lo <= val <= hi:
                            self.canvas.create_line(
                                0,
                                y_of(val),
                                plot_w,
                                y_of(val),
                                fill="#a78bfa",
                                dash=(6, 2),
                            )
                    overlay_tags.append(f"Keltner {self.settings.keltner_period}")
            else:
                st = supertrend(
                    all_candles,
                    period=self.settings.supertrend_period,
                    multiplier=self.settings.supertrend_multiplier,
                )
                if st and isinstance(st.get("line"), (int, float)):
                    st_line = st["line"]
                    if lo <= st_line <= hi:
                        st_col = self.GREEN if st.get("trend") == "UP" else self.RED
                        self.canvas.create_line(
                            0,
                            y_of(st_line),
                            plot_w,
                            y_of(st_line),
                            fill=st_col,
                            width=2,
                            dash=(8, 3),
                        )
                        st_p = self.settings.supertrend_period
                        st_m = self.settings.supertrend_multiplier
                        overlay_tags.append(f"Supertrend {st_p}/{st_m:g}")

        style_mode = self.settings.chart_style
        line_pts: list[float] = []
        ha_prev_open = cs[0][1]
        ha_prev_close = cs[0][4]
        for i, (timestamp, o, high, low, c) in enumerate(cs):
            x = step * i + step / 2
            if self.settings.chart_mark_candle_gaps and i > 0:
                expected_dt = self.gran
                if (timestamp - cs[i - 1][0]) > expected_dt * 2.5:
                    self.canvas.create_line(
                        x - step / 2, 24, x - step / 2, main_h - 24, fill="#334155"
                    )
            if style_mode == "Heikin-Ashi":
                ha_c = (o + high + low + c) / 4.0
                ha_o = (ha_prev_open + ha_prev_close) / 2.0
                ha_h = max(high, ha_o, ha_c)
                ha_l = min(low, ha_o, ha_c)
                ha_prev_open, ha_prev_close = ha_o, ha_c
                o_d, h_d, l_d, c_d = ha_o, ha_h, ha_l, ha_c
            else:
                o_d, h_d, l_d, c_d = o, high, low, c
            yo, yc = y_of(o_d), y_of(c_d)
            col = self.GREEN if c_d >= o_d else self.RED
            half = max(1.5, min(4.0, step * 0.35))
            if style_mode == "Close Line":
                line_pts.extend((x, yc))
            elif style_mode == "OHLC Bars":
                self.canvas.create_line(x, y_of(h_d), x, y_of(l_d), fill=col)
                self.canvas.create_line(x - half, yo, x, yo, fill=col)
                self.canvas.create_line(x, yc, x + half, yc, fill=col)
            elif style_mode == "Hollow Candles" and c_d >= o_d:
                self.canvas.create_line(x, y_of(h_d), x, y_of(l_d), fill=col)
                self.canvas.create_rectangle(
                    x - half,
                    min(yo, yc),
                    x + half,
                    max(yo, yc) + 1,
                    fill=self.BG,
                    outline=col,
                )
            else:
                self.canvas.create_line(x, y_of(h_d), x, y_of(l_d), fill=col)
                self.canvas.create_rectangle(
                    x - half,
                    min(yo, yc),
                    x + half,
                    max(yo, yc) + 1,
                    fill=col,
                    outline=col,
                )
        if style_mode == "Close Line" and len(line_pts) >= 4:
            self.canvas.create_line(*line_pts, fill=self.CYAN, width=2, smooth=True)

        # Configurable Fast / Slow / Trend EMAs
        for enabled, period, color, width in (
            (
                self.settings.chart_show_ema_fast,
                self.settings.chart_ema_fast_period,
                "#f59e0b",
                1,
            ),
            (
                self.settings.chart_show_ema_slow,
                self.settings.chart_ema_slow_period,
                self.CYAN,
                2,
            ),
            (
                self.settings.chart_show_ema_trend,
                self.settings.chart_ema_trend_period,
                "#a855f7",
                1,
            ),
        ):
            if enabled:
                series = ema(closes, period)[-len(cs) :]
                if len(series) > 1:
                    pts = [
                        coord
                        for i, value in enumerate(series)
                        for coord in (step * i + step / 2, y_of(value))
                    ]
                    self.canvas.create_line(*pts, fill=color, width=width, smooth=True)
                    overlay_tags.append(f"EMA {period}")

        # Live Entry / SL / TP guide lines when directional bias exists
        res = self.results.get(self.selected)
        if (
            self.settings.chart_show_entry_sl_tp
            and res
            and res.get("atr")
            and res.get("signal") not in (None, "NEUTRAL")
        ):
            side = "SELL" if "SELL" in res["signal"] else "BUY"
            sl_p, tp_p = atr_levels(
                side,
                cs[-1][4],
                res["atr"],
                self.settings.confluence_atr_stop_mult,
                self.settings.default_reward_to_risk,
            )
            for lvl, col in ((sl_p, self.RED), (tp_p, self.GREEN)):
                if lo <= lvl <= hi:
                    self.canvas.create_line(
                        plot_w * 0.65,
                        y_of(lvl),
                        plot_w,
                        y_of(lvl),
                        fill=col,
                        dash=(3, 3),
                    )

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
        legend = " · ".join(overlay_tags) if overlay_tags else style_mode
        self.canvas.create_text(
            10,
            12,
            text=f"{style_mode}   ·   {legend}",
            fill=self.MUTED,
            anchor="w",
            font=("Helvetica", 8),
        )

        # Optional lower subpane oscillator (RSI 14 or MACD Histogram)
        if subpane != "None" and len(closes) >= 20:
            top_y = main_h + 6
            bot_y = h - 10
            self.canvas.create_line(0, top_y, plot_w, top_y, fill=self.BORDER)
            if subpane == "RSI 14":
                r_vals = rsi_series(closes)[-len(cs) :]
                pts = [
                    coord
                    for i, v in enumerate(r_vals)
                    if v is not None
                    for coord in (
                        step * i + step / 2,
                        bot_y - (v / 100.0) * max(bot_y - top_y, 1),
                    )
                ]
                if len(pts) >= 4:
                    self.canvas.create_line(*pts, fill=self.CYAN, width=1.5)
                self.canvas.create_text(
                    10, top_y + 10, text="RSI 14", fill=self.MUTED, anchor="w"
                )
            elif subpane == "MACD Histogram":
                m_vals = [
                    v
                    for v in macd_histogram_series(closes)[-len(cs) :]
                    if v is not None
                ]
                if m_vals:
                    peak = max(max(abs(v) for v in m_vals), 1e-9)
                    mid_y = (top_y + bot_y) / 2.0
                    for i, v in enumerate(m_vals):
                        x = step * i + step / 2
                        bar_y = mid_y - (v / peak) * ((bot_y - top_y) / 2.0)
                        self.canvas.create_line(
                            x, mid_y, x, bar_y, fill=self.GREEN if v >= 0 else self.RED
                        )
                    self.canvas.create_text(
                        10,
                        top_y + 10,
                        text="MACD Histogram",
                        fill=self.MUTED,
                        anchor="w",
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
