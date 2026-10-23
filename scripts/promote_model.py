#!/usr/bin/env python3
"""Deliberately promote an exact HF candidate after paper-trading validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neezy_backend.model_hub import (  # noqa: E402
    MAX_MANIFEST_BYTES,
    MAX_MODEL_BYTES,
    HuggingFaceDownloader,
    attach_paper_evidence,
    evaluate_model_gate,
    latest_manifest_path,
    safe_repo_path,
)


def _object(content: bytes, label: str) -> dict[str, Any]:
    document = json.loads(content.decode("utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return document


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hf-model-repo", required=True)
    parser.add_argument(
        "--candidate",
        required=True,
        help="candidate manifest path, for example manifests/frx....json",
    )
    parser.add_argument("--paper-report", type=Path, required=True)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--min-test-samples", type=int, default=50)
    parser.add_argument("--min-balanced-accuracy", type=float, default=0.55)
    parser.add_argument("--min-backtest-trades", type=int, default=20)
    parser.add_argument("--min-paper-trades", type=int, default=20)
    parser.add_argument("--min-paper-days", type=int, default=14)
    parser.add_argument("--output", type=Path, help="optionally save promoted manifest")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="upload latest.json; without this flag the command is a dry run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get("HF_TOKEN")
    if args.promote and not token:
        print("--promote requires HF_TOKEN in the environment.", file=sys.stderr)
        return 2
    try:
        downloader = HuggingFaceDownloader(
            args.hf_model_repo,
            revision=args.revision,
            token=token,
        )
        candidate_path = safe_repo_path(args.candidate)
        manifest = _object(
            downloader.download(candidate_path, max_bytes=MAX_MANIFEST_BYTES),
            "candidate manifest",
        )
        model_path = safe_repo_path(manifest.get("model_file", ""))
        model_content = downloader.download(model_path, max_bytes=MAX_MODEL_BYTES)
        if hashlib.sha256(model_content).hexdigest() != manifest.get("model_sha256"):
            raise ValueError("candidate model hash does not match its manifest")
        model = _object(model_content, "candidate model")
        paper = _object(args.paper_report.read_bytes(), "paper report")
        if paper.get("model_sha256") != manifest.get("model_sha256"):
            raise ValueError("paper report is for a different model hash")
        promoted = attach_paper_evidence(manifest, paper)
        symbol = manifest.get("symbol")
        timeframe = manifest.get("timeframe")
        if not isinstance(symbol, str) or not isinstance(timeframe, str):
            raise ValueError("candidate manifest is missing symbol/timeframe")
        issues = evaluate_model_gate(
            model,
            promoted,
            symbol=symbol,
            timeframe=timeframe,
            min_test_samples=args.min_test_samples,
            min_balanced_accuracy=args.min_balanced_accuracy,
            min_backtest_trades=args.min_backtest_trades,
            min_paper_trades=args.min_paper_trades,
            min_paper_days=args.min_paper_days,
        )
        if issues:
            print("Promotion refused:\n- " + "\n- ".join(issues), file=sys.stderr)
            return 1
        content = (
            json.dumps(promoted, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(content)
        destination = latest_manifest_path(symbol, timeframe)
        if args.promote:
            from huggingface_hub import upload_file

            upload_file(
                path_or_fileobj=content,
                path_in_repo=destination,
                repo_id=args.hf_model_repo,
                repo_type="model",
                token=token,
                commit_message=(
                    f"Promote {manifest.get('model_id')} after paper validation"
                ),
            )
        print(
            f"Validation passed for {manifest.get('model_id')}. "
            + (
                f"Promoted to {destination}."
                if args.promote
                else "Dry run only; Hub unchanged."
            )
        )
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Promotion failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
