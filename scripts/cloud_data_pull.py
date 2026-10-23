#!/usr/bin/env python3
"""Collect public candles in GitHub Actions and optionally publish HF/R2 copies."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neezy_backend.markets import PUBLIC_WS_URL, TIMEFRAMES  # noqa: E402
from neezy_backend.stream import fetch_history  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["frxEURUSD"])
    parser.add_argument("--timeframe", choices=sorted(TIMEFRAMES), default="15m")
    parser.add_argument("--candles", type=int, default=5000)
    parser.add_argument("--output", type=Path, default=Path("data-artifacts"))
    parser.add_argument(
        "--hf-dataset-repo", default=os.environ.get("HF_DATASET_REPO", "")
    )
    parser.add_argument("--upload", action="store_true")
    return parser


def _r2_settings() -> dict[str, str]:
    names = (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
    )
    values = {name: os.environ.get(name, "") for name in names}
    if any(values.values()) and not all(values.values()):
        raise ValueError("R2 credentials are incomplete; set all four R2 variables")
    return values


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = os.environ.get("HF_TOKEN", "")
    if args.upload and (not token or not args.hf_dataset_repo):
        print("--upload needs HF_TOKEN and HF_DATASET_REPO.", file=sys.stderr)
        return 2
    try:
        r2 = _r2_settings()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    failures = 0
    for symbol in dict.fromkeys(args.symbols):
        try:
            rows = fetch_history(symbol, TIMEFRAMES[args.timeframe], args.candles)
            if not rows:
                raise ValueError("provider returned no candles")
            now = datetime.now(timezone.utc)
            document = {
                "schema": 1,
                "symbol": symbol,
                "timeframe": args.timeframe,
                "captured_at": now.isoformat(timespec="seconds"),
                "source": PUBLIC_WS_URL,
                "candle_count": len(rows),
                "first_epoch": rows[0][0],
                "last_epoch": rows[-1][0],
                "candles": rows,
            }
            content = (json.dumps(document, indent=2, allow_nan=False) + "\n").encode(
                "utf-8"
            )
            digest = hashlib.sha256(content).hexdigest()[:12]
            filename = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{digest}.json"
            repo_path = f"datasets/{symbol}/{args.timeframe}/{filename}"
            local_path = args.output / symbol / args.timeframe / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(content)

            if args.upload:
                from huggingface_hub import upload_file

                upload_file(
                    path_or_fileobj=content,
                    path_in_repo=repo_path,
                    repo_id=args.hf_dataset_repo,
                    repo_type="dataset",
                    token=token,
                    commit_message=f"Collect {symbol} {args.timeframe} candles",
                )
            if r2:
                import boto3

                client = boto3.client(
                    "s3",
                    endpoint_url=(
                        f"https://{r2['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
                    ),
                    aws_access_key_id=r2["R2_ACCESS_KEY_ID"],
                    aws_secret_access_key=r2["R2_SECRET_ACCESS_KEY"],
                    region_name="auto",
                )
                prefix = os.environ.get("R2_PREFIX", "neezy/data").strip("/")
                key = f"{prefix}/{repo_path}"
                client.put_object(
                    Bucket=r2["R2_BUCKET"],
                    Key=key,
                    Body=content,
                    ContentType="application/json",
                )
            print(f"{symbol}: {len(rows)} candles -> {local_path}")
        except (OSError, RuntimeError, ValueError) as error:
            failures += 1
            print(f"{symbol}: data pull failed: {error}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
