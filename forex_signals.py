#!/usr/bin/env python3
"""
Forex Signals - native desktop app (Python + Tkinter)
Live data: Deriv public WebSocket API (default public app_id 1089, no login/token needed)

Install:  pip install websocket-client
Run:      python forex_signals.py

Signals are computed on CLOSED candles only (no repainting).
Educational tool only - not financial advice.
"""
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from datetime import datetime

try:
    import websocket  # pip install websocket-client
except ImportError:
    raise SystemExit("Missing dependency. Run:  pip install websocket-client")

APP_ID = 1089  # Deriv's default public app id
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
    "R_100": "Volatility 100 (24/7 test)",
}
TIMEFRAMES = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
              "1h": 3600, "4h": 14400, "1d": 86400}
HISTORY = 300


# ----------------------------------------------------------------- indicators
def ema(v, p):
    k = 2 / (p + 1)
    out = [v[0]]
    for x in v[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def rsi(c, p=14):
    if len(c) <= p:
        return None
    g = l = 0.0
    for i in range(1, p + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0)
        l += max(-d, 0)
    g /= p
    l /= p
    for i in range(p + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (p - 1) + max(d, 0)) / p
        l = (l * (p - 1) + max(-d, 0)) / p
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def atr(h, l, c, p=14):
    tr = [h[0] - l[0]] + [
        max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        for i in range(1, len(c))
    ]
    a = sum(tr[:p]) / p
    for x in tr[p:]:
        a = (a * (p - 1) + x) / p
    return a


def bollinger(c, p=20, m=2.0):
    w = c[-p:]
    mid = sum(w) / p
    sd = (sum((x - mid) ** 2 for x in w) / p) ** 0.5
    return mid - m * sd, mid, mid + m * sd


def analyze(candles):
    """candles: list of (epoch, open, high, low, close). Uses closed candles only."""
    closed = candles[:-1]
    if len(closed) < 60:
        return None
    h = [x[2] for x in closed]
    l = [x[3] for x in closed]
    c = [x[4] for x in closed]

    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    macd_line = [a - b for a, b in zip(ema(c, 12), ema(c, 26))]
    hist = [a - b for a, b in zip(macd_line, ema(macd_line, 9))]
    r = rsi(c)
    a = atr(h, l, c)
    lo, mid, up = bollinger(c)
    last = c[-1]

    score, why = 0, []

    if e9[-1] > e21[-1]:
        score += 1; why.append("EMA9 above EMA21 (+1)")
    else:
        score -= 1; why.append("EMA9 below EMA21 (-1)")

    for k in range(1, 4):  # fresh cross within last 3 candles
        prev = e9[-k - 1] - e21[-k - 1]
        cur = e9[-k] - e21[-k]
        if prev <= 0 < cur:
            score += 1; why.append("Fresh bullish EMA cross (+1)"); break
        if prev >= 0 > cur:
            score -= 1; why.append("Fresh bearish EMA cross (-1)"); break

    if last > e50[-1]:
        score += 1; why.append("Price above EMA50 (+1)")
    else:
        score -= 1; why.append("Price below EMA50 (-1)")

    if r is not None:
        if r < 35:
            score += 1; why.append(f"RSI {r:.1f} oversold (+1)")
        elif r > 65:
            score -= 1; why.append(f"RSI {r:.1f} overbought (-1)")
        else:
            why.append(f"RSI {r:.1f} neutral (0)")

    if hist[-1] > 0:
        score += 1; why.append("MACD histogram positive (+1)")
    else:
        score -= 1; why.append("MACD histogram negative (-1)")

    if last < lo:
        score += 1; why.append("Below lower Bollinger band (+1)")
    elif last > up:
        score -= 1; why.append("Above upper Bollinger band (-1)")
    else:
        why.append("Inside Bollinger bands (0)")

    if score >= 5:
        sig = "STRONG BUY"
    elif score >= 3:
        sig = "BUY"
    elif score <= -5:
        sig = "STRONG SELL"
    elif score <= -3:
        sig = "SELL"
    else:
        sig = "NEUTRAL"

    return {"signal": sig, "score": score, "rsi": r, "atr": a, "why": why,
            "ema9": e9[-1], "ema21": e21[-1], "ema50": e50[-1]}


# ------------------------------------------------------------- websocket client
class DerivClient:
    def __init__(self, inbox):
        self.inbox = inbox
        self.ws = None
        self.connected = False
        self.running = True

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while self.running:
            self.ws = websocket.WebSocketApp(
                WS_URL,
                on_open=lambda ws: self._open(),
                on_message=self._msg,
                on_error=lambda ws, e: self.inbox.put(("status", f"Error: {e}")),
                on_close=lambda ws, c, m: setattr(self, "connected", False),
            )
            self.ws.run_forever(ping_interval=20, ping_timeout=10)
            self.connected = False
            if self.running:
                self.inbox.put(("status", "Disconnected - retrying in 5s..."))
                time.sleep(5)

    def _open(self):
        self.connected = True
        self.inbox.put(("open", None))

    def _msg(self, ws, m):
        try:
            self.inbox.put(("msg", json.loads(m)))
        except Exception:
            pass

    def send(self, d):
        try:
            if self.connected:
                self.ws.send(json.dumps(d))
        except Exception:
            pass

    def stop(self):
        self.running = False
        try:
            self.ws.close()
        except Exception:
            pass


# --------------------------------------------------------------------- the app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Forex Signals - Deriv Live")
        self.geometry("1100x700")
        self.minsize(900, 560)

        self.inbox = queue.Queue()
        self.client = DerivClient(self.inbox)
        self.gran = TIMEFRAMES["5m"]
        self.candles = {}
        self.results = {}
        self.last_signal = {}
        self.selected = None

        self._build_ui()
        self.client.start()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    # ---- UI
    def _build_ui(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Timeframe:").pack(side="left")
        self.tf = ttk.Combobox(top, values=list(TIMEFRAMES), width=6, state="readonly")
        self.tf.set("5m")
        self.tf.pack(side="left", padx=6)
        self.tf.bind("<<ComboboxSelected>>", self._tf_changed)
        self.status = ttk.Label(top, text="Connecting...")
        self.status.pack(side="right")

        mid = ttk.PanedWindow(self, orient="horizontal")
        mid.pack(fill="both", expand=True, padx=8)

        left = ttk.Frame(mid)
        cols = ("pair", "price", "signal", "score", "rsi", "upd")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=12)
        for col, txt, w in (("pair", "Pair", 170), ("price", "Price", 90),
                            ("signal", "Signal", 100), ("score", "Score", 50),
                            ("rsi", "RSI", 55), ("upd", "Updated", 75)):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor="center" if col != "pair" else "w")
        self.tree.tag_configure("buy", foreground="#0a8f3c")
        self.tree.tag_configure("sell", foreground="#d12b2b")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        for sym, name in SYMBOLS.items():
            self.tree.insert("", "end", iid=sym, values=(name, "...", "Loading", "", "", ""))
        mid.add(left, weight=3)

        right = ttk.Frame(mid)
        self.detail = tk.Text(right, wrap="word", width=42, state="disabled",
                              font=("Menlo", 11), padx=8, pady=8)
        self.detail.tag_configure("big", font=("Helvetica", 20, "bold"))
        self.detail.tag_configure("buy", foreground="#0a8f3c")
        self.detail.tag_configure("sell", foreground="#d12b2b")
        self.detail.pack(fill="both", expand=True)
        mid.add(right, weight=2)

        ttk.Label(self, text="Signal changes", padding=(8, 6, 8, 0)).pack(anchor="w")
        self.log = tk.Listbox(self, height=7, font=("Menlo", 10))
        self.log.pack(fill="x", padx=8, pady=(0, 4))

        ttk.Label(self, foreground="#777", padding=(8, 0, 8, 8),
                  text="Educational tool only - not financial advice. Forex is closed on weekends; "
                       "use the 24/7 Volatility 100 row to test.").pack(anchor="w")

    # ---- events
    def _tf_changed(self, _):
        self.gran = TIMEFRAMES[self.tf.get()]
        self.last_signal.clear()
        self._subscribe_all()

    def _on_select(self, _):
        sel = self.tree.selection()
        if sel:
            self.selected = sel[0]
            self._show_detail(self.selected)

    # ---- data
    def _subscribe_all(self):
        self.client.send({"forget_all": "candles"})
        self.candles.clear()
        self.results.clear()
        for sym, name in SYMBOLS.items():
            self.tree.item(sym, values=(name, "...", "Loading", "", "", ""), tags=())
            self.client.send({
                "ticks_history": sym,
                "adjust_start_time": 1,
                "count": HISTORY,
                "end": "latest",
                "granularity": self.gran,
                "style": "candles",
                "subscribe": 1,
            })

    def _poll(self):
        try:
            for _ in range(300):
                kind, data = self.inbox.get_nowait()
                if kind == "open":
                    self.status.config(text="● Connected", foreground="#0a8f3c")
                    self._subscribe_all()
                elif kind == "status":
                    self.status.config(text=data, foreground="#d12b2b")
                elif kind == "msg":
                    self._handle(data)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _handle(self, msg):
        req = msg.get("echo_req", {})
        if msg.get("error"):
            sym = req.get("ticks_history")
            if sym in SYMBOLS:
                self.tree.item(sym, values=(SYMBOLS[sym], "-", "n/a", "", "", ""), tags=())
            return
        t = msg.get("msg_type")
        if t == "candles":
            sym = req.get("ticks_history")
            if sym not in SYMBOLS or req.get("granularity") != self.gran:
                return
            self.candles[sym] = [(int(c["epoch"]), float(c["open"]), float(c["high"]),
                                  float(c["low"]), float(c["close"])) for c in msg["candles"]]
            self._refresh(sym)
        elif t == "ohlc":
            o = msg["ohlc"]
            sym = o["symbol"]
            if sym not in SYMBOLS or int(o["granularity"]) != self.gran:
                return
            row = (int(o["open_time"]), float(o["open"]), float(o["high"]),
                   float(o["low"]), float(o["close"]))
            lst = self.candles.setdefault(sym, [])
            if lst and lst[-1][0] == row[0]:
                lst[-1] = row
            elif not lst or row[0] > lst[-1][0]:
                lst.append(row)
                del lst[:-500]
            self._refresh(sym)

    def _fmt(self, sym, p):
        d = 3 if "JPY" in sym else (2 if sym.startswith("R_") else 5)
        return f"{p:.{d}f}"

    def _refresh(self, sym):
        cs = self.candles.get(sym, [])
        if not cs:
            return
        price = self._fmt(sym, cs[-1][4])
        res = analyze(cs)
        if not res:
            self.tree.item(sym, values=(SYMBOLS[sym], price, "Loading", "", "", ""))
            return
        self.results[sym] = res
        sig = res["signal"]
        tag = "buy" if "BUY" in sig else "sell" if "SELL" in sig else ""
        self.tree.item(sym, tags=(tag,) if tag else (), values=(
            SYMBOLS[sym], price, sig, f"{res['score']:+d}",
            f"{res['rsi']:.0f}" if res["rsi"] is not None else "",
            datetime.now().strftime("%H:%M:%S")))

        prev = self.last_signal.get(sym)
        if prev is not None and prev != sig:
            self.log.insert(0, f"{datetime.now():%H:%M:%S}  {SYMBOLS[sym]:<26} {prev} -> {sig}  @ {price}")
            if sig != "NEUTRAL":
                self.bell()
        self.last_signal[sym] = sig

        if sym == self.selected:
            self._show_detail(sym)

    def _show_detail(self, sym):
        res = self.results.get(sym)
        cs = self.candles.get(sym)
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        if not res or not cs:
            self.detail.insert("end", "Collecting data...")
        else:
            price = cs[-1][4]
            sig = res["signal"]
            tag = "buy" if "BUY" in sig else "sell" if "SELL" in sig else ""
            self.detail.insert("end", f"{SYMBOLS[sym]}\n")
            self.detail.insert("end", f"{sig}\n", ("big", tag) if tag else ("big",))
            self.detail.insert("end", f"Score {res['score']:+d} / 6   Price {self._fmt(sym, price)}\n\n")
            if "BUY" in sig or "SELL" in sig:
                d = 1 if "BUY" in sig else -1
                sl = price - d * 1.5 * res["atr"]
                tp = price + d * 2.5 * res["atr"]
                self.detail.insert("end",
                    f"Entry  {self._fmt(sym, price)}\nSL     {self._fmt(sym, sl)}  (1.5x ATR)\n"
                    f"TP     {self._fmt(sym, tp)}  (2.5x ATR)\n\n")
            self.detail.insert("end", "Why:\n")
            for w in res["why"]:
                self.detail.insert("end", f" - {w}\n")
            self.detail.insert("end",
                f"\nEMA9  {self._fmt(sym, res['ema9'])}\nEMA21 {self._fmt(sym, res['ema21'])}\n"
                f"EMA50 {self._fmt(sym, res['ema50'])}\nATR14 {self._fmt(sym, res['atr'])}\n")
        self.detail.config(state="disabled")

    def _close(self):
        self.client.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
