"""Reusable backend services for the NEEZY desktop workspace."""

__version__ = "1.5.0"

from .ai import PROVIDERS, AIClient, AIError, AIKeyStore, free_models
from .alerts import AlertEngine, AlertRule, AlertRuleStore, is_quiet_hours_now
from .analytics import correlation_matrix, rank_opportunities
from .backtest import BacktestConfig, run_backtest
from .config import (
    SETTINGS_PROFILES,
    AppSettings,
    apply_env_overrides,
    apply_profile,
)
from .context import format_context, market_snapshot
from .database import LocalDatabase
from .divergence import (
    correlation_divergence,
    detect_divergence,
    detect_divergences,
    rsi_divergence,
)
from .events import EventBus, StreamEvent
from .indicators import (
    adx,
    analyze,
    atr,
    bollinger,
    ema,
    macd_histogram_series,
    rsi,
    rsi_series,
    sma,
    stochastic,
)
from .patterns import detect_patterns, price_action_summary
from .risk import atr_levels, position_size
from .storage import SettingsStore, SignalHistoryStore, get_data_dir
from .strategies import STRATEGIES, StrategySignal, consensus, evaluate, run_all
from .trend import donchian, keltner, supertrend, trend_summary

__all__ = [
    "PROVIDERS",
    "SETTINGS_PROFILES",
    "STRATEGIES",
    "AIClient",
    "AIError",
    "AIKeyStore",
    "AlertEngine",
    "AlertRule",
    "AlertRuleStore",
    "AppSettings",
    "BacktestConfig",
    "EventBus",
    "LocalDatabase",
    "SettingsStore",
    "SignalHistoryStore",
    "StrategySignal",
    "StreamEvent",
    "adx",
    "analyze",
    "apply_env_overrides",
    "apply_profile",
    "atr",
    "atr_levels",
    "bollinger",
    "consensus",
    "correlation_divergence",
    "correlation_matrix",
    "detect_divergence",
    "detect_divergences",
    "detect_patterns",
    "donchian",
    "ema",
    "evaluate",
    "format_context",
    "free_models",
    "get_data_dir",
    "is_quiet_hours_now",
    "keltner",
    "macd_histogram_series",
    "market_snapshot",
    "position_size",
    "price_action_summary",
    "rank_opportunities",
    "rsi",
    "rsi_divergence",
    "rsi_series",
    "run_all",
    "run_backtest",
    "sma",
    "stochastic",
    "supertrend",
    "trend_summary",
]
