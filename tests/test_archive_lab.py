"""Archive adapter safety, deterministic output and prefix-invariance tests."""

from __future__ import annotations

import importlib.util
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from neezy_backend.cli import main
from neezy_backend.lab.service import ENGINES, MAX_BARS, analyze, catalog, validate_rows


def candles(size=620):
    rows = []
    previous = 1.1
    for i in range(size):
        close = 1.1 + i * 0.00001 + math.sin(i / 7) * 0.0006
        rows.append(
            [
                1700000000 + i * 300,
                previous,
                max(previous, close) + 0.0002,
                min(previous, close) - 0.0002,
                close,
            ]
        )
        previous = close
    return rows


class ArchiveLabTests(unittest.TestCase):
    def test_catalog_is_safe_without_numpy(self):
        with patch(
            "neezy_backend.lab.service.importlib.util.find_spec", return_value=None
        ):
            result = catalog()
        self.assertTrue(result["advisory_only"])
        self.assertEqual(len(result["engines"]), 4)
        self.assertEqual(
            [e["available"] for e in result["engines"]], [True, True, False, False]
        )

    def test_validation_rejects_malformed_prices_epochs_and_ticks(self):
        row = candles(1)[0]
        bad = [
            [],
            [row, row],
            [[-1, *row[1:]]],
            [[True, *row[1:]]],
            [[row[0], float("nan"), *row[2:]]],
            [[row[0], 0, *row[2:]]],
            [[row[0], *row[1:4], 500]],
            [[*row, -1]],
            [[*row, 1.5]],
            ["bad"],
        ]
        for rows in bad:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_rows(rows)
        with self.assertRaises(ValueError):
            validate_rows(candles(MAX_BARS + 1))

    def test_fras_is_deterministic_and_causal(self):
        rows = candles(200)
        full = analyze(rows, include_series=True)
        prefix = analyze(rows[:130], include_series=True)
        self.assertEqual(full["series"][:130], prefix["series"])
        self.assertEqual(full, analyze(rows, include_series=True))
        self.assertTrue(full["latest"]["ready"])
        json.dumps(full, allow_nan=False)

    def test_fxlab_all_three_indicators_are_causal(self):
        for indicator in ENGINES["fxlab"][1]:
            with self.subTest(indicator=indicator):
                result = analyze(
                    candles(190),
                    engine="fxlab",
                    indicator=indicator,
                    include_series=True,
                )
                prefix = analyze(
                    candles(150),
                    engine="fxlab",
                    indicator=indicator,
                    include_series=True,
                )
                self.assertEqual(result["series"][:150], prefix["series"])
                json.dumps(result, allow_nan=False)

    @unittest.skipUnless(
        importlib.util.find_spec("numpy"), "optional NumPy not installed"
    )
    def test_all_numpy_indicators_have_finite_json_and_are_causal(self):
        rows = candles()
        for engine in ("tideforge", "tideglass"):
            for indicator in ENGINES[engine][1]:
                with self.subTest(engine=engine, indicator=indicator):
                    full = analyze(
                        rows, engine=engine, indicator=indicator, include_series=True
                    )
                    prefix = analyze(
                        rows[:580],
                        engine=engine,
                        indicator=indicator,
                        include_series=True,
                    )
                    self.assertEqual(full["series"][:580], prefix["series"])
                    json.dumps(full, allow_nan=False)
                    self.assertEqual(len(full["series"]), len(rows))

    def test_optional_dependency_failure_is_actionable(self):
        with patch(
            "neezy_backend.lab.service.importlib.util.find_spec", return_value=None
        ):
            with self.assertRaisesRegex(RuntimeError, "research-lab"):
                analyze(candles(10), engine="tideforge")

    def test_parameters_are_bounded_and_filesystem_access_rejected(self):
        for params in (
            {"atr_period": True},
            {"atr_period": 2.5},
            {"atr_period": 1000000},
            {"unexpected": 1},
            {"signal_threshold": float("nan")},
        ):
            with self.subTest(params=params), self.assertRaises(ValueError):
                analyze(candles(10), params=params)
        if importlib.util.find_spec("numpy"):
            with self.assertRaisesRegex(ValueError, "local files"):
                analyze(
                    candles(10),
                    engine="tideforge",
                    indicator="CC",
                    params={"weights_path": "/tmp/private"},
                )

    def test_cli_is_offline_and_handles_json(self):
        def no_fetch(*_args):
            self.fail("research must not fetch network data")

        out = io.StringIO()
        self.assertEqual(main(["lab", "catalog", "--json"], fetch=no_fetch, out=out), 0)
        self.assertEqual(len(json.loads(out.getvalue())["engines"]), 4)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candles.json"
            path.write_text(json.dumps({"candles": candles(150)}))
            out = io.StringIO()
            self.assertEqual(
                main(
                    ["lab", "analyze", "--input", str(path), "--series"],
                    fetch=no_fetch,
                    out=out,
                ),
                0,
            )
            self.assertEqual(json.loads(out.getvalue())["bars"], 150)
