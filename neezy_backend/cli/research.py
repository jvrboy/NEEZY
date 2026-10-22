"""Research and learning CLI commands.

``research`` (fresh ML fits), ``datasets`` (shipped knowledge),
``study`` (train-then-validate per instrument), ``knowledge`` (what was
learned), and ``brain`` (local neural research model).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..brain import predict as predict_brain
from ..brain import train_model as train_brain_model
from ..catalog import instruments
from ..config import AppSettings
from ..datasets import dataset_summary, research_report
from ..insights import insight_line, knowledge_brief
from ..knowledge import (
    KNOWLEDGE_PATH,
    load_knowledge,
    save_knowledge,
)
from ..knowledge import summary as knowledge_summary
from ..markets import granularity
from ..research import DEFAULT_RESEARCH_SYMBOLS, training_run
from ..study import StudySettings, describe_method, run_study
from .common import _emit, _open_database, _table


def cmd_research(args, fetch, out) -> int:
    if args.action == "status":
        report = research_report()
    else:
        cfg = AppSettings(
            ml_history_candles=args.candles,
            ml_epochs=args.epochs,
            ml_horizon=args.horizon,
            ml_seed=args.seed,
        )
        report = training_run(
            args.symbols or DEFAULT_RESEARCH_SYMBOLS,
            timeframe=args.timeframe,
            settings=cfg,
            checkpoint=args.out,
        )
    print(json.dumps(report, indent=2, allow_nan=False), file=out)
    return (
        1
        if any(
            rec.get("status") == "error" for rec in report.get("symbols", {}).values()
        )
        else 0
    )


def cmd_datasets(args, fetch, out) -> int:
    """Show the shipped knowledge datasets and what they cover."""
    payload = dataset_summary()
    if args.json:
        print(json.dumps(payload, indent=2), file=out)
        return 0
    print("Shipped knowledge datasets:", file=out)
    for name, info in sorted(payload.get("datasets", {}).items()):
        keys = ", ".join(info.get("keys", [])[:6])
        print(f"  {name}  {info.get('bytes', 0)} bytes  [{keys}]", file=out)
    print(
        f"\nLearned weights cover {payload.get('weighted_symbols', 0)} "
        "symbols (out-of-sample backtests on past candles; not a forecast).",
        file=out,
    )
    brief = knowledge_brief()
    print("\nIndicators:", ", ".join(brief.get("indicators", [])), file=out)
    print("Patterns:", ", ".join(brief.get("patterns", [])), file=out)
    print("Strategies:", ", ".join(brief.get("strategies", [])), file=out)
    if args.symbol:
        from ..datasets import weight_for

        for symbol in args.symbol:
            record = weight_for(symbol)
            if record is None:
                print(f"\n{symbol}: no learned weight.", file=out)
                continue
            print(
                f"\n{symbol}: edge weight {record.get('edge_weight'):+.2f}, "
                f"verdict {record.get('verdict')}, sample coverage "
                f"{record.get('confidence', 0):.0%}",
                file=out,
            )
            line = insight_line(symbol)
            if line:
                print(f"  {line}", file=out)
    return 0


def _study_symbols(args) -> list[str]:
    if args.symbols:
        return list(args.symbols)
    return sorted(
        item.symbol
        for item in instruments().values()
        if not args.category or item.market == args.category
    )


def _study_row(symbol: str, record: dict[str, Any]) -> tuple[Any, ...]:
    test, train = record.get("test"), record.get("train")
    setting = record.get("selected")
    setting_text = (
        f"score>={setting['min_score']} stop={setting['stop_atr_multiple']}"
        f" rr={setting['reward_to_risk']}"
        if setting
        else "-"
    )
    return (
        symbol,
        record["market"],
        record["candles"],
        record["verdict"],
        f"{test['trades']}" if test else "-",
        f"{test['expectancy_r']:+.3f}"
        if test and test["expectancy_r"] is not None
        else "-",
        f"{train['expectancy_r']:+.3f}"
        if train and train["expectancy_r"] is not None
        else "-",
        setting_text,
    )


def cmd_study(args, fetch, out) -> int:
    symbols = _study_symbols(args)
    if not symbols:
        raise ValueError(f"no instruments in category {args.category!r}")
    settings = StudySettings(
        granularity=granularity(args.timeframe),
        candles=args.candles,
        min_candles=args.min_candles,
        spread_pips=args.spread_pips,
    )
    target = Path(args.out) if args.out else KNOWLEDGE_PATH
    previous = load_knowledge(target)  # fail before the slow fetches if unreadable

    def progress(symbol: str, verdict: str) -> None:
        sys.stderr.write(f"{symbol}: {verdict}\n")

    merged = dict(previous["symbols"])
    kept: list[str] = []
    method = describe_method(settings)
    saved: Path | None = None

    def checkpoint(symbol: str, record: dict[str, Any]) -> None:
        # Written after every market: a later hang or crash keeps earlier results.
        nonlocal saved
        # A failed fetch must not erase a verdict from an earlier, successful run.
        if record["verdict"] == "error" and symbol in merged:
            kept.append(symbol)
        else:
            merged[symbol] = record
        if not args.dry_run:
            saved = save_knowledge(
                {**previous, "method": method, "symbols": merged}, target
            )

    document = run_study(
        symbols,
        settings,
        fetch=fetch,
        progress=None if args.json else progress,
        on_record=checkpoint,
    )
    combined = {**previous, "method": method, "symbols": merged}
    final = load_knowledge(saved) if saved else combined

    if args.json:
        _emit(
            out,
            {
                "saved_to": str(saved) if saved else None,
                "kept_previous": kept,
                "summary": knowledge_summary(final),
                "symbols": document["symbols"],
            },
        )
        return 0
    out.write(f"Study · {args.timeframe} · {len(symbols)} instrument(s)\n\n")
    _table(
        out,
        [
            "SYMBOL",
            "MARKET",
            "CANDLES",
            "VERDICT",
            "TEST TRADES",
            "TEST R/TRADE",
            "TRAIN R/TRADE",
            "SETTING",
        ],
        [_study_row(s, r) for s, r in document["symbols"].items()],
    )
    counts = knowledge_summary(final)["verdicts"]
    out.write("\nVerdicts: " + ", ".join(f"{k} {v}" for k, v in counts.items()) + "\n")
    if kept:
        out.write(f"Kept previous verdict after fetch error: {', '.join(kept)}\n")
    out.write(f"Saved to {saved}\n" if saved else "Dry run: nothing written.\n")
    out.write("\nHistorical simulation on the held-out slice only; not a forecast.\n")
    return 0


def cmd_knowledge(args, fetch, out) -> int:
    document = load_knowledge(Path(args.file) if args.file else None)
    records = document["symbols"]
    if args.symbols:
        chosen = {s: records[s] for s in args.symbols if s in records}
        missing = [s for s in args.symbols if s not in records]
    else:
        chosen = dict(
            sorted(
                records.items(),
                key=lambda item: (item[1]["verdict"] != "edge", item[0]),
            )
        )
        missing = []
    summary_data = knowledge_summary(document)
    if args.json:
        _emit(
            out,
            {
                "summary": summary_data,
                "method": document.get("method", ""),
                "symbols": chosen,
                "never_studied": missing,
            },
        )
        return 0
    if not chosen:
        out.write("Nothing studied yet. Run 'neezy-cli study' to train.\n")
        return 0
    out.write(
        f"Knowledge · generated {summary_data['generated_at'] or 'never'} · "
        + ", ".join(f"{k} {v}" for k, v in summary_data["verdicts"].items())
        + "\n\n"
    )
    _table(
        out,
        [
            "SYMBOL",
            "MARKET",
            "CANDLES",
            "VERDICT",
            "TEST TRADES",
            "TEST R/TRADE",
            "TRAIN R/TRADE",
            "SETTING",
        ],
        [_study_row(s, r) for s, r in chosen.items()],
    )
    if missing:
        out.write("\nNever studied: " + ", ".join(missing) + "\n")
    out.write("\nHistorical simulation only; not a forecast.\n")
    return 0


def cmd_brain(args, fetch, out) -> int:
    """Train, inspect, or query the opt-in local neural research model."""
    del fetch
    key = f"brain:model:{args.symbol}:{args.timeframe}"
    with _open_database() as database:
        if args.action == "train":
            candles = database.load_candles(
                args.symbol, args.timeframe, limit=args.limit
            )
            trained = train_brain_model(
                candles,
                symbol=args.symbol,
                timeframe=args.timeframe,
                horizon=args.horizon,
                min_samples=args.min_samples,
            )
            database.set_value(key, trained["model"])
            report = trained["report"]
            if args.json:
                _emit(out, report)
                return 0
            test = report["test"]
            candidate_status = (
                "validated candidate" if report["deployment_ready"] else "research-only"
            )
            out.write(
                f"Trained local research model · {args.symbol} {args.timeframe}\n"
                f"Labeled examples {report['labeled_examples']} · "
                f"test samples {test['samples']} · accuracy "
                f"{test['accuracy']:.1%} · balanced "
                f"{test['balanced_accuracy']:.1%}\n"
                f"Status: {candidate_status}\n"
                f"{report['validation_note']}\n"
                "This does not change the core signal or guarantee future results.\n"
            )
            return 0
        model = database.get_value(key)
        if args.action == "status":
            if not isinstance(model, dict):
                payload = {
                    "symbol": args.symbol,
                    "timeframe": args.timeframe,
                    "trained": False,
                }
            else:
                payload = {
                    "symbol": args.symbol,
                    "timeframe": args.timeframe,
                    "trained": True,
                    "trained_at": model.get("trained_at"),
                    "deployment_ready": model.get("deployment_ready", False),
                    "test_metrics": model.get("test_metrics", {}),
                    "validation_note": model.get("validation_note", ""),
                }
            if args.json:
                _emit(out, payload)
            else:
                out.write(json.dumps(payload, indent=2) + "\n")
            return 0
        if args.action == "predict":
            if not isinstance(model, dict):
                raise ValueError(
                    "no local model; run 'neezy-cli brain train SYMBOL' first"
                )
            candles = database.load_candles(
                args.symbol, args.timeframe, limit=args.limit
            )
            prediction = predict_brain(candles, model)
            if prediction is None:
                raise ValueError("not enough saved candles to create a prediction")
            if args.json:
                _emit(out, prediction)
            else:
                out.write(
                    f"{args.symbol} {args.timeframe} · {prediction['direction']} "
                    f"· P(up) {prediction['up_probability']:.1%} · "
                    f"{prediction['validation_note']}\n"
                    "Experimental research output only; not financial advice.\n"
                )
            return 0
    raise ValueError(f"unknown brain action {args.action!r}")
