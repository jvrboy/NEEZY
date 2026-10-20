"""Explicitly started Cloudflare quick-tunnel process for a loopback service.

This module never opens an inbound firewall port, downloads a tunnel binary, or
handles model/provider secrets. The caller must provide an already-authenticated
loopback HTTP endpoint; remote MCP uses its own read-only registry and token.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

_QUICK_TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.I)


class TunnelError(RuntimeError):
    """A clear, non-secret error starting or monitoring the tunnel client."""


class CloudflareQuickTunnel:
    """Manage one user-opted-in Cloudflare quick tunnel without shell execution."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[str] | Any | None = None
        self._reader: threading.Thread | None = None
        self._url: str | None = None
        self._error = ""
        self._url_ready = threading.Event()
        self._stop_requested = False

    @staticmethod
    def _resolve_executable(executable: str) -> str:
        candidate = executable.strip()
        if not candidate:
            raise TunnelError("enter the path to a cloudflared executable")
        path = Path(candidate).expanduser()
        if path.parent != Path(".") or path.is_absolute():
            if path.is_file():
                return str(path.resolve())
            raise TunnelError("cloudflared executable was not found at that path")
        resolved = shutil.which(candidate)
        if not resolved:
            raise TunnelError(
                "cloudflared was not found; install it separately and enter its path"
            )
        return resolved

    @property
    def running(self) -> bool:
        with self._lock:
            process = self._process
            return process is not None and process.poll() is None

    @property
    def public_url(self) -> str | None:
        with self._lock:
            return self._url

    @property
    def error(self) -> str:
        with self._lock:
            if self._error:
                return self._error
            process = self._process
            if process is not None and process.poll() is not None:
                return f"cloudflared stopped (exit code {process.returncode})"
            return ""

    def start(self, executable: str, local_port: int) -> None:
        """Start the tunnel client to a loopback HTTP service on ``local_port``."""
        if not 1 <= int(local_port) <= 65535:
            raise ValueError("local tunnel port must be between 1 and 65535")
        binary = self._resolve_executable(executable)
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            self._url = None
            self._error = ""
            self._stop_requested = False
            self._url_ready.clear()
            target = f"http://127.0.0.1:{int(local_port)}"
            command = [
                binary,
                "tunnel",
                "--no-autoupdate",
                "--url",
                target,
                "--http-host-header",
                f"127.0.0.1:{int(local_port)}",
            ]
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    shell=False,
                )
            except OSError as error:
                raise TunnelError(f"could not start cloudflared: {error}") from error
            self._process = process
            self._reader = threading.Thread(
                target=self._read_output,
                args=(process,),
                name="neezy-cloudflared-output",
                daemon=True,
            )
            self._reader.start()

    def _read_output(self, process: Any) -> None:
        stream = getattr(process, "stdout", None)
        try:
            if stream is not None:
                for line in stream:
                    match = _QUICK_TUNNEL_URL.search(line)
                    if match:
                        with self._lock:
                            self._url = match.group(0)
                            self._error = ""
                        self._url_ready.set()
                    elif "error" in line.lower() or "failed" in line.lower():
                        # Do not display or retain full client logs; they may
                        # include account metadata or private origin details.
                        with self._lock:
                            if self._url is None and not self._stop_requested:
                                self._error = (
                                    "cloudflared reported an error; check the "
                                    "installed tunnel client"
                                )
        except (OSError, UnicodeError):
            with self._lock:
                if not self._stop_requested and self._url is None:
                    self._error = "could not read cloudflared startup output"
        finally:
            with self._lock:
                if not self._stop_requested and process.poll() is not None:
                    self._url = None
                    if not self._error:
                        self._error = (
                            f"cloudflared stopped (exit code {process.returncode})"
                        )
                    self._url_ready.set()

    def wait_for_url(self, timeout: float = 15.0) -> str | None:
        """Wait briefly for the HTTPS endpoint, mainly useful to CLI clients/tests."""
        seconds = min(max(float(timeout), 0.0), 120.0)
        self._url_ready.wait(seconds)
        with self._lock:
            return self._url

    def stop(self) -> None:
        """Terminate the tunnel process; idempotent and safe during app shutdown."""
        with self._lock:
            process = self._process
            reader = self._reader
            self._stop_requested = True
            self._url = None
            self._error = ""
            self._process = None
            self._reader = None
            self._url_ready.set()
        if process is None:
            return
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=3.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=2.0)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1.0)
