"""Pick an MetaTrader 5 backend for this machine and expose one ``mt5`` name.

The ``MetaTrader5`` package only ships for Windows. ``mt5linux``
(https://github.com/lucas-campagna/mt5linux) runs the terminal under Wine as
``mt5server.exe`` and serves the same API over RPyC (default port 18812). NEEZY
talks to that server directly, so Termux, Colab, Codespaces, GitHub Actions and
plain Linux can use a terminal that runs somewhere else.

Selection rules (all pure, all offline):

* ``NEEZY_MT5_BACKEND`` = ``auto`` (default) | ``native`` | ``rpyc`` | ``none``.
* ``auto`` prefers the native package. The RPyC backend is used only when
  ``NEEZY_MT5_RPYC_HOST`` is set, so a machine with no MT5 configured keeps the
  simulated bridge exactly as before.
* Nothing connects at import time. ``RpycMT5`` opens its socket on the first call.

Limits: the constructor of ``mt5linux.MetaTrader5`` always starts a Docker or
udocker container, which Termux and hosted notebooks do not have. That is why
this module connects with ``rpyc.classic`` and skips the container manager.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import threading
from collections import namedtuple
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

BACKEND_ENV = "NEEZY_MT5_BACKEND"
RPYC_HOST_ENV = "NEEZY_MT5_RPYC_HOST"
RPYC_PORT_ENV = "NEEZY_MT5_RPYC_PORT"
DEFAULT_RPYC_PORT = 18812
BACKEND_CHOICES = ("auto", "native", "rpyc", "none")

# MQL5 numeric constants. The RPyC client needs them at import time, before any
# connection exists. tests/test_mt5_compat.py checks them against mt5linux when
# that package is installed.
REMOTE_CONSTANTS: dict[str, int] = {
    "TIMEFRAME_M1": 1,
    "TIMEFRAME_M2": 2,
    "TIMEFRAME_M3": 3,
    "TIMEFRAME_M4": 4,
    "TIMEFRAME_M5": 5,
    "TIMEFRAME_M6": 6,
    "TIMEFRAME_M10": 10,
    "TIMEFRAME_M12": 12,
    "TIMEFRAME_M15": 15,
    "TIMEFRAME_M20": 20,
    "TIMEFRAME_M30": 30,
    "TIMEFRAME_H1": 16385,
    "TIMEFRAME_H2": 16386,
    "TIMEFRAME_H3": 16387,
    "TIMEFRAME_H4": 16388,
    "TIMEFRAME_H6": 16390,
    "TIMEFRAME_H8": 16392,
    "TIMEFRAME_H12": 16396,
    "TIMEFRAME_D1": 16408,
    "TIMEFRAME_W1": 32769,
    "TIMEFRAME_MN1": 49153,
    "ORDER_TYPE_BUY": 0,
    "ORDER_TYPE_SELL": 1,
    "ORDER_TIME_GTC": 0,
    "ORDER_FILLING_IOC": 1,
    "TRADE_ACTION_DEAL": 1,
    "TRADE_RETCODE_DONE": 10009,
}

# Runs inside the remote Wine/Python process. Everything that crosses the wire
# is a plain builtin (dict/list/str/number), so the client never needs the
# MetaTrader5 package or its struct types to unpickle a result.
_REMOTE_HELPERS = r"""
import MetaTrader5 as _neezy_mt5


def _neezy_plain(value):
    if value is None:
        return None
    if hasattr(value, "_asdict"):
        data = value._asdict()
        return {
            "__record__": True,
            "fields": [str(k) for k in data.keys()],
            "values": [_neezy_plain(v) for v in data.values()],
        }
    names = getattr(getattr(value, "dtype", None), "names", None)
    if names:
        return [dict(zip(names, row)) for row in value.tolist()]
    if hasattr(value, "tolist"):
        return _neezy_plain(value.tolist())
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, tuple):
        return {"__tuple__": True, "values": [_neezy_plain(v) for v in value]}
    if isinstance(value, list):
        return [_neezy_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _neezy_plain(v) for k, v in value.items()}
    return str(value)


