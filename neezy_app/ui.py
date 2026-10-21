#!/usr/bin/env python3
"""NEEZY native trading workspace; live prices are supplied by Deriv's public API.

The application displays educational technical-analysis summaries. Its signals
are not investment advice. The ORDERS page can send a market order to a local
MetaTrader 5 terminal, but only after the saved MT5 bridge is on, the terminal
is confirmed live, and the user confirms the order in a dialog.
"""

from __future__ import annotations

import logging
import sqlite3
import tkinter as tk
from tkinter import ttk

from neezy_app.ui_panels.ai_settings import AiSettingsMixin
from neezy_app.ui_panels.alerts import AlertsMixin
from neezy_app.ui_panels.chat import ChatMixin
from neezy_app.ui_panels.constants import NAV, RESEARCH_CONTROLS
from neezy_app.ui_panels.data_providers import DataProvidersMixin
from neezy_app.ui_panels.database import DatabaseMixin
from neezy_app.ui_panels.history import HistoryMixin
from neezy_app.ui_panels.insights import InsightsMixin
from neezy_app.ui_panels.integrations import IntegrationsMixin
from neezy_app.ui_panels.local_models import LocalModelsMixin
from neezy_app.ui_panels.market import MarketMixin
from neezy_app.ui_panels.mcp import McpMixin
from neezy_app.ui_panels.orders import OrdersMixin
from neezy_app.ui_panels.remote import RemoteMixin
from neezy_app.ui_panels.settings import SettingsMixin
from neezy_app.ui_panels.signals import SignalsMixin
from neezy_app.ui_panels.telegram import TelegramMixin
from neezy_app.ui_panels.tools_page import ToolsPageMixin
from neezy_backend.ai import (
    PROVIDERS,
    AIClient,
    AIKeyStore,
    free_models,
)
from neezy_backend.alerts import (
    AlertEngine,
    AlertRuleStore,
)
from neezy_backend.config import AppSettings
from neezy_backend.events import EventBus
from neezy_backend.local_llm import (
    LocalModelRegistry,
    runtime_status,
)
from neezy_backend.markets import (
    TIMEFRAMES,
    watchlist,
    ws_urls,
)
from neezy_backend.mcp import MCPServer, MCPTokenStore
from neezy_backend.mcp_tools import register_app_tools, register_public_app_tools
from neezy_backend.providers import (
    ProviderKeyStore,
)
from neezy_backend.remote import AppCommandBridge
from neezy_backend.scanner import ConfluenceAnalyzer
from neezy_backend.storage import (
    ConfluenceHistoryStore,
    SettingsStore,
    SignalHistoryStore,
    get_data_dir,
)
from neezy_backend.stream import DerivStreamClient
from neezy_backend.telegram import (
    TelegramBotService,
    TelegramTokenStore,
)
from neezy_backend.tools import ToolRegistry
from neezy_backend.tunnel import CloudflareQuickTunnel

logger = logging.getLogger(__name__)


