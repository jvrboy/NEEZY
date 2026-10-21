"""Allow-listed MCP/Telegram tools for the running desktop workspace."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .alerts import AlertRule
from .brain import predict, train_model
from .database import LocalDatabase
from .datasets import dataset_summary, research_report, shipped_brain_model
from .markets import SYMBOLS, TIMEFRAMES
from .outcomes import evaluate_outcomes, summarize
from .remote import AppCommandBridge
from .research import pair_research
from .tools import ToolPermission, ToolRegistry

REMOTE_SETTINGS_SCHEMA = {
    "name": "update_app_settings",
    "description": "Update a small allow-list of safe workspace settings.",
    "parameters": {
        "type": "object",
        "properties": {
            "updates": {
                "type": "object",
                "properties": {
                    "auto_refresh": {"type": "boolean"},
                    "alerts_enabled": {"type": "boolean"},
                    "compact_mode": {"type": "boolean"},
                    "store_candles": {"type": "boolean"},
                    "save_snapshots": {"type": "boolean"},
                    "polling_ms": {"type": "integer", "minimum": 50, "maximum": 2000},
                    "candle_limit": {"type": "integer", "minimum": 60, "maximum": 1000},
                    "retention_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 3650,
                    },
                    "theme": {
                        "type": "string",
                        "enum": ["Liquid dark", "Midnight blue", "High contrast"],
                    },
                    "alert_min_score": {"type": "integer", "minimum": 1, "maximum": 4},
                    "strategy": {
                        "type": "string",
                        "enum": [
                            "SUPERTREND",
                            "EMA_PULLBACK",
                            "DIVERGENCE",
                            "DONCHIAN",
                            "SQUEEZE",
                            "MACD",
                            "KELTNER",
                        ],
                    },
                    "show_strategy_overlay": {"type": "boolean"},
                    "use_knowledge": {"type": "boolean"},
                    "use_memory": {"type": "boolean"},
                    "use_brain_model": {"type": "boolean"},
                },
                "additionalProperties": False,
                "minProperties": 1,
            }
        },
        "required": ["updates"],
        "additionalProperties": False,
    },
}


def _bounded(value: Any, low: int, high: int) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer") from None
    return min(max(count, low), high)


def _check_market(symbol: str) -> str:
    cleaned = symbol.strip()
    if cleaned not in SYMBOLS:
        raise ValueError(f"unknown market {cleaned!r}; use a canonical Deriv symbol")
    return cleaned


def _model_key(symbol: str, timeframe: str) -> str:
    return f"brain:model:{symbol}:{timeframe}"


def register_app_tools(
    registry: ToolRegistry,
    database: LocalDatabase | None,
    bridge: AppCommandBridge,
) -> ToolRegistry:
    """Register safe tools that work against the running NEEZY desktop app."""

    def db() -> LocalDatabase:
        if database is None:
            raise RuntimeError("local database is unavailable")
        return database

    def app_status() -> dict[str, Any]:
        return bridge.call("app_status")

    def list_markets(market: str = "") -> list[dict[str, str]]:
        group = market.strip().lower()
        return [
            {"symbol": symbol, "name": name}
            for symbol, name in SYMBOLS.items()
            if not group or group in name.lower() or group in symbol.lower()
        ]

    def analyze_market(symbol: str, timeframe: str = "5m") -> dict[str, Any]:
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of: {', '.join(TIMEFRAMES)}")
        return bridge.call(
            "analyze_market", symbol=_check_market(symbol), timeframe=timeframe
        )

    def scan_market(symbol: str, timeframe: str = "5m") -> dict[str, Any]:
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of: {', '.join(TIMEFRAMES)}")
        return bridge.call(
            "scan_market", symbol=_check_market(symbol), timeframe=timeframe
        )

    def ask_copilot(question: str) -> str:
        cleaned = question.strip()
        if not cleaned:
            raise ValueError("question must not be empty")
        return bridge.call("ask_copilot", question=cleaned)

    def get_recent_signals(limit: int = 20, symbol: str = "") -> list[dict[str, Any]]:
        market = _check_market(symbol) if symbol.strip() else None
        return db().recent_signals(limit=_bounded(limit, 1, 100), symbol=market)

    def list_alert_rules() -> list[dict[str, Any]]:
        return bridge.call("list_alert_rules")

    def create_alert_rule(
        symbol: str,
        metric: str,
        operator: str,
        value: str,
        note: str = "",
    ) -> dict[str, Any]:
        market = "*" if symbol.strip() == "*" else _check_market(symbol)
        return bridge.call(
            "create_alert_rule",
            symbol=market,
            metric=metric,
            operator=operator,
            value=value,
            note=note,
        )

    def delete_alert_rule(rule_id: str) -> dict[str, Any]:
        return bridge.call("delete_alert_rule", rule_id=rule_id.strip())

    def get_app_settings() -> dict[str, Any]:
        return bridge.call("get_app_settings")

    def update_app_settings(updates: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(updates, dict) or not updates:
            raise ValueError("updates must be a non-empty object")
        allowed = set(
            REMOTE_SETTINGS_SCHEMA["parameters"]["properties"]["updates"]["properties"]
        )
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(
                f"settings cannot be changed remotely: {', '.join(sorted(unknown))}"
            )
        return bridge.call("update_app_settings", updates=updates)

    def set_active_market(symbol: str) -> dict[str, Any]:
        return bridge.call("set_active_market", symbol=_check_market(symbol))

    def set_active_timeframe(timeframe: str) -> dict[str, Any]:
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of: {', '.join(TIMEFRAMES)}")
        return bridge.call("set_active_timeframe", timeframe=timeframe)

    def search_memory(query: str, limit: int = 5) -> list[dict[str, Any]]:
        return db().search_memory(query, limit=_bounded(limit, 1, 50))

    def save_memory(content: str, category: str = "general") -> dict[str, Any]:
        text = content.strip()
        if not text:
            raise ValueError("memory content must not be empty")
        if len(text) > 4000:
            raise ValueError("memory content must be at most 4000 characters")
        item_id = db().add_memory(text, category=category.strip() or "general")
        return {
            "id": item_id,
            "category": category.strip() or "general",
            "content": text,
        }

    def get_outcome_report(
        symbol: str,
        timeframe: str = "5m",
        horizon: int = 10,
        limit: int = 500,
    ) -> dict[str, Any]:
        market = _check_market(symbol)
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of: {', '.join(TIMEFRAMES)}")
        bars = _bounded(horizon, 1, 100)
        signals = [
            row
            for row in db().recent_signals(
                limit=_bounded(limit, 1, 2000), symbol=market
            )
            if row.get("timeframe") == timeframe
        ]
        candles = db().load_candles(market, timeframe, limit=20_000)
        outcomes = evaluate_outcomes(signals, candles, horizon=bars)
        return {
            "symbol": market,
            "timeframe": timeframe,
            "horizon_candles": bars,
            "resolved": len(outcomes),
            "stats": summarize(outcomes),
            "caveat": "Historical close-to-close outcomes only; not a forecast.",
        }

    def get_research_report() -> dict[str, Any]:
        return research_report()

    def get_dataset_inventory() -> dict[str, Any]:
        return dataset_summary()

    def research_forex_pair(
        left: str, right: str, timeframe: str = "5m"
    ) -> dict[str, Any]:
        if timeframe not in TIMEFRAMES:
            raise ValueError("unsupported timeframe")
        a, b = _check_market(left), _check_market(right)
        if a == b or not all(symbol.startswith("frx") for symbol in (a, b)):
            raise ValueError("two distinct Forex markets are required")
        result = pair_research(
            db().load_candles(a, timeframe, limit=5000),
            db().load_candles(b, timeframe, limit=5000),
        )
        result.pop("path")
        return result

    def mt5_status() -> dict[str, Any]:
        from neezy_backend.mt5_bridge import get_global_mt5_bridge

        return get_global_mt5_bridge().get_status()

    def mt5_account_info() -> dict[str, Any]:
        from neezy_backend.mt5_bridge import get_global_mt5_bridge

        return get_global_mt5_bridge().get_account_info()

    def mt5_get_quote(symbol: str) -> dict[str, Any]:
        from neezy_backend.mt5_bridge import get_global_mt5_bridge

        return get_global_mt5_bridge().get_quote(_check_market(symbol))

    def send_dm_message(webhook_url: str, title: str, message: str) -> dict[str, Any]:
        from neezy_backend.dm import send_dm_notification

        return send_dm_notification(webhook_url, title, message)

    def get_decision_metrics(symbol: str, timeframe: str = "5m") -> dict[str, Any]:
        from neezy_backend.dm import compute_decision_metrics

        market = _check_market(symbol)
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of: {', '.join(TIMEFRAMES)}")
        candles = db().load_candles(market, timeframe, limit=2000)
        return compute_decision_metrics(market, timeframe, candles)

    def get_brain_status(symbol: str, timeframe: str = "5m") -> dict[str, Any]:
        market = _check_market(symbol)
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of: {', '.join(TIMEFRAMES)}")
        model = db().get_value(_model_key(market, timeframe))
        if not isinstance(model, dict):
            model = shipped_brain_model(market, timeframe)
        if not isinstance(model, dict):
            return {"symbol": market, "timeframe": timeframe, "trained": False}
        return {
            "symbol": market,
            "timeframe": timeframe,
            "trained": True,
            "trained_at": model.get("trained_at"),
            "deployment_ready": bool(model.get("deployment_ready")),
            "test_metrics": model.get("test_metrics", {}),
            "validation_note": model.get("validation_note", ""),
        }

    def predict_brain(symbol: str, timeframe: str = "5m") -> dict[str, Any]:
        market = _check_market(symbol)
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of: {', '.join(TIMEFRAMES)}")
        model = db().get_value(_model_key(market, timeframe))
        if not isinstance(model, dict):
            model = shipped_brain_model(market, timeframe)
        if not isinstance(model, dict):
            raise ValueError(
                "no local neural model has been trained for this market/timeframe"
            )
        candles = db().load_candles(market, timeframe, limit=2000)
        result = predict(candles, model)
        if result is None:
            raise ValueError("not enough saved closed candles to create a prediction")
        return result

    def train_signal_brain(
        symbol: str,
        timeframe: str = "5m",
        horizon: int = 5,
        limit: int = 5000,
        min_samples: int = 200,
    ) -> dict[str, Any]:
        market = _check_market(symbol)
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"timeframe must be one of: {', '.join(TIMEFRAMES)}")
        candles = db().load_candles(
            market, timeframe, limit=_bounded(limit, 200, 20_000)
        )
        trained = train_model(
            candles,
            symbol=market,
            timeframe=timeframe,
            horizon=_bounded(horizon, 1, 100),
            min_samples=_bounded(min_samples, 60, 5000),
        )
        db().set_value(_model_key(market, timeframe), trained["model"])
        return trained["report"]

    registry.register(
        "app_status",
        "Read current connection, selection, and signal status.",
        app_status,
    )
    registry.register(
        "list_markets",
        "List supported markets; optionally filter by name or symbol.",
        list_markets,
    )
    registry.register(
        "analyze_market",
        "Read the active local candle cache for one market and timeframe.",
        analyze_market,
    )
    registry.register(
        "scan_market",
        "Score every NEEZY strategy on local candles and return consensus.",
        scan_market,
    )
    registry.register(
        "ask_copilot",
        "Ask the on-device rule-based copilot about current markets.",
        ask_copilot,
    )
    registry.register(
        "get_recent_signals",
        "Read recently persisted signal transitions.",
        get_recent_signals,
    )
    registry.register(
        "list_alert_rules", "Read configured local alert rules.", list_alert_rules
    )
    registry.register(
        "create_alert_rule",
        "Create a validated price, RSI, score, ADX, signal, or pattern alert.",
        create_alert_rule,
        ToolPermission.WRITE,
    )
    registry.register(
        "delete_alert_rule",
        "Delete one alert rule by its rule id.",
        delete_alert_rule,
        ToolPermission.WRITE,
    )
    registry.register(
        "get_app_settings",
        "Read current non-secret application settings.",
        get_app_settings,
    )
    registry.register(
        "update_app_settings",
        "Update safe workspace settings; integration credentials and paths "
        "cannot be changed.",
        update_app_settings,
        ToolPermission.WRITE,
        schema=REMOTE_SETTINGS_SCHEMA,
    )
    registry.register(
        "set_active_market",
        "Change the market selected in the desktop workspace.",
        set_active_market,
        ToolPermission.WRITE,
    )
    registry.register(
        "set_active_timeframe",
        "Change the active desktop analysis timeframe.",
        set_active_timeframe,
        ToolPermission.WRITE,
    )
    registry.register(
        "search_memory", "Search the local FTS5 memory store.", search_memory
    )
    registry.register(
        "save_memory",
        "Save a note to NEEZY's local long-term memory.",
        save_memory,
        ToolPermission.WRITE,
    )
    registry.register(
        "get_outcome_report",
        "Measure resolved saved signal outcomes for one timeframe.",
        get_outcome_report,
    )
    registry.register(
        "get_brain_status",
        "Read neural-model training and held-out validation status.",
        get_brain_status,
    )
    registry.register(
        "predict_brain",
        "Get the local neural experiment's advisory probability, if trained.",
        predict_brain,
    )
    registry.register(
        "train_signal_brain",
        "Train and save the local neural experiment from stored candles with "
        "a chronological holdout.",
        train_signal_brain,
        ToolPermission.WRITE,
    )
    registry.register(
        "get_research_report",
        "Read fresh-data ML and FX-pair evaluation results.",
        get_research_report,
    )
    registry.register(
        "get_dataset_inventory",
        "List packaged JSON knowledge datasets.",
        get_dataset_inventory,
    )
    registry.register(
        "research_forex_pair",
        "Simulate a saved FX pair with lagged signals and costs.",
        research_forex_pair,
    )
    registry.register(
        "mt5_status",
        "Check MetaTrader 5 bridge connection and terminal status.",
        mt5_status,
    )
    registry.register(
        "mt5_account_info",
        "Read MetaTrader 5 account info.",
        mt5_account_info,
    )
    registry.register(
        "mt5_get_quote",
        "Get live tick quote from MetaTrader 5 bridge.",
        mt5_get_quote,
    )
    registry.register(
        "send_dm_message",
        "Send a direct message notification to a webhook.",
        send_dm_message,
        ToolPermission.WRITE,
    )
    registry.register(
        "get_decision_metrics",
        "Compute comprehensive trade decision metrics and strategy matrix.",
        get_decision_metrics,
    )
    return registry


PUBLIC_READ_ONLY_TOOLS = frozenset(
    {
        "app_status",
        "list_markets",
        "analyze_market",
        "scan_market",
        "get_outcome_report",
        "get_brain_status",
        "predict_brain",
    }
)


def register_public_app_tools(registry: ToolRegistry) -> ToolRegistry:
    """Copy a market-only allow-list into a registry for public tunnel use.

    Stateful settings, notes, signal history, alerts, chat, training, and all
    write/destructive tools stay private to the local MCP endpoint.
    """
    public = ToolRegistry()
    for name in sorted(PUBLIC_READ_ONLY_TOOLS):
        tool = registry.get(name)
        if tool is None:
            continue
        if tool.permission is not ToolPermission.READ_ONLY:
            raise ValueError(f"public tool {name!r} must be read-only")
        public.register(
            tool.name,
            tool.description,
            tool.func,
            permission=ToolPermission.READ_ONLY,
            schema=tool.schema,
        )
    return public


def format_alert_rules(rules: list[AlertRule]) -> list[dict[str, Any]]:
    """Serialize alert rules for integrations without exposing UI objects."""
    return [asdict(rule) for rule in rules]
