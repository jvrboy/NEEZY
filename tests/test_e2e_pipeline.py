"""End-to-end offline scenario test for the deterministic signal pipeline.

Roadmap #40: one scripted session exercises the whole chain with fakes and no
network — synthetic candles → stream validation (``parse_candle``) → indicator
analysis (``analyze``) → confluence aggregation (``scan_candles``) → market
snapshot (``market_snapshot``) → user alert rules (``AlertEngine``) → local
persistence (``ConfluenceHistoryStore``) → outcome resolution
(``confluence.resolve_outcome`` + ``outcomes.evaluate_outcomes``) → CLI wiring
(``neezy_backend.cli.main`` with an injected fetcher).

Scenario design (all values below were verified against the real engine, not
invented):

- A seeded ``random.Random(20240)`` generator produces 300 five-minute EUR/USD
  candles: a steady +0.0009/bar uptrend for 140 bars, then a steady downtrend
  for 160 bars, with seeded wick noise. Closes therefore rise strictly through
  bar 139 and fall strictly afterwards.
- Early analysis point (bar 138, still inside the uptrend): the engine reads
  ``BUY`` with score +2 and RSI pinned at 100.0; confluence direction is +1
  (strict mode, score 62.1).
- Late analysis point (bar 280, deep in the downtrend): the engine reads
  ``SELL`` with score -2 and RSI ~0.0031; confluence direction is -1 (strict
  mode, score 72.6). The engine's direction genuinely flips mid-session.
- Alert rule ``rsi > 70`` fires exactly once: RSI sits at 100 for every
  checkpoint of the uptrend and decays below 70 once the downtrend starts, so
  the edge-triggered engine fires on the first uptrend analysis and never
  again.
- Outcomes: the pre-flip BUY is stopped out when the reversal drops through
  its ATR stop six bars later (``SL``); the post-flip SELL hits its ATR target
  three bars later (``TP``). ``evaluate_outcomes`` agrees directionally
  (-0.4484% vs +0.8333% close-to-close).

Pinned deviations from the task's scenario sketch (reality wins):

- ``outcomes.evaluate_outcomes`` never inspects stop/target levels; it scores
  close-to-close returns over a horizon. The stop/target resolver with the
  "stop fills first inside one candle" rule is
  ``confluence.resolve_outcome`` — which is also what the app's own signals
  panel feeds into ``ConfluenceHistoryStore.update_outcomes``. Both resolvers
  are exercised here: ``resolve_outcome`` produces the stored TP/SL,
  ``evaluate_outcomes`` cross-checks the return direction.
- ``ConfluenceHistoryStore`` records use ``timestamp``/``entry`` keys while
  ``evaluate_outcomes`` consumes DB signal rows with ``created_at``/``price``;
  the test bridges the two shapes the same way the app's MCP outcome report
  adapts ``recent_signals`` rows.
- ``ConfluenceSignal.created_at`` is wall-clock time, but the synthetic
  epochs are decoupled from the wall clock, so the test rewrites
  ``created_at`` to the session timeline (via ``dataclasses.replace``) before
  persisting. The app's own UI keys outcomes off exactly this timestamp, so
  the rewrite keeps the offline session faithful to the real flow.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
import random
import tempfile
import unittest
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from unittest import mock

from neezy_backend.alerts import AlertEngine, AlertRule, AlertRuleStore
from neezy_backend.cli import main as cli_main
from neezy_backend.confluence import resolve_outcome, scan_candles
from neezy_backend.context import market_snapshot
from neezy_backend.indicators import analyze
from neezy_backend.markets import granularity
from neezy_backend.outcomes import evaluate_outcomes
from neezy_backend.storage import ConfluenceHistoryStore
from neezy_backend.stream import parse_candle, parse_history_response

SYMBOL = "frxEURUSD"
TIMEFRAME = "5m"
GRANULARITY = granularity(TIMEFRAME)
START_EPOCH = 1_700_000_000
SESSION_SEED = 20240
UP_BARS = 140
DOWN_BARS = 160
START_PRICE = 1.0800
TREND_STEP = 0.0009
EARLY_POINT = 138  # bars fed to the engine at the pre-flip analysis
LATE_POINT = 280  # bars fed to the engine at the post-flip analysis
ALERT_RSI_THRESHOLD = "70"


def build_session() -> list[tuple[int, float, float, float, float]]:
    """Deterministic OHLC session: steady uptrend, then steady downtrend.

    ``random.Random(SESSION_SEED)`` drives only the wick sizes, so the close
    path is exactly +``TREND_STEP`` per bar for the first ``UP_BARS`` bars and
    -``TREND_STEP`` afterwards. Highs/lows always bracket the open/close pair,
    which keeps every row valid for ``parse_candle``.
    """
    rng = random.Random(SESSION_SEED)
    candles: list[tuple[int, float, float, float, float]] = []
    price = START_PRICE
    for index in range(UP_BARS + DOWN_BARS):
        drift = TREND_STEP if index < UP_BARS else -TREND_STEP
        open_ = price
        close = price + drift
        high = max(open_, close) + rng.uniform(0.0001, 0.0004)
        low = min(open_, close) - rng.uniform(0.0001, 0.0004)
        candles.append((START_EPOCH + index * GRANULARITY, open_, high, low, close))
        price = close
    return candles


def _wire_row(candle: tuple[int, float, float, float, float]) -> dict[str, object]:
    """Render one candle as the Deriv wire shape ``parse_candle`` consumes."""
    epoch, open_, high, low, close = candle
    return {"epoch": epoch, "open": open_, "high": high, "low": low, "close": close}


def _iso(epoch: int) -> str:
    """Session-timeline ISO stamp for one candle epoch (aware UTC)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _signal_epoch(point: int) -> int:
    """Epoch when the analysis at ``point`` became actionable.

    The window ``session[:point + 1]`` treats bar ``point`` as in-progress, so
    the signal is keyed to the close of bar ``point - 1``, i.e. the open of
    bar ``point``. This is the boundary the app's signals panel uses to select
    "candles after the signal" (rows with ``epoch >= signal epoch``).
    """
    return START_EPOCH + point * GRANULARITY


