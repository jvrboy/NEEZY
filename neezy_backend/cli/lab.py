"""Offline archive research commands. Never fetches or trades."""

from __future__ import annotations

import json
from pathlib import Path

from ..lab.evaluation import evaluate
from ..lab.service import analyze, catalog
from .common import _emit, _table


def cmd_lab(args, fetch, out) -> int:
    del fetch
    if args.action == "catalog":
        document = catalog()
        if args.json:
            _emit(out, document)
        else:
            _table(
                out,
                ["ENGINE", "INDICATORS", "AVAILABLE"],
                [
                    (e["id"], ", ".join(e["indicators"]), str(e["available"]))
                    for e in document["engines"]
                ],
            )
            out.write(document["warning"] + "\n")
        return 0
    path = Path(args.input)
    with path.open("rb") as source:
        content = source.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError("research input exceeds 2 MB")
    payload = json.loads(content)
    if not isinstance(payload, (list, dict)):
        raise ValueError("research input must be a candle list or object")
    rows = payload.get("candles") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("research input must contain a candles list")
    params = json.loads(args.params)
    if not isinstance(params, dict):
        raise ValueError("--params must be a JSON object")
    options = dict(
        engine=args.engine,
        indicator=args.indicator,
        symbol=args.symbol,
        granularity=args.granularity,
        params=params,
    )
    if args.action == "evaluate":
        result = evaluate(
            rows,
            horizon=args.horizon,
            holdout_fraction=args.holdout,
            threshold=args.threshold,
            cost_bps=args.cost_bps,
            value_field=args.value_field,
            **options,
        )
    else:
        result = analyze(rows, include_series=args.series, **options)
    _emit(out, result)
    return 0
