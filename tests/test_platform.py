"""Tests for the advanced analytics, local database, and AI provider layer."""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from neezy_backend.ai import (
    PROVIDERS,
    AIClient,
    AIError,
    AIKeyStore,
    AllKeysFailed,
    NoAPIKeys,
    build_request,
    free_models,
    is_free_model,
    mask_secret,
    models_with_extra,
    parse_response,
    resolve_model,
    resolve_provider,
    validate_secret,
)
from neezy_backend.config import (
    AI_PROVIDERS,
    AppSettings,
)
from neezy_backend.config import (
    STRATEGIES as CONFIG_STRATEGIES,
)
from neezy_backend.database import LocalDatabase
from neezy_backend.divergence import (
    _divergence_between,
    correlation_divergence,
    detect_divergence,
    detect_divergences,
    pivot_indices,
    rank_correlation_divergences,
)
from neezy_backend.indicators import macd_histogram_series, rsi, rsi_series
from neezy_backend.strategies import (
    STRATEGIES,
    consensus,
    describe_strategies,
    evaluate,
    evaluate_pair,
    run_all,
    strategy_names,
)
from neezy_backend.trend import (
    atr_series,
    band_squeeze,
    cci,
    channel_breakout,
    donchian,
    keltner,
    linear_regression_slope,
    rate_of_change,
    stoch_rsi,
    supertrend,
    trend_summary,
    williams_r,
)


def make_candles(closes, spread=0.0006):
    """Build valid OHLC five-tuples from a close series."""
    candles = []
    previous = closes[0]
    for index, close in enumerate(closes):
        open_ = previous
        high = max(open_, close) + spread
        low = min(open_, close) - spread
        candles.append((index * 300, open_, high, low, close))
        previous = close
    return candles


def trending(count=220, step=0.0012, start=1.05):
    return make_candles([start + step * i for i in range(count)])


def random_walk(count=320, seed=11, sigma=0.0015):
    rng = random.Random(seed)
    closes = [1.10]
    for _ in range(count - 1):
        closes.append(max(0.2, closes[-1] * (1 + rng.gauss(0, sigma))))
    return make_candles(closes)


class TrendTests(unittest.TestCase):
    def test_atr_series_warms_up_and_stays_positive(self) -> None:
        candles = random_walk(80)
        highs = [row[2] for row in candles]
        lows = [row[3] for row in candles]
        closes = [row[4] for row in candles]
        values = atr_series(highs, lows, closes, 14)
        self.assertEqual(len(values), len(candles))
        self.assertTrue(all(value is None for value in values[:13]))
        self.assertIsNotNone(values[13])
        self.assertTrue(all(value > 0 for value in values[13:]))

    def test_supertrend_tracks_an_uptrend_and_marks_warmup(self) -> None:
        candles = trending()
        highs = [row[2] for row in candles]
        lows = [row[3] for row in candles]
        closes = [row[4] for row in candles]
        entries = supertrend(highs, lows, closes, 10, 3.0)
        self.assertEqual(len(entries), len(candles))
        self.assertEqual(entries[0]["direction"], 0)
        self.assertEqual(entries[-1]["direction"], 1)
        self.assertLess(float(entries[-1]["supertrend"]), closes[-1])
        self.assertGreater(int(entries[-1]["direction"]), 0)

    def test_supertrend_validates_arguments(self) -> None:
        candles = trending(40)
        highs = [row[2] for row in candles]
        lows = [row[3] for row in candles]
        closes = [row[4] for row in candles]
        with self.assertRaises(ValueError):
            supertrend(highs, lows, closes, 0, 3.0)
        with self.assertRaises(ValueError):
            supertrend(highs, lows, closes, 10, 0.0)
        with self.assertRaises(ValueError):
            supertrend(highs[:10], lows, closes, 10, 3.0)
        with self.assertRaises(ValueError):
            supertrend(highs, lows, closes, -1, 3.0)

    def test_channels_and_oscillators(self) -> None:
        candles = random_walk(160)
        highs = [row[2] for row in candles]
        lows = [row[3] for row in candles]
        closes = [row[4] for row in candles]
        channels = donchian(highs, lows, 20)
        self.assertIsNone(channels[0]["upper"])
        self.assertGreaterEqual(
            float(channels[-1]["upper"]), float(channels[-1]["mid"])
        )
        bands = keltner(highs, lows, closes, 20, 2.0)
        self.assertGreater(float(bands[-1]["upper"]), float(bands[-1]["lower"]))
        r = williams_r(highs, lows, closes, 14)
        self.assertIsNotNone(r[-1])
        self.assertTrue(-100.0 <= float(r[-1]) <= 0.0)
        commodity = cci(highs, lows, closes, 20)
        self.assertIsNotNone(commodity[-1])
        changes = rate_of_change(closes, 10)
        self.assertIsNone(changes[0])
        self.assertIsNotNone(changes[-1])
        slopes = linear_regression_slope(closes, 20)
        self.assertIsNone(slopes[0])
        self.assertIsNotNone(slopes[-1])
        stochastic_rsi = stoch_rsi(closes, 14, 3)
        self.assertEqual(len(stochastic_rsi), len(closes))
        self.assertTrue(
            all(value is None or 0.0 <= value <= 100.0 for value in stochastic_rsi)
        )

    def test_breakout_squeeze_and_trend_summary(self) -> None:
        candles = trending()
        summary = trend_summary(candles, 10, 3.0)
        self.assertEqual(summary["direction"], 1)
        self.assertEqual(summary["label"], "uptrend")
        self.assertGreater(summary["bars_since_flip"], 0)
        self.assertEqual(channel_breakout(candles, 20), "breakout")
        squeeze = band_squeeze(random_walk(120), 20)
        self.assertIn("squeeze", squeeze)
        self.assertGreaterEqual(float(squeeze["percentile"]), 0.0)


