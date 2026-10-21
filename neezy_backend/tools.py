"""Agent tool registry and structured execution engine."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from enum import Enum, auto
from types import UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints


class ToolPermission(Enum):
    READ_ONLY = auto()
    WRITE = auto()
    DESTRUCTIVE = auto()


def _json_schema(annotation: Any, fallback: Any = None) -> dict[str, Any]:
    """Translate a Python parameter annotation into a JSON Schema fragment."""
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        choices = [_json_schema(arg) for arg in get_args(annotation)]
        return {"anyOf": choices}
    if origin is list:
        args = get_args(annotation)
        return {
            "type": "array",
            "items": _json_schema(args[0]) if args else {},
        }
    if origin is dict:
        return {"type": "object"}
    types = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    json_type = types.get(annotation)
    if json_type is None and fallback is not None:
        json_type = types.get(type(fallback))
    return {"type": json_type or "string"}


class Tool:
    """Wrapped backend tool with schema, permissions, and dry-run execution."""

    def __init__(
        self,
        name: str,
        description: str,
        func: Callable[..., Any],
        *,
        permission: ToolPermission = ToolPermission.READ_ONLY,
        schema: dict[str, Any] | None = None,
    ) -> None:
        self.name = name.strip()
        self.description = description.strip()
        self.func = func
        self.permission = permission
        self._signature = inspect.signature(func)
        self.schema = schema or self._generate_schema(func)

    def _generate_schema(self, func: Callable[..., Any]) -> dict[str, Any]:
        sig = inspect.signature(func)
        try:
            hints = get_type_hints(func)
        except (NameError, TypeError):
            hints = {}
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "dry_run"):
                continue
            annotation = hints.get(param_name, param.annotation)
            properties[param_name] = _json_schema(
                annotation,
                None if param.default is inspect.Parameter.empty else param.default,
            )
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        }

    def execute(self, dry_run: bool = False, **kwargs: Any) -> Any:
        parameters = {
            key: value
            for key, value in self._signature.parameters.items()
            if key not in ("self", "dry_run")
        }
        accepts_extra = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )
        unknown = set(kwargs) - set(parameters)
        if unknown and not accepts_extra:
            raise ValueError(
                f"Unknown parameter(s) for {self.name}: {', '.join(sorted(unknown))}"
            )
        missing = [
            key
            for key, parameter in parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            and key not in kwargs
        ]
        if missing:
            raise ValueError(
                f"Missing parameter(s) for {self.name}: {', '.join(missing)}"
            )
        if dry_run:
            return {
                "status": "dry_run",
                "tool": self.name,
                "permission": self.permission.name,
                "kwargs": kwargs,
            }
        return self.func(**kwargs)


class ToolRegistry:
    """Registry managing available tools for the NEEZY agent."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        func: Callable[..., Any],
        permission: ToolPermission = ToolPermission.READ_ONLY,
        schema: dict[str, Any] | None = None,
    ) -> None:
        cleaned_name = name.strip()
        if not cleaned_name or not cleaned_name.replace("_", "").isalnum():
            raise ValueError(
                "tool name must contain only letters, numbers, and underscores"
            )
        tool = Tool(
            cleaned_name, description, func, permission=permission, schema=schema
        )
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "permission": tool.permission.name,
                "schema": tool.schema,
            }
            for tool in self._tools.values()
        ]

    def execute(self, tool_name: str, dry_run: bool = False, **kwargs: Any) -> Any:
        tool = self.get(tool_name)
        if not tool:
            raise KeyError(f"Tool '{tool_name}' not found in registry")
        return tool.execute(dry_run=dry_run, **kwargs)


# Global default registry instance
DEFAULT_REGISTRY = ToolRegistry()


def _bounded(value: Any, low: int, high: int) -> int:
    """Coerce an agent-supplied count (often a string) into ``[low, high]``."""
    return min(max(int(value), low), high)


