"""Read-only MetaTrader 5 preflight checklist.

Reports whether the saved MT5 settings are ready for NEEZY. It never places,
modifies, or closes orders, and it never changes Market Watch (no symbol_select).
Passwords are reported as set or not set, never printed.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

OK = "ok"
WARN = "warn"
FAIL = "fail"

_TRADE_MODES = {0: "DEMO", 1: "CONTEST", 2: "REAL"}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "_asdict"):
        return dict(obj._asdict())
    if isinstance(obj, dict):
        return dict(obj)
    return {}


def run_preflight(settings: Any = None) -> list[Check]:
    """Return the checklist for the saved (or given) settings."""
    from neezy_backend import mt5_bridge
    from neezy_backend.mt5_bridge import bridge_from_settings

    if settings is None:
        from neezy_backend.storage import SettingsStore

        settings = SettingsStore().load()

    checks: list[Check] = []
    module = mt5_bridge.mt5
    if module is None:
        checks.append(
            Check(
                "MetaTrader5 package",
                FAIL,
                "not installed; install it in the NEEZY venv: pip install MetaTrader5 "
                "(Windows, 64-bit Python)",
            )
        )
    else:
        checks.append(Check("MetaTrader5 package", OK, "installed"))

    path = settings.mt5_path.strip()
    if not path:
        checks.append(
            Check(
                "terminal path",
                WARN,
                "not set; the default installed terminal is used",
            )
        )
    elif os.path.isfile(path):
        checks.append(Check("terminal path", OK, path))
    else:
        checks.append(Check("terminal path", FAIL, f"file not found: {path}"))

    server = settings.mt5_server.strip()
    if settings.mt5_login > 0 and server:
        checks.append(
            Check(
                "login and server",
                OK,
                f"login {settings.mt5_login} on server {server}",
            )
        )
    elif settings.mt5_login <= 0 and not server:
        checks.append(
            Check(
                "login and server",
                WARN,
                "not set; NEEZY uses whichever account the terminal is logged in to",
            )
        )
    else:
        checks.append(
            Check(
                "login and server",
                FAIL,
                "set both the account login and the server, or neither, in "
                "Settings > MT5 BRIDGE",
            )
        )
        # A half-configured account would connect to the wrong place: stop here.
        return checks

    if settings.mt5_password:
        checks.append(Check("password", OK, "set (not shown)"))
    else:
        checks.append(
            Check(
                "password",
                WARN,
                "not set; the terminal must already be logged in to the account",
            )
        )

    bridge = bridge_from_settings(settings)
    mappings = bridge.symbol_mappings
    if mappings:
        checks.append(Check("symbol map", OK, f"{len(mappings)} explicit mapping(s)"))
    else:
        checks.append(
            Check(
                "symbol map",
                OK,
                "none set; the frx prefix is stripped (frxEURUSD -> EURUSD)",
            )
        )

    if module is None:
        checks.append(Check("connection", WARN, "skipped: MetaTrader5 not installed"))
        return checks

    conn = bridge.connect()
    if not conn.get("success"):
        checks.append(
            Check("connection", FAIL, str(conn.get("error", "unknown error")))
        )
        return checks
    checks.append(Check("connection", OK, "connected to the terminal"))

    account = _as_dict(module.account_info())
    if not account:
        checks.append(
            Check(
                "account",
                FAIL,
                "could not read account info; log in to the account in the terminal",
            )
        )
        return checks

    live_login = account.get("login")
    if settings.mt5_login > 0 and live_login != settings.mt5_login:
        checks.append(
            Check(
                "account match",
                WARN,
                f"terminal is logged in as {live_login}, settings say "
                f"{settings.mt5_login}; orders go to the terminal's account",
            )
        )
    else:
        checks.append(Check("account match", OK, f"account {live_login}"))

    mode = _TRADE_MODES.get(account.get("trade_mode"), "UNKNOWN")
    if mode == "REAL":
        checks.append(
            Check(
                "account type",
                WARN,
                f"LIVE account {live_login}: orders use real money",
            )
        )
    else:
        checks.append(Check("account type", OK, f"{mode} account {live_login}"))

    terminal = _as_dict(module.terminal_info())
    terminal_trade = bool(terminal.get("trade_allowed", False))
    account_trade = bool(account.get("trade_allowed", False))
    if terminal_trade and account_trade:
        checks.append(
            Check("trading allowed", OK, "allowed in the terminal and on the account")
        )
    else:
        checks.append(
            Check(
                "trading allowed",
                FAIL,
                f"blocked (terminal={terminal_trade}, account={account_trade}); "
                "enable Algo Trading in the terminal and check the account's "
                "trading permission",
            )
        )

    for mt5_symbol in sorted(set(mappings.values())):
        if module.symbol_info(mt5_symbol) is None:
            checks.append(
                Check(
                    f"symbol {mt5_symbol}",
                    WARN,
                    "not found on this server; check the symbol map",
                )
            )
        else:
            checks.append(Check(f"symbol {mt5_symbol}", OK, "found"))

    return checks


def has_failures(checks: list[Check]) -> bool:
    return any(check.status == FAIL for check in checks)


def checks_as_dicts(checks: list[Check]) -> list[dict[str, str]]:
    return [asdict(check) for check in checks]
