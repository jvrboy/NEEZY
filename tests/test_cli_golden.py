"""Golden-file tests for read-only CLI output (roadmap #39).

Every read-only ``neezy-cli`` command is snapshotted (plain text and ``--json``)
into ``tests/golden/<command>_<mode>.{txt,json}``.  Any drift — a renamed
column, a dropped JSON field, a reformatted number — fails the suite and forces
a conscious update:

    NEEZY_UPDATE_GOLDEN=1 python3 -m unittest tests.test_cli_golden

Determinism strategy
--------------------
* Market data: commands that fetch candles (scan, analyze, read, supertrend,
  divergence, backtest, regime, correlation, corrdiv, strategies SYMBOL,
  decision-metrics) run with ``main(argv, fetch=fake_fetch, out=io)``.
  ``fake_fetch`` builds a seeded random-walk candle series per symbol
  (``random.Random`` seeded from the house base seed 7 plus the symbol name,
  epochs anchored to a fixed base epoch), so every run sees identical data.
* Local state: ``NEEZY_HOME`` points at one fresh temp dir for the whole
  module (house pattern from tests/test_advanced.py), so the SQLite store,
  alert store, and signal history start empty and nothing writes to them.

Normalization (kept minimal on purpose)
---------------------------------------
Only values that genuinely vary between environments are rewritten before the
comparison; everything else must match byte for byte:

1. ``<NEEZY_HOME>`` — the resolved temp data dir (appears in ``db stats``
   as the database path).
2. ``<REPO>`` — the repository root (appears in ``datasets --json`` as
   ``data_dir``).
3. ``"size_bytes": <BYTES>`` / ``"size_mb": <MB>`` — SQLite database sizes
   fluctuate between opens of the same fresh file (WAL/SHM state); the counts
   and settings around them stay exact.

No ISO-timestamp rule is needed: none of the covered commands embed wall-clock
time.  ``knowledge``'s ``generated_at`` comes from the shipped
``data/knowledge.json`` and is pinned on purpose — an accidental regeneration
of the shipped knowledge base must fail this suite.

Excluded from snapshots (not read-only-snapshotable)
----------------------------------------------------
* ``doctor``, ``mt5 status/preflight/account/quote/candles`` — probe the
  network or a local MT5 terminal.
* ``ai chat`` — calls a remote provider.
* ``local-model add/chat``, ``menu``, ``dm send`` — interactive or require
  user-supplied model files / webhooks.
* Writing commands (``alerts add/remove``, ``db save/prune/vacuum/export``,
  ``study``, ``research train``, ``brain train``, ``ai keys add/remove``) are
  covered by their own tests and only snapshotted in read form here.
* ``local-model runtime`` depends on which optional inference libraries are
  installed; the fixture records the stdlib-only layout (all "not
  installed"), so installing torch & co. is a conscious update.
"""

from __future__ import annotations

import io
import json
import math
import os
import random
import re
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from neezy_backend.cli import main

#: Golden fixture directory: ``tests/golden/`` next to this module.
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

#: Repository root, replaced with ``<REPO>`` before comparing.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: Set ``NEEZY_UPDATE_GOLDEN=1`` to rewrite fixtures instead of comparing.
UPDATE_GOLDEN = os.environ.get("NEEZY_UPDATE_GOLDEN") == "1"

#: House base seed for the deterministic fake fetcher (see worklog rules).
BASE_SEED = 7

#: Fixed epoch for the first fake candle; keeps timestamps out of wall time.
BASE_EPOCH = 1_700_000_000

#: Fixtures rewritten this run (reported once from tearDownModule).
_REGENERATED: list[str] = []

_HOME: tempfile.TemporaryDirectory | None = None
_PREVIOUS_HOME: str | None = None


def setUpModule() -> None:
    """Point NEEZY_HOME at a fresh sandbox for the whole module."""
    global _HOME, _PREVIOUS_HOME
    _HOME = tempfile.TemporaryDirectory()
    _PREVIOUS_HOME = os.environ.get("NEEZY_HOME")
    os.environ["NEEZY_HOME"] = _HOME.name


def tearDownModule() -> None:
    """Restore NEEZY_HOME, drop the sandbox, and report regenerated fixtures."""
    if _PREVIOUS_HOME is None:
        os.environ.pop("NEEZY_HOME", None)
    else:
        os.environ["NEEZY_HOME"] = _PREVIOUS_HOME
    assert _HOME is not None
    _HOME.cleanup()
    if _REGENERATED:
        sys.stderr.write(
            "[golden] NEEZY_UPDATE_GOLDEN=1 rewrote "
            f"{len(_REGENERATED)} fixture(s) under {GOLDEN_DIR}\n"
        )


