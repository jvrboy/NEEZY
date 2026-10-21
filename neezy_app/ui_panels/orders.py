"""ORDERS page: place a real MT5 market order after an explicit confirmation.

Orders go to the MetaTrader 5 terminal on this PC, using the saved MT5 settings.
Nothing is sent until the saved bridge is on, the terminal is confirmed live,
and the user answers the confirmation dialog, which defaults to No. The CLI
applies the same terminal rules.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from neezy_backend.markets import SYMBOLS
from neezy_backend.mt5_bridge import get_global_mt5_bridge
from neezy_backend.mt5_orders import (
    ORDER_SIDES,
    check_live_terminal,
    confirmation_lines,
    parse_order_form,
    send_live_order,
)


class OrdersMixin:
    """Methods for the ORDERS screen; mixed into App."""

    def _orders_page(self):
        page = self.pages["ORDERS"]
        self._order_busy = False
        self._label(page, "MT5 orders", 16).pack(anchor="w", pady=(5, 4))
        self._label(
            page,
            "Sends real market orders to the MetaTrader 5 terminal on this PC, "
            "using the saved MT5 settings. Every order asks you to confirm first.",
            10,
            self.MUTED,
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(0, 14))
        grid = tk.Frame(page, bg=self.BG)
        grid.pack(fill="both", expand=True)
        form, output = self._panel(grid), self._panel(grid)
        form.pack(side="left", fill="y", padx=(0, 6))
        output.pack(side="left", fill="both", expand=True, padx=(6, 0))

        self._label(form, "ORDER TICKET", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        self.order_vars = {
            "symbol": tk.StringVar(value=next(iter(SYMBOLS))),
            "side": tk.StringVar(value=ORDER_SIDES[0]),
            "volume": tk.StringVar(value="0.01"),
            "sl": tk.StringVar(value=""),
            "tp": tk.StringVar(value=""),
        }
        self._order_combo(form, "Symbol", self.order_vars["symbol"], list(SYMBOLS))
        self._order_combo(form, "Side", self.order_vars["side"], list(ORDER_SIDES))
        self._field(form, "Volume (lots)", self.order_vars["volume"])
        self._field(form, "Stop loss price (blank = none)", self.order_vars["sl"])
        self._field(form, "Take profit price (blank = none)", self.order_vars["tp"])
        self._action_button(form, "Preview (not sent)", self._order_preview)
        self._action_button(form, "Place live order…", self._order_place)
        self.order_status = self._label(
            form,
            "Nothing sent. Live orders need the MT5 bridge enabled and a "
            "connected terminal.",
            9,
            self.MUTED,
            wraplength=300,
            justify="left",
        )
        self.order_status.pack(anchor="w", padx=16, pady=(12, 14))

        self._label(output, "LAST ORDER", 9, self.CYAN).pack(
            anchor="w", padx=16, pady=(14, 8)
        )
        self.order_out = self._output(output, height=18)

    def _order_combo(self, parent, label, variable, values):
        row = tk.Frame(parent, bg=parent.cget("bg"))
        row.pack(fill="x", padx=16, pady=3)
        self._label(row, label, 9, self.MUTED).pack(side="left")
        ttk.Combobox(
            row,
            textvariable=variable,
            values=values,
            width=12,
            state="readonly",
        ).pack(side="right")

    def _order_read(self):
        """Validate the ticket and preview it locally. Returns None on any error."""
        try:
            order = parse_order_form(
                self.order_vars["symbol"].get(),
                self.order_vars["side"].get(),
                self.order_vars["volume"].get(),
                self.order_vars["sl"].get(),
                self.order_vars["tp"].get(),
            )
        except ValueError as error:
            self._order_show(f"Check the ticket: {error}", self.RED)
            return None
        preview = get_global_mt5_bridge().preview_order(
            order["symbol"],
            order["order_type"],
            order["volume"],
            sl=order["sl"],
            tp=order["tp"],
        )
        if not preview["valid"]:
            self._order_show("; ".join(preview["errors"]), self.RED)
            return None
        order["mt5_symbol"] = preview["mt5_symbol"]
        return order

    def _order_preview(self):
        order = self._order_read()
        if order is None:
            return
        self._order_show(
            "Preview only. Nothing was sent.\n\n"
            + "\n".join(confirmation_lines(order, {})),
            self.MUTED,
        )

    def _order_place(self):
        if self._order_busy:
            return
        order = self._order_read()
        if order is None:
            return
        from neezy_backend.storage import SettingsStore

        if not SettingsStore().load().mt5_enabled:
            self._order_show(
                "The MT5 bridge is off. Turn on 'Enable MetaTrader 5 local bridge' "
                "in SETTINGS → MT5 BRIDGE, save, then try again.",
                self.RED,
            )
            return
        self._order_busy = True
        self._order_show("Checking the MT5 terminal…", self.MUTED)
        bridge = get_global_mt5_bridge()
        threading.Thread(
            target=self._order_check_worker, args=(bridge, order), daemon=True
        ).start()

    def _order_check_worker(self, bridge, order):
        gate = check_live_terminal(bridge)
        self.after(0, lambda: self._order_confirm(bridge, order, gate))

    def _order_confirm(self, bridge, order, gate):
        if not gate["ok"]:
            self._order_done(f"Order not sent: {gate['reason']}", self.RED)
            return
        question = (
            "Send this LIVE order to MetaTrader 5?\n\n"
            + "\n".join(confirmation_lines(order, gate))
            + "\n\nThis uses real money on your broker account."
        )
        if not messagebox.askyesno(
            "Confirm live order", question, icon="warning", default="no"
        ):
            self._order_done("Cancelled. Nothing was sent.", self.MUTED)
            return
        self._order_show("Sending order…", self.MUTED)
        threading.Thread(
            target=self._order_send_worker, args=(bridge, order), daemon=True
        ).start()

    def _order_send_worker(self, bridge, order):
        result = send_live_order(
            bridge,
            confirmed=True,
            symbol=order["symbol"],
            order_type=order["order_type"],
            volume=order["volume"],
            sl=order["sl"],
            tp=order["tp"],
            comment="NEEZY Desktop",
        )
        self.after(0, lambda: self._order_result(result))

    def _order_result(self, result):
        if result.get("success"):
            self._order_done(
                f"Order placed. Ticket {result.get('ticket')} at "
                f"{result.get('price')}.",
                self.GREEN,
                detail=result,
            )
        else:
            self._order_done(
                f"Order not sent: {result.get('error')}", self.RED, detail=result
            )

    def _order_done(self, message, color, detail=None):
        """End an order attempt: free the button and show the outcome."""
        self._order_busy = False
        self._order_show(message, color, detail)

    def _order_show(self, message, color, detail=None):
        self.order_status.config(text=message.splitlines()[0], fg=color)
        body = message if detail is None else f"{message}\n\n{detail}"
        self._write(self.order_out, body)