class RsiSeriesTests(unittest.TestCase):
    def test_series_matches_scalar_rsi(self) -> None:
        closes = [row[4] for row in random_walk(90)]
        series = rsi_series(closes, 14)
        self.assertIsNone(series[13])
        self.assertIsNotNone(series[14])
        self.assertAlmostEqual(float(series[-1]), float(rsi(closes, 14)), places=9)
        self.assertEqual(len(rsi_series(closes[:10], 14)), 10)
        self.assertTrue(all(value is None for value in rsi_series(closes[:10], 14)))

    def test_macd_histogram_is_aligned(self) -> None:
        closes = [row[4] for row in random_walk(120)]
        histogram = macd_histogram_series(closes)
        self.assertEqual(len(histogram), len(closes))
        self.assertTrue(all(isinstance(value, float) for value in histogram))


class DivergenceTests(unittest.TestCase):
    def test_pivot_detection(self) -> None:
        values = [5.0, 4.0, 3.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(pivot_indices(values, "low", 2, 2), [3])
        highs = [1.0, 2.0, 3.0, 4.0, 3.0, 2.0, 1.0]
        self.assertEqual(pivot_indices(highs, "high", 2, 2), [3])
        with self.assertRaises(ValueError):
            pivot_indices(values, "sideways")

    def test_bullish_and_bearish_divergence_rules(self) -> None:
        candles = make_candles([1.10, 1.09, 1.08, 1.09, 1.10, 1.09, 1.07, 1.08])
        oscillator = [50.0, 45.0, 30.0, 42.0, 55.0, 48.0, 38.0, 44.0]
        bullish = _divergence_between(
            candles, oscillator, [2, 6], kind="low", oscillator="rsi"
        )
        self.assertIsNotNone(bullish)
        self.assertEqual(bullish["kind"], "bullish")
        self.assertGreater(bullish["strength"], 0)

        candles = make_candles([1.00, 1.01, 1.03, 1.02, 1.01, 1.02, 1.06, 1.04])
        oscillator = [40.0, 50.0, 72.0, 60.0, 48.0, 55.0, 66.0, 58.0]
        bearish = _divergence_between(
            candles, oscillator, [2, 6], kind="high", oscillator="rsi"
        )
        self.assertIsNotNone(bearish)
        self.assertEqual(bearish["kind"], "bearish")

    def test_no_divergence_when_price_and_oscillator_agree(self) -> None:
        candles = make_candles([1.10, 1.09, 1.08, 1.09, 1.10, 1.09, 1.06, 1.07])
        oscillator = [50.0, 45.0, 30.0, 42.0, 55.0, 48.0, 22.0, 30.0]
        self.assertIsNone(
            _divergence_between(
                candles, oscillator, [2, 6], kind="low", oscillator="rsi"
            )
        )

    def test_detect_helpers_are_safe_on_short_or_flat_data(self) -> None:
        self.assertIsNone(detect_divergence(make_candles([1.0] * 10)))
        self.assertEqual(detect_divergences(make_candles([1.0] * 10)), [])
        self.assertEqual(
            len(detect_divergences(random_walk(200))),
            len([item for item in detect_divergences(random_walk(200))]),
        )

    def test_correlation_divergence_detects_an_inversion(self) -> None:
        base = [row[4] for row in random_walk(320, seed=3)]
        second = base[:250]
        for index in range(250, len(base)):
            second.append(second[-1] * (base[index - 1] / base[index]))
        result = correlation_divergence(base, second, window=50, baseline=200)
        self.assertIsNotNone(result)
        self.assertEqual(result["state"], "inverted")
        self.assertLess(result["recent"], 0)
        self.assertGreater(result["baseline"], 0)
        self.assertGreater(result["strength"], 0)

    def test_correlation_of_identical_series_is_stable(self) -> None:
        base = [row[4] for row in random_walk(300, seed=5)]
        result = correlation_divergence(base, base, window=50, baseline=200)
        self.assertEqual(result["state"], "stable")
        self.assertAlmostEqual(result["baseline"], 1.0, places=6)
        self.assertAlmostEqual(result["recent"], 1.0, places=6)

    def test_correlation_divergence_validates_and_ranks(self) -> None:
        base = [row[4] for row in random_walk(50)]
        with self.assertRaises(ValueError):
            correlation_divergence(base, base, window=3, baseline=10)
        with self.assertRaises(ValueError):
            correlation_divergence(base, base, window=20, baseline=10)
        basket = {
            "a": [row[4] for row in random_walk(300, seed=2)],
            "b": [row[4] for row in random_walk(300, seed=2)],
            "c": [row[4] for row in random_walk(300, seed=9)],
        }
        ranked = rank_correlation_divergences(basket, window=50, baseline=200, limit=2)
        self.assertLessEqual(len(ranked), 2)
        for item in ranked:
            self.assertIn("first", item)
            self.assertIn("state", item)


class StrategyTests(unittest.TestCase):
    def test_registry_metadata(self) -> None:
        self.assertEqual(len(strategy_names()), len(STRATEGIES))
        described = describe_strategies()
        self.assertEqual(len(described), len(STRATEGIES))
        self.assertIn("SUPERTREND", strategy_names())
        self.assertTrue(any(item["pair"] for item in described))
        with self.assertRaises(ValueError):
            evaluate("NOPE", trending())

    def test_supertrend_strategy_long_in_uptrend(self) -> None:
        signal = evaluate("SUPERTREND", trending(), period=10, multiplier=3.0)
        self.assertEqual(signal.direction, 1)
        self.assertEqual(signal.label, "BUY")
        self.assertGreater(signal.confidence, 50)
        self.assertIn("line", signal.metrics)
        self.assertTrue(signal.reasons)

    def test_every_single_market_strategy_returns_a_signal(self) -> None:
        candles = random_walk(320)
        for name in strategy_names():
            if STRATEGIES[name].pair:
                continue
            signal = evaluate(name, candles)
            self.assertIn(signal.direction, (-1, 0, 1), name)
            self.assertGreaterEqual(signal.confidence, 0.0)
            self.assertLessEqual(signal.confidence, 100.0)
            self.assertEqual(signal.strategy, name)
            payload = signal.to_dict()
            json.dumps(payload)

    def test_short_history_is_handled(self) -> None:
        for name in strategy_names():
            if STRATEGIES[name].pair:
                continue
            signal = evaluate(name, make_candles([1.0] * 10))
            self.assertEqual(signal.direction, 0)

    def test_consensus_and_pair_strategy(self) -> None:
        signals = run_all(trending())
        self.assertGreater(len(signals), 3)
        verdict = consensus(signals)
        self.assertIn(verdict["label"], {"BUY", "SELL", "NEUTRAL"})
        self.assertEqual(
            verdict["votes"]["buy"]
            + verdict["votes"]["sell"]
            + verdict["votes"]["neutral"],
            len(signals),
        )
        self.assertEqual(consensus([])["direction"], 0)
        base = [row[4] for row in random_walk(320, seed=3)]
        second = base[:250]
        for index in range(250, len(base)):
            second.append(second[-1] * (base[index - 1] / base[index]))
        pair = evaluate_pair(base, second, 50, 200)
        self.assertEqual(pair.strategy, "CORRELATION_DIVERGENCE")
        self.assertGreater(pair.confidence, 0)


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "neezy.sqlite3"
        self.db = LocalDatabase(self.path)

    def tearDown(self) -> None:
        self.db.close()
        self.directory.cleanup()

    def test_candle_roundtrip_and_upsert(self) -> None:
        candles = trending(30)
        written = self.db.save_candles("frxEURUSD", "5m", candles)
        self.assertEqual(written, 30)
        loaded = self.db.load_candles("frxEURUSD", "5m", 10)
        self.assertEqual(len(loaded), 10)
        self.assertEqual(loaded[-1], tuple(candles[-1]))
        self.db.save_candles("frxEURUSD", "5m", [candles[-1]])
        self.assertEqual(self.db.candle_count("frxEURUSD"), 30)
        self.assertEqual(
            self.db.load_candles("frxEURUSD", "5m", 500)[-1], tuple(candles[-1])
        )

    def test_invalid_candles_are_skipped(self) -> None:
        rows = [
            (1, 1.0, 1.1, 0.9, 1.05),
            (2, float("nan"), 1.1, 0.9, 1.05),
            (3, 1.0, 1.1, 0.9, -1.0),
            (4, 1.0, 1.1),
        ]
        self.assertEqual(self.db.save_candles("frxEURUSD", "5m", rows), 1)

    def test_store_candles_switch(self) -> None:
        db = LocalDatabase(
            Path(self.directory.name) / "other.sqlite3", store_candles=False
        )
        try:
            self.assertEqual(db.save_candles("frxEURUSD", "5m", trending(5)), 0)
            self.assertEqual(db.candle_count(), 0)
        finally:
            db.close()

    def test_signals_and_snapshots(self) -> None:
        signal_id = self.db.save_signal(
            symbol="frxEURUSD",
            timeframe="5m",
            signal="BUY",
            score=3,
            price=1.12345,
            strategy="SUPERTREND",
            direction=1,
            confidence=72.5,
            payload={"why": ["EMA 9 above EMA 21"]},
        )
        self.assertGreater(signal_id, 0)
        records = self.db.recent_signals(10)
        self.assertEqual(records[0]["signal"], "BUY")
        self.assertEqual(records[0]["payload"]["why"][0], "EMA 9 above EMA 21")

        result = {
            "signal": "BUY",
            "score": 3,
            "regime": "Trending",
            "atr": float("inf"),
            "closes": [1.0, 1.1],
        }
        self.assertGreater(
            self.db.save_snapshot(symbol="frxEURUSD", timeframe="5m", result=result), 0
        )
        snapshot = self.db.latest_snapshot("frxEURUSD")
        self.assertEqual(snapshot["regime"], "Trending")
        self.assertIsNone(snapshot["payload"]["atr"])
        self.assertIsNone(self.db.latest_snapshot("frxGBPUSD"))

    def test_kv_and_stats(self) -> None:
        self.db.set_value("last_view", {"symbol": "frxEURUSD"})
        self.assertEqual(self.db.get_value("last_view")["symbol"], "frxEURUSD")
        self.assertEqual(self.db.get_value("missing", "fallback"), "fallback")
        self.db.save_candles("frxEURUSD", "5m", trending(10))
        stats = self.db.stats()
        self.assertEqual(stats["counts"]["candles"], 10)
        self.assertEqual(stats["journal_mode"].lower(), "wal")
        self.assertIn("path", stats)
        self.assertGreater(stats["size_bytes"], 0)

    def test_ai_usage_history(self) -> None:
        self.db.record_ai_call(
            provider="openrouter",
            model="deepseek/deepseek-r1:free",
            status="ok",
            key_label="key 1",
            latency_ms=420,
        )
        self.db.record_ai_call(
            provider="gemini", model="gemini-2.5-flash", status="quota"
        )
        usage = self.db.ai_usage()
        self.assertEqual(usage["total"], 2)
        self.assertEqual(usage["by_provider"]["openrouter"], 1)
        self.assertEqual(usage["by_status"]["quota"], 1)

    def test_prune_export_and_clear(self) -> None:
        self.db.save_candles("frxEURUSD", "5m", trending(20))
        self.db.save_signal(
            symbol="frxEURUSD", timeframe="5m", signal="BUY", score=2, price=1.2
        )
        removed = self.db.prune(
            retention_days=1, now=datetime.now(timezone.utc) + timedelta(days=5)
        )
        self.assertEqual(removed["signals"], 1)
        self.assertGreaterEqual(removed["candles"], 1)
        self.db.save_signal(
            symbol="frxEURUSD", timeframe="5m", signal="SELL", score=-2, price=1.2
        )
        export_path = Path(self.directory.name) / "dump.json"
        counts = self.db.export_json(export_path)
        self.assertEqual(counts["signals"], 1)
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.db.clear("signals")
        self.assertEqual(self.db.recent_signals(5), [])
        with self.assertRaises(ValueError):
            self.db.clear("kv")

    def test_vacuum_keeps_data(self) -> None:
        self.db.save_candles("frxEURUSD", "5m", trending(10))
        self.db.vacuum()
        self.assertEqual(self.db.candle_count(), 10)


class AIProviderTests(unittest.TestCase):
    def test_provider_catalogue(self) -> None:
        self.assertEqual(set(PROVIDERS), {"gemini", "grok", "openrouter", "ollama"})
        for name in PROVIDERS:
            models = free_models(name)
            self.assertTrue(models)
            self.assertTrue(all(is_free_model(name, model) for model in models))
        self.assertEqual(resolve_provider("Google").key, "gemini")
        self.assertEqual(resolve_provider("xAI").key, "grok")
        self.assertEqual(resolve_provider("OLLAMA CLOUD").key, "ollama")
        with self.assertRaises(ValueError):
            resolve_provider("not-a-provider")

    def test_model_helpers(self) -> None:
        self.assertEqual(resolve_model("openrouter"), free_models("openrouter")[0])
        self.assertEqual(resolve_model("openrouter", "custom/model"), "custom/model")
        self.assertEqual(
            resolve_model("openrouter", "   "), free_models("openrouter")[0]
        )
        self.assertTrue(is_free_model("openrouter", "anything/at-all:free"))
        self.assertFalse(is_free_model("openrouter", "openai/gpt-4o"))
        merged = models_with_extra("gemini", ["gemini-2.5-flash", "custom-free"])
        self.assertEqual(len(merged), len(free_models("gemini")) + 1)
        self.assertIn("custom-free", merged)

    def test_secret_validation_and_masking(self) -> None:
        self.assertEqual(
            validate_secret("gemini", "  AIza1234567890 "), "AIza1234567890"
        )
        self.assertEqual(validate_secret("grok", '"xai-abcdefgh"'), "xai-abcdefgh")
        with self.assertRaises(ValueError):
            validate_secret("gemini", "short")
        with self.assertRaises(ValueError):
            validate_secret("gemini", "has a space inside")
        self.assertEqual(mask_secret("sk-or-v1-abcdefgh"), "************efgh")
        self.assertEqual(mask_secret("abc"), "***")
        self.assertNotIn("abcdefgh", mask_secret("sk-or-v1-abcdefgh"))


class AIKeyStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = AIKeyStore(Path(self.directory.name) / "ai-keys.json")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_add_list_remove(self) -> None:
        first = self.store.add("gemini", "AIzaAAAAAAAA1111", "primary")
        second = self.store.add("gemini", "AIzaBBBBBBBB2222")
        self.assertEqual(self.store.count("gemini"), 2)
        statuses = self.store.statuses("gemini")
        self.assertEqual([item.label for item in statuses], ["primary", "key 2"])
        self.assertTrue(all(item.hint.endswith(("1111", "2222")) for item in statuses))
        self.assertTrue(self.store.remove("gemini", first.id))
        self.assertFalse(self.store.remove("gemini", first.id))
        self.assertEqual(len(self.store.statuses("gemini")), 1)
        self.assertEqual(second.provider, "gemini")

    def test_duplicate_key_is_refreshed_not_repeated(self) -> None:
        first = self.store.add("openrouter", "sk-or-v1-aaaa1111")
        self.store.mark_failure("openrouter", first.id, "quota", cooldown_seconds=600)
        again = self.store.add("openrouter", "sk-or-v1-aaaa1111")
        self.assertEqual(again.id, first.id)
        self.assertTrue(again.usable())
        self.assertEqual(self.store.count("openrouter"), 1)
        with self.assertRaises(ValueError):
            self.store.add("openrouter", "sk-or-v1-aaaa1111", replace_duplicate=False)

    def test_cooldown_parks_and_recovers_a_key(self) -> None:
        status = self.store.add("ollama", "ollama-secret-key-1")
        self.assertEqual(len(self.store.secrets("ollama")), 1)
        self.store.mark_failure(
            "ollama", status.id, "rate limited", cooldown_seconds=900
        )
        self.assertEqual(self.store.secrets("ollama"), [])
        self.assertEqual(self.store.usable_count("ollama"), 0)
        parked = self.store.statuses("ollama")[0]
        self.assertFalse(parked.usable())
        self.assertEqual(parked.last_error, "rate limited")
        self.store.mark_failure("ollama", status.id, "rate limited", cooldown_seconds=0)
        self.assertEqual(len(self.store.secrets("ollama")), 1)

    def test_disable_enable_and_reset(self) -> None:
        status = self.store.add("grok", "xai-abcdefgh1234")
        self.assertTrue(self.store.set_enabled("grok", status.id, False))
        self.assertEqual(self.store.secrets("grok"), [])
        self.assertTrue(self.store.set_enabled("grok", status.id, True))
        self.store.mark_failure("grok", status.id, "boom", cooldown_seconds=500)
        self.assertEqual(self.store.reset("grok"), 1)
        self.assertEqual(len(self.store.secrets("grok")), 1)
        self.assertFalse(self.store.set_enabled("grok", "missing", True))

    def test_summary_and_persistence(self) -> None:
        self.store.add("gemini", "AIzaAAAAAAAA1111")
        self.store.add("openrouter", "sk-or-v1-bbbb2222")
        summary = self.store.summary()
        self.assertEqual(summary["gemini"]["keys"], 1)
        self.assertEqual(summary["openrouter"]["usable"], 1)
        reopened = AIKeyStore(self.store.path)
        self.assertEqual(reopened.count("gemini"), 1)
        payload = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)

    def test_corrupt_store_starts_empty(self) -> None:
        self.store.path.write_text("{oops", encoding="utf-8")
        self.assertEqual(self.store.count("gemini"), 0)
        self.assertTrue(self.store.add("gemini", "AIzaCCCCCCCC3333"))


