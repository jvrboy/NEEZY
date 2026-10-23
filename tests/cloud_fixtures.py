"""Small valid JSON models and candles for cloud/executor tests."""

from __future__ import annotations

import math

from neezy_backend.brain import FEATURE_NAMES, HIDDEN_UNITS, MLP_V1
from neezy_backend.model_hub import (
    attach_paper_evidence,
    build_candidate_manifest,
    model_json_bytes,
)


def valid_model(symbol="frxEURUSD", timeframe="15m", *, bias_out=20.0, ready=True):
    return {
        "schema": 1,
        "model_type": MLP_V1,
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_names": list(FEATURE_NAMES),
        "horizon": 5,
        "deadband_atr": 0.1,
        "means": [0.0] * len(FEATURE_NAMES),
        "scales": [1.0] * len(FEATURE_NAMES),
        "weights_in": [[0.0] * len(FEATURE_NAMES) for _ in range(HIDDEN_UNITS)],
        "bias_in": [0.0] * HIDDEN_UNITS,
        "weights_out": [0.0] * HIDDEN_UNITS,
        "bias_out": bias_out,
        "trained_at": "2026-10-23T00:00:00+00:00",
        "deployment_ready": ready,
        "test_metrics": {
            "samples": 100,
            "accuracy": 0.60,
            "balanced_accuracy": 0.60,
            "baseline_accuracy": 0.50,
        },
    }


def model_and_manifest(
    *,
    model_id="frxeurusd-15m-20261023t000000z-abcdef123456",
    paper=True,
    model=None,
):
    model = model or valid_model()
    content = model_json_bytes(model)
    digest = __import__("hashlib").sha256(content).hexdigest()
    manifest = build_candidate_manifest(
        model,
        model_file=f"models/{model_id}.json",
        model_content=content,
        backtest={
            "passed": True,
            "method": "chronological_held_out_trade_backtest_v1",
            "trades": 30,
            "expectancy_r": 0.15,
        },
        model_id=model_id,
    )
    if paper:
        manifest = attach_paper_evidence(
            manifest,
            {
                "passed": True,
                "trades": 30,
                "days": 14,
                "model_sha256": digest,
            },
        )
    return model, content, manifest


def candles(count=400):
    rows = []
    previous = 1.1
    for index in range(count):
        close = 1.1 + index * 0.0001 + math.sin(index / 13) * 0.001
        open_ = previous
        rows.append(
            (
                1_700_000_000 + index * 900,
                open_,
                max(open_, close) + 0.0004,
                min(open_, close) - 0.0004,
                close,
            )
        )
        previous = close
    return rows
