"""Catalog of third-party MCP servers NEEZY can connect to.

This module only *describes* servers and prints client configuration. It never
installs, downloads, or launches third-party code. Every server listed here is
an external project; review it before you run it.

Risk levels:
- "market-data": reads market data and account state.
- "trading": can place, modify, or close live orders.
- "desktop-control": can click, type, run commands, and read files on the PC.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# Read-only tool subset for winremote-mcp (its tier1 list, minus ScreenRecord
# and Notification). Passed with --tools, which takes precedence over tier flags.
_WINREMOTE_READ_ONLY_TOOLS = (
    "Snapshot,AnnotatedSnapshot,GetClipboard,GetSystemInfo,ListProcesses,"
    "FileList,FileSearch,RegRead,ServiceList,TaskList,EventLog,Ping,PortCheck,"
    "NetConnections,OCR"
)


@dataclass(frozen=True)
class McpServer:
    id: str
    repo: str
    license: str
    risk: str
    summary: str
    command: str
    args: tuple[str, ...] = ()
    # Extra args/env that restrict the server to read-only use, when the project
    # supports it. Empty means the project has no read-only mode, so the only
    # protection is to leave its trading or control tools out of your client.
    safe_args: tuple[str, ...] = ()
    safe_env: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    @property
    def has_safe_profile(self) -> bool:
        return bool(self.safe_args or self.safe_env)


MCP_SERVERS: tuple[McpServer, ...] = (
    McpServer(
        id="mt5-qoyyuum",
        repo="https://github.com/Qoyyuum/mcp-metatrader5-server",
        license="MIT (pyproject classifier; no LICENSE file in repo root)",
        risk="trading",
        summary="MT5 data plus order_send, positions, history, and symbol tools.",
        command="uvx",
        args=("--from", "mcp-metatrader5-server", "mt5mcp"),
        notes=(
            "Credentials go through its login tool, so the AI client sees the "
            "password. Exposes order_send and close_* tools. No read-only mode."
        ),
    ),
    McpServer(
        id="mt5-ariadng",
        repo="https://github.com/ariadng/metatrader-mcp-server",
        license="MIT",
        risk="trading",
        summary="MT5 candles, quotes, positions, and market/pending order tools.",
        command="metatrader-mcp-server",
        args=(
            "--login",
            "YOUR_MT5_LOGIN",
            "--password",
            "YOUR_MT5_PASSWORD",
            "--server",
            "YOUR_MT5_SERVER",
            "--transport",
            "stdio",
        ),
        notes=(
            "Needs --login, --password, and --server. Replace the placeholders in "
            "your client config only, never in files in the repo. Exposes "
            "place_market_order and close_position. No read-only mode."
        ),
    ),
    McpServer(
        id="mt5-amirkhonov",
        repo="https://github.com/amirkhonov/metatrader5-mcp",
        license="MIT",
        risk="trading",
        summary="MT5 connection, symbols, rates, ticks, orders, and history tools.",
        command="metatrader5-mcp",
        notes=(
            "Reads MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER from its .env file. "
            "Exposes mt5_order_send. No read-only mode."
        ),
    ),
    McpServer(
        id="desktop-windows-mcp",
        repo="https://github.com/CursorTouch/Windows-MCP",
        license="MIT",
        risk="desktop-control",
        summary="Screenshots, clicks, typing, PowerShell, files, registry, processes.",
        command="uvx",
        args=("windows-mcp", "serve"),
        notes="Full desktop and shell control. No read-only mode.",
    ),
    McpServer(
        id="desktop-win32",
        repo="https://github.com/RandyNorthrup/win32-mcp-server",
        license="MIT",
        risk="desktop-control",
        summary="Windows automation with allow-lists, dry-run, and timeouts.",
        command="win32-mcp-server",
        safe_env={"WIN32_MCP_SECURITY_PROFILE": "read_only"},
        notes="Set WIN32_MCP_SECURITY_PROFILE=read_only to block mutating tools.",
    ),
    McpServer(
        id="desktop-winremote",
        repo="https://github.com/dddabtc/winremote-mcp",
        license="MIT",
        risk="desktop-control",
        summary="Remote Windows control over stdio or streamable HTTP.",
        command="winremote-mcp",
        args=("--transport", "stdio"),
        safe_args=(
            "--transport",
            "stdio",
            "--tools",
            _WINREMOTE_READ_ONLY_TOOLS,
        ),
        notes="Use --tools to allow only read-only tools. Tier 3 is off by default.",
    ),
)

_BY_ID = {server.id: server for server in MCP_SERVERS}


def get_server(server_id: str) -> McpServer:
    try:
        return _BY_ID[server_id]
    except KeyError:
        known = ", ".join(sorted(_BY_ID))
        raise ValueError(
            f"unknown MCP server {server_id!r}; choose from {known}"
        ) from None


def client_config(server_id: str, *, safe: bool = True) -> dict[str, Any]:
    """Return an mcpServers entry for Claude Desktop, Cursor, or similar clients."""
    server = get_server(server_id)
    args = list(server.args)
    env: dict[str, str] = {}
    if safe:
        args = list(server.safe_args) if server.safe_args else args
        env = dict(server.safe_env)
    entry: dict[str, Any] = {"command": server.command, "args": args}
    if env:
        entry["env"] = env
    return {"mcpServers": {server.id: entry}}


def warnings_for(server_id: str, *, safe: bool = True) -> list[str]:
    server = get_server(server_id)
    messages = []
    if server.risk != "market-data":
        messages.append(
            f"{server.id} is {server.risk}; review the project before running it."
        )
    if safe and not server.has_safe_profile:
        messages.append(
            f"{server.id} has no read-only mode. Disable its trading or control "
            "tools in your MCP client."
        )
    if not safe:
        messages.append("Unrestricted config: all tools from this server are enabled.")
    return messages


def config_json(server_id: str, *, safe: bool = True) -> str:
    return json.dumps(client_config(server_id, safe=safe), indent=2)
