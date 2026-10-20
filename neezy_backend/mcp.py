"""Loopback-only Model Context Protocol Streamable HTTP server.

The server intentionally has no shell, filesystem, trading, or arbitrary-code
tools. Authentication uses a separately stored bearer secret, and state-changing
tools can be disabled independently in the application settings.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from . import __version__
from .storage import _atomic_json_write, get_data_dir
from .tools import ToolPermission, ToolRegistry

logger = logging.getLogger(__name__)
PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_PROTOCOL_VERSIONS = frozenset({"2025-06-18", "2025-03-26", "2024-11-05"})
MAX_REQUEST_BYTES = 1_048_576


class MCPTokenStore:
    """Owner-only local persistence for the MCP bearer token."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_data_dir() / "mcp-token.json"
        self._lock = threading.RLock()

    def load(self) -> str | None:
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        token = document.get("token") if isinstance(document, dict) else None
        if isinstance(token, str) and len(token) >= 32:
            return token
        return None

    def save(self, token: str | None = None) -> str:
        secret = token or secrets.token_urlsafe(32)
        if (
            not isinstance(secret, str)
            or len(secret) < 32
            or any(c.isspace() for c in secret)
        ):
            raise ValueError(
                "MCP bearer token must be at least 32 non-space characters"
            )
        with self._lock:
            _atomic_json_write(self.path, {"token": secret})
            try:
                self.path.chmod(0o600)
            except OSError:
                pass
        return secret

    def get_or_create(self) -> str:
        return self.load() or self.save()

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


