#!/usr/bin/env python3
"""Train, backtest, and upload non-promoted candidates from Colab/Kaggle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neezy_backend.brain import train_model  # noqa: E402
from neezy_backend.markets import PUBLIC_WS_URL, TIMEFRAMES  # noqa: E402
from neezy_backend.model_hub import (  # noqa: E402
    build_candidate_manifest,
    model_json_bytes,
    new_model_id,
)
from neezy_backend.model_validation import backtest_model  # noqa: E402
from neezy_backend.stream import fetch_history  # noqa: E402


def _write_json(path: Path, document: dict[str, Any]) -> bytes:
    content = (
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _upload(
    content: bytes,
    *,
    path_in_repo: str,
    repo_id: str,
    repo_type: str,
    token: str,
) -> None:
    # Imported only in the cloud training environment, never by the PC runtime.
    from huggingface_hub import upload_file

    upload_file(
        path_or_fileobj=content,
        path_in_repo=path_in_repo,
        repo_id=repo_id,
        repo_type=repo_type,
        token=token,
        commit_message=f"Add NEEZY artifact {path_in_repo}",
    )


def train_candidate(
    symbol: str,
    *,
    timeframe: str,
    candles: int,
    epochs: int,
    horizon: int,
    min_samples: int,
    seed: int,
    minimum_probability: float,
    spread: float,
    min_backtest_trades: int,
    output: Path,
) -> dict[str, Any]:
    """Return local artifact paths and metadata; never promotes ``latest``."""
    rows = fetch_history(symbol, TIMEFRAMES[timeframe], candles)
    if len(rows) < 400:
        raise ValueError(f"received {len(rows)} candles; at least 400 are required")
    trained = train_model(
        rows,
        symbol=symbol,
        timeframe=timeframe,
        horizon=horizon,
        min_samples=min_samples,
        epochs=epochs,
        seed=seed,
    )
    model = trained["model"]
    content = model_json_bytes(model)
    digest = hashlib.sha256(content).hexdigest()
    now = datetime.now(timezone.utc)
    model_id = new_model_id(model, digest, now=now)
    backtest = backtest_model(
        rows,
        model,
        minimum_probability=minimum_probability,
        spread=spread,
        min_trades=min_backtest_trades,
    )
    model_file = f"models/{model_id}.json"
    manifest = build_candidate_manifest(
        model,
        model_file=model_file,
        model_content=content,
        backtest=backtest,
        model_id=model_id,
    )
    dataset = {
        "schema": 1,
        "symbol": symbol,
        "timeframe": timeframe,
        "captured_at": now.isoformat(timespec="seconds"),
        "source": PUBLIC_WS_URL,
        "candles": rows,
        "candle_count": len(rows),
        "first_epoch": rows[0][0],
        "last_epoch": rows[-1][0],
        "ohlc_sha256": hashlib.sha256(
            json.dumps(rows, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    dataset_file = (
        f"datasets/{symbol}/{timeframe}/"
        f"{now.strftime('%Y%m%dT%H%M%SZ')}-{digest[:12]}.json"
    )
    destination = output / model_id
    _write_json(destination / "model.json", model)
    manifest_content = _write_json(destination / "manifest.json", manifest)
    dataset_content = _write_json(destination / "dataset.json", dataset)
    return {
        "model_id": model_id,
        "model_file": model_file,
        "manifest_file": f"manifests/{model_id}.json",
        "dataset_file": dataset_file,
        "model_content": content,
        "manifest_content": manifest_content,
        "dataset_content": dataset_content,
        "backtest_passed": backtest["passed"],
        "directory": destination,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["frxEURUSD"])
    parser.add_argument("--timeframe", choices=sorted(TIMEFRAMES), default="15m")
    parser.add_argument("--candles", type=int, default=5000)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--min-samples", type=int, default=200)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--minimum-probability", type=float, default=0.60)
    parser.add_argument(
        "--spread",
        type=float,
        default=0.0,
        help="assumed full spread in price units (not pips)",
    )
    parser.add_argument("--min-backtest-trades", type=int, default=20)
    parser.add_argument("--output", type=Path, default=Path("cloud-artifacts"))
    parser.add_argument("--hf-model-repo", default=os.environ.get("HF_MODEL_REPO", ""))
    parser.add_argument(
        "--hf-dataset-repo", default=os.environ.get("HF_DATASET_REPO", "")
    )
    parser.add_argument("--upload", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get("HF_TOKEN", "")
    if args.upload and (
        not token or not args.hf_model_repo or not args.hf_dataset_repo
    ):
        print(
            "--upload needs HF_TOKEN, HF_MODEL_REPO, and HF_DATASET_REPO "
            "in the environment (use notebook/CI secrets).",
            file=sys.stderr,
        )
        return 2

    failures = 0
    for symbol in dict.fromkeys(args.symbols):
        try:
            artifact = train_candidate(
                symbol,
                timeframe=args.timeframe,
                candles=args.candles,
                epochs=args.epochs,
                horizon=args.horizon,
                min_samples=args.min_samples,
                seed=args.seed,
                minimum_probability=args.minimum_probability,
                spread=args.spread,
                min_backtest_trades=args.min_backtest_trades,
                output=args.output,
            )
            if args.upload:
                _upload(
                    artifact["model_content"],
                    path_in_repo=artifact["model_file"],
                    repo_id=args.hf_model_repo,
                    repo_type="model",
                    token=token,
                )
                _upload(
                    artifact["manifest_content"],
                    path_in_repo=artifact["manifest_file"],
                    repo_id=args.hf_model_repo,
                    repo_type="model",
                    token=token,
                )
                _upload(
                    artifact["dataset_content"],
                    path_in_repo=artifact["dataset_file"],
                    repo_id=args.hf_dataset_repo,
                    repo_type="dataset",
                    token=token,
                )
            print(
                f"{symbol}: candidate {artifact['model_id']} saved to "
                f"{artifact['directory']}; backtest_passed="
                f"{artifact['backtest_passed']}; latest NOT changed"
            )
        except (OSError, RuntimeError, ValueError) as error:
            failures += 1
            print(f"{symbol}: training failed: {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