def _symbol_seed(symbol: str) -> int:
    """Per-symbol seed derived from the base seed and the symbol name."""
    return BASE_SEED + zlib.crc32(symbol.encode("utf-8"))


def _start_price(symbol: str) -> float:
    """A stable, plausible starting price for the symbol family."""
    if "JPY" in symbol:
        return 150.0
    if symbol.startswith("R_"):
        return 1000.0
    return 1.1


def fake_fetch(symbol: str, seconds: int, count: int):
    """Deterministic fetcher stand-in used by every market-data command.

    Builds ``count`` valid OHLC candles as a seeded random walk: the RNG is
    seeded from the base seed plus the symbol name, epochs start at a fixed
    base and step by the requested granularity, and prices stay positive.
    The same ``(symbol, seconds, count)`` request always returns the exact
    same series, in any process, on any platform.
    """
    rng = random.Random(_symbol_seed(symbol))
    start = _start_price(symbol)
    drift, sigma, wick = start * 2e-4, start * 4e-4, start * 2e-4
    step = max(int(seconds), 60)
    candles: list[tuple[int, float, float, float, float]] = []
    previous = start
    for index in range(int(count)):
        close = max(0.05, previous + drift + rng.gauss(0.0, sigma))
        high = max(previous, close) + abs(rng.gauss(0.0, wick))
        low = max(0.01, min(previous, close) - abs(rng.gauss(0.0, wick)))
        candles.append((BASE_EPOCH + index * step, previous, high, low, close))
        previous = close
    return candles


def _normalize(text: str) -> str:
    """Rewrite only the values that genuinely vary between environments.

    Rules (see the module docstring for the rationale):
    1. the resolved NEEZY_HOME sandbox -> ``<NEEZY_HOME>``
    2. the repository root -> ``<REPO>``
    3. SQLite ``size_bytes``/``size_mb`` -> ``<BYTES>``/``<MB>`` placeholders
    """
    home = os.environ.get("NEEZY_HOME", "")
    if home:
        text = text.replace(str(Path(home).resolve()), "<NEEZY_HOME>")
    text = text.replace(str(REPO_ROOT), "<REPO>")
    text = re.sub(r'"size_bytes": \d+', '"size_bytes": <BYTES>', text)
    text = re.sub(r'"size_mb": [0-9.]+', '"size_mb": <MB>', text)
    return text


def _first_json_difference(actual: object, expected: object, path: str = "$") -> str:
    """Human-readable path of the first difference between two JSON trees."""
    if isinstance(actual, dict) and isinstance(expected, dict):
        for key in sorted(set(actual) | set(expected)):
            if key not in actual or key not in expected:
                return f"{path}.{key} (missing on one side)"
            detail = _first_json_difference(actual[key], expected[key], f"{path}.{key}")
            if detail:
                return detail
        return ""
    if isinstance(actual, list) and isinstance(expected, list):
        if len(actual) != len(expected):
            return f"{path} (list length {len(actual)} != {len(expected)})"
        for index, (a, e) in enumerate(zip(actual, expected, strict=False)):
            detail = _first_json_difference(a, e, f"{path}[{index}]")
            if detail:
                return detail
        return ""
    if isinstance(actual, bool) or isinstance(expected, bool):
        return "" if actual == expected else f"{path}: {actual!r} != {expected!r}"
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        same = math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12)
        return "" if same else f"{path}: {actual!r} != {expected!r}"
    return "" if actual == expected else f"{path}: {actual!r} != {expected!r}"


def _assert_matches_snapshot(
    test: unittest.TestCase,
    actual: str,
    expected: str,
    argv: list[str],
    fixture: Path,
) -> None:
    """Compare snapshot text; JSON gets float tolerance, everything else exact.

    Python 3.10/3.11/3.12 can differ in the last one or two ULPs of
    statistics-based floats (for example the correlation matrix), so parsed
    JSON documents compare numerically with ``math.isclose`` while structure
    and strings stay exact. Documents that are not parseable JSON (after
    placeholder normalization) fall back to byte-exact comparison.
    """
    message = (
        f"output of 'neezy-cli {' '.join(argv)}' no longer matches golden "
        f"fixture {fixture}.\nIf this change is intentional, regenerate "
        f"with:\n  NEEZY_UPDATE_GOLDEN=1 "
        f"python3 -m unittest tests.test_cli_golden"
    )
    try:
        actual_json = json.loads(actual)
        expected_json = json.loads(expected)
    except (json.JSONDecodeError, ValueError):
        test.assertEqual(actual, expected, message)
        return
    difference = _first_json_difference(actual_json, expected_json)
    if difference:
        test.fail(f"{message}\nfirst difference at {difference}")


