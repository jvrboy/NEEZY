"""Headless NEEZY command-line tools: scan, analyze, backtest, risk, and more.

Run ``neezy-cli --help`` (or ``python -m neezy_backend --help``). Market data
comes from Deriv's public API. Output is educational, not financial advice.

The CLI is a package: one module per command family.

- ``common``      shared output/argument helpers
- ``parser``      argparse construction (``build_parser``)
- ``analysis``    markets, doctor, scan, analyze, regime, read, supertrend,
                  divergence, corrdiv, strategies, correlation, decision-metrics
- ``chart``       closed-candle ASCII OHLC charts
- ``bot``         read-only loopback executor status
- ``kernels``     fused numerical-kernel status and local benchmarks
- ``backtest``    backtest, risk
- ``research``    research, datasets, study, knowledge, brain
- ``db``          db (SQLite), history (signal-transition log)
- ``alerts``      alerts (local rule store)
- ``ai``          ai (BYOK providers), local-model
- ``mt5``         mt5 (local terminal bridge)
- ``mcp``         mcp (third-party MCP catalog)
- ``dm``          dm (webhook notifications)
- ``menu_bridge`` menu (interactive terminal menu)

This ``__init__`` keeps ``main``, ``_default_fetch`` and the historical
re-exports, so ``neezy_backend.cli:main`` and existing ``cli.<name>``
attribute access (including ``mock.patch.object(cli, ...)`` targets such
as ``fetch_candles`` / ``fetch_history`` / ``_default_fetch``) keep
working unchanged.
"""

from __future__ import annotations

import sys
import traceback
from collections.abc import Callable, Sequence
from typing import TextIO

from ..stream import MAX_HISTORY_COUNT, fetch_candles, fetch_history
from .ai import _ai_store, _resolve_secret, cmd_ai, cmd_local_model
from .alerts import cmd_alerts
from .analysis import (
    cmd_analyze,
    cmd_corrdiv,
    cmd_correlation,
    cmd_decision_metrics,
    cmd_divergence,
    cmd_doctor,
    cmd_markets,
    cmd_read,
    cmd_regime,
    cmd_scan,
    cmd_strategies,
    cmd_supertrend,
)

# Advanced capability commands (accessibility, UI, automation)
from .automation import cmd_agents, cmd_bots
from .backtest import cmd_backtest, cmd_risk
from .bot import cmd_bot
from .btoken_cmd import cmd_btoken
from .capabilities_cmd import cmd_capabilities
from .chart import cmd_chart
from .common import (
    _closed,
    _emit,
    _finite,
    _json_default,
    _open_database,
    _symbol,
    _table,
    _without_series,
)
from .db import cmd_db, cmd_history
from .dm import cmd_dm
from .indicators_cmd import cmd_indicators
from .kernels import cmd_kernels
from .market_clock import cmd_sessions
from .mcp import cmd_mcp
from .menu_bridge import cmd_menu
from .mt5 import _mt5_require_live, cmd_mt5
from .parser import build_parser
from .research import (
    _study_row,
    _study_symbols,
    cmd_brain,
    cmd_datasets,
    cmd_knowledge,
    cmd_research,
    cmd_study,
)
from .settings_cmd import cmd_config
from .ui_cmd import cmd_ui
from .watchlist_cmd import cmd_watchlist

Fetcher = Callable[[str, int, int], list[tuple[int, float, float, float, float]]]

# Historical public surface of the former cli.py monolith, kept stable.
__all__ = [
    "MAX_HISTORY_COUNT",
    "Fetcher",
    "_ai_store",
    "_closed",
    "_default_fetch",
    "_emit",
    "_finite",
    "_json_default",
    "_mt5_require_live",
    "_open_database",
    "_resolve_secret",
    "_study_row",
    "_study_symbols",
    "_symbol",
    "_table",
    "_without_series",
    "build_parser",
    "cmd_agents",
    "cmd_ai",
    "cmd_alerts",
    "cmd_analyze",
    "cmd_backtest",
    "cmd_bot",
    "cmd_bots",
    "cmd_brain",
    "cmd_btoken",
    "cmd_capabilities",
    "cmd_chart",
    "cmd_config",
    "cmd_corrdiv",
    "cmd_correlation",
    "cmd_datasets",
    "cmd_db",
    "cmd_decision_metrics",
    "cmd_divergence",
    "cmd_dm",
    "cmd_doctor",
    "cmd_history",
    "cmd_indicators",
    "cmd_kernels",
    "cmd_knowledge",
    "cmd_local_model",
    "cmd_markets",
    "cmd_mcp",
    "cmd_menu",
    "cmd_mt5",
    "cmd_read",
    "cmd_regime",
    "cmd_research",
    "cmd_risk",
    "cmd_scan",
    "cmd_sessions",
    "cmd_strategies",
    "cmd_study",
    "cmd_supertrend",
    "cmd_ui",
    "cmd_watchlist",
    "fetch_candles",
    "fetch_history",
    "main",
]


def _default_fetch(symbol: str, seconds: int, count: int):
    # Deriv caps one request at MAX_HISTORY_COUNT candles; deeper history is paged.
    # No explicit url: the fetchers rotate through every configured endpoint.
    if count > MAX_HISTORY_COUNT:
        return fetch_history(symbol, seconds, count)
    return fetch_candles(symbol, seconds, count)


def _prepare_argv(argv: Sequence[str] | None) -> tuple[list[str], bool]:
    """Dashless-friendly argv preparation (BTOKEN accessibility layer).

    Always applied: ``name=value`` tokens become real flags when ``name``
    matches the active subcommand's options and no free-text positional
    would have consumed the token. Full mode (comma separators, bare flag
    words) switches on via ``NEEZY_BTOKEN=1`` or the ``--btoken`` flag.
    """
    import sys as _sys

    raw = list(_sys.argv[1:] if argv is None else argv)
    from ..btoken import normalize_argv

    prepared, full_mode = normalize_argv(raw, mode="auto")
    return prepared, full_mode


def main(
    argv: Sequence[str] | None = None,
    *,
    fetch: Fetcher | None = None,
    out: TextIO | None = None,
) -> int:
    prepared, full_mode = _prepare_argv(argv)
    parser = build_parser()
    args = parser.parse_args(prepared)
    if getattr(args, "theme", None):
        import os

        os.environ["NEEZY_THEME"] = args.theme
    if getattr(args, "btoken", False) and not full_mode:
        # The flag arrived after a first conservative pass; re-run the
        # preparation in full mode so comma separators and bare flag
        # words take effect for this invocation.
        raw = list(sys.argv[1:] if argv is None else argv)
        from ..btoken import normalize_argv

        prepared, _ = normalize_argv(raw, mode="full")
        args = parser.parse_args(prepared)
    out = out or sys.stdout
    try:
        return args.handler(args, fetch or _default_fetch, out)
    except (OSError, RuntimeError, ValueError) as error:
        if getattr(args, "debug", False):
            traceback.print_exc()
        else:
            sys.stderr.write(f"neezy-cli: {error}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
