#!/usr/bin/env python3
"""NEEZY — a glass-styled, native Python trading workspace.
Live market data uses Deriv's public WebSocket API. Educational use only.
"""
import json, queue, threading, time, tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime

from neezy_backend.config import AppSettings

try:
    import websocket
except ImportError:
    raise SystemExit("Missing dependency: pip install websocket-client")

APP_ID = 1089
WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
SYMBOLS = {"frxEURUSD":"EUR/USD","frxGBPUSD":"GBP/USD","frxUSDJPY":"USD/JPY","frxAUDUSD":"AUD/USD","frxUSDCAD":"USD/CAD","frxUSDCHF":"USD/CHF","frxNZDUSD":"NZD/USD","frxEURGBP":"EUR/GBP","frxEURJPY":"EUR/JPY","frxGBPJPY":"GBP/JPY","R_100":"Volatility 100"}
TIMEFRAMES = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"1d":86400}
HISTORY = 300

# ---------- indicators (closed candles only)
def ema(v, p):
    k=2/(p+1); out=[v[0]]
    for x in v[1:]: out.append(x*k+out[-1]*(1-k))
    return out

def rsi(c,p=14):
    if len(c)<=p:return None
    g=l=0.0
    for i in range(1,p+1):
        d=c[i]-c[i-1]; g+=max(d,0); l+=max(-d,0)
    g/=p; l/=p
    for i in range(p+1,len(c)):
        d=c[i]-c[i-1]; g=(g*(p-1)+max(d,0))/p; l=(l*(p-1)+max(-d,0))/p
    return 100 if l==0 else 100-100/(1+g/l)

