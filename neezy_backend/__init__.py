"""Reusable backend services for the NEEZY desktop workspace."""

__version__ = "1.7.0"

from .agents import Agent, AgentTeam, Blackboard, TeamContext
from .ai import PROVIDERS, AIClient, AIError, AIKeyStore, free_models
from .alerts import AlertEngine, AlertRule, AlertRuleStore, is_quiet_hours_now
from .analytics import correlation_matrix, rank_opportunities
from .backtest import BacktestConfig, run_backtest
from .bots import Bot, BotContext, BotDecision, BotManager, default_bots
from .btoken import BTOKENS, normalize_argv, translate
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
    advanced_suite,
    adx,
    analyze,
    aroon,
    atr,
    bollinger,
    cci,
    choppiness,
    elder_ray,
    ema,
    fisher_transform,
    ichimoku,
    macd_histogram_series,
    pivot_points,
    roc,
    rsi,
    rsi_series,
    sma,
    stochastic,
    trix,
    ultimate_oscillator,
    williams_r,
    zscore,
)
from .patterns import detect_patterns, price_action_summary
from .risk import atr_levels, position_size
from .sessions import active_sessions, sessions_report, summarize
from .storage import SettingsStore, SignalHistoryStore, get_data_dir
from .strategies import STRATEGIES, StrategySignal, consensus, evaluate, run_all
from .trend import donchian, keltner, supertrend, trend_summary

__all__ = [
    "BTOKENS",
    "PROVIDERS",
    "SETTINGS_PROFILES",
    "STRATEGIES",
    "AIClient",
    "AIError",
    "AIKeyStore",
    "Agent",
    "AgentTeam",
    "AlertEngine",
    "AlertRule",
    "AlertRuleStore",
    "AppSettings",
    "BacktestConfig",
    "Blackboard",
    "Bot",
    "BotContext",
    "BotDecision",
    "BotManager",
    "EventBus",
    "LocalDatabase",
    "SettingsStore",
    "SignalHistoryStore",
    "StrategySignal",
    "StreamEvent",
    "TeamContext",
    "active_sessions",
    "advanced_suite",
    "adx",
    "analyze",
    "apply_env_overrides",
    "apply_profile",
    "aroon",
    "atr",
    "atr_levels",
    "bollinger",
    "cci",
    "choppiness",
    "consensus",
    "correlation_divergence",
    "correlation_matrix",
    "default_bots",
    "detect_divergence",
    "detect_divergences",
    "detect_patterns",
    "donchian",
    "elder_ray",
    "ema",
    "evaluate",
    "fisher_transform",
    "format_context",
    "free_models",
    "get_data_dir",
    "ichimoku",
    "is_quiet_hours_now",
    "keltner",
    "macd_histogram_series",
    "market_snapshot",
    "normalize_argv",
    "pivot_points",
    "position_size",
    "price_action_summary",
    "rank_opportunities",
    "roc",
    "rsi",
    "rsi_divergence",
    "rsi_series",
    "run_all",
    "run_backtest",
    "sessions_report",
    "sma",
    "stochastic",
    "summarize",
    "supertrend",
    "translate",
    "trend_summary",
    "trix",
    "ultimate_oscillator",
    "williams_r",
    "zscore",
]
