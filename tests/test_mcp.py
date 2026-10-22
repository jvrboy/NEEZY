"""Security and protocol tests for NEEZY's loopback MCP endpoint."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from neezy_backend.mcp import MAX_REQUEST_BYTES, MCPServer, MCPTokenStore
from neezy_backend.mcp_tools import register_public_app_tools
from neezy_backend.tools import ToolPermission, ToolRegistry


class MCPServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.registry.register(
            "echo", "Return a typed value", lambda text="hello": {"echo": text}
        )
        self.registry.register(
            "write_note", "Save a note", lambda content: content, ToolPermission.WRITE
        )
        self.registry.register(
            "unsafe",
            "Never expose destructive tools",
            lambda: "no",
            ToolPermission.DESTRUCTIVE,
        )
        self.write_enabled = False
        self.token = "t" * 48
        self.server = MCPServer(
            self.registry,
            self.token,
            port=0,
            write_enabled=lambda: self.write_enabled,
        )
        self.url = self.server.start()
        self.addCleanup(self.server.stop)

    def _request(self, payload, *, token=True, host=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {self.token}"
        if host:
            headers["Host"] = host
        request = Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_initialize_lists_only_safe_tools_and_returns_mcp_metadata(self):
        status, response = self._request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(
            response["result"]["serverInfo"]["name"], "NEEZY Market Intelligence"
        )

        _, response = self._request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = response["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["echo"])
        self.assertEqual(
            tools[0]["inputSchema"]["properties"]["text"]["type"], "string"
        )

    def test_tool_call_returns_structured_content(self):
        _, response = self._request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "market"}},
            }
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], {"echo": "market"})

    def test_bearer_token_and_loopback_host_are_required(self):
        status, body = self._request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token=False
        )
        self.assertEqual(status, 401)
        self.assertIn("bearer", body["error"])

        status, _ = self._request(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            host="evil.example:1234",
        )
        self.assertEqual(status, 403)

    def test_write_tools_are_hidden_and_denied_until_enabled(self):
        _, response = self._request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(
            [tool["name"] for tool in response["result"]["tools"]], ["echo"]
        )
        _, response = self._request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "write_note", "arguments": {"content": "x"}},
            }
        )
        self.assertEqual(response["error"]["code"], -32602)

        self.write_enabled = True
        _, response = self._request({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
        self.assertEqual(
            [tool["name"] for tool in response["result"]["tools"]],
            ["echo", "write_note"],
        )
        _, response = self._request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "unsafe", "arguments": {}},
            }
        )
        self.assertEqual(response["error"]["code"], -32602)

    def test_notifications_receive_empty_accepted_response(self):
        request = Request(
            self.url,
            data=json.dumps(
                {"jsonrpc": "2.0", "method": "notifications/initialized"}
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 202)
            self.assertEqual(response.read(), b"")

    def test_optional_public_rate_limit_rejects_bursts(self):
        server = MCPServer(
            self.registry,
            self.token,
            port=0,
            requests_per_minute=1,
        )
        url = server.start()
        try:
            request = Request(
                url,
                data=json.dumps(
                    {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                ).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                },
                method="POST",
            )
            with urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
            with self.assertRaises(HTTPError) as caught:
                urlopen(request, timeout=3)
            self.assertEqual(caught.exception.code, 429)
        finally:
            server.stop()

    def test_server_rejects_non_loopback_bind_address(self):
        with self.assertRaises(ValueError):
            MCPServer(self.registry, self.token, host="0.0.0.0", port=8765)
        with self.assertRaises(ValueError):
            MCPServer(
                self.registry,
                self.token,
                requests_per_minute=0,
            )


class PublicMCPRegistryTest(unittest.TestCase):
    def test_public_registry_exposes_only_market_read_tools(self):
        source = ToolRegistry()
        source.register("app_status", "Read status", lambda: {"ready": True})
        source.register("list_markets", "List markets", lambda: [])
        source.register("analyze_market", "Analyze", lambda symbol: symbol)
        source.register(
            "save_memory",
            "Save private memory",
            lambda content: content,
            ToolPermission.WRITE,
        )
        source.register("get_app_settings", "Read settings", lambda: {})

        public = register_public_app_tools(source)
        names = [item["name"] for item in public.list_tools()]
        self.assertEqual(names, ["analyze_market", "app_status", "list_markets"])
        self.assertTrue(
            all(
                item["permission"] == ToolPermission.READ_ONLY.name
                for item in public.list_tools()
            )
        )
        with self.assertRaises(KeyError):
            public.execute("save_memory", content="private")
        with self.assertRaises(KeyError):
            public.execute("get_app_settings")

    def test_public_registry_rejects_a_mutating_allow_list_entry(self):
        source = ToolRegistry()
        source.register("app_status", "Read status", lambda: {}, ToolPermission.WRITE)
        with self.assertRaisesRegex(ValueError, "must be read-only"):
            register_public_app_tools(source)


class MCPTokenStoreTest(unittest.TestCase):
    def test_token_is_generated_persisted_and_cleared(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mcp-token.json"
            store = MCPTokenStore(path)
            token = store.get_or_create()
            self.assertGreaterEqual(len(token), 32)
            self.assertEqual(store.load(), token)
            if hasattr(path.stat(), "st_mode") and __import__("os").name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            store.clear()
            self.assertIsNone(store.load())


if __name__ == "__main__":
    unittest.main()


class MCPProtocolRobustnessTest(unittest.TestCase):
    """Roadmap #51 addendum: hostile/edge requests must never crash the server."""

    def setUp(self) -> None:
        self.registry = ToolRegistry()
        self.registry.register("ping", "Pong", lambda: {"pong": True})
        self.server = MCPServer(self.registry, "s" * 40, port=0)
        self.url = self.server.start()
        self.addCleanup(self.server.stop)

    def _post_raw(self, body: bytes, headers: dict | None = None):
        headers = {"Content-Type": "application/json", **(headers or {})}
        request = Request(self.url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, response.read()
        except HTTPError as error:
            return error.code, error.read()

    def test_malformed_json_gets_a_clean_error_response(self):
        status, _ = self._post_raw(
            b"{not json at all", {"Authorization": "Bearer " + "s" * 40}
        )
        self.assertEqual(status, 400)
        self.assertTrue(self.server.running)  # server survived

    def test_wrong_content_type_is_rejected(self):
        status, _ = self._post_raw(
            b"{}", {"Content-Type": "text/plain", "Authorization": "Bearer " + "s" * 40}
        )
        self.assertIn(status, (400, 415))

    def test_get_request_is_not_allowed_for_post_endpoint(self):
        request = Request(self.url)  # GET
        try:
            with urlopen(request, timeout=3) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
        self.assertIn(status, (404, 405))
        self.assertTrue(self.server.running)

    def test_missing_auth_is_unauthorized(self):
        status, _ = self._post_raw(b'{"jsonrpc":"2.0","id":1,"method":"ping"}')
        self.assertEqual(status, 401)

    def test_oversized_body_is_rejected(self):
        from urllib.error import URLError

        huge = b"x" * (MAX_REQUEST_BYTES + 1)
        try:
            status, _ = self._post_raw(
                huge,
                {
                    "Authorization": "Bearer " + "s" * 40,
                },
            )
        except URLError as error:
            # The server slams the door mid-upload (broken pipe on our side);
            # that refusal is the protection working.
            self.assertIn("Broken pipe", str(error))
            status = 413
        self.assertIn(status, (413, 400))
        self.assertTrue(self.server.running)

    def test_server_still_serves_after_hostile_requests(self):
        token = "s" * 40
        for body in (b"", b"[", b"null", b"3", b'{"jsonrpc": 1}'):
            self._post_raw(body, {"Authorization": f"Bearer {token}"})
        payload = {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": "ping", "arguments": {}},
        }
        status, body = self._post_raw(
            json.dumps(payload).encode("utf-8"),
            {"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(status, 200)
        self.assertIn(b"pong", body)