def atr(h,l,c,p=14):
    tr=[h[0]-l[0]]+[max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    a=sum(tr[:p])/p
    for x in tr[p:]:a=(a*(p-1)+x)/p
    return a

def analyze(candles):
    closed=candles[:-1]
    if len(closed)<60:return None
    h=[x[2] for x in closed]; l=[x[3] for x in closed]; c=[x[4] for x in closed]
    e9,e21,e50=ema(c,9),ema(c,21),ema(c,50); ml=[a-b for a,b in zip(ema(c,12),ema(c,26))]; hist=[a-b for a,b in zip(ml,ema(ml,9))]; r=rsi(c); a=atr(h,l,c); last=c[-1]
    score=0; why=[]
    score += 1 if e9[-1]>e21[-1] else -1; why.append("EMA9 above EMA21" if score>0 else "EMA9 below EMA21")
    score += 1 if last>e50[-1] else -1; why.append("Price above EMA50" if last>e50[-1] else "Price below EMA50")
    if r is not None:
        if r<35:score+=1;why.append(f"RSI {r:.1f} oversold")
        elif r>65:score-=1;why.append(f"RSI {r:.1f} overbought")
        else:why.append(f"RSI {r:.1f} neutral")
    score += 1 if hist[-1]>0 else -1; why.append("MACD momentum positive" if hist[-1]>0 else "MACD momentum negative")
    sig="STRONG BUY" if score>=4 else "BUY" if score>=2 else "STRONG SELL" if score<=-4 else "SELL" if score<=-2 else "NEUTRAL"
    return {"signal":sig,"score":score,"rsi":r,"atr":a,"why":why,"ema9":e9[-1],"ema21":e21[-1],"ema50":e50[-1],"closes":c}

class DerivClient:
    def __init__(self,inbox):self.inbox=inbox;self.ws=None;self.connected=False;self.running=True
    def start(self):threading.Thread(target=self._run,daemon=True).start()
    def _run(self):
        while self.running:
            self.ws=websocket.WebSocketApp(WS_URL,on_open=lambda w:self._open(),on_message=self._msg,on_error=lambda w,e:self.inbox.put(("status",f"Connection error: {e}")),on_close=lambda w,c,m:setattr(self,"connected",False))
            self.ws.run_forever(ping_interval=20,ping_timeout=10); self.connected=False
            if self.running:self.inbox.put(("status","Reconnecting…"));time.sleep(5)
    def _open(self):self.connected=True;self.inbox.put(("open",None))
    def _msg(self,ws,msg):
        try:self.inbox.put(("msg",json.loads(msg)))
        except Exception:pass
    def send(self,data):
        try:
            if self.connected:self.ws.send(json.dumps(data))
        except Exception:pass
    def stop(self):
        self.running=False
        try:self.ws.close()
        except Exception:pass

class App(tk.Tk):
    BG="#08111f"; PANEL="#101d30"; PANEL2="#14253b"; TEXT="#e6f0ff"; MUTED="#8ea4bd"; CYAN="#55d6ff"; GREEN="#48e6a1"; RED="#ff718c"; BORDER="#203754"
    def __init__(self):
        super().__init__();self.title("NEEZY  /  Market Intelligence");self.geometry("1280x800");self.minsize(1050,650);self.configure(bg=self.BG)
        self.inbox=queue.Queue();self.client=DerivClient(self.inbox);self.gran=300;self.candles={};self.results={};self.last_signal={};self.selected="frxEURUSD";self.history=[];self.chart_points=[];self.settings=AppSettings();self.auto_refresh=tk.BooleanVar(value=self.settings.auto_refresh);self.compact_mode=tk.BooleanVar(value=self.settings.compact_mode);self.alerts_enabled=tk.BooleanVar(value=self.settings.alerts_enabled);self.theme_var=tk.StringVar(value=self.settings.theme);self.polling_var=tk.IntVar(value=self.settings.polling_ms);self.candle_limit_var=tk.IntVar(value=self.settings.candle_limit);self.status_var=tk.StringVar(value="Ready")
        self._style();self._build();self.client.start();self.after(100,self._poll);self.protocol("WM_DELETE_WINDOW",self._close)
    def _style(self):
        s=ttk.Style(self);s.theme_use("clam");s.configure("TCombobox",fieldbackground=self.PANEL2,background=self.PANEL2,foreground=self.TEXT);s.configure("Treeview",background=self.PANEL,fieldbackground=self.PANEL,foreground=self.TEXT,rowheight=34,borderwidth=0);s.map("Treeview",background=[("selected", "#204467")]);s.configure("TNotebook",background=self.BG,borderwidth=0);s.configure("TNotebook.Tab",background=self.PANEL,foreground=self.MUTED,padding=(18,10));s.map("TNotebook.Tab",background=[("selected",self.PANEL2)],foreground=[("selected",self.CYAN)])
    def _label(self,p,text,size=10,color=None,**kw):return tk.Label(p,text=text,bg=p.cget("bg"),fg=color or self.TEXT,font=("Helvetica",size),**kw)
    def _panel(self,p):return tk.Frame(p,bg=self.PANEL,highlightbackground=self.BORDER,highlightthickness=1)
    def _build(self):
        self._sidebar(); self.main=tk.Frame(self,bg=self.BG);self.main.pack(side="left",fill="both",expand=True);self._header();self._tabs()
    def _sidebar(self):
        side=tk.Frame(self,bg="#0b1728",width=220);side.pack(side="left",fill="y");side.pack_propagate(False)
        tk.Label(side,text="N",bg=self.CYAN,fg=self.BG,font=("Helvetica",20,"bold"),width=2,height=1).pack(anchor="w",padx=22,pady=(25,8));tk.Label(side,text="NEEZY",bg=side.cget("bg"),fg=self.TEXT,font=("Helvetica",16,"bold")).pack(anchor="w",padx=22);tk.Label(side,text="MARKET INTELLIGENCE",bg=side.cget("bg"),fg=self.MUTED,font=("Helvetica",8)).pack(anchor="w",padx=23,pady=(0,35))
        self.nav={}
        for name in ["CHAT","SYMBOLS","CHART","SIGNALS","HISTORY","SETTINGS"]:
            b=tk.Button(side,text="  "+name,anchor="w",command=lambda n=name:self._tab(n),bg=side.cget("bg"),fg=self.MUTED,activebackground=self.PANEL2,activeforeground=self.CYAN,relief="flat",bd=0,font=("Helvetica",10,"bold"),padx=18,pady=13);b.pack(fill="x",padx=10,pady=2);self.nav[name]=b
        self.nav["SIGNALS"].configure(fg=self.CYAN,bg=self.PANEL2)
        tk.Label(side,text="LIVE FEED",bg=side.cget("bg"),fg=self.MUTED,font=("Helvetica",8,"bold")).pack(anchor="w",padx=23,pady=(45,8));self.conn=tk.Label(side,text="●  Connecting",bg=side.cget("bg"),fg="#f0bd62",font=("Helvetica",10));self.conn.pack(anchor="w",padx=23)
        tk.Label(side,text="Educational tool · not financial advice",wraplength=170,justify="left",bg=side.cget("bg"),fg="#577089",font=("Helvetica",8)).pack(side="bottom",anchor="w",padx=23,pady=25)
    def _header(self):
        h=tk.Frame(self.main,bg=self.BG);h.pack(fill="x",padx=28,pady=(25,18));self._label(h,"SIGNALS OVERVIEW",19,"#ffffff").pack(side="left");self._label(h,"  Live market workspace",10,self.MUTED).pack(side="left",pady=5);self.status=self._label(h,"●  Connecting",10,"#f0bd62");self.status.pack(side="right")
    def _tabs(self):
        self.nb=ttk.Notebook(self.main);self.nb.pack(fill="both",expand=True,padx=28,pady=(0,28));self.pages={}
        for name in ["CHAT","SYMBOLS","CHART","SIGNALS","HISTORY","SETTINGS"]:
            page=tk.Frame(self.nb,bg=self.BG);self.nb.add(page,text=name);self.pages[name]=page
        self._signals_page();self._symbols_page();self._chart_page();self._chat_page();self._history_page();self._settings_page();self.nb.select(3)
    def _tab(self,name):self.nb.select(self.pages[name]);[b.configure(fg=self.MUTED,bg="#0b1728") for b in self.nav.values()];self.nav[name].configure(fg=self.CYAN,bg=self.PANEL2)
    def _signals_page(self):
        p=self.pages["SIGNALS"];top=tk.Frame(p,bg=self.BG);top.pack(fill="x",pady=(0,12));self._label(top,"Signal monitor",12,"#ffffff").pack(side="left");self._label(top,"  Closed-candle confirmation · no repainting",9,self.MUTED).pack(side="left",pady=2)
        self.signal_cards=tk.Frame(p,bg=self.BG);self.signal_cards.pack(fill="x",pady=(0,12));self.card_values={}
        for key,title,accent in [("active","ACTIVE SETUPS",self.CYAN),("buy","BUY BIAS",self.GREEN),("sell","SELL BIAS",self.RED),("confidence","AVG SCORE",self.MUTED)]:
            card=self._panel(self.signal_cards);card.pack(side="left",fill="x",expand=True,padx=(0,8));self._label(card,title,8,self.MUTED).pack(anchor="w",padx=14,pady=(10,2));v=self._label(card,"—",18,accent);v.pack(anchor="w",padx=14,pady=(0,10));self.card_values[key]=v
        self.tf=ttk.Combobox(top,values=list(TIMEFRAMES),width=7,state="readonly");self.tf.set("5m");self.tf.pack(side="right");self.tf.bind("<<ComboboxSelected>>",lambda e:self._tf_changed())
        body=tk.Frame(p,bg=self.BG);body.pack(fill="both",expand=True);left=self._panel(body);left.pack(side="left",fill="both",expand=True,padx=(0,12));right=self._panel(body);right.pack(side="right",fill="both",expand=False);right.configure(width=320);right.pack_propagate(False)
        cols=("pair","price","signal","score","rsi","updated");self.tree=ttk.Treeview(left,columns=cols,show="headings");
        for c,t,w in [("pair","MARKET",170),("price","PRICE",100),("signal","BIAS",120),("score","SCORE",65),("rsi","RSI",60),("updated","UPDATED",80)]:self.tree.heading(c,text=t);self.tree.column(c,width=w,anchor="center" if c!="pair" else "w")
        self.tree.tag_configure("buy",foreground=self.GREEN);self.tree.tag_configure("sell",foreground=self.RED);self.tree.pack(fill="both",expand=True,padx=10,pady=10);self.tree.bind("<<TreeviewSelect>>",lambda e:self._select())
        for s,n in SYMBOLS.items():self.tree.insert("","end",iid=s,values=(n,"—","Loading","—","—","—"))
        self.detail=tk.Text(right,bg=self.PANEL,fg=self.TEXT,insertbackground=self.TEXT,relief="flat",wrap="word",font=("Helvetica",10),padx=18,pady=18);self.detail.tag_configure("big",font=("Helvetica",22,"bold"));self.detail.tag_configure("buy",foreground=self.GREEN);self.detail.tag_configure("sell",foreground=self.RED);self.detail.pack(fill="both",expand=True)
    def _symbols_page(self):
        p=self.pages["SYMBOLS"];self._label(p,"Market watchlist",16).pack(anchor="w",pady=(5,16));self._label(p,"Select a market to focus the chart and signal detail.",10,self.MUTED).pack(anchor="w",pady=(0,18));self.watch=tk.Listbox(p,bg=self.PANEL,fg=self.TEXT,selectbackground="#204467",relief="flat",font=("Helvetica",12),height=15);self.watch.pack(fill="both",expand=True);[self.watch.insert("end",f"  {n:<22}  {s}") for s,n in SYMBOLS.items()];self.watch.bind("<<ListboxSelect>>",lambda e:self._watch_select())
    def _chart_page(self):
        p=self.pages["CHART"];bar=tk.Frame(p,bg=self.BG);bar.pack(fill="x",pady=(5,12));self.chart_title=self._label(bar,"EUR/USD  ·  5m",16);self.chart_title.pack(side="left");self._label(bar,"TradingView-style canvas",9,self.MUTED).pack(side="left",padx=12);self.canvas=tk.Canvas(p,bg="#0c192b",highlightthickness=1,highlightbackground=self.BORDER);self.canvas.pack(fill="both",expand=True);self.canvas.bind("<Configure>",lambda e:self._draw_chart())
    def _chat_page(self):
        p=self.pages["CHAT"];self._label(p,"Market copilot",16).pack(anchor="w",pady=(5,4));self._label(p,"Ask for a concise read on the active market.",10,self.MUTED).pack(anchor="w",pady=(0,15));self.chat=tk.Text(p,bg=self.PANEL,fg=self.TEXT,relief="flat",font=("Helvetica",11),padx=18,pady=15);self.chat.pack(fill="both",expand=True);self.chat.insert("end","NEEZY  ·  Copilot\n\nSelect a market and ask a question below. I’ll use the live signal context.\n",("intro",));self.chat.tag_configure("intro",foreground=self.MUTED);row=tk.Frame(p,bg=self.BG);row.pack(fill="x",pady=(12,0));self.prompt=tk.Entry(row,bg=self.PANEL2,fg=self.TEXT,insertbackground=self.TEXT,relief="flat",font=("Helvetica",11));self.prompt.pack(side="left",fill="x",expand=True,ipady=10);tk.Button(row,text="Ask",command=self._ask,bg=self.CYAN,fg=self.BG,relief="flat",font=("Helvetica",10,"bold"),padx=22,pady=9).pack(side="right",padx=(10,0))
    def _history_page(self):
        p=self.pages["HISTORY"];self._label(p,"Signal history",16).pack(anchor="w",pady=(5,16));self.hist=tk.Listbox(p,bg=self.PANEL,fg=self.TEXT,relief="flat",font=("Courier",10));self.hist.pack(fill="both",expand=True)
    def _settings_page(self):
        p=self.pages["SETTINGS"];self._label(p,"Workspace settings",16).pack(anchor="w",pady=(5,4));self._label(p,"Tune the workspace without leaving your market view.",10,self.MUTED).pack(anchor="w",pady=(0,16))
        grid=tk.Frame(p,bg=self.BG);grid.pack(fill="both",expand=True)
        left=self._panel(grid);left.pack(side="left",fill="both",expand=True,padx=(0,10));right=self._panel(grid);right.pack(side="right",fill="both",expand=True,padx=(10,0))
        self._label(left,"LIVE WORKSPACE",9,self.CYAN).pack(anchor="w",padx=18,pady=(18,12))
        for text,var in [("Auto-refresh signal feed",self.auto_refresh),("Desktop signal alerts",self.alerts_enabled),("Compact data density",self.compact_mode)]:
            tk.Checkbutton(left,text=text,variable=var,bg=self.PANEL,fg=self.TEXT,activebackground=self.PANEL,activeforeground=self.TEXT,selectcolor=self.PANEL2,anchor="w",font=("Helvetica",10),command=self._settings_changed).pack(fill="x",padx=14,pady=7)
        self._label(left,"Theme preset",10,self.MUTED).pack(anchor="w",padx=18,pady=(18,4));theme=ttk.Combobox(left,textvariable=self.theme_var,values=["Liquid dark","Midnight blue","High contrast"],state="readonly");theme.pack(fill="x",padx=18,pady=(0,18));theme.bind("<<ComboboxSelected>>",lambda e:self._settings_changed())
        self._label(right,"ENGINE & CONNECTION",9,self.CYAN).pack(anchor="w",padx=18,pady=(18,12));self._label(right,"Deriv public WebSocket",12).pack(anchor="w",padx=18,pady=(4,2));self._label(right,"App ID 1089 · live candles · reconnect enabled",10,self.MUTED).pack(anchor="w",padx=18,pady=(0,18));self._label(left,"STREAM CONTROLS",9,self.CYAN).pack(anchor="w",padx=18,pady=(8,12));self._label(left,"UI poll interval (ms)",10,self.MUTED).pack(anchor="w",padx=18,pady=(0,4));poll=tk.Spinbox(left,from_=50,to=2000,increment=50,textvariable=self.polling_var,bg=self.PANEL2,fg=self.TEXT,buttonbackground=self.PANEL2,relief="flat",command=self._settings_changed);poll.pack(fill="x",padx=18,pady=(0,10));self._label(left,"Max candles in memory",10,self.MUTED).pack(anchor="w",padx=18,pady=(0,4));limit=tk.Spinbox(left,from_=60,to=1000,increment=20,textvariable=self.candle_limit_var,bg=self.PANEL2,fg=self.TEXT,buttonbackground=self.PANEL2,relief="flat",command=self._settings_changed);limit.pack(fill="x",padx=18,pady=(0,18));self._label(right,"Signal engine",12).pack(anchor="w",padx=18,pady=(4,2));self._label(right,"EMA 9/21/50 · RSI 14 · ATR 14 · MACD",10,self.MUTED).pack(anchor="w",padx=18,pady=(0,18));tk.Button(right,text="Clear local signal history",command=self._clear_history,bg=self.PANEL2,fg=self.TEXT,relief="flat",font=("Helvetica",10),padx=12,pady=8).pack(anchor="w",padx=18,pady=(4,10));self.settings_status=self._label(right,"Ready",10,self.GREEN);self.settings_status.pack(anchor="w",padx=18,pady=(12,0))
    def _update_signal_cards(self):
        vals=list(self.results.values());active=[r for r in vals if r["signal"]!="NEUTRAL"];buys=sum("BUY" in r["signal"] for r in vals);sells=sum("SELL" in r["signal"] for r in vals);avg=(sum(abs(r["score"]) for r in vals)/len(vals)) if vals else 0
        for key,value in [("active",str(len(active))), ("buy",str(buys)), ("sell",str(sells)), ("confidence",f"{avg:.1f} / 4")]:self.card_values[key].config(text=value)
    def _settings_changed(self):
        try:self.settings=self.settings.updated(auto_refresh=self.auto_refresh.get(),alerts_enabled=self.alerts_enabled.get(),compact_mode=self.compact_mode.get(),theme=self.theme_var.get(),polling_ms=int(self.polling_var.get()),candle_limit=int(self.candle_limit_var.get()))
        except (ValueError, tk.TclError) as error:self.settings_status.config(text=str(error),fg=self.RED);return
        self.status_var.set("Settings updated");self.settings_status.config(text=f"Applied · {self.settings.polling_ms} ms · {self.settings.candle_limit} candles",fg=self.GREEN)

    def _clear_history(self):
        self.history.clear();self.hist.delete(0,"end");self.settings_status.config(text="Local signal history cleared",fg=self.GREEN)
    def _tf_changed(self):self.gran=TIMEFRAMES[self.tf.get()];self._subscribe_all();self.chart_title.config(text=f"{SYMBOLS[self.selected]}  ·  {self.tf.get()}")
    def _select(self):
        s=self.tree.selection();
        if s:self.selected=s[0];self._show_detail();self._draw_chart()
    def _watch_select(self):
        i=self.watch.curselection()
        if i:self.selected=list(SYMBOLS)[i[0]];self._tab("CHART");self.chart_title.config(text=f"{SYMBOLS[self.selected]}  ·  {self.tf.get()}");self._draw_chart()
    def _subscribe_all(self):
        self.client.send({"forget_all":"candles"});self.candles.clear();self.results.clear()
        for s,n in SYMBOLS.items():self.client.send({"ticks_history":s,"adjust_start_time":1,"count":HISTORY,"end":"latest","granularity":self.gran,"style":"candles","subscribe":1})
    def _poll(self):
        try:
            for _ in range(300):
                kind,data=self.inbox.get_nowait()
                if kind=="open":self.status.config(text="●  Connected",fg=self.GREEN);self.conn.config(text="●  Live feed",fg=self.GREEN);self._subscribe_all()
                elif kind=="status":self.status.config(text=data,fg=self.RED);self.conn.config(text="●  Offline",fg=self.RED)
                elif kind=="msg":self._handle(data)
        except queue.Empty:pass
        self.after(self.settings.polling_ms,self._poll)
    def _handle(self,msg):
        req=msg.get("echo_req",{});s=req.get("ticks_history") or msg.get("ohlc",{}).get("symbol")
        if msg.get("error") or s not in SYMBOLS:return
        if msg.get("msg_type")=="candles":self.candles[s]=[(int(c["epoch"]),float(c["open"]),float(c["high"]),float(c["low"]),float(c["close"])) for c in msg["candles"]];self._refresh(s)
        elif msg.get("msg_type")=="ohlc":
            o=msg["ohlc"];row=(int(o["open_time"]),float(o["open"]),float(o["high"]),float(o["low"]),float(o["close"]));lst=self.candles.setdefault(s,[]);lst[-1:]=[row] if lst and lst[-1][0]==row[0] else lst[-1:]+[row];del lst[:-self.settings.candle_limit];self._refresh(s)
    def _fmt(self,s,p):return f"{p:.3f}" if "JPY" in s else f"{p:.2f}" if s.startswith("R_") else f"{p:.5f}"
    def _refresh(self,s):
        cs=self.candles.get(s,[]);res=analyze(cs)
        if not res:return
        self.results[s]=res;sig=res["signal"];tag="buy" if "BUY" in sig else "sell" if "SELL" in sig else "";prev=self.last_signal.get(s)
        if prev and prev!=sig:
            line=f"{datetime.now():%Y-%m-%d %H:%M:%S}  {SYMBOLS[s]:<18} {prev} → {sig}  @ {self._fmt(s,cs[-1][4])}";self.history.insert(0,line);self.hist.insert(0,line)
        self.last_signal[s]=sig;self.tree.item(s,values=(SYMBOLS[s],self._fmt(s,cs[-1][4]),sig,f"{res['score']:+d}",f"{res['rsi']:.0f}" if res['rsi'] else "—",datetime.now().strftime("%H:%M:%S")),tags=(tag,) if tag else ());self._update_signal_cards()
        if s==self.selected:self._show_detail();self._draw_chart()
    def _show_detail(self):
        s=self.selected;res=self.results.get(s);cs=self.candles.get(s,[]);self.detail.config(state="normal");self.detail.delete("1.0","end")
        if not res or not cs:self.detail.insert("end","Collecting live candles…")
        else:
            sig=res["signal"];tag="buy" if "BUY" in sig else "sell" if "SELL" in sig else "";self.detail.insert("end",f"{SYMBOLS[s]}\n",());self.detail.insert("end",f"{sig}\n",("big",tag) if tag else ("big",));self.detail.insert("end",f"Score {res['score']:+d} / 4     Price {self._fmt(s,cs[-1][4])}\n\nWhy this signal\n",());self.detail.insert("end","\n".join("  · "+x for x in res["why"]));self.detail.insert("end",f"\n\nEMA 9    {self._fmt(s,res['ema9'])}\nEMA 21   {self._fmt(s,res['ema21'])}\nEMA 50   {self._fmt(s,res['ema50'])}\nATR 14   {self._fmt(s,res['atr'])}")
        self.detail.config(state="disabled")
    def _draw_chart(self):
        if not hasattr(self,"canvas"):return
        self.canvas.delete("all");cs=self.candles.get(self.selected,[])[-80:]
        if len(cs)<2:self.canvas.create_text(200,100,text="Waiting for live chart data…",fill=self.MUTED,anchor="w");return
        w=max(self.canvas.winfo_width(),500);h=max(self.canvas.winfo_height(),300);lo=min(x[3] for x in cs);hi=max(x[2] for x in cs);span=hi-lo or 1
        for i in range(5):
            y=30+i*(h-60)/4;self.canvas.create_line(0,y,w,y,fill="#19304b");self.canvas.create_text(w-8,y,text=f"{hi-(span*i/4):.4f}",fill=self.MUTED,anchor="e",font=("Helvetica",8))
        step=w/len(cs)
        for i,(t,o,high,low,c) in enumerate(cs):
            x=step*i+step/2;yo=h-30-(o-lo)/span*(h-60);yc=h-30-(c-lo)/span*(h-60);yh=h-30-(high-lo)/span*(h-60);yl=h-30-(low-lo)/span*(h-60);col=self.GREEN if c>=o else self.RED;self.canvas.create_line(x,yh,x,yl,fill=col);self.canvas.create_rectangle(x-3,min(yo,yc),x+3,max(yo,yc)+1,fill=col,outline=col)
    def _ask(self):
        q=self.prompt.get().strip()
        if not q:return
        res=self.results.get(self.selected);sig=res["signal"] if res else "collecting data";self.chat.insert("end",f"\nYOU\n{q}\n\nNEEZY\n{SYMBOLS[self.selected]} is currently {sig}. Review the score and indicator rationale in Signals before making any decision.\n");self.prompt.delete(0,"end")
    def _close(self):self.client.stop();self.destroy()

if __name__=="__main__":App().mainloop()
