"""Batch 7: appearance, backend neural, prompts, evals, onboarding."""

from __future__ import annotations

import json
import unittest

from neezy_app.theme import (
    DENSITY_SCALE,
    WICK_STYLES,
    density_scale,
    merged_palette,
    palette_for,
    validate_wick_style,
)
from neezy_backend.brain_advanced import (
    ADVANCED_ARCHITECTURES,
    ALL_ARCHITECTURES,
    ARCHITECTURE_INFO,
    auto_select_best,
    train_advanced,
    training_manifest,
)
from neezy_backend.config import APPEARANCE_DENSITIES, CANDLE_WICK_STYLES, AppSettings
from neezy_backend.model_router import entry_for, load_registry, save_registry
from neezy_backend.prompts import get_prompt, list_prompts, render


def _candles(n: int = 800) -> list[list[float]]:
    rows: list[list[float]] = []
    price = 100.0
    for i in range(n):
        price += (1 if i % 7 < 4 else -1) * 0.02 * price * 0.1 + 0.05
        open_ = price
        close = price + (0.5 if i % 2 == 0 else -0.5)
        high = max(open_, close) + 1
        low = min(open_, close) - 1
        rows.append([float(i), float(open_), float(high), float(low), float(close)])
    return rows


class ThemeAppearanceTests(unittest.TestCase):
    def test_density_scale_and_validation(self):
        for d in APPEARANCE_DENSITIES:
            self.assertIn(d, DENSITY_SCALE)
            self.assertGreater(density_scale(d), 0)
        self.assertEqual(validate_wick_style("thin"), [])
        self.assertNotEqual(validate_wick_style("nope"), [])

    def test_merged_palette_overrides(self):
        base = palette_for("Liquid dark")
        merged = merged_palette("Liquid dark", custom_tokens={"BG": "#112233"})
        self.assertEqual(merged["BG"], "#112233")
        self.assertEqual(base["BG"], "#08111f")
        # Invalid tokens ignored
        merged2 = merged_palette("Liquid dark", custom_tokens={"BG": "not-a-color"})
        self.assertEqual(merged2["BG"], base["BG"])

    def test_wick_styles_match_config(self):
        self.assertEqual(set(WICK_STYLES), set(CANDLE_WICK_STYLES))


class ConfigAdvancedTests(unittest.TestCase):
    def test_new_fields_default_validation(self):
        s = AppSettings()
        s.__post_init__()  # should not raise
        self.assertIn(s.appearance_density, APPEARANCE_DENSITIES)
        self.assertEqual(s.window_opacity, 1.0)
        self.assertEqual(s.chart_candle_wick_style, "thin")

    def test_invalid_json_rejects(self):
        with self.assertRaises(ValueError):
            AppSettings(theme_custom_tokens="not json").__post_init__()
        with self.assertRaises(ValueError):
            AppSettings(risk_per_symbol="[]").__post_init__()  # must be object

    def test_risk_per_symbol_override(self):
        s = AppSettings(risk_per_symbol=json.dumps({"R_100": 2.5}))
        self.assertAlmostEqual(s.risk_percent_for_symbol("R_100"), 2.5)
        # R_50 is synthetic, so synthetic_risk_percent applies
        self.assertAlmostEqual(
            s.risk_percent_for_symbol("R_50"), s.synthetic_risk_percent
        )

    def test_deriv_endpoints_and_ml_list(self):
        s = AppSettings(deriv_endpoints=json.dumps(["wss://a.example"]))
        self.assertEqual(s.deriv_endpoint_list(), ["wss://a.example"])
        s2 = AppSettings(ml_advanced_architectures=json.dumps(["neezy_mlp_deep_v2"]))
        self.assertEqual(s2.ml_advanced_list(), ["neezy_mlp_deep_v2"])

    def test_onboarding_and_appearance_opacity_validation(self):
        s = AppSettings(window_opacity=0.5)
        s.__post_init__()
        with self.assertRaises(ValueError):
            AppSettings(window_opacity=0.1).__post_init__()
        with self.assertRaises(ValueError):
            AppSettings(ml_eval_holdout_ratio=0.01).__post_init__()


class BrainAdvancedTests(unittest.TestCase):
    def test_architectures_registered(self):
        self.assertGreaterEqual(len(ALL_ARCHITECTURES), 6)
        for arch in ADVANCED_ARCHITECTURES:
            self.assertIn(arch, ALL_ARCHITECTURES)
            self.assertIn(arch, ARCHITECTURE_INFO)

    def test_train_advanced_smoke(self):
        candles = _candles()
        run = train_advanced(candles, architecture="neezy_mlp_deep_v2", symbol="R_100")
        self.assertEqual(run.architecture, "neezy_mlp_deep_v2")
        self.assertIsNotNone(run.model)
        self.assertGreater(run.epochs_ran, 0)
        manifest = training_manifest(run)
        self.assertEqual(manifest["architecture"], "neezy_mlp_deep_v2")
        self.assertIn("artifact_hash", manifest)

    def test_auto_select_best(self):
        candles = _candles()
        r1 = train_advanced(candles, architecture="neezy_mlp_deep_v2")
        r2 = train_advanced(candles, architecture="neezy_seq_mlp_deep_v2")
        best = auto_select_best([r1, r2])
        self.assertIsNotNone(best)
        self.assertIsNone(auto_select_best([]))

    def test_unknown_arch_raises(self):
        with self.assertRaises(ValueError):
            train_advanced([[0, 100, 102, 98, 100.5]], architecture="nope")


class ModelRouterTests(unittest.TestCase):
    def test_save_load_roundtrip(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.json"
            entries = {"R_100:5m": {"architecture": "neezy_mlp_deep_v2"}}
            save_registry(p, entries)
            loaded = load_registry(p)
            self.assertEqual(loaded, entries)
            self.assertEqual(
                entry_for(loaded, "R_100", "5m")["architecture"], "neezy_mlp_deep_v2"
            )
            self.assertIsNone(entry_for(loaded, "R_50", "5m"))


class PromptsRegistryTests(unittest.TestCase):
    def test_list_and_render(self):
        self.assertGreaterEqual(len(list_prompts()), 3)
        p = get_prompt("analysis_v1")
        self.assertIsNotNone(p)
        self.assertIsNone(get_prompt("missing"))
        out = render("analysis_v1", symbol="R_100", context="test")
        self.assertIn("R_100", out)
        with self.assertRaises(ValueError):
            render("analysis_v1", symbol="R_100")
        with self.assertRaises(KeyError):
            render("nope", symbol="x")

    def test_snapshot(self):
        from neezy_backend.prompts import registry_snapshot

        snap = registry_snapshot()
        self.assertIn("analysis_v1", snap)


class EvalsHarnessTests(unittest.TestCase):
    def test_eval_holdout_and_backtest_summary(self):
        from evals.harness import eval_backtest_summary, eval_holdout

        candles = _candles(600)
        res = eval_holdout(candles)
        self.assertEqual(res["schema"], 1)
        self.assertGreater(res["train_rows"], 0)
        self.assertGreater(res["holdout_rows"], 0)
        summary = eval_backtest_summary([1, 2, 3])
        self.assertIn("sharpe", summary)
        self.assertEqual(eval_backtest_summary([])["sharpe"], 0.0)
