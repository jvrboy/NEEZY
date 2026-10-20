"""Small, local neural research model for candle direction.

This is a transparent one-hidden-layer MLP implemented with the standard
library. Training is chronological, labels are defined only from future closes,
and all scaling is fitted on the training partition. It is an optional research
feature: it never changes the deterministic signal score or places trades.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from .indicators import ema, rsi_series

Candle = Sequence[float]
MODEL_SCHEMA = 1
FEATURE_NAMES = (
    "return_1_atr",
    "return_5_atr",
    "return_20_atr",
    "ema_9_21_atr",
    "rsi_centered",
    "range_atr",
    "body_atr",
    "atr_14_50_ratio",
)
HIDDEN_UNITS = 8


def _validate_candles(candles: Sequence[Candle]) -> list[tuple[float, ...]]:
    rows: list[tuple[float, ...]] = []
    previous_epoch: float | None = None
    for row in candles:
        if len(row) < 5:
            raise ValueError(
                "each candle must contain timestamp, open, high, low, close"
            )
        values = tuple(float(value) for value in row[:5])
        if not all(math.isfinite(value) for value in values):
            raise ValueError("candle values must be finite numbers")
        epoch, open_, high, low, close = values
        if min(open_, high, low, close) <= 0 or high < max(open_, close):
            raise ValueError("candle OHLC values are inconsistent")
        if low > min(open_, close) or high < low:
            raise ValueError("candle OHLC values are inconsistent")
        if previous_epoch is not None and epoch <= previous_epoch:
            raise ValueError("candles must be ordered by strictly increasing time")
        previous_epoch = epoch
        rows.append(values)
    return rows


def _atr_series(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int
) -> list[float | None]:
    ranges = [highs[0] - lows[0]]
    for index in range(1, len(closes)):
        ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    values: list[float | None] = [None] * len(closes)
    if len(ranges) < period:
        return values
    average = sum(ranges[:period]) / period
    values[period - 1] = average
    for index in range(period, len(ranges)):
        average = (average * (period - 1) + ranges[index]) / period
        values[index] = average
    return values


def _clamp(value: float, low: float = -6.0, high: float = 6.0) -> float:
    return min(max(value, low), high)


def _feature_rows(
    rows: Sequence[tuple[float, ...]],
    *,
    horizon: int,
    deadband_atr: float,
) -> list[tuple[int, int, list[float], int]]:
    """Build as-of features and future-direction labels without look-ahead."""
    if len(rows) < 80:
        return []
    opens = [row[1] for row in rows]
    highs = [row[2] for row in rows]
    lows = [row[3] for row in rows]
    closes = [row[4] for row in rows]
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    rsi14 = rsi_series(closes, 14)
    atr14 = _atr_series(highs, lows, closes, 14)
    atr50 = _atr_series(highs, lows, closes, 50)
    samples = []
    # Leave the final row out: desktop streams persist the currently forming bar.
    for index in range(50, len(rows) - horizon - 1):
        average = atr14[index]
        long_average = atr50[index]
        oscillator = rsi14[index]
        if not average or not long_average or oscillator is None:
            continue
        scale = max(average, closes[index] * 1e-8)
        future_move = closes[index + horizon] - closes[index]
        threshold = deadband_atr * scale
        if future_move > threshold:
            label = 1
        elif future_move < -threshold:
            label = 0
        else:
            continue
        features = [
            _clamp((closes[index] - closes[index - 1]) / scale),
            _clamp((closes[index] - closes[index - 5]) / scale),
            _clamp((closes[index] - closes[index - 20]) / scale),
            _clamp((ema9[index] - ema21[index]) / scale),
            _clamp((oscillator - 50.0) / 25.0, -2.0, 2.0),
            _clamp((highs[index] - lows[index]) / scale, 0.0, 6.0),
            _clamp((closes[index] - opens[index]) / scale),
            _clamp(average / long_average - 1.0, -3.0, 3.0),
        ]
        if all(math.isfinite(value) for value in features):
            samples.append((index, index + horizon, features, label))
    return samples


def _sigmoid(value: float) -> float:
    value = min(max(value, -30.0), 30.0)
    return 1.0 / (1.0 + math.exp(-value))


def _forward(
    features: Sequence[float],
    weights_in: Sequence[Sequence[float]],
    bias_in: Sequence[float],
    weights_out: Sequence[float],
    bias_out: float,
) -> tuple[list[float], float]:
    hidden = [
        math.tanh(
            bias_in[h]
            + sum(w * x for w, x in zip(weights_in[h], features, strict=True))
        )
        for h in range(len(bias_in))
    ]
    probability = _sigmoid(
        bias_out + sum(w * h for w, h in zip(weights_out, hidden, strict=True))
    )
    return hidden, probability


def _probability(raw: Sequence[float], model: dict[str, Any]) -> float:
    scaled = [
        (value - mean) / scale
        for value, mean, scale in zip(raw, model["means"], model["scales"], strict=True)
    ]
    _hidden, probability = _forward(
        scaled,
        model["weights_in"],
        model["bias_in"],
        model["weights_out"],
        model["bias_out"],
    )
    return probability


def _metrics(
    rows: Sequence[tuple[list[float], int]],
    model: dict[str, Any],
    *,
    normalized: bool = False,
) -> dict[str, Any]:
    if not rows:
        return {
            "samples": 0,
            "accuracy": None,
            "balanced_accuracy": None,
            "baseline_accuracy": None,
            "brier_score": None,
            "log_loss": None,
            "up_fraction": None,
        }
    labels = [label for _features, label in rows]
    if normalized:
        probabilities = [
            _forward(
                features,
                model["weights_in"],
                model["bias_in"],
                model["weights_out"],
                model["bias_out"],
            )[1]
            for features, _label in rows
        ]
    else:
        probabilities = [_probability(features, model) for features, _label in rows]
    predictions = [int(probability >= 0.5) for probability in probabilities]
    correct = sum(
        pred == label for pred, label in zip(predictions, labels, strict=True)
    )
    class_recalls = []
    for category in (0, 1):
        chosen = [
            pred == category
            for pred, label in zip(predictions, labels, strict=True)
            if label == category
        ]
        if chosen:
            class_recalls.append(sum(chosen) / len(chosen))
    baseline = max(labels.count(0), labels.count(1)) / len(labels)
    epsilon = 1e-12
    loss = -sum(
        label * math.log(max(probability, epsilon))
        + (1 - label) * math.log(max(1.0 - probability, epsilon))
        for probability, label in zip(probabilities, labels, strict=True)
    ) / len(labels)
    brier = sum(
        (probability - label) ** 2
        for probability, label in zip(probabilities, labels, strict=True)
    ) / len(labels)
    return {
        "samples": len(rows),
        "accuracy": round(correct / len(rows), 4),
        "balanced_accuracy": round(sum(class_recalls) / len(class_recalls), 4)
        if class_recalls
        else None,
        "baseline_accuracy": round(baseline, 4),
        "brier_score": round(brier, 4),
        "log_loss": round(loss, 4),
        "up_fraction": round(sum(labels) / len(labels), 4),
    }


def train_model(
    candles: Sequence[Candle],
    *,
    symbol: str = "",
    timeframe: str = "",
    horizon: int = 5,
    deadband_atr: float = 0.1,
    min_samples: int = 200,
    epochs: int = 60,
    seed: int = 17,
) -> dict[str, Any]:
    """Train a compact MLP and report a chronological, untouched test partition.

    Each output probability estimates the direction of an ``horizon``-bar move
    that clears the ATR deadband, conditional on the move being non-neutral.
    The final input candle is intentionally ignored because it may be in flight.
    """
    if horizon < 1 or horizon > 100:
        raise ValueError("horizon must be between 1 and 100 candles")
    if not math.isfinite(deadband_atr) or not 0 <= deadband_atr <= 5:
        raise ValueError("deadband_atr must be between 0 and 5")
    if min_samples < 60 or min_samples > 100_000:
        raise ValueError("min_samples must be between 60 and 100000")
    if epochs < 1 or epochs > 500:
        raise ValueError("epochs must be between 1 and 500")
    rows = _validate_candles(candles)
    examples = _feature_rows(rows, horizon=horizon, deadband_atr=deadband_atr)
    if len(examples) < min_samples:
        raise ValueError(
            f"not enough labeled examples: got {len(examples)}, need {min_samples}; "
            "save more historical candles or lower the ATR deadband"
        )

    train_boundary = int(len(rows) * 0.70)
    validation_boundary = int(len(rows) * 0.85)
    train = [
        (features, label)
        for _source, target, features, label in examples
        if target < train_boundary
    ]
    validation = [
        (features, label)
        for source, target, features, label in examples
        if source >= train_boundary and target < validation_boundary
    ]
    test = [
        (features, label)
        for source, _target, features, label in examples
        if source >= validation_boundary
    ]
    if len(train) < 40 or len(validation) < 10 or len(test) < 10:
        raise ValueError(
            "not enough samples in chronological train/validation/test splits"
        )
    if len({label for _features, label in train}) < 2:
        raise ValueError("training history contains only one direction class")

    means = [
        sum(features[index] for features, _label in train) / len(train)
        for index in range(len(FEATURE_NAMES))
    ]
    scales = []
    for index, mean in enumerate(means):
        variance = sum(
            (features[index] - mean) ** 2 for features, _label in train
        ) / len(train)
        scales.append(max(math.sqrt(variance), 1e-6))

    def normalize(sample: tuple[list[float], int]) -> tuple[list[float], int]:
        features, label = sample
        return (
            [
                max(-8.0, min(8.0, (value - mean) / scale))
                for value, mean, scale in zip(features, means, scales, strict=True)
            ],
            label,
        )

    train = [normalize(row) for row in train]
    validation = [normalize(row) for row in validation]
    test = [normalize(row) for row in test]

    rng = random.Random(seed)
    weights_in = [
        [rng.uniform(-0.15, 0.15) for _ in FEATURE_NAMES] for _ in range(HIDDEN_UNITS)
    ]
    bias_in = [0.0] * HIDDEN_UNITS
    weights_out = [rng.uniform(-0.15, 0.15) for _ in range(HIDDEN_UNITS)]
    bias_out = 0.0
    learning_rate = 0.02
    weight_decay = 0.001
    batch_size = 32
    best_loss = math.inf
    best_parameters: (
        tuple[list[list[float]], list[float], list[float], float] | None
    ) = None
    stale_epochs = 0
    epochs_run = 0

    for epoch in range(epochs):
        order = list(range(len(train)))
        rng.shuffle(order)
        for start in range(0, len(order), batch_size):
            batch = [train[index] for index in order[start : start + batch_size]]
            grad_in = [[0.0] * len(FEATURE_NAMES) for _ in range(HIDDEN_UNITS)]
            grad_bias_in = [0.0] * HIDDEN_UNITS
            grad_out = [0.0] * HIDDEN_UNITS
            grad_bias_out = 0.0
            for features, label in batch:
                hidden, probability = _forward(
                    features, weights_in, bias_in, weights_out, bias_out
                )
                output_delta = probability - label
                grad_bias_out += output_delta
                for h in range(HIDDEN_UNITS):
                    grad_out[h] += output_delta * hidden[h]
                    hidden_delta = (
                        output_delta * weights_out[h] * (1.0 - hidden[h] ** 2)
                    )
                    grad_bias_in[h] += hidden_delta
                    for feature_index, value in enumerate(features):
                        grad_in[h][feature_index] += hidden_delta * value
            divisor = float(len(batch))
            for h in range(HIDDEN_UNITS):
                for feature_index in range(len(FEATURE_NAMES)):
                    weights_in[h][feature_index] -= learning_rate * (
                        grad_in[h][feature_index] / divisor
                        + weight_decay * weights_in[h][feature_index]
                    )
                bias_in[h] -= learning_rate * grad_bias_in[h] / divisor
                weights_out[h] -= learning_rate * (
                    grad_out[h] / divisor + weight_decay * weights_out[h]
                )
            bias_out -= learning_rate * grad_bias_out / divisor

        candidate = {
            "means": means,
            "scales": scales,
            "weights_in": weights_in,
            "bias_in": bias_in,
            "weights_out": weights_out,
            "bias_out": bias_out,
        }
        validation_loss = _metrics(validation, candidate, normalized=True)["log_loss"]
        epochs_run = epoch + 1
        if validation_loss is not None and validation_loss < best_loss - 1e-5:
            best_loss = validation_loss
            best_parameters = (
                [row[:] for row in weights_in],
                bias_in[:],
                weights_out[:],
                bias_out,
            )
            stale_epochs = 0
        else:
            stale_epochs += 1
            if stale_epochs >= 10:
                break

    if best_parameters is None:
        raise RuntimeError(
            "neural training failed to produce a finite validation score"
        )
    weights_in, bias_in, weights_out, bias_out = best_parameters
    model = {
        "schema": MODEL_SCHEMA,
        "model_type": "neezy_mlp_v1",
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_names": list(FEATURE_NAMES),
        "horizon": horizon,
        "deadband_atr": deadband_atr,
        "means": means,
        "scales": scales,
        "weights_in": weights_in,
        "bias_in": bias_in,
        "weights_out": weights_out,
        "bias_out": bias_out,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_samples": len(train),
        "validation_samples": len(validation),
        "test_samples": len(test),
        "epochs": epochs_run,
    }
    train_metrics = _metrics(train, model, normalized=True)
    validation_metrics = _metrics(validation, model, normalized=True)
    test_metrics = _metrics(test, model, normalized=True)
    baseline = test_metrics["baseline_accuracy"] or 0.0
    balanced = test_metrics["balanced_accuracy"] or 0.0
    model["test_metrics"] = test_metrics
    model["deployment_ready"] = bool(
        test_metrics["samples"] >= 50
        and balanced >= 0.55
        and test_metrics["accuracy"] is not None
        and test_metrics["accuracy"] >= baseline
    )
    model["validation_note"] = (
        "Chronological holdout has promising directional discrimination; continue "
        "monitoring live outcomes."
        if model["deployment_ready"]
        else "Research-only: held-out evidence is not strong enough to qualify this "
        "model for directional use."
    )
    return {
        "model": model,
        "report": {
            "symbol": symbol,
            "timeframe": timeframe,
            "horizon": horizon,
            "deadband_atr": deadband_atr,
            "labeled_examples": len(examples),
            "train": train_metrics,
            "validation": validation_metrics,
            "test": test_metrics,
            "epochs": epochs_run,
            "deployment_ready": model["deployment_ready"],
            "validation_note": model["validation_note"],
        },
    }


def validate_model(model: dict[str, Any]) -> dict[str, Any]:
    """Validate a stored model document before any weight is used."""
    if not isinstance(model, dict) or model.get("schema") != MODEL_SCHEMA:
        raise ValueError("unsupported neural model schema")
    if model.get("model_type") != "neezy_mlp_v1":
        raise ValueError("unsupported neural model type")
    dimensions = {
        "means": len(FEATURE_NAMES),
        "scales": len(FEATURE_NAMES),
        "weights_in": HIDDEN_UNITS,
        "bias_in": HIDDEN_UNITS,
        "weights_out": HIDDEN_UNITS,
    }
    if model.get("feature_names") != list(FEATURE_NAMES):
        raise ValueError("neural model feature schema does not match")
    for key, length in dimensions.items():
        value = model.get(key)
        if not isinstance(value, list) or len(value) != length:
            raise ValueError(f"neural model {key} has the wrong dimensions")
    if any(
        not isinstance(row, list) or len(row) != len(FEATURE_NAMES)
        for row in model["weights_in"]
    ):
        raise ValueError("neural model input weights have the wrong dimensions")
    numeric = [
        *model["means"],
        *model["scales"],
        *model["bias_in"],
        *model["weights_out"],
        model.get("bias_out"),
    ]
    numeric.extend(value for row in model["weights_in"] for value in row)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in numeric
    ):
        raise ValueError("neural model contains invalid weights")
    if any(scale <= 0 for scale in model["scales"]):
        raise ValueError("neural model scales must be positive")
    return model


def predict(
    candles: Sequence[Candle],
    model: dict[str, Any],
    *,
    minimum_probability: float = 0.60,
) -> dict[str, Any] | None:
    """Predict on the latest fully-formed candle features, if they are available."""
    validate_model(model)
    if not math.isfinite(minimum_probability) or not 0.5 < minimum_probability < 1.0:
        raise ValueError("minimum_probability must be between 0.5 and 1")
    rows = _validate_candles(candles)
    # For prediction, no future label is needed. Remove the active final bar before
    # extracting features and use one synthetic future slot to preserve the same
    # feature function and label-independent calculation path.
    closed = rows[:-1]
    if len(closed) < 80:
        return None
    latest_index = len(closed) - 1
    opens = [row[1] for row in closed]
    highs = [row[2] for row in closed]
    lows = [row[3] for row in closed]
    closes = [row[4] for row in closed]
    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    rsi14 = rsi_series(closes, 14)
    atr14 = _atr_series(highs, lows, closes, 14)
    atr50 = _atr_series(highs, lows, closes, 50)
    average, long_average, oscillator = (
        atr14[latest_index],
        atr50[latest_index],
        rsi14[latest_index],
    )
    if not average or not long_average or oscillator is None:
        return None
    scale = max(average, closes[latest_index] * 1e-8)
    features = [
        _clamp((closes[latest_index] - closes[latest_index - 1]) / scale),
        _clamp((closes[latest_index] - closes[latest_index - 5]) / scale),
        _clamp((closes[latest_index] - closes[latest_index - 20]) / scale),
        _clamp((ema9[latest_index] - ema21[latest_index]) / scale),
        _clamp((oscillator - 50.0) / 25.0, -2.0, 2.0),
        _clamp((highs[latest_index] - lows[latest_index]) / scale, 0.0, 6.0),
        _clamp((closes[latest_index] - opens[latest_index]) / scale),
        _clamp(average / long_average - 1.0, -3.0, 3.0),
    ]
    probability = _probability(features, model)
    ready = bool(model.get("deployment_ready", False))
    direction = (
        "BUY"
        if ready and probability >= minimum_probability
        else "SELL"
        if ready and probability <= 1.0 - minimum_probability
        else "NEUTRAL"
    )
    return {
        "symbol": model.get("symbol", ""),
        "timeframe": model.get("timeframe", ""),
        "direction": direction,
        "up_probability": round(probability, 4),
        "down_probability": round(1.0 - probability, 4),
        "minimum_probability": minimum_probability,
        "deployment_ready": ready,
        "test_metrics": model.get("test_metrics", {}),
        "validation_note": model.get("validation_note", "Research-only model."),
        "horizon": model["horizon"],
    }