def _neezy_call(name, args, kwargs):
    return _neezy_plain(getattr(_neezy_mt5, name)(*args, **kwargs))


def _neezy_const(name):
    return _neezy_plain(getattr(_neezy_mt5, name))
"""


@dataclass(frozen=True)
class Mt5Selection:
    """Which backend was chosen, and why. Safe to log or show in a status view."""

    backend: str  # "native" | "rpyc" | "none"
    runtime: str
    reason: str
    rpyc_host: str = ""
    rpyc_port: int = DEFAULT_RPYC_PORT


def detect_runtime(
    env: Mapping[str, str] | None = None, platform: str | None = None
) -> str:
    """Name the environment NEEZY is running in.

    Returns one of ``termux``, ``codespaces``, ``github_actions``, ``colab``,
    ``windows``, ``macos``, ``linux`` or ``other``. Specific hosts are checked
    first because Termux, Codespaces and Actions all report ``linux``.
    """
    env = os.environ if env is None else env
    platform = _sys_platform() if platform is None else platform
    if env.get("TERMUX_VERSION") or "com.termux" in env.get("PREFIX", ""):
        return "termux"
    if env.get("CODESPACES") == "true":
        return "codespaces"
    if env.get("GITHUB_ACTIONS") == "true":
        return "github_actions"
    if any(env.get(key) for key in ("COLAB_RELEASE_TAG", "COLAB_GPU")):
        return "colab"
    if platform.startswith("win"):
        return "windows"
    if platform == "darwin":
        return "macos"
    if platform.startswith("linux"):
        return "linux"
    return "other"


def _sys_platform() -> str:
    import sys

    return sys.platform


def rpyc_port(env: Mapping[str, str]) -> int:
    """Parse ``NEEZY_MT5_RPYC_PORT``; raise ValueError when it is not a TCP port."""
    raw = env.get(RPYC_PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_RPYC_PORT
    port = int(raw)
    if not 1 <= port <= 65535:
        raise ValueError(f"{RPYC_PORT_ENV} must be 1-65535, got {port}")
    return port


def select_backend(
    env: Mapping[str, str] | None = None,
    *,
    native_importable: bool,
    rpyc_importable: bool,
    runtime: str | None = None,
) -> Mt5Selection:
    """Choose a backend from the environment and what is installed. No I/O."""
    env = os.environ if env is None else env
    runtime = detect_runtime(env) if runtime is None else runtime
    requested = (env.get(BACKEND_ENV, "") or "auto").strip().lower()
    host = env.get(RPYC_HOST_ENV, "").strip()

    def none(reason: str) -> Mt5Selection:
        return Mt5Selection("none", runtime, reason)

    if requested not in BACKEND_CHOICES:
        return none(f"{BACKEND_ENV}={requested!r} is not one of {BACKEND_CHOICES}")
    if requested == "none":
        return none(f"disabled by {BACKEND_ENV}=none")

    try:
        port = rpyc_port(env)
    except ValueError as error:
        return none(str(error))

    def native() -> Mt5Selection:
        return Mt5Selection("native", runtime, "MetaTrader5 package found")

    def remote() -> Mt5Selection:
        return Mt5Selection(
            "rpyc",
            runtime,
            f"terminal over RPyC at {host}:{port}",
            rpyc_host=host,
            rpyc_port=port,
        )

    if requested == "native":
        if native_importable:
            return native()
        return none(f"MetaTrader5 package is not importable on {runtime}")

    if requested == "rpyc":
        if not rpyc_importable:
            return none(
                "rpyc is missing: pip install 'neezy-market-workspace[mt5-remote]'"
            )
        if not host:
            return none(f"{RPYC_HOST_ENV} is not set")
        return remote()

    # auto
    if native_importable:
        return native()
    if not host:
        return none(f"no MetaTrader5 package on {runtime}; {RPYC_HOST_ENV} not set")
    if not rpyc_importable:
        return none("rpyc is missing: pip install 'neezy-market-workspace[mt5-remote]'")
    return remote()


def current_selection(env: Mapping[str, str] | None = None) -> Mt5Selection:
    """Selection for this process, without importing or connecting to anything."""
    return select_backend(
        env,
        native_importable=importlib.util.find_spec("MetaTrader5") is not None,
        rpyc_importable=importlib.util.find_spec("rpyc") is not None,
    )


def load_mt5_module(env: Mapping[str, str] | None = None) -> Any | None:
    """Return the object that stands in for the ``MetaTrader5`` module, or None.

    None means no backend: ``mt5_bridge`` then runs its simulated mode.
    """
    selection = current_selection(env)
    if selection.backend == "native":
        try:
            import MetaTrader5 as native_module
        except ImportError:
            return None
        return native_module
    if selection.backend == "rpyc":
        return RpycMT5(selection.rpyc_host, selection.rpyc_port)
    return None


@lru_cache(maxsize=64)
def _record_class(fields: tuple[str, ...]) -> type:
    return namedtuple("MT5Record", fields, rename=True)  # type: ignore[misc]


def _revive(value: Any) -> Any:
    """Rebuild MT5 records (attribute and ``_asdict`` access) from plain data."""
    if isinstance(value, dict):
        if value.get("__record__") is True:
            cls = _record_class(tuple(value["fields"]))
            return cls(*[_revive(v) for v in value["values"]])
        if value.get("__tuple__") is True:
            return tuple(_revive(v) for v in value["values"])
        return {key: _revive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_revive(item) for item in value]
    return value


class RpycMT5:
    """``MetaTrader5``-shaped client for a terminal served over RPyC.

    Any public function name is forwarded to the remote module. ALL-CAPS names
    come from ``REMOTE_CONSTANTS`` without a network call, or from the remote
    when they are not in the table. The socket opens on the first call.
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_RPYC_PORT,
        timeout: float = 60.0,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._conn: Any = None
        self._helpers: Any = None
        self._lock = threading.RLock()
        self._const_cache: dict[str, Any] = {}

    def __repr__(self) -> str:
        state = "connected" if self._conn is not None else "idle"
        return f"RpycMT5({self.host!r}, port={self.port}, {state})"

    def _ensure(self) -> Any:
        with self._lock:
            if self._conn is None:
                from rpyc.core.stream import SocketStream
                from rpyc.utils.classic import SlaveService
                from rpyc.utils.factory import connect_stream

                # Own the socket so a refused or failed connect closes it.
                sock = socket.create_connection(
                    (self.host, self.port), timeout=self.timeout
                )
                try:
                    sock.settimeout(None)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    conn = connect_stream(SocketStream(sock), SlaveService)
                except Exception:
                    sock.close()
                    raise
                conn._config["sync_request_timeout"] = self.timeout
                try:
                    conn.execute(_REMOTE_HELPERS)
                    helpers = conn.namespace
                except Exception:
                    conn.close()
                    raise
                self._conn = conn
                self._helpers = helpers
            return self._helpers

    def close(self) -> None:
        """Drop the socket. The next call reconnects."""
        with self._lock:
            conn, self._conn, self._helpers = self._conn, None, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - closing a dead socket is fine
                pass

    def _call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        helpers = self._ensure()
        try:
            return _revive(helpers["_neezy_call"](name, list(args), kwargs))
        except (EOFError, OSError):
            self.close()
            raise

    def constant(self, name: str) -> Any:
        if name in REMOTE_CONSTANTS:
            return REMOTE_CONSTANTS[name]
        with self._lock:
            if name not in self._const_cache:
                try:
                    self._const_cache[name] = self._ensure()["_neezy_const"](name)
                except (EOFError, OSError):
                    self.close()
                    raise
            return self._const_cache[name]

    def shutdown(self) -> None:
        """Ask the remote terminal to disconnect, then drop the socket."""
        if self._conn is None:
            return
        try:
            self._call("shutdown")
        finally:
            self.close()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name.isupper():
            return self.constant(name)

        def forward(*args: Any, **kwargs: Any) -> Any:
            return self._call(name, *args, **kwargs)

        forward.__name__ = name
        return forward