def register_default_tools(registry: ToolRegistry = DEFAULT_REGISTRY) -> None:
    """Populate default registry with core NEEZY capabilities."""
    from neezy_backend.database import LocalDatabase
    from neezy_backend.markets import SYMBOLS, granularity
    from neezy_backend.risk import position_size
    from neezy_backend.storage import create_local_backup, restore_local_backup
    from neezy_backend.strategies import consensus, run_all
    from neezy_backend.stream import fetch_candles

    def tool_read_market(symbol: str = "frxEURUSD", timeframe: str = "15m") -> str:
        from neezy_backend.context import format_context, market_snapshot

        if symbol not in SYMBOLS:
            raise ValueError(
                f"Unknown market {symbol!r}; choose from {', '.join(SYMBOLS)}"
            )
        seconds = granularity(timeframe)
        candles = fetch_candles(symbol, seconds, 100)
        snapshot = market_snapshot(candles, symbol=symbol, timeframe=timeframe)
        return format_context(snapshot) if snapshot else "No candles fetched."

    def tool_backup_create(destination: str = "") -> str:
        res = create_local_backup(destination or None)
        return f"Backup created at: {res}"

    def tool_backup_restore(archive_path: str) -> str:
        restored = restore_local_backup(archive_path)
        return f"Restored files: {', '.join(restored)}"

    def tool_scan_strategies(symbol: str = "frxEURUSD", timeframe: str = "15m") -> str:
        if symbol not in SYMBOLS:
            raise ValueError(
                f"Unknown market {symbol!r}; choose from {', '.join(SYMBOLS)}"
            )
        candles = fetch_candles(symbol, granularity(timeframe), 300)
        if len(candles) < 61:
            return f"Not enough candles to scan {symbol} ({len(candles)} fetched)."
        signals = run_all(candles)
        verdict = consensus(signals)
        lines = [
            f"Market: {symbol} ({timeframe})",
            f"Consensus: {verdict['label']} ({verdict['confidence']}%) "
            f"votes {verdict['votes']}",
        ]
        lines.extend(
            f"- {signal.strategy}: {signal.label} {signal.confidence:.0f}% "
            f"- {signal.summary}"
            for signal in signals
        )
        return "\n".join(lines)

    def tool_plan_risk(
        symbol: str,
        balance: float,
        risk_percent: float,
        entry: float,
        stop: float,
        reward_to_risk: float = 2.0,
    ) -> str:
        if symbol not in SYMBOLS:
            raise ValueError(
                f"Unknown market {symbol!r}; choose from {', '.join(SYMBOLS)}"
            )
        plan = position_size(
            symbol=symbol,
            balance=float(balance),
            risk_percent=float(risk_percent),
            entry=float(entry),
            stop=float(stop),
            reward_to_risk=float(reward_to_risk),
        )
        data = plan.to_dict()
        return (
            f"{data['direction']} {symbol} lots={data['lots']} "
            f"units={data['units']} entry={data['entry']} stop={data['stop']} "
            f"target={data['target']} risk={data['risk_amount']:.2f} "
            f"reward={data['reward_amount']:.2f} R:R={data['reward_to_risk']}"
        )

    def tool_search_memory(query: str, limit: int = 5) -> str:
        with LocalDatabase() as database:
            rows = database.search_memory(query, limit=_bounded(limit, 1, 50))
        if not rows:
            return "No matching memory."
        return "\n".join(
            f"#{row['id']} [{row['category']}] {row['content']}" for row in rows
        )

    def tool_add_memory(content: str, category: str = "general") -> str:
        text = content.strip()
        if not text:
            raise ValueError("content must not be empty")
        with LocalDatabase() as database:
            item_id = database.add_memory(text, category=category.strip() or "general")
        return f"Memory saved as #{item_id}"

    def tool_recent_signals(limit: int = 10, symbol: str = "") -> str:
        with LocalDatabase() as database:
            rows = database.recent_signals(
                limit=_bounded(limit, 1, 100), symbol=symbol.strip() or None
            )
        if not rows:
            return "No saved signals."
        return "\n".join(
            f"{row['created_at']} {row['symbol']} {row['timeframe']} "
            f"{row['signal']} score={row['score']:.1f}"
            for row in rows
        )

    def tool_mt5_status() -> str:
        from neezy_backend.mt5_bridge import get_global_mt5_bridge

        bridge = get_global_mt5_bridge()
        status = bridge.get_status()
        return f"MT5 Bridge Status: {status}"

    def tool_mt5_account() -> str:
        from neezy_backend.mt5_bridge import get_global_mt5_bridge

        bridge = get_global_mt5_bridge()
        acc = bridge.get_account_info()
        return f"MT5 Account Info: {acc}"

    def tool_mt5_quote(symbol: str = "frxEURUSD") -> str:
        from neezy_backend.mt5_bridge import get_global_mt5_bridge

        bridge = get_global_mt5_bridge()
        quote = bridge.get_quote(symbol)
        return f"MT5 Quote ({symbol}): {quote}"

    def tool_send_dm(webhook_url: str, title: str, message: str) -> str:
        from neezy_backend.dm import send_dm_notification

        res = send_dm_notification(webhook_url, title, message)
        return f"DM Result: {res}"

    def tool_get_decision_metrics(
        symbol: str = "frxEURUSD", timeframe: str = "15m"
    ) -> str:
        from neezy_backend.dm import compute_decision_metrics

        if symbol not in SYMBOLS:
            raise ValueError(
                f"Unknown market {symbol!r}; choose from {', '.join(SYMBOLS)}"
            )
        candles = fetch_candles(symbol, granularity(timeframe), 200)
        metrics = compute_decision_metrics(symbol, timeframe, candles)
        return (
            f"Decision: {metrics['decision']} ({metrics['confidence']}%) | "
            f"Votes: {metrics['strategy_votes']} | ADX: {metrics['adx']} | "
            f"RSI: {metrics['rsi']} | ATR: {metrics['atr']}"
        )

    registry.register(
        "read_market",
        "Fetch indicator snapshot, Supertrend, divergence, and strategy consensus.",
        tool_read_market,
        permission=ToolPermission.READ_ONLY,
    )
    registry.register(
        "create_backup",
        "Create a zipped backup bundle of all local NEEZY data files.",
        tool_backup_create,
        permission=ToolPermission.WRITE,
    )
    registry.register(
        "restore_backup",
        "Restore local NEEZY state files from a zip archive.",
        tool_backup_restore,
        permission=ToolPermission.DESTRUCTIVE,
    )
    registry.register(
        "scan_strategies",
        "Run every single-market strategy on fresh candles and return the consensus.",
        tool_scan_strategies,
        permission=ToolPermission.READ_ONLY,
    )
    registry.register(
        "plan_risk",
        "Size a position from account balance, risk percent, entry and stop prices.",
        tool_plan_risk,
        permission=ToolPermission.READ_ONLY,
    )
    registry.register(
        "search_memory",
        "Full-text search the saved NEEZY memory notes.",
        tool_search_memory,
        permission=ToolPermission.READ_ONLY,
    )
    registry.register(
        "add_memory",
        "Save a note to NEEZY memory for later search.",
        tool_add_memory,
        permission=ToolPermission.WRITE,
    )
    registry.register(
        "recent_signals",
        "List the most recently saved signals, optionally for one market.",
        tool_recent_signals,
        permission=ToolPermission.READ_ONLY,
    )
    registry.register(
        "mt5_status",
        "Check MetaTrader 5 bridge connection and terminal status.",
        tool_mt5_status,
        permission=ToolPermission.READ_ONLY,
    )
    registry.register(
        "mt5_account",
        "Query MetaTrader 5 account balance, equity, and margin.",
        tool_mt5_account,
        permission=ToolPermission.READ_ONLY,
    )
    registry.register(
        "mt5_quote",
        "Get live tick quote for a symbol from MetaTrader 5.",
        tool_mt5_quote,
        permission=ToolPermission.READ_ONLY,
    )
    registry.register(
        "send_dm",
        "Send a direct message webhook notification.",
        tool_send_dm,
        permission=ToolPermission.WRITE,
    )
    registry.register(
        "decision_metrics",
        "Compute comprehensive trade decision metrics and strategy matrix.",
        tool_get_decision_metrics,
        permission=ToolPermission.READ_ONLY,
    )


register_default_tools()
