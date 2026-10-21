"""Mcp panels for the NEEZY desktop window."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from neezy_backend.mcp import MCPServer
from neezy_backend.tunnel import TunnelError


class McpMixin:
    """Methods for the mcp screen; mixed into App."""

    def _mcp_settings_tab(self, notebook):
        _tab, left, right = self._settings_tab(notebook, "MCP SERVER")
        self._label(left, "LOCAL MODEL CONTEXT PROTOCOL", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self._check_row(left, "Enable local MCP server", self.mcp_enabled_var)
        self._spin_row(left, "MCP port", self.mcp_port_var, 1024, 65535, 1)
        self._check_row(
            left,
            "Allow write tools on the local MCP server",
            self.mcp_writes_var,
        )
        self._check_row(
            left,
            "Enable public Cloudflare quick tunnel (read-only)",
            self.mcp_tunnel_enabled_var,
        )
        self._entry_row(
            left, "cloudflared executable or path", self.mcp_tunnel_executable_var
        )
        self._label(
            left,
            "The default MCP server binds to 127.0.0.1 and requires a bearer "
            "token. The optional public tunnel uses a separate token and a "
            "market-only, read-only tool allow-list; it cannot change settings, "
            "alerts, memory, or models.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        ).pack(anchor="w", padx=16, pady=(8, 10))
        self._label(right, "CONNECT A LOCAL MCP CLIENT", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self._label(right, "MCP server URL", 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(4, 3)
        )
        url_entry = tk.Entry(
            right,
            textvariable=self.mcp_url_var,
            state="readonly",
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
        )
        url_entry.pack(fill="x", padx=16, pady=(0, 4), ipady=4)
        url_row = tk.Frame(right, bg=self.PANEL)
        url_row.pack(fill="x", padx=16, pady=(0, 8))
        tk.Button(
            url_row,
            text="Copy URL",
            command=lambda: self._copy_text(self.mcp_url_var.get(), "MCP URL copied"),
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=5,
        ).pack(side="left")
        self._label(right, "Bearer token (keep private)", 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(4, 3)
        )
        token_entry = tk.Entry(
            right,
            textvariable=self.mcp_token_var,
            show="•",
            state="readonly",
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
        )
        token_entry.pack(fill="x", padx=16, pady=(0, 4), ipady=4)
        token_row = tk.Frame(right, bg=self.PANEL)
        token_row.pack(fill="x", padx=16, pady=(0, 8))
        tk.Button(
            token_row,
            text="Copy token",
            command=lambda: self._copy_text(
                self.mcp_token_var.get(), "MCP token copied"
            ),
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=5,
        ).pack(side="left")
        tk.Button(
            token_row,
            text="Regenerate token",
            command=self._regenerate_mcp_token,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=5,
        ).pack(side="left", padx=(6, 0))
        self.mcp_status = self._label(right, "MCP server is disabled.", 9, self.MUTED)
        self.mcp_status.pack(anchor="w", padx=16, pady=(0, 6))
        self._label(right, "PUBLIC MCP TUNNEL · READ-ONLY", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(12, 5)
        )
        self._label(right, "Remote MCP URL", 10, self.MUTED).pack(
            anchor="w", padx=16, pady=(4, 3)
        )
        tk.Entry(
            right,
            textvariable=self.mcp_public_url_var,
            state="readonly",
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
        ).pack(fill="x", padx=16, pady=(0, 4), ipady=4)
        tk.Button(
            right,
            text="Copy remote URL",
            command=self._copy_public_mcp_url,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=5,
        ).pack(anchor="w", padx=16, pady=(0, 6))
        self._label(
            right, "Separate public bearer token (keep private)", 10, self.MUTED
        ).pack(anchor="w", padx=16, pady=(4, 3))
        tk.Entry(
            right,
            textvariable=self.mcp_public_token_var,
            show="•",
            state="readonly",
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
        ).pack(fill="x", padx=16, pady=(0, 4), ipady=4)
        public_token_row = tk.Frame(right, bg=self.PANEL)
        public_token_row.pack(fill="x", padx=16, pady=(0, 6))
        tk.Button(
            public_token_row,
            text="Copy public token",
            command=lambda: self._copy_text(
                self.mcp_public_token_var.get(), "Public MCP token copied"
            ),
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=5,
        ).pack(side="left")
        tk.Button(
            public_token_row,
            text="Rotate public token",
            command=self._regenerate_mcp_public_token,
            bg=self.PANEL2,
            fg=self.TEXT,
            relief="flat",
            padx=10,
            pady=5,
        ).pack(side="left", padx=(6, 0))
        self.mcp_tunnel_status = self._label(
            right,
            "Public tunnel is disabled.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        )
        self.mcp_tunnel_status.pack(anchor="w", padx=16, pady=(0, 6))
        self._label(
            right,
            "The tunnel sends traffic through Cloudflare and creates an ephemeral "
            "HTTPS URL. Anyone with the public token can read the exposed market "
            "tools; do not paste it into an untrusted agent. The public endpoint "
            "never offers write tools, even if local MCP writes are enabled. "
            "Disable the toggle or rotate the token to revoke access. This uses "
            "cloudflared already installed on your device; NEEZY does not download it.",
            9,
            self.MUTED,
            justify="left",
            wraplength=330,
        ).pack(anchor="w", padx=16, pady=(0, 10))

    def _copy_public_mcp_url(self):
        url = self.mcp_public_url_var.get().strip()
        if not url.startswith("https://"):
            self.settings_status.config(
                text="The public tunnel URL is not ready yet.", fg=self.RED
            )
            return
        self._copy_text(url, "Remote MCP URL copied")

    def _regenerate_mcp_token(self):
        if not messagebox.askyesno(
            "Regenerate MCP token",
            "The current token will stop working for connected MCP clients. Continue?",
        ):
            return
        self._stop_mcp_server()
        try:
            token = self.mcp_token_store.save()
        except OSError as error:
            self.mcp_status.config(text=f"Could not save token: {error}", fg=self.RED)
            return
        self.mcp_token_var.set(token)
        self._sync_mcp_server()

    def _stop_public_mcp_services(self):
        self.mcp_tunnel_service.stop()
        self._mcp_tunnel_signature = None
        if self.mcp_public_server is not None:
            self.mcp_public_server.stop()
            self.mcp_public_server = None
        if hasattr(self, "mcp_public_url_var"):
            self.mcp_public_url_var.set("Not running")
        if hasattr(self, "mcp_tunnel_status"):
            self.mcp_tunnel_status.config(
                text="Public tunnel is disabled.", fg=self.MUTED
            )

    def _stop_mcp_server(self):
        self._stop_public_mcp_services()
        if self.mcp_server is not None:
            self.mcp_server.stop()
            self.mcp_server = None
            self._mcp_server_port = None

    def _schedule_mcp_tunnel_poll(self, delay=1000):
        if self._mcp_tunnel_poll_scheduled:
            return
        self._mcp_tunnel_poll_scheduled = True
        self.after(delay, self._refresh_mcp_tunnel_status)

    def _refresh_mcp_tunnel_status(self):
        self._mcp_tunnel_poll_scheduled = False
        if not hasattr(self, "mcp_tunnel_status"):
            return
        if not self.mcp_tunnel_enabled_var.get():
            return
        url = self.mcp_tunnel_service.public_url
        error = self.mcp_tunnel_service.error
        if url and self.mcp_tunnel_service.running:
            self.mcp_public_url_var.set(f"{url}/mcp")
            self.mcp_tunnel_status.config(
                text="Tunnel active · public tools are read-only.", fg=self.GREEN
            )
        elif error:
            self.mcp_public_url_var.set("Not available")
            self.mcp_tunnel_status.config(text=f"Tunnel error: {error}", fg=self.RED)
        else:
            self.mcp_public_url_var.set("Starting…")
            self.mcp_tunnel_status.config(
                text="Starting Cloudflare quick tunnel…", fg=self.MUTED
            )
        if self.mcp_tunnel_service.running:
            self._schedule_mcp_tunnel_poll()

    def _sync_mcp_tunnel(self):
        if not hasattr(self, "mcp_tunnel_status"):
            return
        if not self.mcp_tunnel_enabled_var.get():
            self._stop_public_mcp_services()
            return
        if self.mcp_server is None or not self.mcp_server.running:
            self._stop_public_mcp_services()
            self.mcp_tunnel_status.config(
                text="Enable the local MCP server before starting the tunnel.",
                fg=self.RED,
            )
            return
        try:
            token = self.mcp_public_token_store.get_or_create()
            self.mcp_public_token_var.set(token)
            if self.mcp_public_server is None or not self.mcp_public_server.running:
                if self.mcp_public_server is not None:
                    self.mcp_public_server.stop()
                self.mcp_public_server = MCPServer(
                    self.public_remote_registry,
                    token,
                    host="127.0.0.1",
                    port=0,
                    write_enabled=False,
                    name="NEEZY Public Market Tools",
                    requests_per_minute=60,
                )
                self.mcp_public_server.start()
            executable = self.mcp_tunnel_executable_var.get().strip()
            signature = (executable, self.mcp_public_server.port)
            if (
                self.mcp_tunnel_service.running
                and self._mcp_tunnel_signature != signature
            ):
                self.mcp_tunnel_service.stop()
            if not self.mcp_tunnel_service.running:
                self.mcp_tunnel_service.start(executable, self.mcp_public_server.port)
                self._mcp_tunnel_signature = signature
            self.mcp_tunnel_status.config(
                text="Starting Cloudflare quick tunnel…", fg=self.MUTED
            )
            self._schedule_mcp_tunnel_poll(1000)
        except (OSError, ValueError, TunnelError) as error:
            self.mcp_tunnel_service.stop()
            if self.mcp_public_server is not None:
                self.mcp_public_server.stop()
                self.mcp_public_server = None
            self._mcp_tunnel_signature = None
            self.mcp_tunnel_status.config(text=f"Tunnel failed: {error}", fg=self.RED)
            self.mcp_public_url_var.set("Not available")

    def _regenerate_mcp_public_token(self):
        if not messagebox.askyesno(
            "Rotate public MCP token",
            "This revokes the current public MCP token and disconnects remote "
            "agents. Continue?",
        ):
            return
        self._stop_public_mcp_services()
        try:
            token = self.mcp_public_token_store.save()
        except OSError as error:
            self.mcp_tunnel_status.config(
                text=f"Could not save public token: {error}", fg=self.RED
            )
            return
        self.mcp_public_token_var.set(token)
        self._sync_mcp_tunnel()

    def _sync_mcp_server(self):
        if not hasattr(self, "mcp_status"):
            return
        try:
            enabled = self.mcp_enabled_var.get()
            port = int(self.mcp_port_var.get())
        except (tk.TclError, ValueError):
            self.mcp_status.config(text="Enter a valid MCP port.", fg=self.RED)
            return
        self.mcp_url_var.set(f"http://127.0.0.1:{port}/mcp")
        if not enabled:
            self._stop_mcp_server()
            self.mcp_status.config(text="MCP server is disabled.", fg=self.MUTED)
            if self.mcp_tunnel_enabled_var.get():
                self.mcp_tunnel_status.config(
                    text="Enable the local MCP server before starting the tunnel.",
                    fg=self.RED,
                )
            return
        if self.mcp_server is not None and self._mcp_server_port != port:
            self._stop_mcp_server()
        if self.mcp_server is not None and self.mcp_server.running:
            self.mcp_status.config(
                text=f"Running · {self.mcp_server.url}", fg=self.GREEN
            )
            self._sync_mcp_tunnel()
            return
        try:
            token = self.mcp_token_store.get_or_create()
            self.mcp_token_var.set(token)
            self.mcp_server = MCPServer(
                self.remote_registry,
                token,
                host="127.0.0.1",
                port=port,
                write_enabled=lambda: self.settings.mcp_allow_writes,
            )
            self.mcp_server.start()
            self._mcp_server_port = port
            self.mcp_url_var.set(self.mcp_server.url)
            self.mcp_status.config(
                text=f"Running · {self.mcp_server.url}", fg=self.GREEN
            )
            self._sync_mcp_tunnel()
        except (OSError, ValueError) as error:
            self._stop_mcp_server()
            self.mcp_status.config(text=f"MCP server failed: {error}", fg=self.RED)