class _ThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    max_active_requests = 32

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._request_slots = threading.BoundedSemaphore(self.max_active_requests)
        super().__init__(*args, **kwargs)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._request_slots.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._request_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class MCPServer:
    """Stateless MCP server using JSON responses over Streamable HTTP."""

    def __init__(
        self,
        registry: ToolRegistry,
        token: str,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        write_enabled: bool | Callable[[], bool] = False,
        name: str = "NEEZY Market Intelligence",
        version: str = __version__,
        requests_per_minute: int | None = None,
    ) -> None:
        try:
            address = ipaddress.ip_address(host)
        except ValueError as error:
            raise ValueError("MCP server must bind to a loopback IP address") from error
        if not address.is_loopback:
            raise ValueError("MCP server must bind to loopback only")
        if not 0 <= int(port) <= 65535:
            raise ValueError("MCP port must be between 0 and 65535")
        if requests_per_minute is not None and (
            not isinstance(requests_per_minute, int)
            or isinstance(requests_per_minute, bool)
            or not 1 <= requests_per_minute <= 6000
        ):
            raise ValueError("MCP request rate must be between 1 and 6000 per minute")
        if not isinstance(token, str) or len(token) < 32:
            raise ValueError("MCP bearer token must be at least 32 characters")
        self.registry = registry
        self.token = token
        self.host = host
        self.requested_port = int(port)
        self.write_enabled = write_enabled
        self.name = name
        self.version = version
        self.requests_per_minute = requests_per_minute
        self._rate_lock = threading.Lock()
        self._request_timestamps: deque[float] = deque()
        self._httpd: _ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    @property
    def port(self) -> int:
        with self._lock:
            if self._httpd is not None:
                return int(self._httpd.server_address[1])
        return self.requested_port

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    @property
    def running(self) -> bool:
        with self._lock:
            return (
                self._httpd is not None
                and self._thread is not None
                and self._thread.is_alive()
            )

    def start(self) -> str:
        """Bind and start the server thread; return the actual local endpoint."""
        with self._lock:
            if self.running:
                return self.url
            owner = self

            class Handler(BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"
                server_version = "NEEZY-MCP"
                sys_version = ""

                def log_message(self, _format: str, *args: Any) -> None:
                    # Avoid logging request data or bearer tokens.
                    return

                def _write(self, status: int, payload: Any = None) -> None:
                    if payload is None:
                        self.send_response(status)
                        self.send_header("Content-Length", "0")
                        self.send_header("Connection", "close")
                        origin = self.headers.get("Origin")
                        if origin and self._local_origin():
                            self.send_header("Access-Control-Allow-Origin", origin)
                            self.send_header("Vary", "Origin")
                        self.end_headers()
                        return
                    encoded = json.dumps(
                        payload, ensure_ascii=False, allow_nan=False
                    ).encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
                    origin = self.headers.get("Origin")
                    if origin and self._local_origin():
                        self.send_header("Access-Control-Allow-Origin", origin)
                        self.send_header("Vary", "Origin")
                    self.end_headers()
                    self.wfile.write(encoded)

                def _local_origin(self) -> bool:
                    origin = self.headers.get("Origin")
                    if not origin:
                        return True
                    try:
                        parsed = urlsplit(origin)
                        hostname = parsed.hostname or ""
                        if hostname.lower() == "localhost":
                            return parsed.scheme in {"http", "https"}
                        return ipaddress.ip_address(
                            hostname
                        ).is_loopback and parsed.scheme in {
                            "http",
                            "https",
                        }
                    except ValueError:
                        return False

                def _local_host(self) -> bool:
                    header = self.headers.get("Host", "")
                    try:
                        parsed = urlsplit(f"//{header}")
                        hostname = parsed.hostname or ""
                        host_is_local = (
                            hostname.lower() == "localhost"
                            or ipaddress.ip_address(hostname).is_loopback
                        )
                        return host_is_local and parsed.port == int(
                            self.server.server_address[1]
                        )
                    except ValueError:
                        return False

                def _authorized(self) -> bool:
                    header = self.headers.get("Authorization", "")
                    scheme, _, candidate = header.partition(" ")
                    return scheme.lower() == "bearer" and hmac.compare_digest(
                        candidate.strip(), owner.token
                    )

                def do_OPTIONS(self) -> None:
                    if not self._local_host():
                        self._write(403, {"error": "host not allowed"})
                        return
                    if not self._local_origin():
                        self._write(403, {"error": "origin not allowed"})
                        return
                    self.send_response(204)
                    self.send_header(
                        "Access-Control-Allow-Origin",
                        self.headers.get("Origin", "null"),
                    )
                    self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                    self.send_header(
                        "Access-Control-Allow-Headers",
                        "Authorization, Content-Type, MCP-Protocol-Version",
                    )
                    self.send_header("Access-Control-Max-Age", "600")
                    self.send_header("Content-Length", "0")
                    self.end_headers()

                def do_GET(self) -> None:
                    self._write(405, {"error": "MCP uses authenticated POST requests"})

                def do_DELETE(self) -> None:
                    self._write(
                        405, {"error": "stateless MCP sessions do not support DELETE"}
                    )

                def do_POST(self) -> None:
                    if self.path != "/mcp":
                        self._write(404, {"error": "not found"})
                        return
                    if not self._local_host():
                        self._write(403, {"error": "host not allowed"})
                        return
                    if not self._local_origin():
                        self._write(403, {"error": "origin not allowed"})
                        return
                    if not self._authorized():
                        self._write(401, {"error": "valid bearer token required"})
                        return
                    if owner._rate_limited():
                        self._write(429, {"error": "request rate limit exceeded"})
                        return
                    content_type = (
                        self.headers.get("Content-Type", "").split(";", 1)[0].strip()
                    )
                    if content_type != "application/json":
                        self._write(
                            415, {"error": "Content-Type must be application/json"}
                        )
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                    except ValueError:
                        self._write(400, {"error": "invalid Content-Length"})
                        return
                    if length <= 0 or length > MAX_REQUEST_BYTES:
                        self._write(
                            413, {"error": "request body is empty or too large"}
                        )
                        return
                    try:
                        body = json.loads(self.rfile.read(length))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        self._write(400, {"error": "invalid JSON body"})
                        return
                    if isinstance(body, list):
                        if not body:
                            self._write(
                                200, _rpc_error(None, -32600, "Invalid Request")
                            )
                            return
                        responses = [owner._handle_message(item) for item in body]
                        responses = [item for item in responses if item is not None]
                        self._write(200, responses) if responses else self._write(202)
                        return
                    response = owner._handle_message(body)
                    if response is None:
                        self._write(202)
                    else:
                        self._write(200, response)

            httpd = _ThreadingHTTPServer((self.host, self.requested_port), Handler)
            httpd.daemon_threads = True
            httpd.block_on_close = False
            self._httpd = httpd
            self._thread = threading.Thread(
                target=httpd.serve_forever,
                name="neezy-mcp-http",
                daemon=True,
            )
            self._thread.start()
            return self.url

    def stop(self) -> None:
        """Stop serving and close the bound socket."""
        with self._lock:
            httpd, thread = self._httpd, self._thread
            self._httpd = None
            self._thread = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _rate_limited(self) -> bool:
        limit = self.requests_per_minute
        if limit is None:
            return False
        now = time.monotonic()
        with self._rate_lock:
            while self._request_timestamps and now - self._request_timestamps[0] >= 60:
                self._request_timestamps.popleft()
            if len(self._request_timestamps) >= limit:
                return True
            self._request_timestamps.append(now)
            return False

    def _writes_allowed(self) -> bool:
        if callable(self.write_enabled):
            try:
                return bool(self.write_enabled())
            except Exception:  # noqa: BLE001 - fail closed on a bad setting callback
                return False
        return bool(self.write_enabled)

    def _visible_tools(self) -> list[dict[str, Any]]:
        visible = []
        for tool in self.registry.list_tools():
            if tool["permission"] == ToolPermission.DESTRUCTIVE.name:
                continue
            if (
                tool["permission"] == ToolPermission.WRITE.name
                and not self._writes_allowed()
            ):
                continue
            visible.append(
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "inputSchema": tool["schema"].get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                }
            )
        return visible

    def _handle_message(self, request: Any) -> dict[str, Any] | None:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return _rpc_error(None, -32600, "Invalid Request")
        method = request.get("method")
        request_id = request.get("id", None)
        notification = "id" not in request
        if not isinstance(method, str):
            return (
                None
                if notification
                else _rpc_error(request_id, -32600, "Invalid Request")
            )
        params = request.get("params", {})
        if not isinstance(params, dict):
            return (
                None
                if notification
                else _rpc_error(request_id, -32602, "Invalid params")
            )
        try:
            result = self._dispatch(method, params)
        except _RPCFault as error:
            if notification:
                return None
            return _rpc_error(request_id, error.code, error.message)
        except Exception as error:
            logger.exception("MCP request failed (%s)", method)
            if notification:
                return None
            return _rpc_error(request_id, -32603, f"Internal error: {str(error)[:240]}")
        if notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            requested = params.get("protocolVersion")
            selected = (
                requested
                if requested in SUPPORTED_PROTOCOL_VERSIONS
                else PROTOCOL_VERSION
            )
            return {
                "protocolVersion": selected,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": self.version},
                "instructions": (
                    "NEEZY provides educational market analysis, signal history, "
                    "alerts, and local research tools. It does not place trades."
                ),
            }
        if method == "notifications/initialized":
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": self._visible_tools()}
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not name:
                raise _RPCFault(-32602, "tools/call requires a tool name")
            if not isinstance(arguments, dict):
                raise _RPCFault(-32602, "tool arguments must be an object")
            tool = self.registry.get(name)
            if tool is None:
                raise _RPCFault(-32602, f"unknown tool: {name}")
            if tool.permission is ToolPermission.DESTRUCTIVE:
                raise _RPCFault(-32602, "destructive tools are not available over MCP")
            if tool.permission is ToolPermission.WRITE and not self._writes_allowed():
                raise _RPCFault(-32602, "remote writes are disabled in NEEZY settings")
            try:
                value = self.registry.execute(name, **arguments)
            except Exception as error:  # noqa: BLE001 - serialize tool errors as results
                return {
                    "content": [
                        {"type": "text", "text": f"Tool error: {str(error)[:500]}"}
                    ],
                    "isError": True,
                }
            return _tool_result(value)
        raise _RPCFault(-32601, f"Method not found: {method}")

    def __enter__(self) -> MCPServer:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()


def _tool_result(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"content": [{"type": "text", "text": value}], "isError": False}
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        encoded = str(value)
        value = encoded
    result: dict[str, Any] = {
        "content": [{"type": "text", "text": encoded}],
        "isError": False,
    }
    if isinstance(value, (dict, list, bool, int, float)) or value is None:
        result["structuredContent"] = value
    return result


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


class _RPCFault(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
