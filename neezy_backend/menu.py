"""Plain-text terminal menu for NEEZY.

Stdlib only, no curses, so it runs in cmd.exe, PowerShell, and any ANSI-less
terminal. Each choice runs the same command the CLI exposes, so the menu adds
no new behaviour and no new trading paths.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TextIO

from .mcp_catalog import MCP_SERVERS

LIVE_CONFIRM_PHRASE = "SEND"


def _ask(prompt: str, input_fn: Callable[[str], str]) -> str:
    return input_fn(prompt).strip()


def _order_args(input_fn: Callable[[str], str]) -> list[str]:
    symbol = _ask("Symbol (e.g. frxEURUSD): ", input_fn)
    side = _ask("Side BUY or SELL: ", input_fn).upper()
    volume = _ask("Volume (lots): ", input_fn)
    if not symbol or side not in ("BUY", "SELL") or not volume:
        raise ValueError("symbol, BUY/SELL, and volume are all required")
    return ["mt5", "order", symbol, "--type", side, "--volume", volume]


MENU: tuple[tuple[str, str], ...] = (
    ("1", "Market data connectivity check"),
    ("2", "MT5 bridge status"),
    ("3", "MT5 account info"),
    ("4", "MT5 quote"),
    ("5", "MT5 candles"),
    ("6", "MT5 order: DRY RUN (not sent)"),
    ("7", "MT5 order: LIVE (type SEND to confirm)"),
    ("8", "MCP server catalog"),
    ("9", "MCP client config for one server"),
    ("p", "MT5 preflight checklist (read-only)"),
    ("0", "Quit"),
)


def run_menu(
    out: TextIO,
    *,
    input_fn: Callable[[str], str] = input,
    run: Callable[[list[str]], int] | None = None,
) -> int:
    """Loop over the menu until the user quits. `run` executes one CLI argv."""
    if run is None:
        from .cli import main as cli_main

        def run(argv: list[str]) -> int:
            return cli_main(argv, out=out)

    while True:
        out.write("\nNEEZY\n")
        for key, label in MENU:
            out.write(f"  {key}) {label}\n")
        choice = _ask("Choose: ", input_fn)
        try:
            if choice in ("0", "q", "Q", ""):
                return 0
            if choice == "1":
                argv = ["doctor"]
            elif choice == "p":
                argv = ["mt5", "preflight"]
            elif choice == "2":
                argv = ["mt5", "status"]
            elif choice == "3":
                argv = ["mt5", "account"]
            elif choice == "4":
                argv = ["mt5", "quote", _ask("Symbol: ", input_fn)]
            elif choice == "5":
                argv = ["mt5", "candles", _ask("Symbol: ", input_fn)]
            elif choice == "6":
                argv = [*_order_args(input_fn), "--dry-run"]
            elif choice == "7":
                argv = _order_args(input_fn)
                prompt = f"Type {LIVE_CONFIRM_PHRASE} to send a live order: "
                if _ask(prompt, input_fn) != LIVE_CONFIRM_PHRASE:
                    out.write("Cancelled. No order sent.\n")
                    continue
                argv.append("--confirm")
            elif choice == "8":
                argv = ["mcp", "list"]
            elif choice == "9":
                ids = ", ".join(server.id for server in MCP_SERVERS)
                out.write(f"Servers: {ids}\n")
                argv = ["mcp", "config", _ask("Server id: ", input_fn)]
            else:
                out.write(f"Unknown choice {choice!r}\n")
                continue
            code = run(argv)
            out.write(f"(exit {code})\n")
        except (OSError, RuntimeError, ValueError) as error:
            out.write(f"neezy: {error}\n")