class App(
    MarketMixin,
    SignalsMixin,
    InsightsMixin,
    ChatMixin,
    ToolsPageMixin,
    AlertsMixin,
    HistoryMixin,
    DatabaseMixin,
    SettingsMixin,
    AiSettingsMixin,
    LocalModelsMixin,
    DataProvidersMixin,
    McpMixin,
    TelegramMixin,
    RemoteMixin,
    IntegrationsMixin,
    OrdersMixin,
    tk.Tk,
):
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
        self.confluence_store = ConfluenceHistoryStore()
        self.provider_keys = ProviderKeyStore()
        self.analyzer = ConfluenceAnalyzer(settings=self.settings)
        self.settings = self.settings_store.load()
        self.db = self._open_database()
        self.command_bridge = AppCommandBridge(timeout=15.0)
        self.remote_registry = register_app_tools(
            ToolRegistry(), self.db, self.command_bridge
        )
        self.public_remote_registry = register_public_app_tools(self.remote_registry)
        self.mcp_token_store = MCPTokenStore()
        self.mcp_public_token_store = MCPTokenStore(
            get_data_dir() / "mcp-public-token.json"
        )
        self.mcp_server: MCPServer | None = None
        self._mcp_server_port: int | None = None
        self.mcp_public_server: MCPServer | None = None
        self.mcp_tunnel_service = CloudflareQuickTunnel()
        self._mcp_tunnel_signature: tuple[str, int] | None = None
        self._mcp_tunnel_poll_scheduled = False
        self.local_model_registry = LocalModelRegistry()
        self._local_model_labels: dict[str, str] = {}
        self._local_model_status_cache = runtime_status()
        self.telegram_token_store = TelegramTokenStore()
        self.telegram_service: TelegramBotService | None = None
        self._telegram_service_signature: tuple[str, tuple[str, ...]] | None = None
        self._telegram_testing = False
        self._brain_training = False
        self.ai_keys = AIKeyStore()
        self.ai_client = AIClient(
            self.ai_keys,
            recorder=self.db.record_ai_call if self.db is not None else None,
        )
        self._snapshot_at = {}
        self._ai_key_rows = []
        try:
            self.watch_symbols = watchlist(self.settings.watchlist_extra)
        except ValueError as error:
            logger.warning("Ignoring saved extra markets: %s", error)
            self.watch_symbols = watchlist()
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
        self._analysis_running = False
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
        self.watchlist_var = tk.StringVar(value=self.settings.watchlist_extra)
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
        self.data_provider_var = tk.StringVar(value=self.settings.market_data_provider)
        self.provider_key_var = tk.StringVar()
        self.provider_count_var = tk.IntVar(value=self.settings.provider_candle_count)
        self.conf_min_score_var = tk.DoubleVar(value=self.settings.confluence_min_score)
        self.conf_search_score_var = tk.DoubleVar(
            value=self.settings.confluence_search_score
        )
        self.conf_stop_var = tk.DoubleVar(value=self.settings.confluence_atr_stop_mult)
        self.conf_tp_var = tk.DoubleVar(value=self.settings.confluence_atr_tp_mult)
        self.conf_horizon_var = tk.IntVar(value=self.settings.confluence_horizon)
        self.conf_min_analogs_var = tk.IntVar(
            value=self.settings.confluence_min_analogs
        )
        self.use_knowledge_var = tk.BooleanVar(value=self.settings.use_knowledge)
        self.use_memory_var = tk.BooleanVar(value=self.settings.use_memory)
        self.research_vars = {
            name: (
                tk.IntVar
                if isinstance(getattr(self.settings, name), int)
                else tk.DoubleVar
            )(value=getattr(self.settings, name))
            for name, *_rest in RESEARCH_CONTROLS
        }
        self._research_running = False
        self.research_market_var = tk.StringVar(value="frxEURUSD")
        self.pair_reference_var = tk.StringVar(value="frxGBPUSD")
        self.use_brain_var = tk.BooleanVar(value=self.settings.use_brain_model)
        self.mcp_enabled_var = tk.BooleanVar(value=self.settings.mcp_enabled)
        self.mcp_port_var = tk.IntVar(value=self.settings.mcp_port)
        self.mcp_writes_var = tk.BooleanVar(value=self.settings.mcp_allow_writes)
        self.mcp_url_var = tk.StringVar(
            value=f"http://127.0.0.1:{self.settings.mcp_port}/mcp"
        )
        self.mcp_token_var = tk.StringVar(value=self.mcp_token_store.load() or "")
        self.mcp_tunnel_enabled_var = tk.BooleanVar(
            value=self.settings.mcp_tunnel_enabled
        )
        self.mcp_tunnel_executable_var = tk.StringVar(
            value=self.settings.mcp_tunnel_executable
        )
        self.mcp_public_url_var = tk.StringVar(value="Not running")
        self.mcp_public_token_var = tk.StringVar(
            value=self.mcp_public_token_store.load() or ""
        )
        self.local_llm_enabled_var = tk.BooleanVar(
            value=self.settings.local_llm_enabled
        )
        self.local_llm_model_var = tk.StringVar()
        self.local_llm_context_var = tk.IntVar(
            value=self.settings.local_llm_context_tokens
        )
        self.local_llm_tokens_var = tk.IntVar(value=self.settings.local_llm_max_tokens)
        self.local_llm_threads_var = tk.IntVar(value=self.settings.local_llm_threads)
        self.local_llm_batch_var = tk.IntVar(value=self.settings.local_llm_batch_size)
        self.local_llm_disk_offload_var = tk.BooleanVar(
            value=self.settings.local_llm_disk_offload
        )
        self.local_llm_memory_var = tk.IntVar(
            value=self.settings.local_llm_cpu_memory_mb
        )
        self._local_model_selection_labels: list[str] = []
        self.telegram_enabled_var = tk.BooleanVar(value=self.settings.telegram_enabled)
        self.telegram_chat_ids_var = tk.StringVar(value=self.settings.telegram_chat_ids)
        self.telegram_alerts_var = tk.BooleanVar(
            value=self.settings.telegram_alerts_enabled
        )
        self.telegram_commands_var = tk.BooleanVar(
            value=self.settings.telegram_allow_commands
        )
        self.telegram_token_var = tk.StringVar(value="")

        self.mt5_enabled_var = tk.BooleanVar(value=self.settings.mt5_enabled)
        self.mt5_server_var = tk.StringVar(value=self.settings.mt5_server)
        self.mt5_login_var = tk.IntVar(value=self.settings.mt5_login)
        self.mt5_password_var = tk.StringVar(value=self.settings.mt5_password)
        self.mt5_path_var = tk.StringVar(value=self.settings.mt5_path)
        self.mt5_magic_var = tk.IntVar(value=self.settings.mt5_magic)
        self.mt5_symbol_map_var = tk.StringVar(value=self.settings.mt5_symbol_map)
        self.mt5_auto_sync_var = tk.BooleanVar(value=self.settings.mt5_auto_sync)

        self.dm_enabled_var = tk.BooleanVar(value=self.settings.dm_enabled)
        self.dm_webhook_url_var = tk.StringVar(value=self.settings.dm_webhook_url)
        self.dm_min_score_var = tk.IntVar(value=self.settings.dm_min_score)
        self.dm_notify_signals_var = tk.BooleanVar(
            value=self.settings.dm_notify_signals
        )
        self.dm_notify_alerts_var = tk.BooleanVar(value=self.settings.dm_notify_alerts)
        self.default_risk_percent_var = tk.DoubleVar(
            value=self.settings.default_risk_percent
        )
        self.max_drawdown_limit_var = tk.DoubleVar(
            value=self.settings.max_drawdown_limit
        )
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
        self._sync_mcp_server()
        self._sync_telegram_service()
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
        self._insights_page()
        self._symbols_page()
        self._chart_page()
        self._chat_page()
        self._tools_page()
        self._orders_page()
        self._alerts_page()
        self._history_page()
        self._settings_page()
        self.nb.select(self.pages["SIGNALS"])

    def _tab(self, name):
        self.nb.select(self.pages[name])
        for button in self.nav.values():
            button.configure(fg=self.MUTED, bg=self.BG)
        self.nav[name].configure(fg=self.CYAN, bg=self.PANEL2)

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

    def _copy_text(self, text, message):
        if not text:
            self.settings_status.config(text="Nothing to copy yet", fg=self.RED)
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.settings_status.config(text=message, fg=self.GREEN)
        except tk.TclError as error:
            self.settings_status.config(
                text=f"Clipboard unavailable: {error}", fg=self.RED
            )

    def _bind_commit(self, widget):
        """Persist typed values too, not only arrow-button changes."""
        widget.bind("<Return>", lambda _: self._settings_changed())
        widget.bind("<FocusOut>", lambda _: self._settings_changed())

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
                watchlist_extra=self.watchlist_var.get().strip(),
                market_data_provider=self._data_provider_key(),
                provider_candle_count=int(self.provider_count_var.get()),
                confluence_min_score=float(self.conf_min_score_var.get()),
                confluence_search_score=float(self.conf_search_score_var.get()),
                confluence_atr_stop_mult=float(self.conf_stop_var.get()),
                confluence_atr_tp_mult=float(self.conf_tp_var.get()),
                confluence_horizon=int(self.conf_horizon_var.get()),
                confluence_min_analogs=int(self.conf_min_analogs_var.get()),
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
                use_knowledge=self.use_knowledge_var.get(),
                use_memory=self.use_memory_var.get(),
                use_brain_model=self.use_brain_var.get(),
                local_llm_enabled=self.local_llm_enabled_var.get(),
                local_llm_model_id=self._local_model_labels.get(
                    self.local_llm_model_var.get(), ""
                ),
                local_llm_context_tokens=int(self.local_llm_context_var.get()),
                local_llm_max_tokens=int(self.local_llm_tokens_var.get()),
                local_llm_threads=int(self.local_llm_threads_var.get()),
                local_llm_batch_size=int(self.local_llm_batch_var.get()),
                local_llm_disk_offload=self.local_llm_disk_offload_var.get(),
                local_llm_cpu_memory_mb=int(self.local_llm_memory_var.get()),
                mcp_enabled=self.mcp_enabled_var.get(),
                mcp_port=int(self.mcp_port_var.get()),
                mcp_allow_writes=self.mcp_writes_var.get(),
                mcp_tunnel_enabled=self.mcp_tunnel_enabled_var.get(),
                mcp_tunnel_executable=self.mcp_tunnel_executable_var.get().strip(),
                telegram_enabled=self.telegram_enabled_var.get(),
                telegram_chat_ids=self.telegram_chat_ids_var.get().strip(),
                telegram_alerts_enabled=self.telegram_alerts_var.get(),
                telegram_allow_commands=self.telegram_commands_var.get(),
                mt5_enabled=self.mt5_enabled_var.get(),
                mt5_server=self.mt5_server_var.get().strip(),
                mt5_login=int(self.mt5_login_var.get()),
                mt5_password=self.mt5_password_var.get(),
                mt5_path=self.mt5_path_var.get().strip(),
                mt5_magic=int(self.mt5_magic_var.get()),
                mt5_symbol_map=self.mt5_symbol_map_var.get().strip(),
                mt5_auto_sync=self.mt5_auto_sync_var.get(),
                dm_enabled=self.dm_enabled_var.get(),
                dm_webhook_url=self.dm_webhook_url_var.get().strip(),
                dm_min_score=int(self.dm_min_score_var.get()),
                dm_notify_signals=self.dm_notify_signals_var.get(),
                dm_notify_alerts=self.dm_notify_alerts_var.get(),
                default_risk_percent=float(self.default_risk_percent_var.get()),
                max_drawdown_limit=float(self.max_drawdown_limit_var.get()),
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
                **{
                    name: (
                        int(var.get())
                        if isinstance(getattr(self.settings, name), int)
                        else float(var.get())
                    )
                    for name, var in self.research_vars.items()
                },
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
            candidate.watchlist_extra,
        ) != (
            self.settings.deriv_endpoint,
            self.settings.reconnect_seconds,
            self.settings.max_reconnect_seconds,
            self.settings.watchlist_extra,
        )
        self.settings = candidate
        self._apply_theme()
        self._sync_mcp_server()
        self._sync_telegram_service()
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
            summary += " · connection and watchlist changes apply after restart"
        self.settings_status.config(text=summary, fg=self.GREEN)

    def _close(self):
        self.client.stop()
        self._stop_mcp_server()
        self._stop_telegram_service()
        self.command_bridge.close()
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
