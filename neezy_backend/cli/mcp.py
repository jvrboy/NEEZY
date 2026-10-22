"""Third-party MCP server catalog CLI commands."""

from __future__ import annotations

import sys

from .common import _emit


def cmd_mcp(args, fetch, out) -> int:
    """List, describe, and print client config for third-party MCP servers."""
    del fetch
    from ..mcp_catalog import MCP_SERVERS, client_config, get_server, warnings_for

    if args.action == "list":
        if args.json:
            _emit(
                out,
                [
                    {"id": s.id, "risk": s.risk, "license": s.license, "repo": s.repo}
                    for s in MCP_SERVERS
                ],
            )
        else:
            for s in MCP_SERVERS:
                out.write(f"{s.id:<20} [{s.risk}] {s.summary}\n")
        return 0
    if args.action == "show":
        server = get_server(args.server_id)
        data = {
            "id": server.id,
            "repo": server.repo,
            "license": server.license,
            "risk": server.risk,
            "summary": server.summary,
            "command": [server.command, *server.args],
            "read_only_profile": server.has_safe_profile,
            "notes": server.notes,
        }
        if args.json:
            _emit(out, data)
        else:
            for key, value in data.items():
                out.write(f"{key}: {value}\n")
        return 0
    if args.action == "config":
        safe = not args.unsafe
        for message in warnings_for(args.server_id, safe=safe):
            sys.stderr.write(f"neezy-cli: warning: {message}\n")
        _emit(out, client_config(args.server_id, safe=safe))
        return 0
    raise ValueError(f"unknown mcp action {args.action!r}")
