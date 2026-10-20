"""Tests for the isolated local neural research model."""

from __future__ import annotations

import json
import math
import random
import unittest

from neezy_backend.brain import predict, train_model, validate_model


def _candles(count: int = 1500, seed: int = 17):
    rng = random.Random(seed)
    rows = []
    price = 1.1
    momentum = 0.0
    for index in range(count):
        opening = price
        momentum = momentum * 0.55 + rng.gauss(0.0, 0.00015)
        close = max(0.5, opening + momentum + rng.gauss(0.0, 0.00015))
        high = max(opening, close) + abs(rng.gauss(0, 0.0001))
        low = min(opening, close) - abs(rng.gauss(0, 0.0001))
        rows.append((index * 300, opening, high, low, close))
        price = close
    return rows


class NeuralBrainTest(unittest.TestCase):
    def test_training_produces_json_safe_model_and_chronological_report(self):
        result = train_model(
            _candles(),
            symbol="frxEURUSD",
            timeframe="5m",
            horizon=5,
            min_samples=100,
            epochs=3,
        )
        model, report = result["model"], result["report"]
        self.assertEqual(model["symbol"], "frxEURUSD")
        self.assertEqual(report["symbol"], "frxEURUSD")
        self.assertGreater(report["train"]["samples"], report["test"]["samples"])
        self.assertGreater(report["validation"]["samples"], 0)
        self.assertEqual(len(model["weights_in"]), 8)
        self.assertIn("balanced_accuracy", report["test"])
        self.assertTrue(model["validation_note"])
        self.assertTrue(math.isfinite(model["bias_out"]))
        json.dumps(result, allow_nan=False)
        self.assertIs(validate_model(model), model)

    def test_prediction_is_advisory_and_neutral_without_holdout_evidence(self):
        result = train_model(_candles(), min_samples=100, epochs=3)
        model = result["model"]
        model["deployment_ready"] = False
        prediction = predict(_candles(), model)
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction["direction"], "NEUTRAL")
        self.assertGreaterEqual(prediction["up_probability"], 0.0)
        self.assertLessEqual(prediction["up_probability"], 1.0)
        self.assertFalse(prediction["deployment_ready"])

    def test_training_rejects_short_or_unsorted_history(self):
        with self.assertRaisesRegex(ValueError, "not enough labeled"):
            train_model(_candles(150), min_samples=100, epochs=1)
        rows = _candles(500)
        rows[100], rows[101] = rows[101], rows[100]
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            train_model(rows, min_samples=60, epochs=1)

    def test_invalid_model_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_model({"schema": 999})


if __name__ == "__main__":
    unittest.main()
