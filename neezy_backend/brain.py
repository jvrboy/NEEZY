"""Small, local neural research models for candle direction.

Three transparent model types, all implemented with the standard library:

- ``neezy_mlp_v1``: one hidden layer over eight as-of candle features.
- ``neezy_mlp_ensemble_v1``: bagged v1 members, each trained on a bootstrap
  resample of the training partition. The reported probability is the member
  average; the standard deviation across members is ``probability_spread``, a
  rough uncertainty estimate.
- ``neezy_seq_mlp_v1``: the same MLP over the last ``window`` ATR-normalized log
  returns plus the eight v1 features.

Training is chronological, labels are defined only from future closes, and all
scaling is fitted on the training partition. It is an optional research feature:
it never changes the deterministic signal score or places trades.
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
MLP_V1 = "neezy_mlp_v1"
ENSEMBLE_V1 = "neezy_mlp_ensemble_v1"
SEQUENCE_V1 = "neezy_seq_mlp_v1"
MODEL_TYPES = (MLP_V1, ENSEMBLE_V1, SEQUENCE_V1)
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
ENSEMBLE_MEMBERS = 5
MAX_ENSEMBLE_MEMBERS = 25
SEQUENCE_WINDOW = 10
MIN_SEQUENCE_WINDOW = 2
MAX_SEQUENCE_WINDOW = 40
# ATR(50) and the 20-bar lookback need this many closed bars before a row is usable.
_WARMUP = 50


def sequence_feature_names(window: int) -> tuple[str, ...]:
    """Feature names for ``window`` lagged returns followed by the v1 features.

    ``window=0`` returns exactly ``FEATURE_NAMES``, so v1 and ensemble models share
    the same layout. Lag 0 is the most recent closed bar.
    """
    lagged = tuple(f"log_return_lag{offset}_atr" for offset in range(window))
    return lagged + FEATURE_NAMES


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


def _indicator_arrays(rows: Sequence[tuple[float, ...]]) -> dict[str, Any]:
    opens = [row[1] for row in rows]
    highs = [row[2] for row in rows]
    lows = [row[3] for row in rows]
    closes = [row[4] for row in rows]
    return {
        "opens": opens,
        "highs": highs,
        "lows": lows,
        "closes": closes,
        "ema9": ema(closes, 9),
        "ema21": ema(closes, 21),
        "rsi14": rsi_series(closes, 14),
        "atr14": _atr_series(highs, lows, closes, 14),
        "atr50": _atr_series(highs, lows, closes, 50),
    }


def _as_of_features(
    series: dict[str, Any], index: int, window: int
) -> tuple[list[float], float] | None:
    """Features known at ``index``, plus the ATR scale; None during warm-up."""
    closes = series["closes"]
    average = series["atr14"][index]
    long_average = series["atr50"][index]
    oscillator = series["rsi14"][index]
    if not average or not long_average or oscillator is None:
        return None
    scale = max(average, closes[index] * 1e-8)
    features: list[float] = []
    if window:
        # Log return of each bar, expressed in units of the current ATR as a
        # fraction of price, so the scale is comparable across symbols.
        atr_fraction = average / closes[index]
        for offset in range(window):
            bar = index - offset
            features.append(
                _clamp(math.log(closes[bar] / closes[bar - 1]) / atr_fraction)
            )
    features.extend(
        [
            _clamp((closes[index] - closes[index - 1]) / scale),
            _clamp((closes[index] - closes[index - 5]) / scale),
            _clamp((closes[index] - closes[index - 20]) / scale),
            _clamp((series["ema9"][index] - series["ema21"][index]) / scale),
            _clamp((oscillator - 50.0) / 25.0, -2.0, 2.0),
            _clamp((series["highs"][index] - series["lows"][index]) / scale, 0.0, 6.0),
            _clamp((closes[index] - series["opens"][index]) / scale),
            _clamp(average / long_average - 1.0, -3.0, 3.0),
        ]
    )
    return features, scale


def _feature_rows(
    rows: Sequence[tuple[float, ...]],
    *,
    horizon: int,
    deadband_atr: float,
    window: int = 0,
) -> list[tuple[int, int, list[float], int]]:
    """Build as-of features and future-direction labels without look-ahead."""
    if len(rows) < 80:
        return []
    series = _indicator_arrays(rows)
    closes = series["closes"]
    samples = []
    # Leave the final row out: desktop streams persist the currently forming bar.
    for index in range(_WARMUP, len(rows) - horizon - 1):
        built = _as_of_features(series, index, window)
        if built is None:
            continue
        features, scale = built
        future_move = closes[index + horizon] - closes[index]
        threshold = deadband_atr * scale
        if future_move > threshold:
            label = 1
        elif future_move < -threshold:
            label = 0
        else:
            continue
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


def _member_probabilities(
    features: Sequence[float], model: dict[str, Any]
) -> list[float]:
    members = model["members"] if "members" in model else [model]
    return [
        _forward(
            features,
            member["weights_in"],
            member["bias_in"],
            member["weights_out"],
            member["bias_out"],
        )[1]
        for member in members
    ]


def _summarize(probabilities: Sequence[float]) -> tuple[float, float]:
    mean = sum(probabilities) / len(probabilities)
    spread = math.sqrt(
        sum((value - mean) ** 2 for value in probabilities) / len(probabilities)
    )
    return mean, spread


def _score_normalized(
    features: Sequence[float], model: dict[str, Any]
) -> tuple[float, float]:
    """Mean up-probability and member spread for already-standardized features."""
    return _summarize(_member_probabilities(features, model))


def _score(raw: Sequence[float], model: dict[str, Any]) -> tuple[float, float]:
    scaled = [
        (value - mean) / scale
        for value, mean, scale in zip(raw, model["means"], model["scales"], strict=True)
    ]
    return _score_normalized(scaled, model)


def _probability(raw: Sequence[float], model: dict[str, Any]) -> float:
    return _score(raw, model)[0]


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
    scorer = _score_normalized if normalized else _score
    scored = [scorer(features, model) for features, _label in rows]
    probabilities = [probability for probability, _spread in scored]
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
    metrics: dict[str, Any] = {
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
    if "members" in model:
        spreads = [spread for _probability_value, spread in scored]
        metrics["mean_probability_spread"] = round(sum(spreads) / len(spreads), 4)
    return metrics


def _chronological_splits(
    examples: Sequence[tuple[int, int, list[float], int]], row_count: int
) -> tuple[
    list[tuple[list[float], int]],
    list[tuple[list[float], int]],
    list[tuple[list[float], int]],
]:
    """Split labeled rows by time, purging rows whose label crosses a boundary."""
    train_boundary = int(row_count * 0.70)
    validation_boundary = int(row_count * 0.85)
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
    return train, validation, test


def _standardize(
    train: Sequence[tuple[list[float], int]],
    validation: Sequence[tuple[list[float], int]],
    test: Sequence[tuple[list[float], int]],
    *,
    input_dim: int,
) -> tuple[
    list[float],
    list[float],
    list[tuple[list[float], int]],
    list[tuple[list[float], int]],
    list[tuple[list[float], int]],
]:
    """Fit mean and scale on the training partition only, then apply to all."""
    means = [
        sum(features[index] for features, _label in train) / len(train)
        for index in range(input_dim)
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

    return (
        means,
        scales,
        [normalize(row) for row in train],
        [normalize(row) for row in validation],
        [normalize(row) for row in test],
    )


def _fit_member(
    train: Sequence[tuple[list[float], int]],
    validation: Sequence[tuple[list[float], int]],
    *,
    input_dim: int,
    rng: random.Random,
    epochs: int,
) -> tuple[dict[str, Any], int]:
    """Train one one-hidden-layer MLP with early stopping on validation log loss."""
    weights_in = [
        [rng.uniform(-0.15, 0.15) for _ in range(input_dim)]
        for _ in range(HIDDEN_UNITS)
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
            grad_in = [[0.0] * input_dim for _ in range(HIDDEN_UNITS)]
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
                for feature_index in range(input_dim):
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
    return (
        {
            "weights_in": weights_in,
            "bias_in": bias_in,
            "weights_out": weights_out,
            "bias_out": bias_out,
        },
        epochs_run,
    )


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
    model_type: str = MLP_V1,
    members: int = ENSEMBLE_MEMBERS,
    window: int = SEQUENCE_WINDOW,
) -> dict[str, Any]:
    """Train a compact MLP and report a chronological, untouched test partition.

    Each output probability estimates the direction of an ``horizon``-bar move
    that clears the ATR deadband, conditional on the move being non-neutral.
    The final input candle is intentionally ignored because it may be in flight.

    ``model_type`` selects the layout: ``neezy_mlp_v1`` (default),
    ``neezy_mlp_ensemble_v1`` (``members`` bagged MLPs), or
    ``neezy_seq_mlp_v1`` (``window`` lagged log returns plus the v1 features).
    """
    if model_type not in MODEL_TYPES:
        raise ValueError("unsupported neural model type")
    if horizon < 1 or horizon > 100:
        raise ValueError("horizon must be between 1 and 100 candles")
    if not math.isfinite(deadband_atr) or not 0 <= deadband_atr <= 5:
        raise ValueError("deadband_atr must be between 0 and 5")
    if min_samples < 60 or min_samples > 100_000:
        raise ValueError("min_samples must be between 60 and 100000")
    if epochs < 1 or epochs > 500:
        raise ValueError("epochs must be between 1 and 500")
    if model_type == ENSEMBLE_V1 and not 2 <= members <= MAX_ENSEMBLE_MEMBERS:
        raise ValueError(
            f"members must be between 2 and {MAX_ENSEMBLE_MEMBERS} for an ensemble"
        )
    if model_type == SEQUENCE_V1 and not (
        MIN_SEQUENCE_WINDOW <= window <= MAX_SEQUENCE_WINDOW
    ):
        raise ValueError(
            f"window must be between {MIN_SEQUENCE_WINDOW} and {MAX_SEQUENCE_WINDOW}"
        )
    rows = _validate_candles(candles)
    window_size = window if model_type == SEQUENCE_V1 else 0
    names = sequence_feature_names(window_size)
    examples = _feature_rows(
        rows, horizon=horizon, deadband_atr=deadband_atr, window=window_size
    )
    if len(examples) < min_samples:
        raise ValueError(
            f"not enough labeled examples: got {len(examples)}, need {min_samples}; "
            "save more historical candles or lower the ATR deadband"
        )

    train, validation, test = _chronological_splits(examples, len(rows))
    if len(train) < 40 or len(validation) < 10 or len(test) < 10:
        raise ValueError(
            "not enough samples in chronological train/validation/test splits"
        )
    if len({label for _features, label in train}) < 2:
        raise ValueError("training history contains only one direction class")

    means, scales, train, validation, test = _standardize(
        train, validation, test, input_dim=len(names)
    )

    rng = random.Random(seed)
    if model_type == ENSEMBLE_V1:
        fitted: list[dict[str, Any]] = []
        epochs_run = 0
        for _member in range(members):
            # Bagging: each member sees a bootstrap resample of the training rows.
            resample = [train[rng.randrange(len(train))] for _ in range(len(train))]
            parameters, ran = _fit_member(
                resample, validation, input_dim=len(names), rng=rng, epochs=epochs
            )
            fitted.append(parameters)
            epochs_run = max(epochs_run, ran)
        layout: dict[str, Any] = {"members": fitted}
    else:
        layout, epochs_run = _fit_member(
            train, validation, input_dim=len(names), rng=rng, epochs=epochs
        )

    model: dict[str, Any] = {
        "schema": MODEL_SCHEMA,
        "model_type": model_type,
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_names": list(names),
        "horizon": horizon,
        "deadband_atr": deadband_atr,
        "means": means,
        "scales": scales,
        **layout,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "train_samples": len(train),
        "validation_samples": len(validation),
        "test_samples": len(test),
        "epochs": epochs_run,
    }
    if model_type == SEQUENCE_V1:
        model["window"] = window
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
    report: dict[str, Any] = {
        "symbol": symbol,
        "timeframe": timeframe,
        "model_type": model_type,
        "horizon": horizon,
        "deadband_atr": deadband_atr,
        "labeled_examples": len(examples),
        "train": train_metrics,
        "validation": validation_metrics,
        "test": test_metrics,
        "epochs": epochs_run,
        "deployment_ready": model["deployment_ready"],
        "validation_note": model["validation_note"],
    }
    if model_type == ENSEMBLE_V1:
        report["members"] = len(fitted)
    return {"model": model, "report": report}


def _finite_numbers(values: Sequence[Any]) -> bool:
    return all(
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        for value in values
    )


def _require_vector(value: Any, length: int, key: str) -> None:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"neural model {key} has the wrong dimensions")
    if not _finite_numbers(value):
        raise ValueError("neural model contains invalid weights")


def _validate_member(member: Any, input_dim: int) -> None:
    if not isinstance(member, dict):
        raise ValueError("neural model member is malformed")
    rows = member.get("weights_in")
    if not isinstance(rows, list) or len(rows) != HIDDEN_UNITS:
        raise ValueError("neural model weights_in has the wrong dimensions")
    if any(not isinstance(row, list) or len(row) != input_dim for row in rows):
        raise ValueError("neural model input weights have the wrong dimensions")
    _require_vector(member.get("bias_in"), HIDDEN_UNITS, "bias_in")
    _require_vector(member.get("weights_out"), HIDDEN_UNITS, "weights_out")
    if not _finite_numbers([member.get("bias_out")]):
        raise ValueError("neural model contains invalid weights")
    if not _finite_numbers([value for row in rows for value in row]):
        raise ValueError("neural model contains invalid weights")


def validate_model(model: dict[str, Any]) -> dict[str, Any]:
    """Validate a stored model document before any weight is used."""
    if not isinstance(model, dict) or model.get("schema") != MODEL_SCHEMA:
        raise ValueError("unsupported neural model schema")
    model_type = model.get("model_type")
    if model_type not in MODEL_TYPES:
        raise ValueError("unsupported neural model type")
    window = 0
    if model_type == SEQUENCE_V1:
        window = model.get("window")
        if (
            isinstance(window, bool)
            or not isinstance(window, int)
            or not MIN_SEQUENCE_WINDOW <= window <= MAX_SEQUENCE_WINDOW
        ):
            raise ValueError("neural model sequence window is invalid")
    names = sequence_feature_names(window)
    if model.get("feature_names") != list(names):
        raise ValueError("neural model feature schema does not match")
    _require_vector(model.get("means"), len(names), "means")
    _require_vector(model.get("scales"), len(names), "scales")
    if any(scale <= 0 for scale in model["scales"]):
        raise ValueError("neural model scales must be positive")
    if model_type == ENSEMBLE_V1:
        members = model.get("members")
        if (
            not isinstance(members, list)
            or not 2 <= len(members) <= MAX_ENSEMBLE_MEMBERS
        ):
            raise ValueError("neural ensemble has the wrong member count")
        for member in members:
            _validate_member(member, len(names))
    else:
        _validate_member(model, len(names))
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
    # extracting features.
    closed = rows[:-1]
    if len(closed) < 80:
        return None
    window = int(model["window"]) if model["model_type"] == SEQUENCE_V1 else 0
    series = _indicator_arrays(closed)
    built = _as_of_features(series, len(closed) - 1, window)
    if built is None:
        return None
    features, _scale = built
    probability, spread = _score(features, model)
    ready = bool(model.get("deployment_ready", False))
    direction = (
        "BUY"
        if ready and probability >= minimum_probability
        else "SELL"
        if ready and probability <= 1.0 - minimum_probability
        else "NEUTRAL"
    )
    result: dict[str, Any] = {
        "symbol": model.get("symbol", ""),
        "timeframe": model.get("timeframe", ""),
        "model_type": model["model_type"],
        "direction": direction,
        "up_probability": round(probability, 4),
        "down_probability": round(1.0 - probability, 4),
        "minimum_probability": minimum_probability,
        "deployment_ready": ready,
        "test_metrics": model.get("test_metrics", {}),
        "validation_note": model.get("validation_note", "Research-only model."),
        "horizon": model["horizon"],
    }
    if "members" in model:
        result["probability_spread"] = round(spread, 4)
    return result
