"""Shared rules for sending live MT5 orders.

The CLI (``neezy-cli mt5 order --confirm``), the terminal menu (which runs the
CLI), and the desktop ORDERS page all send through these helpers, so the
refusal rules cannot drift apart. Agent and MCP tools never call them: they
can read MT5 or preview an order, nothing more.
"""

from __future__ import annotations

import math
from typing import Any

from .mt5_bridge import MT5Bridge

ORDER_SIDES = ("BUY", "SELL")


def check_live_terminal(bridge: MT5Bridge) -> dict[str, Any]:
    """Connect and report whether a real terminal is available for orders.

    Simulated and disconnected bridges are refused. When accepted, the result
    carries the account and server so the user can confirm them.
    """
    conn = bridge.connect()
    if not conn.get("success") or conn.get("mock"):
        reason = conn.get("error") or "terminal is simulated, not connected"
        return {"ok": False, "reason": f"MT5 not connected ({reason})"}
    return {
        "ok": True,
        "reason": None,
        "account": conn.get("account"),
        "server": conn.get("server") or "",
    }


def send_live_order(
    bridge: MT5Bridge,
    *,
    confirmed: bool,
    symbol: str,
    order_type: str,
    volume: float,
    price: float = 0.0,
    sl: float = 0.0,
    tp: float = 0.0,
    comment: str = "NEEZY Trade",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Send one order to the real terminal. Nothing is sent unless ``confirmed``.

    ``confirmed`` means the caller has shown the order to the user and the user
    agreed. The terminal is checked again here, at the moment of sending.

    ``dry_run``: when True, the order is validated but never sent (roadmap #100).
    """
    if dry_run:
        return {
            "success": True,
            "sent": False,
            "dry_run": True,
            "error": None,
            "note": "dry-run: order validated, no order sent",
            "order": {
                "symbol": symbol,
                "order_type": order_type,
                "volume": volume,
                "sl": sl,
                "tp": tp,
            },
        }
    if not confirmed:
        return {
            "success": False,
            "sent": False,
            "error": "live order needs explicit confirmation",
        }
    gate = check_live_terminal(bridge)
    if not gate["ok"]:
        return {
            "success": False,
            "sent": False,
            "error": f"live order refused: {gate['reason']}",
        }
    return bridge.place_order(
        symbol,
        order_type,
        volume,
        price=price,
        sl=sl,
        tp=tp,
        comment=comment,
    )


def _number(text: str, label: str) -> float:
    raw = (text or "").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{label} must be a number.") from error
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number.")
    if value < 0:
        raise ValueError(f"{label} must not be negative.")
    return value


def parse_order_form(
    symbol: str, side: str, volume: str, sl: str = "", tp: str = ""
) -> dict[str, Any]:
    """Validate the desktop form. Raises ``ValueError`` with a readable message.

    A blank stop or target means "none" (0). Prices are not part of the form:
    the desktop ORDERS page only sends market orders.
    """
    symbol_clean = (symbol or "").strip()
    if not symbol_clean:
        raise ValueError("Choose a symbol.")
    side_clean = (side or "").strip().upper()
    if side_clean not in ORDER_SIDES:
        raise ValueError("Side must be BUY or SELL.")
    volume_value = _number(volume, "Volume")
    if volume_value <= 0:
        raise ValueError("Volume must be greater than zero.")
    return {
        "symbol": symbol_clean,
        "order_type": side_clean,
        "volume": volume_value,
        "sl": _number(sl, "Stop loss"),
        "tp": _number(tp, "Take profit"),
    }


def confirmation_lines(order: dict[str, Any], gate: dict[str, Any]) -> list[str]:
    """Plain-text summary shown to the user before a live order is sent."""

    def level(value: float) -> str:
        return f"{value:g}" if value > 0 else "none"

    mt5_symbol = order.get("mt5_symbol", order["symbol"])
    if gate.get("account") is None:
        account_line = "Account: checked when the order is placed"
    else:
        account_line = (
            f"Account: {gate['account']} on {gate.get('server') or 'unknown server'}"
        )
    return [
        f"Symbol: {order['symbol']} (MT5: {mt5_symbol})",
        f"Side: {order['order_type']} at market (fills at the current price)",
        f"Volume: {order['volume']:g} lots",
        f"Stop loss: {level(order['sl'])}",
        f"Take profit: {level(order['tp'])}",
        account_line,
    ]