class GoldenCliTests(unittest.TestCase):
    """Snapshot the output of every read-only CLI command."""

    maxDiff = None

    def run_cli(self, *argv: str) -> str:
        """Run ``main`` with the deterministic fetcher; return stdout text."""
        out = io.StringIO()
        code = main(list(argv), fetch=fake_fetch, out=out)
        self.assertEqual(
            code,
            0,
            f"expected exit 0 from {' '.join(argv)!r}, got {code}",
        )
        return out.getvalue()

    def assert_snapshot(self, fixture_name: str, argv: list[str]) -> None:
        """Compare a command's normalized output with tests/golden/<name>.

        With ``NEEZY_UPDATE_GOLDEN=1`` the fixture is (re)written instead and
        the test passes — the standard snapshot-test update flow.
        """
        fixture = GOLDEN_DIR / fixture_name
        actual = _normalize(self.run_cli(*argv))
        if UPDATE_GOLDEN:
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_text(actual, encoding="utf-8")
            _REGENERATED.append(fixture_name)
            return
        try:
            expected = fixture.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.fail(
                f"golden fixture {fixture} is missing; create it with "
                f"NEEZY_UPDATE_GOLDEN=1 python3 -m unittest tests.test_cli_golden"
            )
        _assert_matches_snapshot(self, actual, expected, argv, fixture)

    # ------------------------------------------------------------------
    # Static catalogue commands (no fetch, no local state)
    # ------------------------------------------------------------------

    def test_markets_plain_and_json(self) -> None:
        self.assert_snapshot("markets_plain.txt", ["markets"])
        self.assert_snapshot("markets_json.json", ["markets", "--json"])

    def test_datasets_plain_and_json(self) -> None:
        self.assert_snapshot("datasets_plain.txt", ["datasets"])
        self.assert_snapshot("datasets_json.json", ["datasets", "--json"])

    def test_knowledge_plain_and_json(self) -> None:
        self.assert_snapshot("knowledge_plain.txt", ["knowledge"])
        self.assert_snapshot("knowledge_json.json", ["knowledge", "--json"])

    def test_strategies_catalogue_plain_and_json(self) -> None:
        self.assert_snapshot("strategies_plain.txt", ["strategies"])
        self.assert_snapshot("strategies_json.json", ["strategies", "--json"])

    def test_mcp_list_plain_and_json(self) -> None:
        self.assert_snapshot("mcp_list_plain.txt", ["mcp", "list"])
        self.assert_snapshot("mcp_list_json.json", ["mcp", "list", "--json"])

    def test_mcp_show_plain_and_json(self) -> None:
        self.assert_snapshot("mcp_show_plain.txt", ["mcp", "show", "desktop-win32"])
        self.assert_snapshot(
            "mcp_show_json.json", ["mcp", "show", "desktop-win32", "--json"]
        )

    def test_mcp_config_json_safe_profile(self) -> None:
        # Warnings go to stderr; keep them out of the test log and out of the
        # snapshot, which only covers stdout.
        with mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assert_snapshot(
                "mcp_config_json.json", ["mcp", "config", "desktop-win32"]
            )

    def test_ai_providers_plain_and_json(self) -> None:
        self.assert_snapshot("ai_providers_plain.txt", ["ai", "providers"])
        self.assert_snapshot("ai_providers_json.json", ["ai", "providers", "--json"])

    def test_ai_models_plain_and_json(self) -> None:
        # ``ai models`` reads the static provider catalogue, no network call.
        self.assert_snapshot("ai_models_plain.txt", ["ai", "models", "openrouter"])
        self.assert_snapshot(
            "ai_models_json.json", ["ai", "models", "openrouter", "--json"]
        )

    def test_local_model_runtime_plain_and_json(self) -> None:
        self.assert_snapshot(
            "local_model_runtime_plain.txt", ["local-model", "runtime"]
        )
        self.assert_snapshot(
            "local_model_runtime_json.json", ["local-model", "runtime", "--json"]
        )

    # ------------------------------------------------------------------
    # Local-state commands on the empty module sandbox
    # ------------------------------------------------------------------

    def test_history_summary_json_empty_store(self) -> None:
        self.assert_snapshot(
            "history_summary_json.json", ["history", "--summary", "--json"]
        )

    def test_alerts_plain_and_json_empty_store(self) -> None:
        self.assert_snapshot("alerts_plain.txt", ["alerts"])
        self.assert_snapshot("alerts_json.json", ["alerts", "--json"])

    def test_db_stats_json(self) -> None:
        self.assert_snapshot("db_stats_json.json", ["db", "stats", "--json"])

    def test_db_signals_json_empty(self) -> None:
        self.assert_snapshot("db_signals_json.json", ["db", "signals", "--json"])

    # ------------------------------------------------------------------
    # Fetch-driven analysis commands (deterministic fake fetcher)
    # ------------------------------------------------------------------

    def test_scan_plain_and_json_default_watchlist(self) -> None:
        self.assert_snapshot("scan_plain.txt", ["scan"])
        self.assert_snapshot("scan_json.json", ["scan", "--json"])

    def test_analyze_plain_and_json(self) -> None:
        self.assert_snapshot("analyze_plain.txt", ["analyze", "frxEURUSD"])
        self.assert_snapshot("analyze_json.json", ["analyze", "frxEURUSD", "--json"])

    def test_regime_plain_and_json(self) -> None:
        self.assert_snapshot("regime_plain.txt", ["regime", "frxEURUSD"])
        self.assert_snapshot("regime_json.json", ["regime", "frxEURUSD", "--json"])

    def test_read_plain_and_json(self) -> None:
        self.assert_snapshot("read_plain.txt", ["read", "frxEURUSD"])
        self.assert_snapshot("read_json.json", ["read", "frxEURUSD", "--json"])

    def test_supertrend_plain_and_json(self) -> None:
        self.assert_snapshot("supertrend_plain.txt", ["supertrend", "frxEURUSD"])
        self.assert_snapshot(
            "supertrend_json.json", ["supertrend", "frxEURUSD", "--json"]
        )

    def test_divergence_plain_and_json(self) -> None:
        self.assert_snapshot("divergence_plain.txt", ["divergence", "frxEURUSD"])
        self.assert_snapshot(
            "divergence_json.json", ["divergence", "frxEURUSD", "--json"]
        )

    def test_strategies_symbol_plain_and_json(self) -> None:
        self.assert_snapshot("strategies_symbol_plain.txt", ["strategies", "frxEURUSD"])
        self.assert_snapshot(
            "strategies_symbol_json.json", ["strategies", "frxEURUSD", "--json"]
        )

    # Backtest is the one heavyweight command (~2s per snapshot at the default
    # 2000 candles), so plain and JSON get separate tests to stay well inside
    # the per-test time budget.
    def test_backtest_plain(self) -> None:
        self.assert_snapshot("backtest_plain.txt", ["backtest", "frxEURUSD"])

    def test_backtest_json(self) -> None:
        self.assert_snapshot("backtest_json.json", ["backtest", "frxEURUSD", "--json"])

    def test_correlation_plain_and_json_default_watchlist(self) -> None:
        self.assert_snapshot("correlation_plain.txt", ["correlation"])
        self.assert_snapshot("correlation_json.json", ["correlation", "--json"])

    def test_corrdiv_plain_and_json(self) -> None:
        argv = ["corrdiv", "EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "R_100"]
        self.assert_snapshot("corrdiv_plain.txt", argv)
        self.assert_snapshot("corrdiv_json.json", [*argv, "--json"])

    def test_decision_metrics_plain_and_json(self) -> None:
        self.assert_snapshot(
            "decision_metrics_plain.txt", ["decision-metrics", "frxEURUSD"]
        )
        self.assert_snapshot(
            "decision_metrics_json.json", ["decision-metrics", "frxEURUSD", "--json"]
        )

    def test_risk_plain_and_json(self) -> None:
        argv = [
            "risk",
            "EURUSD",
            "--balance",
            "10000",
            "--entry",
            "1.1",
            "--stop",
            "1.095",
        ]
        self.assert_snapshot("risk_plain.txt", argv)
        self.assert_snapshot("risk_json.json", [*argv, "--json"])


if __name__ == "__main__":
    unittest.main()