def _outcome_rows(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Bridge confluence history records into ``evaluate_outcomes`` rows.

    The card history persists ``timestamp``/``entry`` while the outcome
    evaluator consumes DB signal rows with ``created_at``/``price`` (the same
    shape ``LocalDatabase.recent_signals`` returns and the MCP outcome report
    feeds to ``evaluate_outcomes``). The mapping is mechanical.
    """
    return [
        {
            "id": index,
            "symbol": record["symbol"],
            "direction": record["direction"],
            "price": record["entry"],
            "created_at": record["timestamp"],
        }
        for index, record in enumerate(records, start=1)
    ]


class E2EPipelineTests(unittest.TestCase):
    """One scripted offline session through every stage of the pipeline."""

    def setUp(self) -> None:
        """Fresh deterministic session and an isolated NEEZY_HOME."""
        self.session = build_session()
        self.early_window = self.session[: EARLY_POINT + 1]
        self.late_window = self.session[: LATE_POINT + 1]
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = Path(home.name)
        env = mock.patch.dict(os.environ, {"NEEZY_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    # ------------------------------------------------------------- stage 1

    def test_stage1_generator_is_deterministic_trend_then_reversal(self) -> None:
        """The synthetic feed is reproducible and shaped as trend → reversal.

        Pins: same seed rebuilds the byte-identical series; epochs are strictly
        increasing five-minute steps; closes rise strictly through bar 139 and
        fall strictly afterwards; every bar's OHLC is internally consistent
        (high ≥ max(open, close), low ≤ min(open, close), positive, finite).
        """
        self.assertEqual(build_session(), self.session)
        self.assertEqual(len(self.session), UP_BARS + DOWN_BARS)
        for index, candle in enumerate(self.session):
            epoch, open_, high, low, close = candle
            self.assertEqual(epoch, START_EPOCH + index * GRANULARITY)
            self.assertGreater(high, 0.0)
            self.assertGreater(low, 0.0)
            self.assertGreaterEqual(high, max(open_, close))
            self.assertLessEqual(low, min(open_, close))
            self.assertGreaterEqual(high, low)
        closes = [row[4] for row in self.session]
        self.assertEqual(closes.index(max(closes)), UP_BARS - 1)
        for before, after in pairwise(closes[:UP_BARS]):
            self.assertGreater(after, before)
        for before, after in pairwise(closes[UP_BARS - 1 :]):
            self.assertLess(after, before)
        self.assertAlmostEqual(closes[0], START_PRICE + TREND_STEP, places=12)
        expected_last = START_PRICE - (DOWN_BARS - UP_BARS) * TREND_STEP
        self.assertAlmostEqual(closes[-1], expected_last, places=9)

    # ------------------------------------------------------------- stage 2

    def test_stage2_stream_validation_accepts_session_and_rejects_corrupt_rows(
        self,
    ) -> None:
        """Stream-level validation: good rows pass, corrupt rows are rejected.

        Every session row survives ``parse_candle`` unchanged. Corrupt wire
        rows (inverted highs/lows, non-positive, NaN, infinity, non-numeric
        epoch, missing OHLC keys) all raise ``ValueError`` — the parser was
        hardened (roadmap #38) so the websocket boundary never escapes with
        an arbitrary ``KeyError``/``TypeError``.
        ``parse_history_response`` is all-or-nothing: one corrupt candle fails
        the whole payload.
        """
        wire = [_wire_row(candle) for candle in self.session]
        parsed = [parse_candle(row) for row in wire]
        self.assertEqual(parsed, self.session)
        self.assertEqual(parsed[0][0], START_EPOCH)

        good = wire[100]
        corrupt: dict[str, dict[str, object]] = {
            "high below low": {**good, "high": 1.0, "low": 2.0},
            "high below close": {**good, "high": good["open"], "close": good["high"]},
            "low above open": {**good, "low": good["high"], "open": good["low"]},
            "zero price": {**good, "close": 0.0},
            "negative price": {**good, "open": -1.08},
            "nan high": {**good, "high": float("nan")},
            "infinite low": {**good, "low": float("inf")},
            "non-numeric epoch": {**good, "epoch": "not-a-number"},
        }
        for label, row in corrupt.items():
            with self.subTest(corrupt=label):
                with self.assertRaises(ValueError):
                    parse_candle(row)
        with self.assertRaises(ValueError):
            parse_candle({"epoch": 1, "open": 1.0, "high": 1.1, "low": 0.9})

        clean_payload = {"candles": wire[:3]}
        self.assertEqual(parse_history_response(clean_payload), self.session[:3])
        with self.assertRaises(ValueError):
            parse_history_response(
                {"candles": [wire[0], corrupt["high below low"], wire[1]]}
            )

    # ------------------------------------------------------------- stage 3

    def test_stage3a_indicator_engine_flips_buy_to_sell(self) -> None:
        """``analyze`` flips from BUY (score +2) to SELL (score -2).

        Early window (139 rows, 138 closed): signal BUY, score +2, RSI exactly
        100.0 (steady gains pin Wilder RSI at its ceiling — overbought, which
        *subtracts* from the score), Bullish trend, Trending regime, positive
        MACD histogram. Late window (281 rows, 280 closed): signal SELL, score
        -2, RSI ≈ 0.0031, Bearish trend. The direction genuinely flips.
        """
        early = analyze(self.early_window)
        late = analyze(self.late_window)
        self.assertIsNotNone(early)
        self.assertIsNotNone(late)

        self.assertEqual(early["signal"], "BUY")
        self.assertEqual(early["score"], 2)
        self.assertEqual(early["rsi"], 100.0)
        self.assertEqual(early["trend"], "Bullish")
        self.assertEqual(early["regime"], "Trending")
        self.assertEqual(early["closed_candles"], EARLY_POINT)
        self.assertGreater(early["macd_histogram"], 0.0)
        self.assertGreater(early["adx"]["plus_di"], early["adx"]["minus_di"])
        self.assertIn("RSI 100.0 overbought", early["why"])

        self.assertEqual(late["signal"], "SELL")
        self.assertEqual(late["score"], -2)
        self.assertAlmostEqual(late["rsi"], 0.003120, places=6)
        self.assertEqual(late["trend"], "Bearish")
        self.assertEqual(late["regime"], "Trending")
        self.assertEqual(late["closed_candles"], LATE_POINT)
        self.assertLess(late["macd_histogram"], 0.0)
        self.assertGreater(late["adx"]["minus_di"], late["adx"]["plus_di"])
        self.assertIn("RSI 0.0 oversold", late["why"])

        self.assertNotEqual(early["signal"], late["signal"])
        self.assertGreater(early["score"], 0)
        self.assertLess(late["score"], 0)

    def test_stage3b_confluence_and_snapshot_flip(self) -> None:
        """Confluence aggregation and the shared snapshot flip with the engine.

        ``scan_candles`` returns exactly one strict-mode signal per window with
        direction +1 (score ≈ 62.1, BUY votes 8/3) before the flip and -1
        (score ≈ 72.6, SELL votes 2/9) after it. ``market_snapshot`` — the
        shared read used by the UI, CLI and AI prompts — carries the same
        signal, score, price and SUPERTREND verdict on the same windows.
        """
        early_signals = scan_candles({SYMBOL: self.early_window}, TIMEFRAME)
        late_signals = scan_candles({SYMBOL: self.late_window}, TIMEFRAME)
        self.assertEqual(len(early_signals), 1)
        self.assertEqual(len(late_signals), 1)
        early, late = early_signals[0], late_signals[0]

        self.assertEqual(early.direction, 1)
        self.assertEqual(early.label, "BUY")
        self.assertEqual(early.mode, "strict")
        self.assertAlmostEqual(early.score, 62.105, places=3)
        self.assertAlmostEqual(early.entry, 1.2042, places=9)
        self.assertLess(early.stop_loss, early.entry)
        self.assertGreater(early.take_profit, early.entry)
        self.assertEqual(early.votes, {"buy": 8, "sell": 3, "neutral": 0})

        self.assertEqual(late.direction, -1)
        self.assertEqual(late.label, "SELL")
        self.assertEqual(late.mode, "strict")
        self.assertAlmostEqual(late.score, 72.632, places=3)
        self.assertAlmostEqual(late.entry, 1.0800, places=9)
        self.assertGreater(late.stop_loss, late.entry)
        self.assertLess(late.take_profit, late.entry)
        self.assertEqual(late.votes, {"buy": 2, "sell": 9, "neutral": 0})

        early_snapshot = market_snapshot(
            self.early_window, symbol=SYMBOL, timeframe=TIMEFRAME
        )
        late_snapshot = market_snapshot(
            self.late_window, symbol=SYMBOL, timeframe=TIMEFRAME
        )
        self.assertEqual(early_snapshot["signal"], "BUY")
        self.assertEqual(late_snapshot["signal"], "SELL")
        self.assertEqual(early_snapshot["score"], 2)
        self.assertEqual(late_snapshot["score"], -2)
        self.assertEqual(early_snapshot["consensus"]["direction"], 1)
        self.assertEqual(late_snapshot["consensus"]["direction"], -1)
        self.assertEqual(early_snapshot["strategy"]["label"], "BUY")
        self.assertEqual(late_snapshot["strategy"]["label"], "SELL")
        self.assertAlmostEqual(early_snapshot["price"], early.entry, places=12)
        self.assertAlmostEqual(late_snapshot["price"], late.entry, places=12)
        self.assertEqual(early_snapshot["candles"], EARLY_POINT)
        self.assertEqual(late_snapshot["candles"], LATE_POINT)

    # ------------------------------------------------------------- stage 4

    def test_stage4_alert_rule_fires_exactly_once_at_the_flip(self) -> None:
        """The registered RSI rule fires once, on the uptrend, never after.

        ``rsi > 70`` goes active on the very first analysable checkpoint of
        the uptrend (RSI is pinned at 100 from bar 14 on) and stays active
        through the trend; once the downtrend takes over RSI never returns
        above 70, so the edge-triggered engine fires exactly once. Re-feeding
        the early analysis does not re-fire, and the late analysis alone never
        activates the rule. Pinned reality: a *fresh* engine that sees the late
        analysis first and the early one second fires once on that transition
        too — edge-triggering keys on the rule *becoming* true, so an engine
        with no memory of the uptrend treats 0.003 → 100 as a fresh
        activation. The rule round-trips through ``AlertRuleStore`` in the
        isolated NEEZY_HOME before evaluation.
        """
        rule = AlertRule(
            symbol=SYMBOL,
            metric="rsi",
            operator=">",
            value=ALERT_RSI_THRESHOLD,
            note="e2e once-only overbought alert",
        )
        store = AlertRuleStore()
        self.assertEqual(store.path, self.home / "alert-rules.json")
        store.save([rule])
        loaded = store.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].describe(), rule.describe())
        self.assertTrue(loaded[0].enabled)

        engine = AlertEngine(loaded)
        firings: list[int] = []
        for rows in range(61, len(self.session) + 1, 10):
            analysis = analyze(self.session[:rows])
            if analysis is None:
                continue
            fired = engine.evaluate(
                SYMBOL, analysis, self.session[rows - 1][4], patterns=[]
            )
            if fired:
                firings.append(rows)
        self.assertEqual(firings, [61])

        early = analyze(self.early_window)
        late = analyze(self.late_window)
        fresh = AlertEngine([rule])
        first = fresh.evaluate(SYMBOL, early, early["closes"][-1])
        self.assertEqual([item.describe() for item in first], [rule.describe()])
        self.assertEqual(fresh.evaluate(SYMBOL, early, early["closes"][-1]), [])
        self.assertEqual(fresh.evaluate(SYMBOL, late, late["closes"][-1]), [])
        reverse = AlertEngine([rule])
        self.assertEqual(reverse.evaluate(SYMBOL, late, late["closes"][-1]), [])
        reactivated = reverse.evaluate(SYMBOL, early, early["closes"][-1])
        self.assertEqual([item.describe() for item in reactivated], [rule.describe()])
        self.assertEqual(reverse.evaluate(SYMBOL, early, early["closes"][-1]), [])

    # ------------------------------------------------------------- stage 5

    def _recorded_session(
        self,
    ) -> tuple[ConfluenceHistoryStore, list[dict[str, object]]]:
        """Persist the early/late signals; return the store and its records.

        Mirrors the app's ANALYSIS-button flow: ``scan_candles`` produces the
        cards, ``created_at`` is stamped on the session timeline (see the
        module docstring for why the wall-clock stamp is rewritten offline),
        and ``ConfluenceHistoryStore.append_signal`` writes the JSONL records
        under the isolated NEEZY_HOME.
        """
        signals = []
        windows = ((EARLY_POINT, self.early_window), (LATE_POINT, self.late_window))
        for point, window in windows:
            (signal,) = scan_candles({SYMBOL: window}, TIMEFRAME)
            signals.append(
                dataclasses.replace(signal, created_at=_iso(_signal_epoch(point)))
            )
        store = ConfluenceHistoryStore()
        for signal in signals:
            store.append_signal(signal)
        return store, store.read()

    def test_stage5a_confluence_history_roundtrip_in_neezy_home(self) -> None:
        """Signals persist to the card history and read back intact.

        Both session signals land in ``confluence-history.jsonl`` inside the
        temp NEEZY_HOME with ``outcome`` still open (``None``). The typed
        read-back preserves symbol, timeframe, direction, entry, stop, target
        and the session-timeline timestamp.
        """
        store, records = self._recorded_session()
        self.assertEqual(store.path, self.home / "confluence-history.jsonl")
        self.assertTrue(store.path.is_file())
        self.assertEqual(len(records), 2)

        early_record, late_record = records
        self.assertIsNone(early_record["outcome"])
        self.assertIsNone(late_record["outcome"])
        self.assertEqual(early_record["symbol"], SYMBOL)
        self.assertEqual(early_record["timeframe"], TIMEFRAME)
        self.assertEqual(early_record["direction"], 1)
        self.assertEqual(late_record["direction"], -1)
        self.assertAlmostEqual(early_record["entry"], 1.2042, places=9)
        self.assertAlmostEqual(late_record["entry"], 1.0800, places=9)

        typed = store.read_signals()
        self.assertEqual([signal.direction for signal in typed], [1, -1])
        self.assertEqual(
            [signal.created_at for signal in typed],
            [_iso(_signal_epoch(EARLY_POINT)), _iso(_signal_epoch(LATE_POINT))],
        )
        self.assertAlmostEqual(typed[0].stop_loss, early_record["stop_loss"], places=12)
        self.assertAlmostEqual(
            typed[0].take_profit, early_record["take_profit"], places=12
        )

    def test_stage5b_outcomes_resolve_and_persist(self) -> None:
        """Outcome resolution: pre-flip BUY → SL, post-flip SELL → TP.

        The reversal drops through the early BUY's ATR stop six bars after the
        signal; the late SELL reaches its ATR target three bars in. A candle
        that spans both levels resolves to ``SL`` (stop fills first — the
        resolver's documented conservative rule). ``evaluate_outcomes``
        cross-checks direction close-to-close: the BUY loses ≈ -0.4484%, the
        SELL gains ≈ +0.8333%. ``update_outcomes`` persists both cards'
        outcomes and is idempotent on re-runs.
        """
        store, records = self._recorded_session()
        early_record, late_record = records

        # Same selection the app's signals panel uses: closed candles whose
        # epoch is at or after the signal timestamp.
        after_early = [
            row for row in self.session if row[0] >= _signal_epoch(EARLY_POINT)
        ]
        after_late = [
            row for row in self.session if row[0] >= _signal_epoch(LATE_POINT)
        ]
        early_outcome = resolve_outcome(
            int(early_record["direction"]),
            float(early_record["entry"]),
            float(early_record["stop_loss"]),
            float(early_record["take_profit"]),
            after_early,
        )
        late_outcome = resolve_outcome(
            int(late_record["direction"]),
            float(late_record["entry"]),
            float(late_record["stop_loss"]),
            float(late_record["take_profit"]),
            after_late,
        )
        self.assertEqual(early_outcome, "SL")
        self.assertEqual(late_outcome, "TP")

        both_inside = [(START_EPOCH, 100.0, 102.0, 98.0, 101.0)]
        self.assertEqual(
            resolve_outcome(1, 100.0, 99.0, 101.0, both_inside, horizon=1), "SL"
        )

        rows = _outcome_rows(records)
        outcomes = evaluate_outcomes(rows, self.session, horizon=10)
        self.assertEqual([outcome.signal_id for outcome in outcomes], [1, 2])
        self.assertAlmostEqual(outcomes[0].return_pct, -0.4484, places=4)
        self.assertAlmostEqual(outcomes[1].return_pct, 0.8333, places=4)
        self.assertFalse(outcomes[0].hit)
        self.assertTrue(outcomes[1].hit)
        self.assertAlmostEqual(outcomes[0].exit, 1.1988, places=6)
        self.assertAlmostEqual(outcomes[1].exit, 1.0710, places=6)

        changed = store.update_outcomes(
            {
                (str(early_record["symbol"]), str(early_record["timestamp"])): "SL",
                (str(late_record["symbol"]), str(late_record["timestamp"])): "TP",
            }
        )
        self.assertEqual(changed, 2)
        stored = store.read()
        self.assertEqual([record["outcome"] for record in stored], ["SL", "TP"])
        again = store.update_outcomes(
            {(str(early_record["symbol"]), str(early_record["timestamp"])): "SL"}
        )
        self.assertEqual(again, 0)

    # ------------------------------------------------------------- stage 6

    def _fake_fetch(self, symbol: str, seconds: int, count: int):
        """Injectable CLI fetcher: asserts the wiring, replays the session.

        The CLI must ask for the requested symbol at the 5-minute granularity
        with its default 300-candle count; the fetcher answers with the late
        analysis window so the CLI's JSON is directly comparable with stage 3.
        """
        self.assertEqual(symbol, SYMBOL)
        self.assertEqual(seconds, GRANULARITY)
        self.assertEqual(count, 300)
        return self.late_window

    def test_stage6_cli_analyze_json_uses_same_engine_and_data(self) -> None:
        """``cli main analyze --json`` drives the same engine on the same feed.

        The injected fetcher serves the late window; the CLI's payload must
        equal the stage-3a analysis dict exactly (minus the ``closes`` series
        the CLI strips for JSON) and carry the price-action block, proving the
        argument parsing, fetch injection, analysis and JSON emission layers
        are wired to the identical deterministic pipeline.
        """
        out = io.StringIO()
        code = cli_main(["analyze", SYMBOL, "--json"], fetch=self._fake_fetch, out=out)
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(set(payload), {"analysis", "price_action"})

        expected = analyze(self.late_window)
        assert expected is not None  # pinned by stage 3a
        self.assertEqual(
            payload["analysis"],
            {key: value for key, value in expected.items() if key != "closes"},
        )
        self.assertEqual(payload["analysis"]["signal"], "SELL")
        self.assertEqual(payload["analysis"]["score"], -2)
        self.assertEqual(payload["analysis"]["closed_candles"], LATE_POINT)
        self.assertNotIn("closes", payload["analysis"])
        self.assertEqual(set(payload["price_action"]), {"levels", "patterns", "pivots"})

    # -------------------------------------------------------- whole session

    def test_whole_session_in_order(self) -> None:
        """Stages 2-6 in sequence: the cumulative story of one session.

        Ingest 300 validated candles → read BUY/+1/RSI 100 before the flip →
        read SELL/-1/RSI ~0 after it → the RSI alert fires exactly once (at
        the first uptrend checkpoint) → both cards persist with open outcomes
        → the reversal stops out the BUY (SL) and the trend pays the SELL (TP)
        → ``update_outcomes`` stores both → the CLI emits the same late
        analysis as JSON. Every stage consumes the outputs of the previous
        ones, exactly as the live app chains them.
        """
        # Stage 2: stream validation over the whole wire feed.
        wire = [_wire_row(candle) for candle in self.session]
        validated = [parse_candle(row) for row in wire]
        self.assertEqual(validated, self.session)

        # Stage 3: analysis, confluence and snapshot at both session points.
        early = analyze(self.early_window)
        late = analyze(self.late_window)
        self.assertEqual((early["signal"], early["score"]), ("BUY", 2))
        self.assertEqual((late["signal"], late["score"]), ("SELL", -2))
        (early_card,) = scan_candles({SYMBOL: self.early_window}, TIMEFRAME)
        (late_card,) = scan_candles({SYMBOL: self.late_window}, TIMEFRAME)
        self.assertEqual((early_card.direction, late_card.direction), (1, -1))
        early_snapshot = market_snapshot(
            self.early_window, symbol=SYMBOL, timeframe=TIMEFRAME
        )
        late_snapshot = market_snapshot(
            self.late_window, symbol=SYMBOL, timeframe=TIMEFRAME
        )
        self.assertEqual(
            (early_snapshot["signal"], late_snapshot["signal"]), ("BUY", "SELL")
        )

        # Stage 4: the alert rule fires once, on the uptrend side only.
        rule = AlertRule(SYMBOL, "rsi", ">", ALERT_RSI_THRESHOLD)
        engine = AlertEngine([rule])
        firings = []
        for rows in range(61, len(self.session) + 1, 10):
            checkpoint = analyze(self.session[:rows])
            if checkpoint is None:
                continue
            if engine.evaluate(SYMBOL, checkpoint, checkpoint["closes"][-1]):
                firings.append(rows)
        self.assertEqual(firings, [61])

        # Stage 5: persist, resolve, and store both outcomes.
        store, records = self._recorded_session()
        self.assertEqual(len(records), 2)
        early_record, late_record = records
        resolutions = {}
        for record, after in (
            (early_record, self.session[EARLY_POINT:]),
            (late_record, self.session[LATE_POINT:]),
        ):
            outcome = resolve_outcome(
                int(record["direction"]),
                float(record["entry"]),
                float(record["stop_loss"]),
                float(record["take_profit"]),
                after,
            )
            self.assertIn(outcome, {"TP", "SL"})
            resolutions[(str(record["symbol"]), str(record["timestamp"]))] = outcome
        self.assertEqual(sorted(resolutions.values()), ["SL", "TP"])
        outcomes = evaluate_outcomes(_outcome_rows(records), self.session, horizon=10)
        self.assertLess(outcomes[0].return_pct, 0.0)
        self.assertGreater(outcomes[1].return_pct, 0.0)
        self.assertEqual(store.update_outcomes(resolutions), 2)
        self.assertEqual([record["outcome"] for record in store.read()], ["SL", "TP"])

        # Stage 6: the CLI layer on the same fake feed.
        out = io.StringIO()
        code = cli_main(["analyze", SYMBOL, "--json"], fetch=self._fake_fetch, out=out)
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(
            payload["analysis"],
            {key: value for key, value in late.items() if key != "closes"},
        )


if __name__ == "__main__":
    unittest.main()
