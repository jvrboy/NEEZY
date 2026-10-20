"""Reusable backend services for the NEEZY desktop workspace."""

__version__ = "1.1.0"

from .alerts import AlertEngine, AlertRule, AlertRuleStore
from .analytics import correlation_matrix, rank_opportunities
from .backtest import BacktestConfig, run_backtest
from .config import AppSettings
from .events import EventBus, StreamEvent
from .indicators import adx, analyze, atr, bollinger, ema, rsi, sma, stochastic
from .patterns import detect_patterns, price_action_summary
from .risk import atr_levels, position_size
from .storage import SettingsStore, SignalHistoryStore, get_data_dir

__all__ = [
    "AlertEngine",
    "AlertRule",
    "AlertRuleStore",
    "AppSettings",
    "BacktestConfig",
    "EventBus",
    "SettingsStore",
    "SignalHistoryStore",
    "StreamEvent",
    "adx",
    "analyze",
    "atr",
    "atr_levels",
    "bollinger",
    "correlation_matrix",
    "detect_patterns",
    "ema",
    "get_data_dir",
    "position_size",
    "price_action_summary",
    "rank_opportunities",
    "rsi",
    "run_backtest",
    "sma",
    "stochastic",
]
