#!/usr/bin/env python3
"""NEEZY native trading workspace; live prices are supplied by Deriv's public API.

The application displays educational technical-analysis summaries. Its signals
are not investment advice. The ORDERS page can send a market order to a local
MetaTrader 5 terminal, but only after the saved MT5 bridge is on, the terminal
is confirmed live, and the user confirms the order in a dialog.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from neezy_app.theme import (
    DEFAULT_THEME,
    THEME_CANVAS_BG,
    palette_for,
)
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
from neezy_backend.config import AppSettings, apply_profile
from neezy_backend.events import EventBus
from neezy_backend.local_llm import (
    LocalModelRegistry,
    runtime_status,
)
from neezy_backend.markets import (
    SYMBOLS,
    TIMEFRAMES,
    watchlist,
    ws_urls,
)
from neezy_backend.mcp import MCPServer, MCPTokenStore
from neezy_backend.mcp_tools import register_app_tools, register_public_app_tools
from neezy_backend.mt5_bridge import get_global_mt5_bridge
from neezy_backend.providers import (
    ProviderKeyStore,
    resolve_provider,
)
from neezy_backend.remote import AppCommandBridge
from neezy_backend.scanner import ConfluenceAnalyzer
from neezy_backend.storage import (
    ConfluenceHistoryStore,
    SettingsStore,
    SignalHistoryStore,
    create_local_backup,
    get_data_dir,
    restore_local_backup,
)
from neezy_backend.stream import DerivStreamClient
from neezy_backend.telegram import (
    TelegramBotService,
    TelegramTokenStore,
)
from neezy_backend.tools import ToolRegistry
from neezy_backend.tunnel import CloudflareQuickTunnel

logger = logging.getLogger(__name__)


def _tk_var_for(value: Any) -> tk.Variable:
    if isinstance(value, bool):
        return tk.BooleanVar(value=value)
    if isinstance(value, int):
        return tk.IntVar(value=value)
    if isinstance(value, float):
        return tk.DoubleVar(value=value)
    return tk.StringVar(value=str(value))


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

    _EXTRA_SETTING_FIELDS = (
        # Workspace & UX
        "colorblind_palette",
        "reduced_motion",
        "ui_scale_percent",
        "font_size_offset",
        "remember_window_geometry",
        "startup_page",
        "startup_symbol",
        "display_timezone",
        "price_flash_on_tick",
        "dim_ui_when_offline",
        "stale_tick_timeout_seconds",
        "confirm_on_exit",
        # Chart & Visuals
        "chart_visible_candles",
        "chart_style",
        "chart_show_ema_fast",
        "chart_ema_fast_period",
        "chart_show_ema_slow",
        "chart_ema_slow_period",
        "chart_show_ema_trend",
        "chart_ema_trend_period",
        "chart_show_bollinger",
        "chart_show_sr_levels",
        "chart_sr_count",
        "chart_show_pivots",
        "chart_show_entry_sl_tp",
        "chart_show_session_boxes",
        "chart_subpane_oscillator",
        "chart_show_crosshair",
        "chart_show_grid",
        "chart_mark_candle_gaps",
        # Engine & Indicators
        "live_signal_source",
        "indicator_ema_fast",
        "indicator_ema_mid",
        "indicator_ema_slow",
        "indicator_rsi_period",
        "indicator_rsi_oversold",
        "indicator_rsi_overbought",
        "indicator_atr_period",
        "indicator_adx_trend_threshold",
        "bollinger_period",
        "bollinger_std",
        "donchian_period",
        "keltner_period",
        "consensus_net_threshold",
        # Storage & Exports
        "snapshot_interval_seconds",
        "auto_prune_on_startup",
        "auto_backup_enabled",
        "max_backup_count",
        "max_signal_history_rows",
        "csv_delimiter",
        "cache_max_size_mb",
        # AI & Agentic Copilot
        "ai_fallback_provider",
        "ai_allow_custom_models",
        "ai_cache_enabled",
        "ai_cache_ttl_seconds",
        "ai_chat_history_turns",
        "ai_daily_request_cap",
        "agent_mode_enabled",
        "agent_max_steps",
        "agent_require_write_confirmation",
        # ML & Backtest Research extras
        "ml_model_architecture",
        "ml_ensemble_members",
        "ml_sequence_window",
        "backtest_default_spread_pips",
        "outcome_eval_horizon",
        # Local Models extras
        "local_llm_gpu_layers",
        "local_llm_top_p",
        "local_llm_repeat_penalty",
        "local_llm_keep_alive_minutes",
        "local_llm_seed",
        "local_llm_verify_sha256",
        # MCP Server extras
        "mcp_rate_limit_rpm",
        "mcp_tool_timeout_seconds",
        "mcp_strict_origin_check",
        "mcp_audit_log_enabled",
        # Alerts & Quiet Hours
        "alert_sound_mode",
        "alert_cooldown_seconds",
        "toast_notifications_enabled",
        "toast_duration_ms",
        "quiet_hours_enabled",
        "quiet_hours_start",
        "quiet_hours_end",
        "alert_on_stream_disconnect",
        "alert_on_drawdown_breach",
        "auto_disable_one_shot_price_alerts",
        # Telegram extras
        "telegram_min_signal_score",
        "telegram_include_sl_tp_levels",
        "telegram_daily_digest_enabled",
        "telegram_digest_hour_utc",
        # MT5 Bridge extras
        "mt5_order_deviation_points",
        "mt5_filling_mode",
        "mt5_sync_interval_seconds",
        # Direct Messaging extras
        "dm_webhook_format",
        "dm_https_only",
        # Risk & Order Safety
        "account_balance_default",
        "account_currency",
        "default_reward_to_risk",
        "default_pip_value_per_lot",
        "fx_risk_percent",
        "synthetic_risk_percent",
        "crypto_risk_percent",
        "order_dry_run_mode",
        "require_stop_loss_on_live_orders",
        "max_lot_size_cap",
        "max_open_positions",
        "daily_max_loss_percent",
        "daily_max_trades",
        "min_rr_for_live_order",
        "pre_trade_checklist_enabled",
        "pre_trade_checklist_items",
        # Data Providers & Confluence extras
        "fallback_data_provider",
        "provider_cache_enabled",
        "provider_cache_ttl_seconds",
        "provider_requests_per_minute",
        "confluence_require_strict_only",
        "confluence_mtf_confirmation",
        "confluence_higher_timeframe",
        # Profiles & Diagnostics
        "active_settings_profile",
        "log_level",
    )

    def __init__(self):
        super().__init__()
        self.title("NEEZY / Market Intelligence")
        self.geometry("1280x800")
        self.minsize(1050, 650)
        self.settings_store = SettingsStore()
        self.settings = self.settings_store.load()
        self._apply_runtime_log_and_scale()
        self.history_store = SignalHistoryStore(
            keep_records=self.settings.max_signal_history_rows
        )
        self.confluence_store = ConfluenceHistoryStore(
            keep_records=self.settings.max_signal_history_rows
        )
        self.provider_keys = ProviderKeyStore()
        self.analyzer = ConfluenceAnalyzer(settings=self.settings)
        self.db = self._open_database()
        if self.db is not None and self.settings.auto_prune_on_startup:
            try:
                self.db.prune()
            except (sqlite3.Error, ValueError) as error:
                logger.warning("Startup database prune skipped: %s", error)
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
        self._mt5_sync_scheduled = False
        self.local_model_registry = LocalModelRegistry()
        self._local_model_labels: dict[str, str] = {}
        self._local_model_status_cache = runtime_status()
        self.telegram_token_store = TelegramTokenStore()
        self.telegram_service: TelegramBotService | None = None
        self._telegram_service_signature: tuple[str, tuple[str, ...]] | None = None
        self._telegram_testing = False
        self._brain_training = False
        self._chat_history_turns: list[dict[str, str]] = []
        self._ai_cache: dict[str, tuple[float, str]] = {}
        self._ai_requests_today = 0
        self._provider_candle_cache: dict[tuple[str, str, str], tuple[float, list]] = {}
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
        self.alert_engine = AlertEngine(
            self.alert_store.load(),
            cooldown_seconds=self.settings.alert_cooldown_seconds,
        )
        self.gran = TIMEFRAMES[self.settings.default_timeframe]
        self.candles = {}
        self.results = {}
        self.price_action = {}
        self._backtest_running = False
        self._analysis_running = False
        self.last_signal = {}
        self.selected = (
            self.settings.startup_symbol
            if self.settings.startup_symbol in SYMBOLS
            else "frxEURUSD"
        )
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
        self.extra_vars: dict[str, tk.Variable] = {
            name: _tk_var_for(getattr(self.settings, name))
            for name in self._EXTRA_SETTING_FIELDS
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
        self._schedule_mt5_sync()
        self.client.start()
        self.after(100, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _apply_runtime_log_and_scale(self) -> None:
        level = getattr(logging, self.settings.log_level, logging.INFO)
        logging.getLogger().setLevel(level)
        try:
            self.tk.call("tk", "scaling", self.settings.ui_scale_percent / 75.0)
        except (tk.TclError, AttributeError):
            pass

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
            padding=(12, 8),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.PANEL2)],
            foreground=[("selected", self.CYAN)],
        )

    def _apply_theme(self):
        current_settings = getattr(self, "settings", AppSettings())
        palette = palette_for(
            current_settings.theme,
            colorblind=current_settings.colorblind_palette,
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
            canvas_bg = THEME_CANVAS_BG.get(
                self.theme_var.get(), THEME_CANVAS_BG[DEFAULT_THEME]
            )
            self.canvas.configure(bg=canvas_bg)
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
        offset = int(getattr(self.settings, "font_size_offset", 0))
        return tk.Label(
            p,
            text=text,
            bg=p.cget("bg"),
            fg=color or self.TEXT,
            font=("Helvetica", max(7, size + offset)),
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
        initial = (
            self.settings.startup_page
            if self.settings.startup_page in NAV
            else "SIGNALS"
        )
        self.nav[initial].configure(fg=self.CYAN, bg=self.PANEL2)
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
        initial = (
            self.settings.startup_page
            if self.settings.startup_page in NAV
            else "SIGNALS"
        )
        self.nb.select(self.pages[initial])

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

    def _cast_extra_var(self, field_name: str) -> Any:
        default = getattr(self.settings, field_name)
        raw = self.extra_vars[field_name].get()
        if isinstance(default, bool):
            return bool(raw)
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
        return str(raw).strip()

    def _sync_vars_from_settings(self, s: AppSettings) -> None:
        """Synchronize every Tkinter control variable from an ``AppSettings``."""
        self.auto_refresh.set(s.auto_refresh)
        self.alerts_enabled.set(s.alerts_enabled)
        self.compact_mode.set(s.compact_mode)
        self.theme_var.set(s.theme)
        self.polling_var.set(s.polling_ms)
        self.candle_limit_var.set(s.candle_limit)
        self.alert_min_score_var.set(s.alert_min_score)
        self.default_tf_var.set(s.default_timeframe)
        self.history_var.set(s.history_candles)
        self.watchlist_var.set(s.watchlist_extra)
        self.endpoint_var.set(s.deriv_endpoint)
        self.reconnect_var.set(s.reconnect_seconds)
        self.max_reconnect_var.set(s.max_reconnect_seconds)
        self.strategy_var.set(s.strategy)
        self.st_period_var.set(s.supertrend_period)
        self.st_mult_var.set(s.supertrend_multiplier)
        self.div_lookback_var.set(s.divergence_lookback)
        self.corr_window_var.set(s.correlation_window)
        self.corr_baseline_var.set(s.correlation_baseline)
        self.overlay_var.set(s.show_strategy_overlay)
        prov = resolve_provider(s.market_data_provider)
        self.data_provider_var.set(f"{prov.label} ({prov.key})")
        self.provider_count_var.set(s.provider_candle_count)
        self.conf_min_score_var.set(s.confluence_min_score)
        self.conf_search_score_var.set(s.confluence_search_score)
        self.conf_stop_var.set(s.confluence_atr_stop_mult)
        self.conf_tp_var.set(s.confluence_atr_tp_mult)
        self.conf_horizon_var.set(s.confluence_horizon)
        self.conf_min_analogs_var.set(s.confluence_min_analogs)
        self.use_knowledge_var.set(s.use_knowledge)
        self.use_memory_var.set(s.use_memory)
        self.use_brain_var.set(s.use_brain_model)
        self.mcp_enabled_var.set(s.mcp_enabled)
        self.mcp_port_var.set(s.mcp_port)
        self.mcp_writes_var.set(s.mcp_allow_writes)
        self.mcp_tunnel_enabled_var.set(s.mcp_tunnel_enabled)
        self.mcp_tunnel_executable_var.set(s.mcp_tunnel_executable)
        self.local_llm_enabled_var.set(s.local_llm_enabled)
        self.local_llm_context_var.set(s.local_llm_context_tokens)
        self.local_llm_tokens_var.set(s.local_llm_max_tokens)
        self.local_llm_threads_var.set(s.local_llm_threads)
        self.local_llm_batch_var.set(s.local_llm_batch_size)
        self.local_llm_disk_offload_var.set(s.local_llm_disk_offload)
        self.local_llm_memory_var.set(s.local_llm_cpu_memory_mb)
        self.telegram_enabled_var.set(s.telegram_enabled)
        self.telegram_chat_ids_var.set(s.telegram_chat_ids)
        self.telegram_alerts_var.set(s.telegram_alerts_enabled)
        self.telegram_commands_var.set(s.telegram_allow_commands)
        self.mt5_enabled_var.set(s.mt5_enabled)
        self.mt5_server_var.set(s.mt5_server)
        self.mt5_login_var.set(s.mt5_login)
        self.mt5_password_var.set(s.mt5_password)
        self.mt5_path_var.set(s.mt5_path)
        self.mt5_magic_var.set(s.mt5_magic)
        self.mt5_symbol_map_var.set(s.mt5_symbol_map)
        self.mt5_auto_sync_var.set(s.mt5_auto_sync)
        self.dm_enabled_var.set(s.dm_enabled)
        self.dm_webhook_url_var.set(s.dm_webhook_url)
        self.dm_min_score_var.set(s.dm_min_score)
        self.dm_notify_signals_var.set(s.dm_notify_signals)
        self.dm_notify_alerts_var.set(s.dm_notify_alerts)
        self.default_risk_percent_var.set(s.default_risk_percent)
        self.max_drawdown_limit_var.set(s.max_drawdown_limit)
        self.store_candles_var.set(s.store_candles)
        self.retention_var.set(s.retention_days)
        self.snapshots_var.set(s.save_snapshots)
        self.ai_enabled_var.set(s.ai_enabled)
        self.ai_provider_var.set(self._provider_label(s.ai_provider))
        self.ai_model_var.set(s.ai_model or free_models(s.ai_provider)[0])
        self.ai_base_var.set(s.ai_base_url)
        self.ai_temp_var.set(s.ai_temperature)
        self.ai_tokens_var.set(s.ai_max_tokens)
        self.ai_timeout_var.set(s.ai_timeout)
        self.ai_system_var.set(s.ai_system_prompt)
        for name, var in self.research_vars.items():
            var.set(getattr(s, name))
        for name, var in self.extra_vars.items():
            var.set(getattr(s, name))

    def _reload_stream_and_watchlist(self, candidate: AppSettings) -> None:
        """Hot-reload WebSocket connection & active watchlist without restart."""
        self.watch_symbols = watchlist(candidate.watchlist_extra)
        if hasattr(self, "watch"):
            self.watch.delete(0, "end")
            for sym, title in self.watch_symbols.items():
                self.watch.insert("end", f"  {title:<22}  {sym}")
        if hasattr(self, "tree"):
            existing = set(self.tree.get_children() or ())
            for sym, title in self.watch_symbols.items():
                if sym not in existing:
                    self.tree.insert(
                        "",
                        "end",
                        iid=sym,
                        values=(title, "—", "Loading", "—", "—", "—", "—"),
                    )
            for stale in existing - set(self.watch_symbols):
                self.tree.delete(stale)
        if hasattr(self, "chart_symbol_var"):
            self.chart_symbol_combo.configure(values=list(self.watch_symbols))
        self.client.stop()
        self.client = DerivStreamClient(
            ws_urls(candidate.deriv_endpoint),
            self.bus,
            reconnect_seconds=candidate.reconnect_seconds,
            max_reconnect_seconds=candidate.max_reconnect_seconds,
        )
        self.client.start()

    def _schedule_mt5_sync(self) -> None:
        if self._mt5_sync_scheduled or not self.winfo_exists():
            return
        self._mt5_sync_scheduled = True
        delay_ms = max(1, int(self.settings.mt5_sync_interval_seconds)) * 1000
        self.after(delay_ms, self._run_mt5_auto_sync)

    def _run_mt5_auto_sync(self) -> None:
        self._mt5_sync_scheduled = False
        if not self.winfo_exists():
            return
        if self.settings.mt5_enabled and self.settings.mt5_auto_sync:

            def worker() -> None:
                try:
                    bridge = get_global_mt5_bridge()
                    status = bridge.connect()
                    account = bridge.get_account_info() if status.get("success") else {}
                except Exception as exc:  # noqa: BLE001
                    status = {"success": False, "error": str(exc)}
                    account = {}
                self.after(0, lambda: self._apply_mt5_sync(status, account))

            threading.Thread(target=worker, name="neezy-mt5-sync", daemon=True).start()
        self._schedule_mt5_sync()

    def _apply_mt5_sync(self, status: dict[str, Any], account: dict[str, Any]) -> None:
        if not hasattr(self, "mt5_status_label"):
            return
        if status.get("success"):
            bal = account.get("balance")
            eq = account.get("equity")
            cur = account.get("currency", self.settings.account_currency)
            summary = f"Auto-synced · Account {status.get('account')}"
            if isinstance(bal, (int, float)) and isinstance(eq, (int, float)):
                summary += f" · Balance {bal:,.2f} {cur} · Equity {eq:,.2f} {cur}"
                if bal > 0 and self.settings.alert_on_drawdown_breach:
                    dd_pct = max(0.0, (bal - eq) / bal * 100.0)
                    if dd_pct >= self.settings.max_drawdown_limit:
                        summary += f" · DRAWDOWN {dd_pct:.1f}%!"
            self.mt5_status_label.config(text=summary, fg=self.GREEN)
        else:
            self.mt5_status_label.config(
                text=f"MT5 auto-sync waiting: {status.get('error', 'offline')}",
                fg=self.MUTED,
            )

    def _apply_profile_preset(self, profile_name: str | None = None) -> None:
        chosen = profile_name or str(self.extra_vars["active_settings_profile"].get())
        try:
            updated = apply_profile(self.settings, chosen)
            self._sync_vars_from_settings(updated)
            self._settings_changed()
            self.settings_status.config(
                text=f"Applied profile '{chosen}' and saved locally", fg=self.GREEN
            )
        except ValueError as error:
            self.settings_status.config(text=str(error), fg=self.RED)

    def _reset_settings_to_defaults(self) -> None:
        if not messagebox.askyesno(
            "Reset settings",
            "Reset workspace settings to defaults (API keys & tokens stay intact)?",
        ):
            return
        defaults = apply_profile(self.settings, "Default")
        self._sync_vars_from_settings(defaults)
        self._settings_changed()
        self.settings_status.config(
            text="Settings reset to factory defaults (API keys preserved)",
            fg=self.GREEN,
        )

    def _rollback_previous_settings(self) -> None:
        restored = self.settings_store.rollback_latest()
        if restored is None:
            self.settings_status.config(
                text="No prior settings revision available yet", fg=self.MUTED
            )
            return
        self._sync_vars_from_settings(restored)
        self._settings_changed()
        self.settings_status.config(
            text="Rolled back to previous saved settings revision", fg=self.GREEN
        )

    def _export_settings_json(self) -> None:
        dest = filedialog.asksaveasfilename(
            title="Export NEEZY settings JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile="neezy-settings.json",
        )
        if not dest:
            return
        payload = self.settings.to_dict()
        payload.pop("mt5_password", None)
        payload["dm_webhook_url"] = ""
        Path(dest).write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.settings_status.config(
            text=f"Exported redacted settings JSON to {dest}", fg=self.GREEN
        )

    def _import_settings_json(self) -> None:
        src = filedialog.askopenfilename(
            title="Import NEEZY settings JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not src:
            return
        try:
            raw = json.loads(Path(src).read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("Settings JSON must contain an object")
            merged = self.settings.to_dict()
            for key, val in raw.items():
                if key in AppSettings.__dataclass_fields__ and key not in {
                    "mt5_password",
                    "dm_webhook_url",
                }:
                    merged[key] = val
            loaded = AppSettings.from_dict(merged)
            self._sync_vars_from_settings(loaded)
            self._settings_changed()
            self.settings_status.config(
                text=f"Imported settings from {Path(src).name}", fg=self.GREEN
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            self.settings_status.config(text=f"Import failed: {error}", fg=self.RED)

    def _create_backup_archive(self) -> None:
        dest = filedialog.asksaveasfilename(
            title="Create NEEZY local backup zip",
            defaultextension=".zip",
            filetypes=[("Zip archive", "*.zip")],
            initialfile="neezy_backup.zip",
        )
        if not dest:
            return
        try:
            written = create_local_backup(
                dest, max_backups=self.settings.max_backup_count
            )
            self.settings_status.config(
                text=f"Local backup created: {written}", fg=self.GREEN
            )
        except OSError as error:
            self.settings_status.config(text=f"Backup failed: {error}", fg=self.RED)

    def _restore_backup_archive(self) -> None:
        src = filedialog.askopenfilename(
            title="Restore NEEZY local backup zip",
            filetypes=[("Zip archive", "*.zip")],
        )
        if not src:
            return
        if not messagebox.askyesno(
            "Restore local backup",
            "Overwrite local settings, rules, and databases from this backup archive?",
        ):
            return
        try:
            files = restore_local_backup(src)
            reloaded = self.settings_store.load()
            self._sync_vars_from_settings(reloaded)
            self._settings_changed()
            self.settings_status.config(
                text=f"Restored {len(files)} file(s) from backup", fg=self.GREEN
            )
        except (OSError, ValueError) as error:
            self.settings_status.config(text=f"Restore failed: {error}", fg=self.RED)

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
                **{
                    name: self._cast_extra_var(name)
                    for name in self._EXTRA_SETTING_FIELDS
                },
            )
            self.settings_store.save(candidate)
        except (ValueError, TypeError, tk.TclError, OSError) as error:
            self.settings_status.config(text=str(error), fg=self.RED)
            return
        if self.db is not None:
            self.db.retention_days = candidate.retention_days
            self.db.store_candles = candidate.store_candles
        should_refresh = (
            (not self.settings.auto_refresh and candidate.auto_refresh)
            or self.settings.live_signal_source != candidate.live_signal_source
            or self.settings.strategy != candidate.strategy
        )
        stream_changed = (
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
        self._apply_runtime_log_and_scale()
        self.analyzer = ConfluenceAnalyzer(settings=candidate)
        self.alert_engine.cooldown_seconds = candidate.alert_cooldown_seconds
        self.history_store.keep_records = candidate.max_signal_history_rows
        self.confluence_store.keep_records = candidate.max_signal_history_rows
        if hasattr(self, "ai_model_combo"):
            self.ai_model_combo.config(
                state="normal" if candidate.ai_allow_custom_models else "readonly"
            )
        if hasattr(self, "risk_vars"):
            self.risk_vars["balance"].set(f"{candidate.account_balance_default:g}")
            self.risk_vars["risk"].set(
                f"{candidate.risk_percent_for_symbol(self.selected):g}"
            )
            self.risk_vars["reward"].set(f"{candidate.default_reward_to_risk:g}")
            self.risk_vars["pip_value"].set(f"{candidate.default_pip_value_per_lot:g}")
        self._apply_theme()
        self._sync_mcp_server()
        self._sync_telegram_service()
        if stream_changed:
            self._reload_stream_and_watchlist(candidate)
        if should_refresh:
            for symbol in list(self.candles):
                try:
                    self._refresh(symbol)
                except ValueError as error:
                    logger.warning("Could not refresh %s: %s", symbol, error)
        self._draw_chart()
        self.status_var.set("Settings saved")
        summary = (
            f"Saved · {candidate.polling_ms} ms · {candidate.candle_limit} candles"
        )
        if stream_changed:
            summary += (
                " · live connection reloaded (restart only needed if socket cached)"
            )
        self.settings_status.config(text=summary, fg=self.GREEN)

    def _close(self):
        if self.settings.confirm_on_exit and not messagebox.askyesno(
            "Exit NEEZY", "Close the NEEZY workspace now?"
        ):
            return
        if self.settings.auto_backup_enabled:
            try:
                create_local_backup(max_backups=self.settings.max_backup_count)
            except OSError as error:
                logger.warning("Auto-backup on exit failed: %s", error)
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
