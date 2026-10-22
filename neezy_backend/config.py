"""Validated application settings kept separate from the Tkinter view."""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, fields, replace
from typing import Any

from neezy_backend.markets import SYMBOLS, TIMEFRAMES
from neezy_backend.strategies import (
    SINGLE_MARKET_STRATEGIES as _SINGLE_MARKET_STRATEGIES,
)

THEMES = frozenset({"Liquid dark", "Midnight blue", "High contrast"})
NAV_PAGES = frozenset(
    {
        "CHAT",
        "SYMBOLS",
        "CHART",
        "SIGNALS",
        "INSIGHTS",
        "TOOLS",
        "ORDERS",
        "ALERTS",
        "HISTORY",
        "SETTINGS",
    }
)
DISPLAY_TIMEZONES = frozenset(
    {
        "UTC",
        "Local System",
        "Africa/Johannesburg",
        "Europe/London",
        "America/New_York",
        "Asia/Tokyo",
        "Australia/Sydney",
    }
)
CHART_STYLES = frozenset(
    {
        "Candlesticks",
        "Hollow Candles",
        "OHLC Bars",
        "Heikin-Ashi",
        "Close Line",
    }
)
CHART_SUBPANE_OSCILLATORS = frozenset({"None", "RSI 14", "MACD Histogram"})
LIVE_SIGNAL_SOURCES = frozenset({"core", "active_strategy", "consensus"})
ACCOUNT_CURRENCIES = frozenset({"USD", "ZAR", "EUR", "GBP", "AUD", "JPY", "CAD", "CHF"})
ALERT_SOUND_MODES = frozenset({"System Bell", "Muted"})
ML_ARCHITECTURES = frozenset({"v1", "sequence", "ensemble"})
CSV_DELIMITERS = frozenset({"comma", "semicolon", "tab"})
MT5_FILLING_MODES = frozenset({"Auto", "IOC", "FOK", "RETURN"})
DM_WEBHOOK_FORMATS = frozenset({"auto", "discord", "slack", "generic"})
LOG_LEVELS = frozenset({"WARNING", "INFO", "DEBUG"})
SETTINGS_PROFILE_NAMES = (
    "Default",
    "Conservative Prop",
    "Active Intraday",
    "Scalping",
    "Offline Low-CPU",
)

# Derived from the engine registry in strategies.py (single-market strategies
# only: the `strategy` setting never selects a pair strategy) so config
# validation, CLI choices, and context can never drift from the engine.
STRATEGIES = frozenset(_SINGLE_MARKET_STRATEGIES)
AI_PROVIDERS = frozenset({"gemini", "grok", "openrouter", "ollama"})
AI_FALLBACK_PROVIDERS = AI_PROVIDERS | frozenset({"none", "local_llm"})
# External market-data providers used by the confluence engine.
MARKET_DATA_PROVIDERS = frozenset(
    {"deriv", "alpha_vantage", "finnhub", "binance", "twelve_data"}
)
FALLBACK_DATA_PROVIDERS = MARKET_DATA_PROVIDERS | frozenset({"none"})

_HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _require_bool(field_name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a boolean")


def _require_int(field_name: str, value: object, low: int, high: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if not low <= value <= high:
        raise ValueError(f"{field_name} must be between {low} and {high}")


def _require_float(field_name: str, value: object, low: float, high: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    if not low <= float(value) <= high:
        raise ValueError(f"{field_name} must be between {low:g} and {high:g}")


def _require_hhmm(field_name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not _HHMM_RE.match(value.strip()):
        raise ValueError(f"{field_name} must be a valid 24-hour HH:MM time")


@dataclass(frozen=True, slots=True)
class AppSettings:
    """User-configurable settings with validation at every construction point.

    Older config files keep working: :meth:`from_dict` ignores unknown keys and
    any missing key falls back to the defaults declared here.
    """

    # Workspace & UX
    auto_refresh: bool = True
    alerts_enabled: bool = True
    compact_mode: bool = False
    theme: str = "Liquid dark"
    colorblind_palette: bool = False
    reduced_motion: bool = False
    ui_scale_percent: int = 100
    font_size_offset: int = 0
    remember_window_geometry: bool = True
    startup_page: str = "SIGNALS"
    startup_symbol: str = "frxEURUSD"
    display_timezone: str = "UTC"
    price_flash_on_tick: bool = True
    dim_ui_when_offline: bool = True
    stale_tick_timeout_seconds: int = 60
    confirm_on_exit: bool = False
    polling_ms: int = 100
    candle_limit: int = 300
    alert_min_score: int = 2
    default_timeframe: str = "5m"
    history_candles: int = 300
    # Comma-separated extra Deriv symbols streamed on top of the default
    # watchlist (see markets.DEFAULT_WATCHLIST).
    watchlist_extra: str = ""

    # Chart & Visuals
    chart_visible_candles: int = 80
    chart_style: str = "Candlesticks"
    chart_show_ema_fast: bool = True
    chart_ema_fast_period: int = 9
    chart_show_ema_slow: bool = True
    chart_ema_slow_period: int = 21
    chart_show_ema_trend: bool = True
    chart_ema_trend_period: int = 50
    chart_show_bollinger: bool = True
    chart_show_sr_levels: bool = True
    chart_sr_count: int = 1
    chart_show_pivots: bool = False
    chart_show_entry_sl_tp: bool = True
    chart_show_session_boxes: bool = False
    chart_subpane_oscillator: str = "None"
    chart_show_crosshair: bool = True
    chart_show_grid: bool = True
    chart_mark_candle_gaps: bool = True

    # Connection
    deriv_endpoint: str = ""
    reconnect_seconds: float = 2.0
    max_reconnect_seconds: float = 30.0

    # Strategy & Indicator Engine
    strategy: str = "SUPERTREND"
    live_signal_source: str = "core"
    supertrend_period: int = 10
    supertrend_multiplier: float = 3.0
    divergence_lookback: int = 5
    correlation_window: int = 50
    correlation_baseline: int = 200
    show_strategy_overlay: bool = True
    indicator_ema_fast: int = 9
    indicator_ema_mid: int = 21
    indicator_ema_slow: int = 50
    indicator_rsi_period: int = 14
    indicator_rsi_oversold: int = 35
    indicator_rsi_overbought: int = 65
    indicator_atr_period: int = 14
    indicator_adx_trend_threshold: float = 25.0
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    donchian_period: int = 20
    keltner_period: int = 20
    consensus_net_threshold: float = 0.15

    # Local storage, backups & exports
    store_candles: bool = True
    retention_days: int = 90
    save_snapshots: bool = True
    snapshot_interval_seconds: int = 60
    auto_prune_on_startup: bool = False
    auto_backup_enabled: bool = False
    max_backup_count: int = 20
    max_signal_history_rows: int = 5000
    csv_delimiter: str = "comma"
    cache_max_size_mb: int = 256

    # AI providers & agentic copilot
    ai_enabled: bool = False
    ai_provider: str = "openrouter"
    ai_fallback_provider: str = "none"
    ai_allow_custom_models: bool = False
    ai_model: str = ""
    ai_base_url: str = ""
    ai_temperature: float = 0.3
    ai_max_tokens: int = 700
    ai_timeout: float = 45.0
    ai_system_prompt: str = ""
    ai_cache_enabled: bool = True
    ai_cache_ttl_seconds: int = 900
    ai_chat_history_turns: int = 6
    ai_daily_request_cap: int = 0
    agent_mode_enabled: bool = False
    agent_max_steps: int = 5
    agent_require_write_confirmation: bool = True
    # Add each market's backtest record (neezy-cli knowledge) to AI context.
    # Off by default: the records are simulations, not evidence of future profit.
    use_knowledge: bool = False
    # Include relevant on-device notes in provider prompts only when explicitly enabled.
    use_memory: bool = False

    # Optional local neural experiment. It is advisory-only and never changes
    # the deterministic signal score or places trades.
    use_brain_model: bool = False

    # Reproducible public-data research (advisory; never places orders).
    ml_model_architecture: str = "v1"
    ml_ensemble_members: int = 5
    ml_sequence_window: int = 10
    ml_history_candles: int = 3000
    ml_epochs: int = 60
    ml_horizon: int = 5
    ml_deadband_atr: float = 0.1
    ml_min_samples: int = 100
    ml_seed: int = 17
    ml_probability: float = 0.60
    ml_fetch_timeout: float = 15.0
    backtest_default_spread_pips: float = 0.0
    outcome_eval_horizon: int = 10
    pair_lookback: int = 60
    pair_min_overlap: int = 300
    pair_entry_z: float = 2.0
    pair_exit_z: float = 0.5
    pair_stop_z: float = 4.0
    pair_cost_bps: float = 2.0
    pair_max_holding: int = 48
    pair_min_correlation: float = 0.3
    insights_max_rows: int = 25

    # Optional local generative model.
    local_llm_enabled: bool = False
    local_llm_model_id: str = ""
    local_llm_context_tokens: int = 512
    local_llm_max_tokens: int = 128
    local_llm_threads: int = 1
    local_llm_batch_size: int = 32
    local_llm_disk_offload: bool = False
    local_llm_cpu_memory_mb: int = 512
    local_llm_gpu_layers: int = 0
    local_llm_top_p: float = 0.90
    local_llm_repeat_penalty: float = 1.10
    local_llm_keep_alive_minutes: int = 10
    local_llm_seed: int = 42
    local_llm_verify_sha256: bool = True

    # Local Model Context Protocol bridge.
    mcp_enabled: bool = False
    mcp_port: int = 8765
    mcp_allow_writes: bool = False
    mcp_tunnel_enabled: bool = False
    mcp_tunnel_executable: str = "cloudflared"
    mcp_rate_limit_rpm: int = 60
    mcp_tool_timeout_seconds: float = 15.0
    mcp_strict_origin_check: bool = True
    mcp_audit_log_enabled: bool = True

    # Alerts & Quiet Hours
    alert_sound_mode: str = "System Bell"
    alert_cooldown_seconds: int = 0
    toast_notifications_enabled: bool = True
    toast_duration_ms: int = 4500
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "06:00"
    alert_on_stream_disconnect: bool = False
    alert_on_drawdown_breach: bool = True
    auto_disable_one_shot_price_alerts: bool = False

    # Telegram
    telegram_enabled: bool = False
    telegram_chat_ids: str = ""
    telegram_alerts_enabled: bool = True
    telegram_allow_commands: bool = False
    telegram_min_signal_score: int = 2
    telegram_include_sl_tp_levels: bool = True
    telegram_daily_digest_enabled: bool = False
    telegram_digest_hour_utc: int = 20

    # MetaTrader 5 Bridge
    mt5_enabled: bool = False
    mt5_server: str = ""
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_path: str = ""
    mt5_magic: int = 123456
    mt5_symbol_map: str = ""
    mt5_auto_sync: bool = False
    mt5_order_deviation_points: int = 20
    mt5_filling_mode: str = "Auto"
    mt5_sync_interval_seconds: int = 5

    # Direct Messaging, Risk & Order Safety
    dm_enabled: bool = False
    dm_webhook_url: str = ""
    dm_webhook_format: str = "auto"
    dm_https_only: bool = False
    dm_min_score: int = 3
    dm_notify_signals: bool = True
    dm_notify_alerts: bool = True
    account_balance_default: float = 10000.0
    account_currency: str = "USD"
    default_risk_percent: float = 1.0
    default_reward_to_risk: float = 2.0
    default_pip_value_per_lot: float = 10.0
    fx_risk_percent: float = 1.0
    synthetic_risk_percent: float = 0.5
    crypto_risk_percent: float = 0.5
    max_drawdown_limit: float = 10.0
    order_dry_run_mode: bool = False
    require_stop_loss_on_live_orders: bool = False
    max_lot_size_cap: float = 10.0
    max_open_positions: int = 10
    daily_max_loss_percent: float = 5.0
    daily_max_trades: int = 20
    min_rr_for_live_order: float = 1.0
    pre_trade_checklist_enabled: bool = False
    pre_trade_checklist_items: str = (
        "Higher timeframe aligned;Stop loss at invalidation;Within daily risk budget"
    )

    # Confluence engine + external data providers
    market_data_provider: str = "deriv"
    fallback_data_provider: str = "deriv"
    provider_candle_count: int = 300
    provider_cache_enabled: bool = True
    provider_cache_ttl_seconds: int = 30
    provider_requests_per_minute: int = 30
    confluence_min_score: float = 55.0
    confluence_search_score: float = 30.0
    confluence_require_strict_only: bool = False
    confluence_mtf_confirmation: bool = False
    confluence_higher_timeframe: str = "1h"
    confluence_atr_stop_mult: float = 1.5
    confluence_atr_tp_mult: float = 2.5
    confluence_horizon: int = 20
    confluence_min_analogs: int = 4

    # Profiles & Diagnostics
    active_settings_profile: str = "Default"
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        for field_name, low, high in (
            ("ui_scale_percent", 75, 200),
            ("font_size_offset", -2, 6),
            ("stale_tick_timeout_seconds", 10, 600),
            ("polling_ms", 50, 2000),
            ("candle_limit", 60, 1000),
            ("alert_min_score", 1, 4),
            ("history_candles", 60, 1000),
            ("chart_visible_candles", 30, 500),
            ("chart_ema_fast_period", 2, 200),
            ("chart_ema_slow_period", 2, 200),
            ("chart_ema_trend_period", 5, 500),
            ("chart_sr_count", 1, 5),
            ("supertrend_period", 2, 100),
            ("divergence_lookback", 1, 30),
            ("correlation_window", 10, 500),
            ("correlation_baseline", 20, 2000),
            ("indicator_ema_fast", 2, 100),
            ("indicator_ema_mid", 5, 200),
            ("indicator_ema_slow", 10, 500),
            ("indicator_rsi_period", 2, 100),
            ("indicator_rsi_oversold", 5, 49),
            ("indicator_rsi_overbought", 51, 95),
            ("indicator_atr_period", 2, 100),
            ("bollinger_period", 5, 100),
            ("donchian_period", 5, 200),
            ("keltner_period", 5, 200),
            ("retention_days", 1, 3650),
            ("snapshot_interval_seconds", 15, 3600),
            ("max_backup_count", 1, 100),
            ("max_signal_history_rows", 100, 50000),
            ("cache_max_size_mb", 16, 4096),
            ("ai_max_tokens", 64, 8192),
            ("ai_cache_ttl_seconds", 30, 86400),
            ("ai_chat_history_turns", 0, 30),
            ("ai_daily_request_cap", 0, 5000),
            ("agent_max_steps", 1, 20),
            ("ml_ensemble_members", 2, 15),
            ("ml_sequence_window", 3, 60),
            ("ml_history_candles", 400, 50000),
            ("ml_epochs", 1, 500),
            ("ml_horizon", 1, 100),
            ("ml_min_samples", 60, 10000),
            ("ml_seed", 0, 2147483647),
            ("outcome_eval_horizon", 1, 200),
            ("pair_lookback", 20, 1000),
            ("pair_min_overlap", 100, 20000),
            ("pair_max_holding", 1, 2000),
            ("insights_max_rows", 5, 200),
            ("local_llm_context_tokens", 128, 32768),
            ("local_llm_max_tokens", 1, 8192),
            ("local_llm_threads", 1, 16),
            ("local_llm_batch_size", 1, 1024),
            ("local_llm_cpu_memory_mb", 256, 262144),
            ("local_llm_gpu_layers", -1, 128),
            ("local_llm_keep_alive_minutes", 0, 120),
            ("local_llm_seed", -1, 2147483647),
            ("mcp_port", 1024, 65535),
            ("mcp_rate_limit_rpm", 5, 600),
            ("alert_cooldown_seconds", 0, 86400),
            ("toast_duration_ms", 1500, 30000),
            ("telegram_min_signal_score", 1, 4),
            ("telegram_digest_hour_utc", 0, 23),
            ("mt5_login", 0, 2147483647),
            ("mt5_magic", 1, 2147483647),
            ("mt5_order_deviation_points", 0, 200),
            ("mt5_sync_interval_seconds", 1, 300),
            ("dm_min_score", 1, 4),
            ("max_open_positions", 1, 50),
            ("daily_max_trades", 1, 100),
            ("provider_candle_count", 60, 1000),
            ("provider_cache_ttl_seconds", 5, 900),
            ("provider_requests_per_minute", 1, 300),
            ("confluence_horizon", 3, 120),
            ("confluence_min_analogs", 2, 100),
        ):
            _require_int(field_name, getattr(self, field_name), low, high)

        for field_name, low, high in (
            ("reconnect_seconds", 0.5, 60.0),
            ("max_reconnect_seconds", 1.0, 600.0),
            ("supertrend_multiplier", 0.5, 10.0),
            ("indicator_adx_trend_threshold", 10.0, 50.0),
            ("bollinger_std", 0.5, 4.0),
            ("consensus_net_threshold", 0.05, 0.80),
            ("ai_temperature", 0.0, 2.0),
            ("ai_timeout", 5.0, 300.0),
            ("ml_deadband_atr", 0.0, 5.0),
            ("ml_probability", 0.51, 0.99),
            ("ml_fetch_timeout", 2.0, 120.0),
            ("backtest_default_spread_pips", 0.0, 20.0),
            ("pair_entry_z", 0.5, 6.0),
            ("pair_exit_z", 0.0, 3.0),
            ("pair_stop_z", 1.0, 10.0),
            ("pair_cost_bps", 0.0, 100.0),
            ("pair_min_correlation", 0.0, 1.0),
            ("local_llm_top_p", 0.1, 1.0),
            ("local_llm_repeat_penalty", 1.0, 2.0),
            ("mcp_tool_timeout_seconds", 2.0, 120.0),
            ("account_balance_default", 10.0, 10000000.0),
            ("default_risk_percent", 0.1, 100.0),
            ("default_reward_to_risk", 0.5, 10.0),
            ("default_pip_value_per_lot", 0.1, 1000.0),
            ("fx_risk_percent", 0.1, 20.0),
            ("synthetic_risk_percent", 0.1, 20.0),
            ("crypto_risk_percent", 0.1, 20.0),
            ("max_drawdown_limit", 0.1, 100.0),
            ("max_lot_size_cap", 0.01, 100.0),
            ("daily_max_loss_percent", 0.5, 50.0),
            ("min_rr_for_live_order", 0.1, 10.0),
            ("confluence_min_score", 0.0, 100.0),
            ("confluence_search_score", 0.0, 100.0),
            ("confluence_atr_stop_mult", 0.5, 6.0),
            ("confluence_atr_tp_mult", 0.5, 10.0),
        ):
            _require_float(field_name, getattr(self, field_name), low, high)

        for field_name in (
            "auto_refresh",
            "alerts_enabled",
            "compact_mode",
            "colorblind_palette",
            "reduced_motion",
            "remember_window_geometry",
            "price_flash_on_tick",
            "dim_ui_when_offline",
            "confirm_on_exit",
            "chart_show_ema_fast",
            "chart_show_ema_slow",
            "chart_show_ema_trend",
            "chart_show_bollinger",
            "chart_show_sr_levels",
            "chart_show_pivots",
            "chart_show_entry_sl_tp",
            "chart_show_session_boxes",
            "chart_show_crosshair",
            "chart_show_grid",
            "chart_mark_candle_gaps",
            "show_strategy_overlay",
            "store_candles",
            "save_snapshots",
            "auto_prune_on_startup",
            "auto_backup_enabled",
            "ai_enabled",
            "ai_allow_custom_models",
            "ai_cache_enabled",
            "agent_mode_enabled",
            "agent_require_write_confirmation",
            "use_knowledge",
            "use_memory",
            "use_brain_model",
            "local_llm_enabled",
            "local_llm_disk_offload",
            "local_llm_verify_sha256",
            "mcp_enabled",
            "mcp_allow_writes",
            "mcp_tunnel_enabled",
            "mcp_strict_origin_check",
            "mcp_audit_log_enabled",
            "toast_notifications_enabled",
            "quiet_hours_enabled",
            "alert_on_stream_disconnect",
            "alert_on_drawdown_breach",
            "auto_disable_one_shot_price_alerts",
            "telegram_enabled",
            "telegram_alerts_enabled",
            "telegram_allow_commands",
            "telegram_include_sl_tp_levels",
            "telegram_daily_digest_enabled",
            "mt5_enabled",
            "mt5_auto_sync",
            "dm_enabled",
            "dm_https_only",
            "dm_notify_signals",
            "dm_notify_alerts",
            "order_dry_run_mode",
            "require_stop_loss_on_live_orders",
            "pre_trade_checklist_enabled",
            "provider_cache_enabled",
            "confluence_require_strict_only",
            "confluence_mtf_confirmation",
        ):
            _require_bool(field_name, getattr(self, field_name))

        for field_name, allowed in (
            ("theme", THEMES),
            ("startup_page", NAV_PAGES),
            ("startup_symbol", set(SYMBOLS)),
            ("display_timezone", DISPLAY_TIMEZONES),
            ("default_timeframe", set(TIMEFRAMES)),
            ("chart_style", CHART_STYLES),
            ("chart_subpane_oscillator", CHART_SUBPANE_OSCILLATORS),
            ("strategy", STRATEGIES),
            ("live_signal_source", LIVE_SIGNAL_SOURCES),
            ("csv_delimiter", CSV_DELIMITERS),
            ("ai_provider", AI_PROVIDERS),
            ("ai_fallback_provider", AI_FALLBACK_PROVIDERS),
            ("ml_model_architecture", ML_ARCHITECTURES),
            ("alert_sound_mode", ALERT_SOUND_MODES),
            ("mt5_filling_mode", MT5_FILLING_MODES),
            ("dm_webhook_format", DM_WEBHOOK_FORMATS),
            ("account_currency", ACCOUNT_CURRENCIES),
            ("market_data_provider", MARKET_DATA_PROVIDERS),
            ("fallback_data_provider", FALLBACK_DATA_PROVIDERS),
            ("confluence_higher_timeframe", set(TIMEFRAMES)),
            ("active_settings_profile", set(SETTINGS_PROFILE_NAMES)),
            ("log_level", LOG_LEVELS),
        ):
            val = getattr(self, field_name)
            if val not in allowed:
                raise ValueError(
                    f"Unsupported {field_name} {val!r}; "
                    f"choose from {', '.join(sorted(allowed))}"
                )

        _require_hhmm("quiet_hours_start", self.quiet_hours_start)
        _require_hhmm("quiet_hours_end", self.quiet_hours_end)

        if not self.pair_exit_z < self.pair_entry_z < self.pair_stop_z:
            raise ValueError("pair thresholds must satisfy exit < entry < stop")
        if self.pair_min_overlap < self.pair_lookback * 3:
            raise ValueError("pair overlap must be at least three lookback windows")
        if self.history_candles > self.candle_limit:
            raise ValueError("history candles cannot exceed max candles in memory")
        if self.confluence_search_score > self.confluence_min_score:
            raise ValueError(
                "the search threshold cannot exceed the strict confluence threshold"
            )
        if self.confluence_atr_tp_mult <= self.confluence_atr_stop_mult:
            raise ValueError("the take-profit multiple must exceed the stop multiple")
        if self.max_reconnect_seconds < self.reconnect_seconds:
            raise ValueError("max reconnect delay must be at least the first delay")
        if self.correlation_baseline < self.correlation_window:
            raise ValueError("correlation baseline must be at least the window")

        if not isinstance(self.deriv_endpoint, str):
            raise TypeError("deriv_endpoint must be a string")
        endpoint = self.deriv_endpoint.strip()
        if endpoint and (
            not endpoint.startswith(("ws://", "wss://"))
            or any(char.isspace() for char in endpoint)
        ):
            raise ValueError(
                "deriv_endpoint must be a ws:// or wss:// URL with no spaces"
            )
        if not isinstance(self.watchlist_extra, str):
            raise TypeError("watchlist_extra must be a string")
        extras = [part.strip() for part in self.watchlist_extra.split(",")]
        extras = [symbol for symbol in extras if symbol]
        unknown = [symbol for symbol in extras if symbol not in SYMBOLS]
        if unknown:
            raise ValueError(f"unknown extra markets: {', '.join(unknown)}")
        if len(set(extras)) > 25:
            raise ValueError("at most 25 extra markets can be watched")

        if (
            not isinstance(self.local_llm_model_id, str)
            or len(self.local_llm_model_id) > 64
        ):
            raise ValueError(
                "local_llm_model_id must be a string of at most 64 characters"
            )
        if not isinstance(self.mcp_tunnel_executable, str):
            raise TypeError("mcp_tunnel_executable must be a string")
        if (
            not self.mcp_tunnel_executable.strip()
            or len(self.mcp_tunnel_executable) > 1024
        ):
            raise ValueError("mcp_tunnel_executable must contain 1 to 1024 characters")
        if any(ord(character) < 32 for character in self.mcp_tunnel_executable):
            raise ValueError("mcp_tunnel_executable cannot contain control characters")
        if not isinstance(self.telegram_chat_ids, str):
            raise TypeError("telegram_chat_ids must be a string")
        if len(self.telegram_chat_ids) > 1000:
            raise ValueError("telegram_chat_ids must be at most 1000 characters")

        for field_name in (
            "ai_model",
            "ai_base_url",
            "ai_system_prompt",
            "mt5_server",
            "mt5_password",
            "mt5_path",
            "mt5_symbol_map",
            "dm_webhook_url",
            "pre_trade_checklist_items",
        ):
            if not isinstance(getattr(self, field_name), str):
                raise TypeError(f"{field_name} must be a string")

    def risk_percent_for_symbol(self, symbol: str) -> float:
        """Return class-specific risk % when configured, defaulting cleanly."""
        if symbol.startswith("cry"):
            return self.crypto_risk_percent
        if symbol.startswith(("R_", "1HZ", "BOOM", "CRASH", "JD", "STPRNG")):
            return self.synthetic_risk_percent
        if symbol.startswith("frx") and self.fx_risk_percent != 1.0:
            return self.fx_risk_percent
        return self.default_risk_percent

    def csv_separator(self) -> str:
        """Character delimiter matching ``csv_delimiter``."""
        return {"comma": ",", "semicolon": ";", "tab": "\t"}[self.csv_delimiter]

    def updated(self, **changes: Any) -> AppSettings:
        """Return a new validated settings object."""
        return replace(self, **changes)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> AppSettings:
        """Load known fields only, making older config files forward compatible."""
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in values.items() if key in allowed})

    def apply_profile(self, profile_name: str) -> AppSettings:
        return apply_profile(self, profile_name)

    def apply_env_overrides(self, env: dict[str, str] | None = None) -> AppSettings:
        return apply_env_overrides(self, env=env)


SETTINGS_PROFILES: dict[str, dict[str, Any]] = {
    "Default": {},
    "Conservative Prop": {
        "default_risk_percent": 0.5,
        "fx_risk_percent": 0.5,
        "synthetic_risk_percent": 0.25,
        "crypto_risk_percent": 0.25,
        "max_drawdown_limit": 5.0,
        "daily_max_loss_percent": 2.5,
        "daily_max_trades": 5,
        "min_rr_for_live_order": 2.0,
        "require_stop_loss_on_live_orders": True,
        "pre_trade_checklist_enabled": True,
        "confluence_min_score": 65.0,
        "confluence_require_strict_only": True,
        "alert_min_score": 3,
    },
    "Active Intraday": {
        "default_timeframe": "15m",
        "strategy": "SUPERTREND",
        "live_signal_source": "consensus",
        "default_risk_percent": 1.0,
        "confluence_min_score": 55.0,
        "chart_visible_candles": 120,
        "chart_show_pivots": True,
        "chart_show_entry_sl_tp": True,
        "chart_subpane_oscillator": "RSI 14",
        "alert_min_score": 2,
    },
    "Scalping": {
        "default_timeframe": "1m",
        "polling_ms": 50,
        "compact_mode": True,
        "strategy": "EMA_PULLBACK",
        "chart_visible_candles": 60,
        "confluence_atr_stop_mult": 1.2,
        "confluence_atr_tp_mult": 2.0,
        "default_risk_percent": 0.5,
    },
    "Offline Low-CPU": {
        "polling_ms": 500,
        "reduced_motion": True,
        "price_flash_on_tick": False,
        "candle_limit": 200,
        "history_candles": 150,
        "snapshot_interval_seconds": 300,
    },
}


_PROFILE_ALIASES: dict[str, str] = {
    "default": "Default",
    "conservative": "Conservative Prop",
    "conservative_prop": "Conservative Prop",
    "intraday": "Active Intraday",
    "active_intraday": "Active Intraday",
    "swing": "Active Intraday",
    "scalper": "Scalping",
    "scalping": "Scalping",
    "low_ram": "Offline Low-CPU",
    "low_cpu": "Offline Low-CPU",
    "offline_low_cpu": "Offline Low-CPU",
}


def apply_profile(base: AppSettings, profile_name: str) -> AppSettings:
    """Apply a named preset on top of ``base`` while preserving secrets/keys."""
    by_norm = {k.lower(): k for k in SETTINGS_PROFILES}
    by_norm.update(_PROFILE_ALIASES)
    canonical = by_norm.get(profile_name.strip().lower())
    if canonical is None:
        raise ValueError(
            f"Unknown settings profile {profile_name!r}; "
            f"choose from {', '.join(SETTINGS_PROFILE_NAMES)}"
        )
    if canonical == "Default":
        preserved = {
            key: getattr(base, key)
            for key in (
                "ai_provider",
                "ai_model",
                "ai_base_url",
                "telegram_chat_ids",
                "mt5_server",
                "mt5_login",
                "mt5_password",
                "mt5_path",
                "mt5_symbol_map",
                "dm_webhook_url",
                "local_llm_model_id",
            )
        }
        return AppSettings(**preserved, active_settings_profile="Default")
    return base.updated(
        **SETTINGS_PROFILES[canonical],
        active_settings_profile=canonical,
    )


def apply_env_overrides(
    base: AppSettings, env: dict[str, str] | None = None
) -> AppSettings:
    """Apply ``NEEZY_<FIELD_NAME>`` environment overrides with full validation."""
    source = os.environ if env is None else env
    updates: dict[str, Any] = {}
    for field in fields(AppSettings):
        env_key = f"NEEZY_{field.name.upper()}"
        if env_key not in source:
            continue
        raw = source[env_key]
        current = getattr(base, field.name)
        if isinstance(current, bool):
            low = raw.strip().lower()
            if low not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
                raise ValueError(f"{env_key} must be a boolean value, got {raw!r}")
            updates[field.name] = low in {"1", "true", "yes", "on"}
        elif isinstance(current, int):
            updates[field.name] = int(raw.strip())
        elif isinstance(current, float):
            updates[field.name] = float(raw.strip())
        else:
            updates[field.name] = raw
    return base.updated(**updates) if updates else base
