"""Argparse construction for ``neezy-cli``.

One subcommand group per command family; handlers are imported from the
sibling modules. The ``common`` helper below adds the shared ``--json``
/ ``-t`` / ``-n`` flags that most read commands accept.
"""

from __future__ import annotations

import argparse

from .. import __version__
from ..ai import PROVIDERS
from ..alerts import METRICS, OPERATORS
from ..knowledge import KNOWLEDGE_PATH
from ..markets import TIMEFRAMES
from ..strategies import STRATEGIES
from .ai import cmd_ai, cmd_local_model
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
from .backtest import cmd_backtest, cmd_risk
from .common import _symbol
from .db import cmd_db, cmd_history
from .dm import cmd_dm
from .mcp import cmd_mcp
from .menu_bridge import cmd_menu
from .mt5 import cmd_mt5
from .research import cmd_brain, cmd_datasets, cmd_knowledge, cmd_research, cmd_study


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="neezy-cli",
        description="NEEZY market tools (educational analysis, not financial advice).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print full tracebacks and diagnostics for this command",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, *, timeframe=True, count=None):
        p.add_argument("--json", action="store_true", help="machine-readable output")
        if timeframe:
            p.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
        if count:
            p.add_argument(
                "-n", "--count", type=int, default=count, help="candles to fetch"
            )
        return p

    p = common(
        sub.add_parser("markets", help="list supported markets"), timeframe=False
    )
    p.add_argument(
        "--category",
        help="only this category, e.g. forex, synthetic_index, indices, commodities",
    )
    p.set_defaults(handler=cmd_markets)

    p = common(
        sub.add_parser("doctor", help="check market-data connectivity"),
        timeframe=False,
    )
    p.add_argument("--timeout", type=float, default=8.0, help="seconds per endpoint")
    p.set_defaults(handler=cmd_doctor)

    p = common(
        sub.add_parser("scan", help="rank all markets by signal strength"), count=300
    )
    p.add_argument("symbols", nargs="*", type=_symbol)
    p.set_defaults(handler=cmd_scan)

    p = common(
        sub.add_parser("analyze", help="full indicator & price-action read"), count=300
    )
    p.add_argument("symbol", type=_symbol)
    p.set_defaults(handler=cmd_analyze)

    p = common(
        sub.add_parser("backtest", help="simulate the signal engine"), count=2000
    )
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--min-score", type=int, default=2)
    p.add_argument("--stop-atr", type=float, default=1.5)
    p.add_argument("--reward-risk", type=float, default=2.0)
    p.add_argument("--spread-pips", type=float, default=0.0)
    p.add_argument("--max-bars", type=int, default=0, help="time stop (0 = off)")
    p.add_argument("--hold-through-reversals", action="store_true")
    p.add_argument("--trades", action="store_true", help="list every trade")
    p.set_defaults(handler=cmd_backtest)

    p = common(
        sub.add_parser(
            "study", help="train-then-validate backtest per instrument; saves knowledge"
        ),
        timeframe=False,
    )
    p.add_argument(
        "symbols",
        nargs="*",
        type=_symbol,
        help="markets to study (default: every catalogue instrument)",
    )
    p.add_argument("--category", help="catalogue category when no symbols are given")
    p.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="1m")
    p.add_argument("--candles", type=int, default=12_000, help="history per market")
    p.add_argument("--min-candles", type=int, default=2_000)
    p.add_argument(
        "--spread-pips",
        type=float,
        default=1.0,
        help="spread charged per trade, in pips (default 1; 0 reports pre-cost)",
    )
    p.add_argument(
        "--out",
        help=f"knowledge file to update (default: {KNOWLEDGE_PATH})",
    )
    p.add_argument("--dry-run", action="store_true", help="report without saving")
    p.set_defaults(handler=cmd_study)

    p = common(
        sub.add_parser("knowledge", help="show what the study has learned"),
        timeframe=False,
    )
    p.add_argument("symbols", nargs="*", type=_symbol)
    p.add_argument("--file", help="knowledge file (default: bundled copy)")
    p.set_defaults(handler=cmd_knowledge)

    p = sub.add_parser(
        "datasets",
        help="show the shipped knowledge datasets and learned weights",
    )
    p.add_argument("symbol", nargs="*", type=str, help="optional symbols to look up")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=cmd_datasets)

    p = common(sub.add_parser("risk", help="position size calculator"), timeframe=False)
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--balance", type=float, required=True)
    p.add_argument("--risk", type=float, default=1.0, help="percent of balance")
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float)
    p.add_argument("--direction", type=str.upper, choices=["BUY", "SELL"])
    p.add_argument("--atr", type=float, help="ATR value for an ATR-based stop")
    p.add_argument("--stop-atr", type=float, default=1.5)
    p.add_argument("--reward-risk", type=float, default=2.0)
    p.add_argument("--pip-value", type=float, default=10.0, help="per standard lot")
    p.set_defaults(handler=cmd_risk)

    p = common(sub.add_parser("correlation", help="cross-market return correlation"))
    p.add_argument("symbols", nargs="*", type=_symbol)
    p.add_argument("--window", type=int, default=100)
    p.add_argument("--top", type=int, default=8)
    p.set_defaults(handler=cmd_correlation)

    p = common(
        sub.add_parser("regime", help="trend, range, or squeeze regime and volatility"),
        count=300,
    )
    p.add_argument("symbol", type=_symbol)
    p.set_defaults(handler=cmd_regime)

    p = common(
        sub.add_parser("history", help="local signal-transition history"),
        timeframe=False,
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument("--summary", action="store_true")
    group.add_argument("--export", metavar="CSV")
    group.add_argument("--compact", type=int, metavar="KEEP")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(handler=cmd_history)

    p = common(sub.add_parser("alerts", help="manage alert rules"), timeframe=False)
    p.set_defaults(handler=cmd_alerts)
    actions = p.add_subparsers(dest="action")
    add = actions.add_parser("add")
    add.add_argument("symbol", help="market or * for all markets")
    add.add_argument("metric", choices=METRICS)
    add.add_argument("operator", choices=OPERATORS)
    add.add_argument("value")
    add.add_argument("--note")
    remove = actions.add_parser("remove")
    remove.add_argument("rule_id")
    p = common(sub.add_parser("read", help="full advanced market read"), count=300)
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--strategy", choices=sorted(STRATEGIES), default="SUPERTREND")
    p.add_argument("--period", type=int, default=10)
    p.add_argument("--multiplier", type=float, default=3.0)
    p.add_argument("--lookback", type=int, default=5)
    p.set_defaults(handler=cmd_read)

    p = common(
        sub.add_parser("supertrend", help="Supertrend line and flip state"), count=300
    )
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--period", type=int, default=10)
    p.add_argument("--multiplier", type=float, default=3.0)
    p.set_defaults(handler=cmd_supertrend)

    p = common(
        sub.add_parser("divergence", help="RSI/MACD divergence near the last swing"),
        count=300,
    )
    p.add_argument("symbol", type=_symbol)
    p.add_argument("--lookback", type=int, default=5)
    p.set_defaults(handler=cmd_divergence)

    p = common(
        sub.add_parser("corrdiv", help="correlation divergence across markets"),
        timeframe=True,
    )
    p.add_argument("symbols", nargs="*", type=_symbol)
    p.add_argument("--window", type=int, default=50)
    p.add_argument("--baseline", type=int, default=200)
    p.add_argument("--top", type=int, default=8)
    p.set_defaults(handler=cmd_corrdiv)

    p = common(
        sub.add_parser("strategies", help="list or score every strategy"), count=300
    )
    p.add_argument("symbol", nargs="?", type=_symbol)
    p.set_defaults(handler=cmd_strategies)

    p = sub.add_parser("db", help="local SQLite database tools")
    p.set_defaults(handler=cmd_db)
    db_actions = p.add_subparsers(dest="action", required=True)

    a = db_actions.add_parser("stats", help="database size and row counts")
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("signals", help="signals saved on this PC")
    a.add_argument("--limit", type=int, default=20)
    a.add_argument("--symbol", help="restrict to one market")
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("candles", help="stored candles for a market")
    a.add_argument("symbol")
    a.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
    a.add_argument("--limit", type=int, default=20)
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("save", help="fetch candles and store them locally")
    a.add_argument("symbol")
    a.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
    a.add_argument("-n", "--count", type=int, default=300)
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("export", help="export the whole database to JSON")
    a.add_argument("path")
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("prune", help="apply the retention window now")
    a.add_argument("--days", type=int)
    a.add_argument("--json", action="store_true")

    a = db_actions.add_parser("vacuum", help="reclaim disk space")
    a.add_argument("--json", action="store_true")

    p = sub.add_parser("brain", help="local neural research model tools")
    p.set_defaults(handler=cmd_brain)
    brain_actions = p.add_subparsers(dest="action", required=True)

    brain_train = brain_actions.add_parser(
        "train", help="train from stored candles with a chronological holdout"
    )
    brain_train.add_argument("symbol", type=_symbol)
    brain_train.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
    brain_train.add_argument("--limit", type=int, default=5000)
    brain_train.add_argument("--horizon", type=int, default=5)
    brain_train.add_argument("--min-samples", type=int, default=200)
    brain_train.add_argument("--json", action="store_true")

    brain_status = brain_actions.add_parser(
        "status", help="inspect a saved model and holdout metrics"
    )
    brain_status.add_argument("symbol", type=_symbol)
    brain_status.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
    brain_status.add_argument("--json", action="store_true")

    brain_predict = brain_actions.add_parser(
        "predict", help="get an advisory local prediction"
    )
    brain_predict.add_argument("symbol", type=_symbol)
    brain_predict.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
    brain_predict.add_argument("--limit", type=int, default=2000)
    brain_predict.add_argument("--json", action="store_true")

    p = sub.add_parser("ai", help="AI providers, key pools, and chat")
    p.set_defaults(handler=cmd_ai)
    ai_actions = p.add_subparsers(dest="action", required=True)

    a = ai_actions.add_parser("providers", help="list providers and key counts")
    a.add_argument("--json", action="store_true")

    a = ai_actions.add_parser("models", help="list free models for a provider")
    a.add_argument("provider", choices=sorted(PROVIDERS))
    a.add_argument("--json", action="store_true")

    keys = ai_actions.add_parser("keys", help="manage the local key pool")
    keys.add_argument("--json", action="store_true")
    key_actions = keys.add_subparsers(dest="verb")

    a = key_actions.add_parser("add", help="store another key for a provider")
    a.add_argument("provider", choices=sorted(PROVIDERS))
    a.add_argument(
        "--key", help="key value; omit to paste it hidden or use NEEZY_AI_KEY"
    )
    a.add_argument("--label", help="friendly name, e.g. 'work laptop'")

    a = key_actions.add_parser("remove", help="delete a stored key")
    a.add_argument("provider", choices=sorted(PROVIDERS))
    a.add_argument("key_id")

    a = key_actions.add_parser("reset", help="clear cooldowns and failure counters")
    a.add_argument("provider", nargs="?", choices=sorted(PROVIDERS))

    a = ai_actions.add_parser("chat", help="ask the configured provider a question")
    a.add_argument("prompt")
    a.add_argument("--provider", choices=sorted(PROVIDERS), default="openrouter")
    a.add_argument("--model", help="free model id (default: provider default)")
    a.add_argument("--temperature", type=float, default=0.3)
    a.add_argument("--max-tokens", type=int, default=700)
    a.add_argument("--timeout", type=float, default=45.0)
    a.add_argument("--symbol", help="attach live indicator context for this market")
    a.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="15m")
    a.add_argument("-n", "--count", type=int, default=300)
    a.add_argument("--json", action="store_true")

    a = ai_actions.add_parser("usage", help="recent AI calls logged locally")
    a.add_argument("--limit", type=int, default=50)
    a.add_argument("--json", action="store_true")

    a = ai_actions.add_parser("reset", help="clear every key cooldown")
    a.add_argument("--json", action="store_true")

    p = sub.add_parser("research", help="fresh public-data ML and FX-pair experiments")
    p.set_defaults(handler=cmd_research)
    actions = p.add_subparsers(dest="action", required=True)
    actions.add_parser("status", help="show bundled live-data evaluation reports")
    train = actions.add_parser(
        "train", help="fetch fresh candles and checkpoint staged ML fits"
    )
    train.add_argument("symbols", nargs="*", type=str)
    train.add_argument("--timeframe", choices=TIMEFRAMES, default="5m")
    train.add_argument("--candles", type=int, default=3000)
    train.add_argument("--epochs", type=int, default=60)
    train.add_argument("--horizon", type=int, default=5)
    train.add_argument("--seed", type=int, default=17)
    train.add_argument("--out", required=True, help="local checkpoint JSON path")

    p = sub.add_parser("local-model", help="manage offline GGUF/Transformers models")
    p.set_defaults(handler=cmd_local_model)
    local_actions = p.add_subparsers(dest="action", required=True)

    a = local_actions.add_parser("runtime", help="show optional local runtimes")
    a.add_argument("--json", action="store_true")

    a = local_actions.add_parser("list", help="list registered local models")
    a.add_argument("--json", action="store_true")

    a = local_actions.add_parser("add", help="register a GGUF file or model folder")
    a.add_argument("path", help="local model file/folder; no download or copy")
    a.add_argument("--name", help="friendly display name")
    a.add_argument("--json", action="store_true")

    a = local_actions.add_parser("remove", help="remove a model index entry only")
    a.add_argument("model_id")
    a.add_argument("--json", action="store_true")

    a = local_actions.add_parser("chat", help="prompt one registered local model")
    a.add_argument("model_id")
    a.add_argument("prompt")
    a.add_argument("--context", type=int, default=512)
    a.add_argument("--max-tokens", type=int, default=128)
    a.add_argument("--threads", type=int, default=1)
    a.add_argument("--batch-size", type=int, default=32)
    a.add_argument("--disk-offload", action="store_true")
    a.add_argument("--cpu-memory-mb", type=int, default=512)
    a.add_argument("--temperature", type=float, default=0.3)
    a.add_argument("--json", action="store_true")

    p = sub.add_parser("mt5", help="MetaTrader 5 local terminal bridge tools")
    p.set_defaults(handler=cmd_mt5)
    mt5_actions = p.add_subparsers(dest="action", required=True)
    a = mt5_actions.add_parser("status", help="check MT5 bridge status")
    a.add_argument("--json", action="store_true")
    a = mt5_actions.add_parser(
        "preflight",
        help="read-only checklist of saved MT5 settings (never sends orders)",
    )
    a.add_argument("--json", action="store_true")
    a = mt5_actions.add_parser("account", help="query MT5 account info")
    a.add_argument("--json", action="store_true")
    a = mt5_actions.add_parser("quote", help="get MT5 tick quote")
    a.add_argument("symbol", help="market symbol e.g. frxEURUSD")
    a.add_argument("--json", action="store_true")
    a = mt5_actions.add_parser("candles", help="fetch MT5 historical candles")
    a.add_argument("symbol", help="market symbol e.g. frxEURUSD")
    a.add_argument("-t", "--timeframe", choices=TIMEFRAMES, default="5m")
    a.add_argument("-n", "--count", type=int, default=100)
    a.add_argument("--json", action="store_true")
    a = mt5_actions.add_parser("order", help="place order via MT5 bridge")
    a.add_argument("symbol", help="market symbol e.g. frxEURUSD")
    a.add_argument("--type", choices=["BUY", "SELL"], required=True)
    a.add_argument("--volume", type=float, required=True)
    a.add_argument("--price", type=float, default=0.0)
    a.add_argument("--sl", type=float, default=0.0)
    a.add_argument("--tp", type=float, default=0.0)
    a.add_argument("--comment", default="NEEZY Trade")
    a.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the order without contacting MT5",
    )
    a.add_argument(
        "--confirm",
        action="store_true",
        help="required to send a live order to the MT5 terminal",
    )
    a.add_argument("--json", action="store_true")

    p = sub.add_parser("menu", help="interactive menu for cmd.exe and PowerShell")
    p.add_argument("--plain", action="store_true", help="no colour (also: NO_COLOR=1)")
    p.set_defaults(handler=cmd_menu)

    p = sub.add_parser("mcp", help="third-party MCP server catalog and configs")
    p.set_defaults(handler=cmd_mcp)
    mcp_actions = p.add_subparsers(dest="action", required=True)
    a = mcp_actions.add_parser("list", help="list known MCP servers")
    a.add_argument("--json", action="store_true")
    a = mcp_actions.add_parser("show", help="describe one MCP server")
    a.add_argument("server_id", help="e.g. mt5-ariadng or desktop-win32")
    a.add_argument("--json", action="store_true")
    a = mcp_actions.add_parser("config", help="print an MCP client config entry")
    a.add_argument("server_id", help="e.g. mt5-ariadng or desktop-win32")
    a.add_argument(
        "--unsafe",
        action="store_true",
        help="skip the read-only profile and enable every tool",
    )

    p = sub.add_parser("dm", help="direct message webhook notifications")
    p.set_defaults(handler=cmd_dm)
    dm_actions = p.add_subparsers(dest="action", required=True)
    a = dm_actions.add_parser("send", help="send webhook direct message")
    a.add_argument("url", help="webhook URL")
    a.add_argument("title", help="notification title")
    a.add_argument("message", help="notification body")
    a.add_argument("--level", choices=["info", "warning", "error"], default="info")
    a.add_argument("--json", action="store_true")

    p = common(
        sub.add_parser(
            "decision-metrics", help="trade decision matrix and risk evaluation"
        ),
        count=300,
    )
    p.set_defaults(handler=cmd_decision_metrics)
    p.add_argument("symbol", help="market symbol e.g. frxEURUSD")
    p.add_argument("--balance", type=float, default=10000.0)
    p.add_argument("--risk", type=float, default=1.0)

    return parser