OPENAI_BODY = json.dumps(
    {
        "choices": [{"message": {"content": "Momentum is aligned."}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    }
).encode()
GEMINI_BODY = json.dumps(
    {
        "candidates": [{"content": {"parts": [{"text": "Regime is trending."}]}}],
        "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 5},
    }
).encode()


class AIClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = AIKeyStore(Path(self.directory.name) / "ai-keys.json")
        self.recorder_calls: list[dict] = []

    def tearDown(self) -> None:
        self.directory.cleanup()

    def client(self, responses):
        """Transport returning queued ``(status, body)`` responses."""
        queue = list(responses)

        def transport(url, headers, body, timeout):
            self.requests.append((url, headers, json.loads(body.decode())))
            return queue.pop(0) if queue else (500, b"{}")

        self.requests: list[tuple] = []
        return AIClient(
            self.store,
            transport=transport,
            recorder=lambda **kwargs: self.recorder_calls.append(kwargs),
        )

    def test_no_keys_raises(self) -> None:
        client = self.client([])
        with self.assertRaises(NoAPIKeys):
            client.chat("gemini", [{"role": "user", "content": "hi"}])
        with self.assertRaises(ValueError):
            client.chat("gemini", [])

    def test_openai_style_success_and_recording(self) -> None:
        self.store.add("openrouter", "sk-or-v1-key1111")
        client = self.client([(200, OPENAI_BODY)])
        result = client.chat(
            "openrouter",
            [{"role": "user", "content": "read the market"}],
            model="deepseek/deepseek-r1:free",
        )
        self.assertEqual(result.text, "Momentum is aligned.")
        self.assertEqual(result.provider, "openrouter")
        self.assertEqual(result.usage["completion_tokens"], 7)
        self.assertEqual(result.attempts[0]["status"], "ok")
        url, headers, body = self.requests[0]
        self.assertTrue(url.endswith("/chat/completions"))
        self.assertEqual(headers["Authorization"], "Bearer sk-or-v1-key1111")
        self.assertEqual(headers["X-Title"], "NEEZY")
        self.assertEqual(body["model"], "deepseek/deepseek-r1:free")
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(self.recorder_calls[-1]["status"], "ok")
        self.assertEqual(self.store.statuses("openrouter")[0].uses, 1)

    def test_gemini_style_request_and_parse(self) -> None:
        self.store.add("gemini", "AIzaAAAAAAAA1111")
        client = self.client([(200, GEMINI_BODY)])
        result = client.chat("gemini", [{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "Regime is trending.")
        url, headers, body = self.requests[0]
        self.assertIn("models/gemini-2.5-flash:generateContent", url)
        self.assertEqual(headers["x-goog-api-key"], "AIzaAAAAAAAA1111")
        self.assertIn("systemInstruction", body)
        self.assertEqual(body["contents"][0]["role"], "user")
        self.assertEqual(result.usage["prompt_tokens"], 9)

    def test_quota_on_first_key_rotates_to_the_second(self) -> None:
        self.store.add("openrouter", "sk-or-v1-key1111", "primary")
        self.store.add("openrouter", "sk-or-v1-key2222", "backup")
        quota = json.dumps({"error": {"message": "free-tier limit reached"}}).encode()
        client = self.client([(429, quota), (200, OPENAI_BODY)])
        result = client.chat("openrouter", [{"role": "user", "content": "hi"}])
        self.assertEqual(result.key_label, "backup")
        self.assertEqual(result.attempts[0]["status"], "quota")
        self.assertEqual(self.store.usable_count("openrouter"), 1)
        self.assertEqual(
            len([call for call in self.recorder_calls if call["status"] == "quota"]), 1
        )

    def test_auth_failure_parks_key_and_all_failed_reports_attempts(self) -> None:
        self.store.add("grok", "xai-key11111111", "one")
        self.store.add("grok", "xai-key22222222", "two")
        unauthorized = json.dumps({"error": {"message": "bad key"}}).encode()
        client = self.client([(401, unauthorized), (403, unauthorized)])
        with self.assertRaises(AllKeysFailed) as caught:
            client.chat("grok", [{"role": "user", "content": "hi"}])
        self.assertEqual(len(caught.exception.attempts), 2)
        self.assertIn("one", str(caught.exception))
        self.assertEqual(self.store.usable_count("grok"), 0)

    def test_request_error_does_not_burn_other_keys(self) -> None:
        self.store.add("gemini", "AIzaAAAAAAAA1111")
        self.store.add("gemini", "AIzaBBBBBBBB2222")
        bad = json.dumps({"error": {"message": "unknown model"}}).encode()
        client = self.client([(400, bad)])
        with self.assertRaises(AIError):
            client.chat("gemini", [{"role": "user", "content": "hi"}], model="nope")
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.store.usable_count("gemini"), 2)

    def test_transient_failure_cools_down_then_succeeds(self) -> None:
        self.store.add("ollama", "ollama-key-1111")
        client = self.client([(503, b"upstream down"), (200, OPENAI_BODY)])
        with self.assertRaises(AllKeysFailed):
            client.chat("ollama", [{"role": "user", "content": "hi"}])
        parked = self.store.statuses("ollama")[0]
        self.assertFalse(parked.usable())
        self.store.reset("ollama")
        result = client.chat("ollama", [{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "Momentum is aligned.")

    def test_custom_base_url_and_system_prompt(self) -> None:
        self.store.add("ollama", "ollama-key-1111")
        client = self.client([(200, OPENAI_BODY)])
        client.chat(
            "ollama",
            [{"role": "user", "content": "hi"}],
            base_url="http://localhost:11434/v1/",
            system_prompt="Be terse.",
        )
        url, _headers, body = self.requests[0]
        self.assertEqual(url, "http://localhost:11434/v1/chat/completions")
        self.assertEqual(body["messages"][0]["content"], "Be terse.")

    def test_build_request_and_parse_roundtrip_for_both_styles(self) -> None:
        url, headers, body = build_request(
            "gemini", "k" * 12, "gemini-2.0-flash", [{"role": "user", "content": "x"}]
        )
        self.assertTrue(url.endswith("gemini-2.0-flash:generateContent"))
        self.assertEqual(headers["x-goog-api-key"], "k" * 12)
        self.assertIn("generationConfig", json.loads(body))
        text, usage = parse_response("gemini", GEMINI_BODY)
        self.assertTrue(text)
        self.assertEqual(usage["completion_tokens"], 5)
        text, usage = parse_response("openrouter", OPENAI_BODY)
        self.assertTrue(text)
        self.assertEqual(usage["prompt_tokens"], 12)
        with self.assertRaises(AIError):
            parse_response("openrouter", b"not-json")
        with self.assertRaises(AIError):
            parse_response("openrouter", b'{"choices": []}')
        with self.assertRaises(AIError):
            parse_response("gemini", b'{"candidates": []}')


class SettingsTests(unittest.TestCase):
    def test_defaults_cover_the_new_sections(self) -> None:
        settings = AppSettings()
        self.assertEqual(settings.strategy, "SUPERTREND")
        self.assertEqual(settings.correlation_baseline, 200)
        self.assertTrue(settings.store_candles)
        self.assertFalse(settings.ai_enabled)
        self.assertIn(settings.ai_provider, PROVIDERS)
        self.assertEqual(settings.ai_max_tokens, 700)

    def test_new_field_validation(self) -> None:
        with self.assertRaises(ValueError):
            AppSettings(strategy="UNKNOWN")
        with self.assertRaises(ValueError):
            AppSettings(supertrend_period=1)
        with self.assertRaises(ValueError):
            AppSettings(ai_provider="chatgpt")
        with self.assertRaises(ValueError):
            AppSettings(ai_temperature=3.0)
        with self.assertRaises(ValueError):
            AppSettings(retention_days=0)
        with self.assertRaises(ValueError):
            AppSettings(correlation_window=100, correlation_baseline=50)
        with self.assertRaises(TypeError):
            AppSettings(store_candles="yes")

    def test_forward_and_backward_compatibility(self) -> None:
        settings = AppSettings.from_dict(
            {
                "theme": "High contrast",
                "strategy": "DIVERGENCE",
                "retired_field": 1,
                "ai_model": "custom/model",
            }
        )
        self.assertEqual(settings.theme, "High contrast")
        self.assertEqual(settings.strategy, "DIVERGENCE")
        self.assertEqual(settings.ai_model, "custom/model")
        self.assertEqual(settings.polling_ms, 100)
        restored = AppSettings.from_dict(settings.to_dict())
        self.assertEqual(restored, settings)

    def test_config_catalogues_match_the_engine(self) -> None:
        self.assertEqual(set(AI_PROVIDERS), set(PROVIDERS))
        self.assertEqual(
            set(CONFIG_STRATEGIES), set(strategy_names()) - {"CORRELATION_DIVERGENCE"}
        )

    def test_settings_roundtrip_with_updates(self) -> None:
        updated = AppSettings().updated(
            strategy="SQUEEZE", store_candles=False, ai_enabled=True
        )
        self.assertEqual(updated.strategy, "SQUEEZE")
        self.assertFalse(updated.store_candles)
        self.assertTrue(updated.ai_enabled)


if __name__ == "__main__":
    unittest.main()
