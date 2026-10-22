"""MetaTrader 5 terminal bridge for local PC market integration and trade routing."""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from .mt5_compat import load_mt5_module

# Native MetaTrader5 on Windows, a remote terminal over RPyC when configured, or None
# (simulated mode). Tests patch this name; keep it the single module reference.
mt5 = load_mt5_module()

logger = logging.getLogger(__name__)

# MT5 Timeframe Mapping
MT5_TIMEFRAMES: dict[str, Any] = {}
if mt5 is not None:
    MT5_TIMEFRAMES = {
        "1m": mt5.TIMEFRAME_M1,
        "2m": mt5.TIMEFRAME_M2,
        "3m": mt5.TIMEFRAME_M3,
        "5m": mt5.TIMEFRAME_M5,
        "10m": mt5.TIMEFRAME_M10,
        "15m": mt5.TIMEFRAME_M15,
        "30m": mt5.TIMEFRAME_M30,
        "1h": mt5.TIMEFRAME_H1,
        "4h": mt5.TIMEFRAME_H4,
        "1d": mt5.TIMEFRAME_D1,
    }


NOT_CONNECTED = "MT5 not connected; no live data returned"
MT5_TIMEFRAME_NAMES = ("1m", "2m", "3m", "5m", "10m", "15m", "30m", "1h", "4h", "1d")
DEAL_TYPES = {0: "BUY", 1: "SELL"}
DEAL_ENTRIES = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}


def ready_bridge() -> tuple[MT5Bridge, str | None]:
    """Connect the global bridge for a read; return (bridge, error) with no fake data.

    Read methods on a disconnected simulated bridge return sample values, so
    every read path must check the error before reporting anything.
    """
    bridge = get_global_mt5_bridge()
    status = bridge.connect()
    if not status.get("success"):
        return bridge, f"MT5 not connected: {status.get('error', 'unknown error')}"
    return bridge, None


def is_mt5_available() -> bool:
    """Return True if the MetaTrader5 Python package is installed."""
    return mt5 is not None


