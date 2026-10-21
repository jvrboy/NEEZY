"""Tests for the ensemble and sequence neural model types."""

from __future__ import annotations

import copy
import json
import math
import statistics
import unittest

from neezy_backend.brain import (
    ENSEMBLE_V1,
    FEATURE_NAMES,
    HIDDEN_UNITS,
    MLP_V1,
    SEQUENCE_V1,
    _feature_rows,
    _validate_candles,
    predict,
    sequence_feature_names,
    train_model,
    validate_model,
)
from tests.test_brain import _candles


def _single_from_member(model: dict, member: dict) -> dict:
    """A plain v1 document carrying one ensemble member's weights."""
    single = copy.deepcopy(model)
    single["model_type"] = MLP_V1
    for key in ("members",):
        single.pop(key, None)
    single.update(copy.deepcopy(member))
    return single


class EnsembleModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = train_model(
            _candles(),
            symbol="frxEURUSD",
            timeframe="5m",
            min_samples=100,
            epochs=4,
            model_type=ENSEMBLE_V1,
            members=3,
        )
        cls.model = cls.result["model"]

    def test_ensemble_stores_bagged_members_and_validates(self):
        model = self.model
        self.assertEqual(model["model_type"], ENSEMBLE_V1)
        self.assertEqual(len(model["members"]), 3)
        self.assertIs(validate_model(model), model)
        for member in model["members"]:
            self.assertEqual(len(member["weights_in"]), HIDDEN_UNITS)
            self.assertEqual(len(member["weights_in"][0]), len(FEATURE_NAMES))
        # Members start from different seeds and bootstrap samples.
        self.assertNotEqual(
            model["members"][0]["weights_in"], model["members"][1]["weights_in"]
        )
        self.assertEqual(self.result["report"]["model_type"], ENSEMBLE_V1)
        self.assertEqual(self.result["report"]["members"], 3)
        self.assertIn("mean_probability_spread", self.result["report"]["test"])
        json.dumps(self.result, allow_nan=False)

    def test_prediction_averages_members_and_reports_spread(self):
        candles = _candles()
        ensemble = predict(candles, self.model)
        self.assertIsNotNone(ensemble)
        self.assertEqual(ensemble["model_type"], ENSEMBLE_V1)

        member_predictions = []
        for member in self.model["members"]:
            single = predict(candles, _single_from_member(self.model, member))
            member_predictions.append(single["up_probability"])

        mean = sum(member_predictions) / len(member_predictions)
        spread = statistics.pstdev(member_predictions)
        self.assertAlmostEqual(ensemble["up_probability"], mean, delta=1e-3)
        self.assertAlmostEqual(ensemble["probability_spread"], spread, delta=1e-3)
        self.assertGreater(ensemble["probability_spread"], 0.0)
        self.assertAlmostEqual(
            ensemble["down_probability"], 1.0 - ensemble["up_probability"], delta=1e-3
        )

    def test_identical_members_have_zero_spread(self):
        model = copy.deepcopy(self.model)
        model["members"] = [model["members"][0], copy.deepcopy(model["members"][0])]
        prediction = predict(_candles(), model)
        self.assertEqual(prediction["probability_spread"], 0.0)

    def test_member_count_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "members must be between"):
            train_model(
                _candles(), min_samples=100, epochs=1, model_type=ENSEMBLE_V1, members=1
            )
        with self.assertRaisesRegex(ValueError, "wrong member count"):
            broken = copy.deepcopy(self.model)
            broken["members"] = broken["members"][:1]
            validate_model(broken)

    def test_malformed_member_is_rejected(self):
        broken = copy.deepcopy(self.model)
        broken["members"][1]["weights_out"] = broken["members"][1]["weights_out"][:-1]
        with self.assertRaisesRegex(ValueError, "wrong dimensions"):
            validate_model(broken)
        broken = copy.deepcopy(self.model)
        broken["members"][2]["bias_out"] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid weights"):
            validate_model(broken)


class SequenceModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = train_model(
            _candles(),
            symbol="frxEURUSD",
            timeframe="5m",
            min_samples=100,
            epochs=4,
            model_type=SEQUENCE_V1,
            window=6,
        )
        cls.model = cls.result["model"]

    def test_sequence_model_layout_includes_lagged_returns(self):
        model = self.model
        self.assertEqual(model["model_type"], SEQUENCE_V1)
        self.assertEqual(model["window"], 6)
        self.assertEqual(model["feature_names"], list(sequence_feature_names(6)))
        self.assertEqual(len(model["feature_names"]), 6 + len(FEATURE_NAMES))
        self.assertEqual(len(model["means"]), 14)
        self.assertEqual(len(model["weights_in"][0]), 14)
        self.assertIs(validate_model(model), model)
        self.assertEqual(self.result["report"]["model_type"], SEQUENCE_V1)

    def test_sequence_features_are_bounded_and_finite(self):
        rows = _validate_candles(_candles(400))
        samples = _feature_rows(rows, horizon=5, deadband_atr=0.1, window=6)
        self.assertGreater(len(samples), 0)
        for _index, _target, features, label in samples:
            self.assertEqual(len(features), 14)
            self.assertIn(label, (0, 1))
            self.assertTrue(all(math.isfinite(value) for value in features))
            self.assertTrue(all(-6.0 <= value <= 6.0 for value in features[:6]))

    def test_sequence_model_round_trips_through_json_and_predict(self):
        candles = _candles()
        before = predict(candles, self.model)
        self.assertIsNotNone(before)
        self.assertEqual(before["model_type"], SEQUENCE_V1)
        self.assertNotIn("probability_spread", before)
        restored = json.loads(json.dumps(self.model, allow_nan=False))
        after = predict(candles, restored)
        self.assertEqual(before["up_probability"], after["up_probability"])
        self.assertEqual(before["direction"], after["direction"])

    def test_sequence_window_is_bounded_and_checked_on_load(self):
        for window in (1, 41):
            with self.assertRaisesRegex(ValueError, "window must be between"):
                train_model(
                    _candles(),
                    min_samples=100,
                    epochs=1,
                    model_type=SEQUENCE_V1,
                    window=window,
                )
        broken = copy.deepcopy(self.model)
        broken["window"] = 3
        with self.assertRaisesRegex(ValueError, "feature schema"):
            validate_model(broken)
        broken = copy.deepcopy(self.model)
        del broken["window"]
        with self.assertRaisesRegex(ValueError, "sequence window"):
            validate_model(broken)


class ModelCompatibilityTest(unittest.TestCase):
    def test_v1_model_still_validates_and_predicts(self):
        result = train_model(_candles(), min_samples=100, epochs=3)
        model = result["model"]
        self.assertEqual(model["model_type"], MLP_V1)
        self.assertNotIn("members", model)
        self.assertNotIn("window", model)
        self.assertEqual(result["report"]["model_type"], MLP_V1)
        self.assertIs(validate_model(model), model)
        prediction = predict(_candles(), model)
        self.assertEqual(prediction["model_type"], MLP_V1)
        self.assertNotIn("probability_spread", prediction)

    def test_v1_training_is_deterministic_for_a_seed(self):
        first = train_model(_candles(), min_samples=100, epochs=3, seed=9)["model"]
        second = train_model(_candles(), min_samples=100, epochs=3, seed=9)["model"]
        self.assertEqual(first["weights_in"], second["weights_in"])
        self.assertEqual(first["bias_out"], second["bias_out"])

    def test_unknown_model_types_are_rejected(self):
        result = train_model(_candles(), min_samples=100, epochs=1)
        for bad in ("neezy_mlp_v9", "", None):
            model = copy.deepcopy(result["model"])
            model["model_type"] = bad
            with self.assertRaisesRegex(ValueError, "unsupported neural model type"):
                validate_model(model)
        with self.assertRaisesRegex(ValueError, "unsupported neural model type"):
            train_model(
                _candles(), min_samples=100, epochs=1, model_type="neezy_gbm_v1"
            )


if __name__ == "__main__":
    unittest.main()
