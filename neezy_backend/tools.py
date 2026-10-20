"""Agent tool registry and structured execution engine."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from enum import Enum, auto
from typing import Any


class ToolPermission(Enum):
    READ_ONLY = auto()
    WRITE = auto()
    DESTRUCTIVE = auto()


class Tool:
    """Wrapped backend tool with schema, permissions, and dry-run execution support."""

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
        self.schema = schema or self._generate_schema(func)

    def _generate_schema(self, func: Callable[..., Any]) -> dict[str, Any]:
        sig = inspect.signature(func)
        properties = {}
        required = []
        for param_name, param in sig.parameters.items():
            if param_name in ("self", "dry_run"):
                continue
            properties[param_name] = {
                "type": "string",
                "description": f"Parameter {param_name}",
            }
            if param.default == inspect.Parameter.empty:
                required.append(param_name)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def execute(self, dry_run: bool = False, **kwargs: Any) -> Any:
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
        tool = Tool(name, description, func, permission=permission, schema=schema)
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

    def execute(self, name: str, dry_run: bool = False, **kwargs: Any) -> Any:
        tool = self.get(name)
        if not tool:
            raise KeyError(f"Tool '{name}' not found in registry")
        return tool.execute(dry_run=dry_run, **kwargs)


# Global default tool registry instance
DEFAULT_REGISTRY = ToolRegistry()


def register_default_tools(registry: ToolRegistry = DEFAULT_REGISTRY) -> None:
    """Populate default registry with core NEEZY capabilities."""
    from neezy_backend.storage import create_local_backup, restore_local_backup
    from neezy_backend.stream import fetch_candles

    def tool_read_market(symbol: str = "EURUSD", timeframe: str = "15m") -> str:
        from neezy_backend.context import format_context, market_snapshot

        candles = fetch_candles(symbol, seconds=60, count=100)
        snapshot = market_snapshot(candles, symbol=symbol, timeframe=timeframe)
        return format_context(snapshot) if snapshot else "No candles fetched."

    def tool_backup_create(destination: str = "") -> str:
        res = create_local_backup(destination or None)
        return f"Backup created at: {res}"

    def tool_backup_restore(archive_path: str) -> str:
        restored = restore_local_backup(archive_path)
        return f"Restored files: {', '.join(restored)}"

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


register_default_tools()