class MT5Bridge:
    """Bridge for communicating with a local MetaTrader 5 terminal."""

    def __init__(
        self,
        login: int = 0,
        password: str = "",
        server: str = "",
        path: str = "",
        magic: int = 123456,
        symbol_map: str = "",
        mock: bool = False,
    ) -> None:
        self.login = login
        self.password = password
        self.server = server
        self.path = path
        self.magic = magic
        self.symbol_map_str = symbol_map
        self.mock = mock or (mt5 is None)
        self.connected = False
        self._lock = threading.RLock()
        self._mappings = self._parse_symbol_map(symbol_map)

    def _parse_symbol_map(self, map_str: str) -> dict[str, str]:
        """Parse comma-separated 'DERIV=MT5' pairs or JSON string."""
        mapping: dict[str, str] = {}
        if not map_str.strip():
            return mapping
        try:
            if map_str.strip().startswith("{"):
                loaded = json.loads(map_str)
                if isinstance(loaded, dict):
                    return {str(k).strip(): str(v).strip() for k, v in loaded.items()}
        except Exception:  # noqa: BLE001
            pass

        for part in map_str.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                if k.strip() and v.strip():
                    mapping[k.strip()] = v.strip()
        return mapping

    @property
    def symbol_mappings(self) -> dict[str, str]:
        """Explicit NEEZY-to-MT5 symbol pairs from the saved symbol map."""
        return dict(self._mappings)

    def map_symbol(self, symbol: str) -> str:
        """Translate a canonical symbol to the local MT5 symbol name."""
        cleaned = symbol.strip()
        if cleaned in self._mappings:
            return self._mappings[cleaned]
        # Remove Deriv prefix if needed e.g. frxEURUSD -> EURUSD
        if cleaned.startswith("frx"):
            raw = cleaned[3:]
            if raw in self._mappings:
                return self._mappings[raw]
            return raw
        return cleaned

    def initialize(self) -> dict[str, Any]:
        return self.connect()

    def connect(self) -> dict[str, Any]:
        """Connect to local MetaTrader 5 terminal."""
        if self.mock:
            self.connected = True
            return {
                "success": True,
                "connected": True,
                "mock": True,
                "message": "Connected to MT5 Bridge (Mock / Simulated mode)",
                "account": self.login or 1000001,
            }

        kwargs: dict[str, Any] = {}
        if self.path.strip():
            kwargs["path"] = self.path.strip()
        if self.login > 0:
            kwargs["login"] = self.login
        if self.password.strip():
            kwargs["password"] = self.password.strip()
        if self.server.strip():
            kwargs["server"] = self.server.strip()

        try:
            init_ok = mt5.initialize(**kwargs) if kwargs else mt5.initialize()
            if not init_ok:
                err = mt5.last_error()
                self.connected = False
                return {
                    "success": False,
                    "connected": False,
                    "mock": False,
                    "error": f"MT5 initialize failed: {err}",
                }
            self.connected = True
            acc_info = mt5.account_info()
            acc_dict = acc_info._asdict() if acc_info else {}
            return {
                "success": True,
                "connected": True,
                "mock": False,
                "message": "Connected to MetaTrader 5 terminal",
                "account": acc_dict.get("login", self.login),
                "server": acc_dict.get("server", self.server),
                "balance": acc_dict.get("balance", 0.0),
                "equity": acc_dict.get("equity", 0.0),
            }
        except Exception as ex:  # noqa: BLE001
            self.connected = False
            return {
                "success": False,
                "connected": False,
                "mock": False,
                "error": f"Connection error: {ex}",
            }

    def disconnect(self) -> None:
        """Shutdown connection to MT5 terminal."""
        if not self.mock and mt5 is not None:
            try:
                mt5.shutdown()
            except Exception:  # noqa: BLE001
                pass
        self.connected = False

    def get_status(self) -> dict[str, Any]:
        """Return status of MT5 connection and terminal info."""
        if self.mock:
            return {
                "available": is_mt5_available(),
                "connected": self.connected,
                "mock": True,
                "login": self.login or 1000001,
                "server": self.server or "Simulated-Server",
            }
        if not self.connected:
            return {
                "available": True,
                "connected": False,
                "mock": False,
                "login": self.login,
                "server": self.server,
            }
        try:
            terminal = mt5.terminal_info()
            term_dict = terminal._asdict() if terminal else {}
            return {
                "available": True,
                "connected": True,
                "mock": False,
                "login": self.login,
                "server": self.server,
                "terminal_name": term_dict.get("name", "MetaTrader 5"),
                "company": term_dict.get("company", ""),
                "connected_to_trade_server": term_dict.get("connected", True),
            }
        except Exception as ex:  # noqa: BLE001
            return {
                "available": True,
                "connected": False,
                "mock": False,
                "error": str(ex),
            }

    def get_account_info(self) -> dict[str, Any]:
        """Query active MT5 account information."""
        if not self.mock and not self.connected:
            return {"error": NOT_CONNECTED, "mock": False}
        if self.mock:
            return {
                "login": self.login or 1000001,
                "trade_mode": "DEMO",
                "leveraged": 100,
                "balance": 10000.00,
                "equity": 10000.00,
                "margin": 0.00,
                "free_margin": 10000.00,
                "currency": "USD",
                "server": self.server or "Simulated-Server",
                "mock": self.mock,
            }

        acc = mt5.account_info()
        if acc is None:
            return {"error": "Failed to retrieve account info", "mock": False}
        info = acc._asdict()
        return {
            "login": info.get("login"),
            "trade_mode": info.get("trade_mode"),
            "leverage": info.get("leverage"),
            "balance": info.get("balance"),
            "equity": info.get("equity"),
            "margin": info.get("margin"),
            "free_margin": info.get("margin_free"),
            "currency": info.get("currency"),
            "server": info.get("server"),
            "mock": False,
        }

    def get_quote(self, symbol: str) -> dict[str, Any]:
        """Fetch real-time tick quote for a given symbol."""
        mt5_sym = self.map_symbol(symbol)
        if not self.mock and not self.connected:
            return {
                "symbol": symbol,
                "mt5_symbol": mt5_sym,
                "error": NOT_CONNECTED,
                "mock": False,
            }
        if self.mock:
            now = time.time()
            return {
                "symbol": symbol,
                "mt5_symbol": mt5_sym,
                "bid": 1.0850,
                "ask": 1.0852,
                "last": 1.0851,
                "volume": 100,
                "time": int(now),
                "mock": True,
            }

        tick = mt5.symbol_info_tick(mt5_sym)
        if tick is None:
            return {
                "symbol": symbol,
                "mt5_symbol": mt5_sym,
                "error": f"Symbol {mt5_sym} not found or no quote available",
            }
        tdict = tick._asdict()
        return {
            "symbol": symbol,
            "mt5_symbol": mt5_sym,
            "bid": tdict.get("bid"),
            "ask": tdict.get("ask"),
            "last": tdict.get("last"),
            "volume": tdict.get("volume"),
            "time": tdict.get("time"),
            "mock": False,
        }

    def fetch_candles(
        self, symbol: str, timeframe: str = "5m", count: int = 100
    ) -> list[dict[str, Any]]:
        """Fetch historical candle rates from MT5 terminal."""
        mt5_sym = self.map_symbol(symbol)
        if not self.mock and not self.connected:
            return []
        if self.mock:
            now = int(time.time())
            step = 300 if timeframe == "5m" else 60
            candles = []
            base = 1.0800
            for i in range(count):
                ts = now - (count - i) * step
                candles.append(
                    {
                        "time": ts,
                        "open": round(base + (i * 0.0001), 5),
                        "high": round(base + (i * 0.0001) + 0.0005, 5),
                        "low": round(base + (i * 0.0001) - 0.0005, 5),
                        "close": round(base + (i * 0.0001) + 0.0002, 5),
                        "tick_volume": 100 + i,
                    }
                )
            return candles

        tf_const = MT5_TIMEFRAMES.get(timeframe, mt5.TIMEFRAME_M5)
        rates = mt5.copy_rates_from_pos(mt5_sym, tf_const, 0, count)
        if rates is None or len(rates) == 0:
            return []

        result = []
        for r in rates:
            result.append(
                {
                    "time": int(r["time"]),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "tick_volume": int(r["tick_volume"]),
                }
            )
        return result

    def get_positions(self) -> list[dict[str, Any]]:
        """Query open trading positions."""
        if not self.mock and not self.connected:
            return []
        if self.mock:
            return [
                {
                    "ticket": 987654321,
                    "symbol": "EURUSD",
                    "type": "BUY",
                    "volume": 0.1,
                    "price_open": 1.0820,
                    "sl": 1.0790,
                    "tp": 1.0880,
                    "profit": 30.00,
                    "magic": self.magic,
                    "comment": "NEEZY mock position",
                }
            ]

        positions = mt5.positions_get()
        if positions is None:
            return []

        res = []
        for p in positions:
            pdict = p._asdict()
            res.append(
                {
                    "ticket": pdict.get("ticket"),
                    "symbol": pdict.get("symbol"),
                    "type": "BUY" if pdict.get("type") == 0 else "SELL",
                    "volume": pdict.get("volume"),
                    "price_open": pdict.get("price_open"),
                    "sl": pdict.get("sl"),
                    "tp": pdict.get("tp"),
                    "profit": pdict.get("profit"),
                    "magic": pdict.get("magic"),
                    "comment": pdict.get("comment"),
                }
            )
        return res

    def get_account_history(
        self, days: int = 7, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Read closed deals from the last ``days`` days. Read-only; never trades."""
        if not self.mock and not self.connected:
            return []
        if self.mock:
            return [
                {
                    "ticket": 555001,
                    "order": 555001,
                    "time": int(time.time()) - 86400,
                    "symbol": "EURUSD",
                    "type": "SELL",
                    "entry": "OUT",
                    "volume": 0.1,
                    "price": 1.0850,
                    "profit": 12.50,
                    "commission": -0.70,
                    "swap": 0.0,
                    "comment": "NEEZY mock deal",
                    "mock": True,
                }
            ]

        now = int(time.time())
        deals = mt5.history_deals_get(now - int(days) * 86400, now)
        if not deals:
            return []
        rows = []
        for deal in sorted(deals, key=lambda d: d.time)[-int(limit) :]:
            d = deal._asdict()
            rows.append(
                {
                    "ticket": d.get("ticket"),
                    "order": d.get("order"),
                    "time": d.get("time"),
                    "symbol": d.get("symbol"),
                    "type": DEAL_TYPES.get(d.get("type"), "OTHER"),
                    "entry": DEAL_ENTRIES.get(d.get("entry"), "OTHER"),
                    "volume": d.get("volume"),
                    "price": d.get("price"),
                    "profit": d.get("profit"),
                    "commission": d.get("commission"),
                    "swap": d.get("swap"),
                    "comment": d.get("comment"),
                    "mock": False,
                }
            )
        return rows

    def _resolve_filling_mode(self, mt5_sym: str, filling_mode: str = "Auto") -> Any:
        if mt5 is None:
            return 1
        fok = getattr(mt5, "ORDER_FILLING_FOK", 0)
        ioc = getattr(mt5, "ORDER_FILLING_IOC", 1)
        ret = getattr(mt5, "ORDER_FILLING_RETURN", 2)
        choice = (filling_mode or "Auto").strip().upper()
        if choice == "FOK":
            return fok
        if choice == "IOC":
            return ioc
        if choice == "RETURN":
            return ret
        sym_info_fn = getattr(mt5, "symbol_info", None)
        if callable(sym_info_fn):
            info = sym_info_fn(mt5_sym)
            raw_mask = getattr(info, "filling_mode", 0) if info else 0
            mask = raw_mask if isinstance(raw_mask, int) else 0
            if mask & 2:
                return ioc
            if mask & 1:
                return fok
            if mask & 4:
                return ret
        return ioc

    def place_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        price: float = 0.0,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "NEEZY Trade",
        *,
        deviation: int = 20,
        filling_mode: str = "Auto",
    ) -> dict[str, Any]:
        """Place or send an order to MT5 terminal."""
        with self._lock:
            mt5_sym = self.map_symbol(symbol)
            order_type_clean = order_type.strip().upper()

            if order_type_clean not in ("BUY", "SELL"):
                return {"success": False, "error": f"Unknown order type {order_type!r}"}
            if volume <= 0:
                return {"success": False, "error": "Volume must be greater than zero"}
            if not self.connected:
                return {
                    "success": False,
                    "error": "MT5 bridge is not connected; order not sent",
                    "mock": self.mock,
                }

            if self.mock:
                ticket = int(time.time() * 1000) % 1000000000
                fill_price = (
                    price
                    if price > 0
                    else (1.0850 if order_type_clean == "BUY" else 1.0848)
                )
                return {
                    "success": True,
                    "ticket": ticket,
                    "symbol": symbol,
                    "mt5_symbol": mt5_sym,
                    "order_type": order_type_clean,
                    "volume": volume,
                    "price": fill_price,
                    "sl": sl,
                    "tp": tp,
                    "magic": self.magic,
                    "comment": comment,
                    "mock": True,
                    "message": "Order placed successfully (Mock)",
                }

            mt5_type = (
                mt5.ORDER_TYPE_BUY if order_type_clean == "BUY" else mt5.ORDER_TYPE_SELL
            )
            if price <= 0:
                tick = mt5.symbol_info_tick(mt5_sym)
                if tick is None:
                    return {
                        "success": False,
                        "error": f"Failed to get price tick for {mt5_sym}",
                    }
                price = tick.ask if order_type_clean == "BUY" else tick.bid

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": mt5_sym,
                "volume": float(volume),
                "type": mt5_type,
                "price": float(price),
                "deviation": max(0, int(deviation)),
                "sl": float(sl),
                "tp": float(tp),
                "magic": int(self.magic),
                "comment": comment,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._resolve_filling_mode(mt5_sym, filling_mode),
            }

            result = mt5.order_send(request)
            if result is None:
                return {"success": False, "error": "Order send returned None"}
            rdict = result._asdict()
            if rdict.get("retcode") != mt5.TRADE_RETCODE_DONE:
                return {
                    "success": False,
                    "error": (
                        f"Order failed with retcode {rdict.get('retcode')}: "
                        f"{rdict.get('comment')}"
                    ),
                }
            return {
                "success": True,
                "ticket": rdict.get("order"),
                "symbol": symbol,
                "mt5_symbol": mt5_sym,
                "order_type": order_type_clean,
                "volume": volume,
                "price": rdict.get("price"),
                "sl": sl,
                "tp": tp,
                "magic": self.magic,
                "comment": comment,
                "mock": False,
                "message": "Order placed successfully",
            }

    def preview_order(
        self,
        symbol: str,
        order_type: str,
        volume: float,
        price: float = 0.0,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "NEEZY Trade",
    ) -> dict[str, Any]:
        """Describe the order that would be sent, without contacting MT5."""
        order_type_clean = order_type.strip().upper()
        errors = []
        if order_type_clean not in ("BUY", "SELL"):
            errors.append(f"Unknown order type {order_type!r}")
        if volume <= 0:
            errors.append("Volume must be greater than zero")
        return {
            "status": "dry_run",
            "sent": False,
            "valid": not errors,
            "errors": errors,
            "symbol": symbol,
            "mt5_symbol": self.map_symbol(symbol),
            "order_type": order_type_clean,
            "volume": volume,
            "price": price,
            "sl": sl,
            "tp": tp,
            "magic": self.magic,
            "comment": comment,
        }

    def close_position(self, ticket: int) -> dict[str, Any]:
        """Close an open position by ticket number."""
        if not self.connected:
            return {
                "success": False,
                "error": "MT5 bridge is not connected; position not closed",
                "mock": self.mock,
            }
        if self.mock:
            return {
                "success": True,
                "ticket": ticket,
                "message": f"Position #{ticket} closed successfully (Mock)",
                "mock": True,
            }

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"success": False, "error": f"Position #{ticket} not found"}
        p = positions[0]._asdict()

        mt5_type = mt5.ORDER_TYPE_SELL if p.get("type") == 0 else mt5.ORDER_TYPE_BUY
        symbol = p.get("symbol")
        tick = mt5.symbol_info_tick(symbol)
        price = tick.bid if p.get("type") == 0 else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": p.get("volume"),
            "type": mt5_type,
            "price": price,
            "magic": self.magic,
            "comment": "NEEZY Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            return {"success": False, "error": "Order send returned None"}
        rdict = result._asdict()
        if rdict.get("retcode") != mt5.TRADE_RETCODE_DONE:
            return {
                "success": False,
                "error": (
                    f"Close failed with retcode {rdict.get('retcode')}: "
                    f"{rdict.get('comment')}"
                ),
            }
        return {
            "success": True,
            "ticket": ticket,
            "message": f"Position #{ticket} closed successfully",
            "mock": False,
        }


# Global active MT5 bridge instance, keyed by the connection settings it was
# built from so a settings change takes effect on the next call.
_GLOBAL_BRIDGE: MT5Bridge | None = None
_GLOBAL_KEY: tuple[Any, ...] | None = None


def bridge_from_settings(settings: Any = None) -> MT5Bridge:
    """Build a bridge from saved NEEZY settings (``settings.json``) by default."""
    if settings is None:
        from neezy_backend.storage import SettingsStore

        settings = SettingsStore().load()
    return MT5Bridge(
        login=settings.mt5_login,
        password=settings.mt5_password,
        server=settings.mt5_server,
        path=settings.mt5_path,
        magic=settings.mt5_magic,
        symbol_map=settings.mt5_symbol_map,
    )


def get_global_mt5_bridge(
    login: int | None = None,
    password: str | None = None,
    server: str | None = None,
    path: str | None = None,
    magic: int | None = None,
    symbol_map: str | None = None,
) -> MT5Bridge:
    """Return the shared bridge, configured from saved settings unless overridden.

    Passing no arguments uses the MT5 fields saved by the GUI, so the CLI, the
    agent tools, and the MCP tools all connect with the same account.
    """
    global _GLOBAL_BRIDGE, _GLOBAL_KEY
    explicit = (login, password, server, path, magic, symbol_map)
    if all(value is None for value in explicit):
        bridge = bridge_from_settings()
        key: tuple[Any, ...] = (
            bridge.login,
            bridge.password,
            bridge.server,
            bridge.path,
            bridge.magic,
            bridge.symbol_map_str,
        )
    else:
        key = (
            0 if login is None else login,
            "" if password is None else password,
            "" if server is None else server,
            "" if path is None else path,
            123456 if magic is None else magic,
            "" if symbol_map is None else symbol_map,
        )
        bridge = MT5Bridge(
            login=key[0],
            password=key[1],
            server=key[2],
            path=key[3],
            magic=key[4],
            symbol_map=key[5],
        )
    if _GLOBAL_BRIDGE is None or _GLOBAL_KEY != key:
        _GLOBAL_BRIDGE = bridge
        _GLOBAL_KEY = key
    return _GLOBAL_BRIDGE
