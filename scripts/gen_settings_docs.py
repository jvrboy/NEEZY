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
    "deriv_endpoint": (
        "Optional custom Deriv WebSocket endpoint",
        "SETTINGS > Connection",
    ),
    "reconnect_seconds": ("First reconnect delay in seconds", "SETTINGS > Connection"),
    "max_reconnect_seconds": (
        "Reconnect backoff ceiling in seconds",
        "SETTINGS > Connection",
    ),
    "strategy": ("Active single-market strategy", "INSIGHTS"),
    "supertrend_period": ("Supertrend lookback", "INSIGHTS"),
    "supertrend_multiplier": ("Supertrend band multiple", "INSIGHTS"),
    "divergence_lookback": ("Divergence detection lookback", "INSIGHTS"),
    "correlation_window": ("Rolling correlation window", "INSIGHTS"),
    "correlation_baseline": ("Correlation baseline sample count", "INSIGHTS"),
    "show_strategy_overlay": ("Draw strategy overlays on the chart", "CHART"),
    "store_candles": ("Persist candles to the local database", "SETTINGS > Storage"),
    "retention_days": ("Days before stored candles are pruned", "SETTINGS > Storage"),
    "save_snapshots": ("Save analysis snapshots to the database", "SETTINGS > Storage"),
    "ai_enabled": ("Enable the AI copilot", "SETTINGS > AI"),
    "ai_provider": ("Which bring-your-own-key provider to use", "SETTINGS > AI"),
    "ai_model": ("Model name for the provider", "SETTINGS > AI"),
    "ai_base_url": ("Optional custom provider base URL", "SETTINGS > AI"),
    "ai_temperature": ("Response randomness 0-2", "SETTINGS > AI"),
    "ai_max_tokens": ("Maximum response tokens", "SETTINGS > AI"),
    "ai_timeout": ("Provider timeout in seconds", "SETTINGS > AI"),
    "ai_system_prompt": ("Extra instructions sent to the provider", "SETTINGS > AI"),
    "use_knowledge": ("Include backtest knowledge in prompts", "SETTINGS > AI"),
    "use_memory": ("Include saved memory notes in prompts", "SETTINGS > AI"),
    "use_brain_model": ("Advisory local brain model vote", "INSIGHTS > BRAIN"),
    "ml_history_candles": ("Candles fetched for ML research", "INSIGHTS > ML RESEARCH"),
    "ml_epochs": ("Training epochs", "INSIGHTS > ML RESEARCH"),
    "ml_horizon": ("Prediction horizon in bars", "INSIGHTS > ML RESEARCH"),
    "ml_deadband_atr": ("ATR-neutral deadband for labels", "INSIGHTS > ML RESEARCH"),
    "ml_min_samples": ("Minimum labelled examples", "INSIGHTS > ML RESEARCH"),
    "ml_seed": ("Reproducibility seed", "INSIGHTS > ML RESEARCH"),
    "ml_probability": ("Advisory probability threshold", "INSIGHTS > ML RESEARCH"),
    "ml_fetch_timeout": (
        "Public API timeout for research fetches",
        "INSIGHTS > ML RESEARCH",
    ),
    "pair_lookback": (
        "Lagged z-score window for pair research",
        "INSIGHTS > PAIR RESEARCH",
    ),
    "pair_min_overlap": (
        "Minimum aligned candles for pairs",
        "INSIGHTS > PAIR RESEARCH",
    ),
    "pair_entry_z": ("Entry z threshold", "INSIGHTS > PAIR RESEARCH"),
    "pair_exit_z": ("Exit z threshold", "INSIGHTS > PAIR RESEARCH"),
    "pair_stop_z": ("Stop z threshold", "INSIGHTS > PAIR RESEARCH"),
    "pair_cost_bps": ("Turnover cost in basis points", "INSIGHTS > PAIR RESEARCH"),
    "pair_max_holding": ("Maximum holding bars", "INSIGHTS > PAIR RESEARCH"),
    "pair_min_correlation": ("Minimum train correlation", "INSIGHTS > PAIR RESEARCH"),
    "insights_max_rows": ("Insight table row limit", "INSIGHTS"),
    "local_llm_enabled": ("Enable the on-device model", "SETTINGS > LOCAL MODELS"),
    "local_llm_model_id": ("Registered local model id", "SETTINGS > LOCAL MODELS"),
    "local_llm_context_tokens": ("Context window tokens", "SETTINGS > LOCAL MODELS"),
    "local_llm_max_tokens": ("Generation token budget", "SETTINGS > LOCAL MODELS"),
    "local_llm_threads": ("CPU threads for inference", "SETTINGS > LOCAL MODELS"),
    "local_llm_batch_size": ("Batch size", "SETTINGS > LOCAL MODELS"),
    "local_llm_disk_offload": ("Offload layers to disk", "SETTINGS > LOCAL MODELS"),
    "local_llm_cpu_memory_mb": ("CPU memory budget", "SETTINGS > LOCAL MODELS"),
    "mcp_enabled": ("Run the local MCP server", "SETTINGS > MCP"),
    "mcp_port": ("MCP loopback port", "SETTINGS > MCP"),
    "mcp_allow_writes": ("Expose write tools over MCP", "SETTINGS > MCP"),
    "mcp_tunnel_enabled": ("Expose the read-only public tunnel", "SETTINGS > MCP"),
    "mcp_tunnel_executable": ("cloudflared binary name or path", "SETTINGS > MCP"),
    "telegram_enabled": ("Run the Telegram bot", "SETTINGS > TELEGRAM"),
    "telegram_chat_ids": ("Comma-separated authorized chat ids", "SETTINGS > TELEGRAM"),
    "telegram_alerts_enabled": ("Send alerts through Telegram", "SETTINGS > TELEGRAM"),
    "telegram_allow_commands": ("Accept Telegram commands", "SETTINGS > TELEGRAM"),
    "mt5_enabled": ("Enable the MT5 bridge", "SETTINGS > INTEGRATIONS"),
    "mt5_server": ("Broker server name", "SETTINGS > INTEGRATIONS"),
    "mt5_login": ("MT5 account number", "SETTINGS > INTEGRATIONS"),
    "mt5_password": ("MT5 password (stored owner-only)", "SETTINGS > INTEGRATIONS"),
    "mt5_path": ("Optional terminal64.exe path", "SETTINGS > INTEGRATIONS"),
    "mt5_magic": ("Order magic number", "SETTINGS > INTEGRATIONS"),
    "mt5_symbol_map": (
        "Symbol mapping DERIV=MT5 pairs or JSON",
        "SETTINGS > INTEGRATIONS",
    ),
    "mt5_auto_sync": ("Reconnect the bridge automatically", "SETTINGS > INTEGRATIONS"),
    "dm_enabled": ("Enable direct messaging notifications", "SETTINGS > DM"),
    "dm_webhook_url": ("Webhook target URL", "SETTINGS > DM"),
    "dm_min_score": ("Minimum score for DM signal alerts", "SETTINGS > DM"),
    "dm_notify_signals": ("Send signal notifications", "SETTINGS > DM"),
    "dm_notify_alerts": ("Send alert notifications", "SETTINGS > DM"),
    "default_risk_percent": ("Default risk per trade (percent)", "TOOLS"),
    "max_drawdown_limit": ("Drawdown guard limit (percent)", "TOOLS"),
    "market_data_provider": (
        "Candle provider for analysis",
        "SETTINGS > DATA PROVIDERS",
    ),
    "provider_candle_count": (
        "Candles fetched per provider request",
        "SETTINGS > DATA PROVIDERS",
    ),
    "confluence_min_score": (
        "Strict confluence threshold",
        "SETTINGS > DATA PROVIDERS",
    ),
    "confluence_search_score": (
        "Search-mode threshold floor",
        "SETTINGS > DATA PROVIDERS",
    ),
    "confluence_atr_stop_mult": ("ATR multiple for stops", "SETTINGS > DATA PROVIDERS"),
    "confluence_atr_tp_mult": ("ATR multiple for targets", "SETTINGS > DATA PROVIDERS"),
    "confluence_horizon": ("Outcome horizon in bars", "SETTINGS > DATA PROVIDERS"),
    "confluence_min_analogs": (
        "Minimum analog matches for win rate",
        "SETTINGS > DATA PROVIDERS",
    ),
}

HEADER = """# Settings reference

> Generated by `scripts/gen_settings_docs.py` from
> `neezy_backend/config.py` — do not edit by hand; run the script instead.
> Validation errors always name the field.

| Field | Default | Description | Where |
|-------|---------|-------------|-------|
"""


def main() -> int:
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
    target = Path(__file__).resolve().parent.parent / "docs" / "SETTINGS.md"
    target.write_text("".join(lines), encoding="utf-8")
    print(f"wrote {target} ({len(fields(AppSettings))} fields)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
