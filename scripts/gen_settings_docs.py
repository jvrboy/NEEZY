#!/usr/bin/env python3
"""Generate docs/SETTINGS.md from AppSettings (roadmap update #87).

Documents every settings field with its default, validation range, and a
plain-language description. Generated docs cannot drift from the code.
Run from the repo root:  python scripts/gen_settings_docs.py
"""

from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from neezy_backend.config import AppSettings

# Field -> (plain description, where it lives in the UI)
DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "auto_refresh": (
        "Refresh the watchlist and chart automatically",
        "SETTINGS > Workspace",
    ),
    "alerts_enabled": ("Master switch for alert evaluation", "SETTINGS > Workspace"),
    "compact_mode": ("Denser layout with smaller paddings", "SETTINGS > Workspace"),
    "theme": ("Color theme preset", "SETTINGS > Workspace"),
    "colorblind_palette": (
        "Deuteranopia/protanopia-safe cyan & amber directional palette",
        "SETTINGS > Workspace",
    ),
    "reduced_motion": (
        "Disable non-essential animations and pulse indicators",
        "SETTINGS > Workspace",
    ),
    "ui_scale_percent": (
        "DPI scaling factor (75-200%)",
        "SETTINGS > Workspace",
    ),
    "font_size_offset": (
        "Global UI & monospace font point offset (-2 to +6)",
        "SETTINGS > Workspace",
    ),
    "remember_window_geometry": (
        "Save and restore desktop window size & coordinates",
        "SETTINGS > Workspace",
    ),
    "startup_page": (
        "Initial navigation screen selected on launch",
        "SETTINGS > Workspace",
    ),
    "startup_symbol": (
        "Default active symbol loaded on launch",
        "SETTINGS > Workspace",
    ),
    "display_timezone": (
        "Timezone used on clocks and timestamps",
        "SETTINGS > Workspace",
    ),
    "price_flash_on_tick": (
        "Highlight price changes briefly when live quotes arrive",
        "SETTINGS > Workspace",
    ),
    "dim_ui_when_offline": (
        "Show stale-data warning styling when market feed disconnects",
        "SETTINGS > Workspace",
    ),
    "stale_tick_timeout_seconds": (
        "Seconds without a tick before feed is flagged stale",
        "SETTINGS > Workspace",
    ),
    "confirm_on_exit": (
        "Prompt before closing desktop window",
        "SETTINGS > Workspace",
    ),
    "polling_ms": ("UI poll interval in milliseconds", "SETTINGS > Workspace"),
    "candle_limit": (
        "Maximum candles held in memory per symbol",
        "SETTINGS > Workspace",
    ),
    "alert_min_score": ("Minimum strategy score that can fire alerts", "ALERTS"),
    "default_timeframe": ("Timeframe used on new charts", "SYMBOLS/CHART"),
    "history_candles": ("Candles kept for the history replay view", "HISTORY"),
    "watchlist_extra": (
        "Comma-separated extra Deriv symbols beyond the default watchlist",
        "SYMBOLS",
    ),
    "chart_visible_candles": (
        "Default number of visible candles on chart canvas",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_style": (
        "Primary price rendering mode (Candlesticks, Hollow, OHLC, Heikin-Ashi, Line)",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_ema_fast": (
        "Render fast EMA line on chart",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_ema_fast_period": (
        "Fast chart EMA lookback period",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_ema_slow": (
        "Render medium EMA line on chart",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_ema_slow_period": (
        "Medium chart EMA lookback period",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_ema_trend": (
        "Render slow trend EMA line on chart",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_ema_trend_period": (
        "Slow trend chart EMA lookback period",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_bollinger": (
        "Render Bollinger upper/lower bands on chart",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_sr_levels": (
        "Draw horizontal swing support & resistance levels",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_sr_count": (
        "Number of support/resistance levels drawn per side",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_pivots": (
        "Draw classic P / R1 / S1 pivot levels on chart",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_entry_sl_tp": (
        "Draw ATR Entry / Stop-Loss / Take-Profit guide lines on chart",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_session_boxes": (
        "Shade London/New York/Asian session windows on intraday charts",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_subpane_oscillator": (
        "Optional lower oscillator subpane (None, RSI 14, MACD Histogram)",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_crosshair": (
        "Enable interactive mouse crosshair and OHLC HUD tooltip",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_show_grid": (
        "Draw horizontal price grid lines on chart",
        "SETTINGS > Chart & Visuals",
    ),
    "chart_mark_candle_gaps": (
        "Mark missing timestamp gaps along candle axis",
        "SETTINGS > Chart & Visuals",
    ),
    "deriv_endpoint": (
        "Optional custom Deriv WebSocket endpoint",
        "SETTINGS > Workspace",
    ),
    "reconnect_seconds": ("First reconnect delay in seconds", "SETTINGS > Workspace"),
    "max_reconnect_seconds": (
        "Reconnect backoff ceiling in seconds",
        "SETTINGS > Workspace",
    ),
    "strategy": ("Active single-market strategy", "SETTINGS > Engine"),
    "live_signal_source": (
        "Live watchlist signal source (core, active_strategy, consensus)",
        "SETTINGS > Engine",
    ),
    "supertrend_period": ("Supertrend lookback", "SETTINGS > Engine"),
    "supertrend_multiplier": ("Supertrend band multiple", "SETTINGS > Engine"),
    "divergence_lookback": ("Divergence detection lookback", "SETTINGS > Engine"),
    "correlation_window": ("Rolling correlation window", "SETTINGS > Engine"),
    "correlation_baseline": ("Correlation baseline sample count", "SETTINGS > Engine"),
    "show_strategy_overlay": (
        "Draw active strategy overlays (Supertrend/Donchian/Keltner) on chart",
        "SETTINGS > Engine",
    ),
    "indicator_ema_fast": ("Core engine fast EMA period", "SETTINGS > Engine"),
    "indicator_ema_mid": ("Core engine medium EMA period", "SETTINGS > Engine"),
    "indicator_ema_slow": ("Core engine slow EMA period", "SETTINGS > Engine"),
    "indicator_rsi_period": ("Core engine RSI period", "SETTINGS > Engine"),
    "indicator_rsi_oversold": ("RSI oversold threshold", "SETTINGS > Engine"),
    "indicator_rsi_overbought": ("RSI overbought threshold", "SETTINGS > Engine"),
    "indicator_atr_period": ("Core engine ATR period", "SETTINGS > Engine"),
    "indicator_adx_trend_threshold": (
        "ADX threshold separating trending vs ranging regimes",
        "SETTINGS > Engine",
    ),
    "bollinger_period": ("Bollinger band lookback period", "SETTINGS > Engine"),
    "bollinger_std": ("Bollinger standard deviation multiplier", "SETTINGS > Engine"),
    "donchian_period": ("Donchian breakout channel lookback", "SETTINGS > Engine"),
    "keltner_period": ("Keltner channel lookback", "SETTINGS > Engine"),
    "consensus_net_threshold": (
        "Minimum net vote margin required for directional consensus",
        "SETTINGS > Engine",
    ),
    "store_candles": ("Persist candles to the local database", "SETTINGS > Local Data"),
    "retention_days": (
        "Days before stored candles are pruned",
        "SETTINGS > Local Data",
    ),
    "save_snapshots": (
        "Save analysis snapshots to the database",
        "SETTINGS > Local Data",
    ),
    "snapshot_interval_seconds": (
        "Minimum seconds between saved snapshots per symbol",
        "SETTINGS > Local Data",
    ),
    "auto_prune_on_startup": (
        "Automatically prune expired DB rows on app startup",
        "SETTINGS > Local Data",
    ),
    "auto_backup_enabled": (
        "Create automatic local zip backup cleanly on exit",
        "SETTINGS > Local Data",
    ),
    "max_backup_count": (
        "Maximum local backup zip archives retained",
        "SETTINGS > Local Data",
    ),
    "max_signal_history_rows": (
        "Maximum rows retained in JSONL signal history",
        "SETTINGS > Local Data",
    ),
    "csv_delimiter": (
        "Delimiter used when exporting history CSVs (comma, semicolon, tab)",
        "SETTINGS > Local Data",
    ),
    "cache_max_size_mb": (
        "Maximum disk budget for local provider/model caches (MB)",
        "SETTINGS > Local Data",
    ),
    "ai_enabled": ("Enable the AI copilot", "SETTINGS > AI Providers"),
    "ai_provider": (
        "Which bring-your-own-key provider to use",
        "SETTINGS > AI Providers",
    ),
    "ai_fallback_provider": (
        "Automatic secondary provider when primary AI provider fails",
        "SETTINGS > AI Providers",
    ),
    "ai_allow_custom_models": (
        "Unlock custom/paid model names in the AI model selector",
        "SETTINGS > AI Providers",
    ),
    "ai_model": ("Model name for the provider", "SETTINGS > AI Providers"),
    "ai_base_url": (
        "Optional custom provider base URL",
        "SETTINGS > AI Providers",
    ),
    "ai_temperature": ("Response randomness 0-2", "SETTINGS > AI Providers"),
    "ai_max_tokens": ("Maximum response tokens", "SETTINGS > AI Providers"),
    "ai_timeout": ("Provider timeout in seconds", "SETTINGS > AI Providers"),
    "ai_system_prompt": (
        "Extra instructions sent to the provider",
        "SETTINGS > AI Providers",
    ),
    "ai_cache_enabled": (
        "Cache identical AI prompts briefly to save quota",
        "SETTINGS > AI Providers",
    ),
    "ai_cache_ttl_seconds": (
        "Seconds before cached AI responses expire",
        "SETTINGS > AI Providers",
    ),
    "ai_chat_history_turns": (
        "Number of recent chat turns included in multi-turn prompts",
        "SETTINGS > AI Providers",
    ),
    "ai_daily_request_cap": (
        "Optional daily cloud AI request budget (0 = unlimited)",
        "SETTINGS > AI Providers",
    ),
    "agent_mode_enabled": (
        "Enable multi-step tool planning in Copilot chat",
        "SETTINGS > AI Providers",
    ),
    "agent_max_steps": (
        "Maximum tool steps per agent plan",
        "SETTINGS > AI Providers",
    ),
    "agent_require_write_confirmation": (
        "Require explicit confirmation before any state-changing agent tool runs",
        "SETTINGS > AI Providers",
    ),
    "use_knowledge": (
        "Include backtest knowledge in prompts",
        "SETTINGS > AI Providers",
    ),
    "use_memory": (
        "Include saved memory notes in prompts",
        "SETTINGS > AI Providers",
    ),
    "use_brain_model": ("Advisory local brain model vote", "SETTINGS > Engine"),
    "ml_model_architecture": (
        "Neural model architecture (v1 MLP, sequence GRU, or ensemble)",
        "SETTINGS > ML Research",
    ),
    "ml_ensemble_members": (
        "Member count when training ensemble neural models",
        "SETTINGS > ML Research",
    ),
    "ml_sequence_window": (
        "Lookback sequence length for temporal GRU models",
        "SETTINGS > ML Research",
    ),
    "ml_history_candles": (
        "Candles fetched for ML research",
        "SETTINGS > ML Research",
    ),
    "ml_epochs": ("Training epochs", "SETTINGS > ML Research"),
    "ml_horizon": ("Prediction horizon in bars", "SETTINGS > ML Research"),
    "ml_deadband_atr": ("ATR-neutral deadband for labels", "SETTINGS > ML Research"),
    "ml_min_samples": ("Minimum labelled examples", "SETTINGS > ML Research"),
    "ml_seed": ("Reproducibility seed", "SETTINGS > ML Research"),
    "ml_probability": ("Advisory probability threshold", "SETTINGS > ML Research"),
    "ml_fetch_timeout": (
        "Public API timeout for research fetches",
        "SETTINGS > ML Research",
    ),
    "backtest_default_spread_pips": (
        "Default simulated round-turn spread cost in pips",
        "SETTINGS > ML Research",
    ),
    "outcome_eval_horizon": (
        "Bar horizon used by Signal Outcomes evaluation",
        "SETTINGS > ML Research",
    ),
    "pair_lookback": (
        "Lagged z-score window for pair research",
        "SETTINGS > Pair Research",
    ),
    "pair_min_overlap": (
        "Minimum aligned candles for pairs",
        "SETTINGS > Pair Research",
    ),
    "pair_entry_z": ("Entry z threshold", "SETTINGS > Pair Research"),
    "pair_exit_z": ("Exit z threshold", "SETTINGS > Pair Research"),
    "pair_stop_z": ("Stop z threshold", "SETTINGS > Pair Research"),
    "pair_cost_bps": ("Turnover cost in basis points", "SETTINGS > Pair Research"),
    "pair_max_holding": ("Maximum holding bars", "SETTINGS > Pair Research"),
    "pair_min_correlation": ("Minimum train correlation", "SETTINGS > Pair Research"),
    "insights_max_rows": ("Insight table row limit", "INSIGHTS"),
    "local_llm_enabled": ("Enable the on-device model", "SETTINGS > Local Models"),
    "local_llm_model_id": ("Registered local model id", "SETTINGS > Local Models"),
    "local_llm_context_tokens": ("Context window tokens", "SETTINGS > Local Models"),
    "local_llm_max_tokens": ("Generation token budget", "SETTINGS > Local Models"),
    "local_llm_threads": ("CPU threads for inference", "SETTINGS > Local Models"),
    "local_llm_batch_size": ("Batch size", "SETTINGS > Local Models"),
    "local_llm_disk_offload": ("Offload layers to disk", "SETTINGS > Local Models"),
    "local_llm_cpu_memory_mb": ("CPU memory budget", "SETTINGS > Local Models"),
    "local_llm_gpu_layers": (
        "GGUF GPU layer offload count (-1 = all layers, 0 = CPU)",
        "SETTINGS > Local Models",
    ),
    "local_llm_top_p": (
        "Nucleus sampling top-p cutoff",
        "SETTINGS > Local Models",
    ),
    "local_llm_repeat_penalty": (
        "Token repetition penalty multiplier",
        "SETTINGS > Local Models",
    ),
    "local_llm_keep_alive_minutes": (
        "Minutes to retain local model weights in memory after chat",
        "SETTINGS > Local Models",
    ),
    "local_llm_seed": (
        "Deterministic generation seed (-1 = random)",
        "SETTINGS > Local Models",
    ),
    "local_llm_verify_sha256": (
        "Verify SHA-256 digest when loading local model files",
        "SETTINGS > Local Models",
    ),
    "mcp_enabled": ("Run the local MCP server", "SETTINGS > MCP Server"),
    "mcp_port": ("MCP loopback port", "SETTINGS > MCP Server"),
    "mcp_allow_writes": ("Expose write tools over MCP", "SETTINGS > MCP Server"),
    "mcp_tunnel_enabled": (
        "Expose the read-only public tunnel",
        "SETTINGS > MCP Server",
    ),
    "mcp_tunnel_executable": (
        "cloudflared binary name or path",
        "SETTINGS > MCP Server",
    ),
    "mcp_rate_limit_rpm": (
        "Maximum requests per minute accepted by local MCP server",
        "SETTINGS > MCP Server",
    ),
    "mcp_tool_timeout_seconds": (
        "Execution timeout per MCP tool invocation (seconds)",
        "SETTINGS > MCP Server",
    ),
    "mcp_strict_origin_check": (
        "Reject non-loopback Origin headers to block DNS rebinding",
        "SETTINGS > MCP Server",
    ),
    "mcp_audit_log_enabled": (
        "Log every MCP tool invocation locally",
        "SETTINGS > MCP Server",
    ),
    "alert_sound_mode": (
        "Audible alert mode (System Bell or Muted)",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "alert_cooldown_seconds": (
        "Minimum seconds before the same alert rule can fire again",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "toast_notifications_enabled": (
        "Display sliding toast cards in Enterprise desktop mode",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "toast_duration_ms": (
        "Toast notification display duration in milliseconds",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "quiet_hours_enabled": (
        "Suppress bells and outbound webhook/bot notifications during quiet window",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "quiet_hours_start": (
        "Quiet hours start time in 24-hour HH:MM format",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "quiet_hours_end": (
        "Quiet hours end time in 24-hour HH:MM format",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "alert_on_stream_disconnect": (
        "Trigger desktop alert if live market feed stays disconnected",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "alert_on_drawdown_breach": (
        "Warn immediately if planned risk or MT5 equity exceeds max drawdown",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "auto_disable_one_shot_price_alerts": (
        "Automatically disable price cross alerts after firing once",
        "SETTINGS > Alerts & Quiet Hours",
    ),
    "telegram_enabled": ("Run the Telegram bot", "SETTINGS > Telegram"),
    "telegram_chat_ids": (
        "Comma-separated authorized chat ids",
        "SETTINGS > Telegram",
    ),
    "telegram_alerts_enabled": (
        "Send alerts through Telegram",
        "SETTINGS > Telegram",
    ),
    "telegram_allow_commands": ("Accept Telegram commands", "SETTINGS > Telegram"),
    "telegram_min_signal_score": (
        "Minimum absolute signal score sent to Telegram",
        "SETTINGS > Telegram",
    ),
    "telegram_include_sl_tp_levels": (
        "Include ATR Stop-Loss and Take-Profit estimates in Telegram messages",
        "SETTINGS > Telegram",
    ),
    "telegram_daily_digest_enabled": (
        "Send daily market summary digest to authorized chats",
        "SETTINGS > Telegram",
    ),
    "telegram_digest_hour_utc": (
        "UTC hour (0-23) for daily Telegram summary digest",
        "SETTINGS > Telegram",
    ),
    "mt5_enabled": ("Enable the MT5 bridge", "SETTINGS > MT5 Bridge"),
    "mt5_server": ("Broker server name", "SETTINGS > MT5 Bridge"),
    "mt5_login": ("MT5 account number", "SETTINGS > MT5 Bridge"),
    "mt5_password": ("MT5 password (stored owner-only)", "SETTINGS > MT5 Bridge"),
    "mt5_path": ("Optional terminal64.exe path", "SETTINGS > MT5 Bridge"),
    "mt5_magic": ("Order magic number", "SETTINGS > MT5 Bridge"),
    "mt5_symbol_map": (
        "Symbol mapping DERIV=MT5 pairs or JSON",
        "SETTINGS > MT5 Bridge",
    ),
    "mt5_auto_sync": (
        "Sync MT5 bridge status & quotes automatically",
        "SETTINGS > MT5 Bridge",
    ),
    "mt5_order_deviation_points": (
        "Maximum acceptable slippage in points on market orders",
        "SETTINGS > MT5 Bridge",
    ),
    "mt5_filling_mode": (
        "Broker order filling policy (Auto, IOC, FOK, RETURN)",
        "SETTINGS > MT5 Bridge",
    ),
    "mt5_sync_interval_seconds": (
        "Background sync cadence in seconds when MT5 auto-sync is enabled",
        "SETTINGS > MT5 Bridge",
    ),
    "dm_enabled": (
        "Enable direct messaging notifications",
        "SETTINGS > Direct Messaging",
    ),
    "dm_webhook_url": ("Webhook target URL", "SETTINGS > Direct Messaging"),
    "dm_webhook_format": (
        "Webhook JSON schema (auto, discord, slack, generic)",
        "SETTINGS > Direct Messaging",
    ),
    "dm_https_only": (
        "Reject non-HTTPS webhook URLs",
        "SETTINGS > Direct Messaging",
    ),
    "dm_min_score": (
        "Minimum score for DM signal alerts",
        "SETTINGS > Direct Messaging",
    ),
    "dm_notify_signals": (
        "Send signal notifications",
        "SETTINGS > Direct Messaging",
    ),
    "dm_notify_alerts": (
        "Send alert notifications",
        "SETTINGS > Direct Messaging",
    ),
    "account_balance_default": (
        "Default account balance pre-filled in risk planner",
        "SETTINGS > Risk & Safety",
    ),
    "account_currency": (
        "Display currency code for risk & equity calculations",
        "SETTINGS > Risk & Safety",
    ),
    "default_risk_percent": (
        "Default risk per trade (percent)",
        "SETTINGS > Risk & Safety",
    ),
    "default_reward_to_risk": (
        "Default target Reward:Risk ratio in Tools & Orders",
        "SETTINGS > Risk & Safety",
    ),
    "default_pip_value_per_lot": (
        "Default pip value per standard lot in Risk Planner",
        "SETTINGS > Risk & Safety",
    ),
    "fx_risk_percent": (
        "Per-trade risk percent override for Forex pairs",
        "SETTINGS > Risk & Safety",
    ),
    "synthetic_risk_percent": (
        "Per-trade risk percent override for Synthetic indices",
        "SETTINGS > Risk & Safety",
    ),
    "crypto_risk_percent": (
        "Per-trade risk percent override for Crypto pairs",
        "SETTINGS > Risk & Safety",
    ),
    "max_drawdown_limit": (
        "Drawdown guard limit (percent)",
        "SETTINGS > Risk & Safety",
    ),
    "order_dry_run_mode": (
        "Paper/simulation lock preventing live MT5 order submission",
        "SETTINGS > Risk & Safety",
    ),
    "require_stop_loss_on_live_orders": (
        "Block live MT5 orders when Stop-Loss is blank",
        "SETTINGS > Risk & Safety",
    ),
    "max_lot_size_cap": (
        "Hard ceiling on single-order volume in lots",
        "SETTINGS > Risk & Safety",
    ),
    "max_open_positions": (
        "Maximum simultaneous open MT5 positions permitted",
        "SETTINGS > Risk & Safety",
    ),
    "daily_max_loss_percent": (
        "Daily drawdown circuit breaker threshold (percent)",
        "SETTINGS > Risk & Safety",
    ),
    "daily_max_trades": (
        "Maximum live orders allowed per UTC day",
        "SETTINGS > Risk & Safety",
    ),
    "min_rr_for_live_order": (
        "Minimum Reward:Risk required when both SL and TP are specified",
        "SETTINGS > Risk & Safety",
    ),
    "pre_trade_checklist_enabled": (
        "Prompt pre-trade checklist confirmation before sending live orders",
        "SETTINGS > Risk & Safety",
    ),
    "pre_trade_checklist_items": (
        "Semicolon-separated checklist items verified before live order execution",
        "SETTINGS > Risk & Safety",
    ),
    "market_data_provider": (
        "Candle provider for analysis",
        "SETTINGS > Data Providers",
    ),
    "fallback_data_provider": (
        "Fallback candle provider when primary source fails",
        "SETTINGS > Data Providers",
    ),
    "provider_candle_count": (
        "Candles fetched per provider request",
        "SETTINGS > Data Providers",
    ),
    "provider_cache_enabled": (
        "Cache provider candle responses briefly to prevent rate-limiting",
        "SETTINGS > Data Providers",
    ),
    "provider_cache_ttl_seconds": (
        "Seconds before cached provider candles expire",
        "SETTINGS > Data Providers",
    ),
    "provider_requests_per_minute": (
        "Client-side rate limit for external market data providers",
        "SETTINGS > Data Providers",
    ),
    "confluence_min_score": (
        "Strict confluence threshold",
        "SETTINGS > Data Providers",
    ),
    "confluence_search_score": (
        "Search-mode threshold floor",
        "SETTINGS > Data Providers",
    ),
    "confluence_require_strict_only": (
        "Hide relaxed search-mode fallback cards in ANALYSIS scans",
        "SETTINGS > Data Providers",
    ),
    "confluence_mtf_confirmation": (
        "Require higher-timeframe trend alignment in confluence scans",
        "SETTINGS > Data Providers",
    ),
    "confluence_higher_timeframe": (
        "Higher timeframe used when MTF confirmation is active",
        "SETTINGS > Data Providers",
    ),
    "confluence_atr_stop_mult": ("ATR multiple for stops", "SETTINGS > Data Providers"),
    "confluence_atr_tp_mult": ("ATR multiple for targets", "SETTINGS > Data Providers"),
    "confluence_horizon": ("Outcome horizon in bars", "SETTINGS > Data Providers"),
    "confluence_min_analogs": (
        "Minimum analog matches for win rate",
        "SETTINGS > Data Providers",
    ),
    "active_settings_profile": (
        "Active workspace settings preset profile",
        "SETTINGS > Profiles & Diagnostics",
    ),
    "log_level": (
        "Application diagnostic log verbosity (WARNING, INFO, DEBUG)",
        "SETTINGS > Profiles & Diagnostics",
    ),
    "config_version": (
        "Internal config schema version (do not edit)",
        "SETTINGS > Profiles & Diagnostics",
    ),
    "dry_run": (
        "Global dry-run lock: when on, no live order is ever sent",
        "SETTINGS > Risk & Safety",
    ),
}

HEADER = """# Settings reference

> Generated by `scripts/gen_settings_docs.py` from
> `neezy_backend/config.py` — do not edit by hand; run the script instead.
> Validation errors always name the field.

| Field | Default | Description | Where |
|-------|---------|-------------|-------|
"""


def render() -> str:
    lines = [HEADER]
    for field in fields(AppSettings):
        default = field.default
        description, location = DESCRIPTIONS.get(field.name, ("(undocumented)", "—"))
        rendered = "*(empty)*" if default == "" else f"`{default!r}`"
        lines.append(f"| `{field.name}` | {rendered} | {description} | {location} |\n")
    undocumented = [
        field.name for field in fields(AppSettings) if field.name not in DESCRIPTIONS
    ]
    if undocumented:
        lines.append(
            f"\n> NOTE: {len(undocumented)} fields lack descriptions: "
            + ", ".join(f"`{name}`" for name in undocumented)
            + "\n"
        )
    return "".join(lines)


def main() -> int:
    target = Path(__file__).resolve().parent.parent / "docs" / "SETTINGS.md"
    target.write_text(render(), encoding="utf-8")
    print(f"wrote {target} ({len(fields(AppSettings))} fields)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
