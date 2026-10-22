"""Local-data CLI commands: the SQLite database and signal history."""

from __future__ import annotations

from pathlib import Path

from ..markets import display_name, format_price, granularity
from ..storage import SignalHistoryStore
from .common import _emit, _open_database, _symbol, _table


def cmd_db(args, fetch, out) -> int:
    with _open_database() as database:
        if args.action == "stats":
            payload = database.stats()
            if args.json:
                _emit(out, payload)
                return 0
            _table(
                out,
                ["FIELD", "VALUE"],
                [
                    ("database", payload["path"]),
                    ("size", f"{payload['size_mb']} MB"),
                    ("journal", payload["journal_mode"]),
                    ("retention", f"{payload['retention_days']} days"),
                    *[(name, count) for name, count in payload["counts"].items()],
                ],
            )
            return 0
        if args.action == "signals":
            records = database.recent_signals(
                args.limit, _symbol(args.symbol) if args.symbol else None
            )
            if args.json:
                _emit(out, records)
                return 0
            _table(
                out,
                ["TIME", "MARKET", "TIMEFRAME", "SIGNAL", "SCORE", "STRATEGY"],
                [
                    (
                        record["created_at"][:19],
                        display_name(record["symbol"]),
                        record["timeframe"],
                        record["signal"],
                        f"{record['score']:+.1f}",
                        record["strategy"] or "-",
                    )
                    for record in records
                ],
            )
            return 0
        if args.action == "candles":
            symbol = _symbol(args.symbol)
            rows = database.load_candles(symbol, args.timeframe, args.limit)
            if args.json:
                _emit(
                    out,
                    [
                        {
                            "epoch": row[0],
                            "open": row[1],
                            "high": row[2],
                            "low": row[3],
                            "close": row[4],
                        }
                        for row in rows
                    ],
                )
                return 0
            _table(
                out,
                ["EPOCH", "OPEN", "HIGH", "LOW", "CLOSE"],
                rows[-args.limit :],
            )
            return 0
        if args.action == "save":
            symbol = _symbol(args.symbol)
            seconds = granularity(args.timeframe)
            candles = fetch(symbol, seconds, args.count)
            written = database.save_candles(symbol, args.timeframe, candles)
            from ..context import market_snapshot

            snapshot = market_snapshot(candles, symbol=symbol, timeframe=args.timeframe)
            if snapshot is not None:
                database.save_snapshot(
                    symbol=symbol, timeframe=args.timeframe, result=snapshot
                )
            if args.json:
                _emit(
                    out,
                    {"symbol": symbol, "written": written},
                )
                return 0
            out.write(
                f"Stored {written} candles for {display_name(symbol)} "
                f"{args.timeframe} locally.\n"
            )
            return 0
        if args.action == "export":
            destination = Path(args.path).expanduser()
            counts = database.export_json(destination)
            if args.json:
                _emit(out, {"destination": str(destination), "counts": counts})
                return 0
            out.write(f"Exported local database to {destination}\n")
            for name, count in counts.items():
                out.write(f"  {name}: {count}\n")
            return 0
        if args.action == "prune":
            removed = database.prune(retention_days=args.days)
            if args.json:
                _emit(out, removed)
                return 0
            out.write(
                "Pruned rows: "
                + ", ".join(f"{k}={v}" for k, v in removed.items())
                + "\n"
            )
            return 0
        if args.action == "vacuum":
            database.vacuum()
            out.write("Database vacuumed.\n")
            return 0
    raise ValueError(f"unknown db action {args.action!r}")


def cmd_history(args, fetch, out) -> int:
    store = SignalHistoryStore()
    if args.export:
        out.write(f"Exported {store.export_csv(Path(args.export))} records\n")
        return 0
    if args.compact:
        out.write(f"Kept {store.compact(args.compact)} records\n")
        return 0
    if args.summary:
        summary = store.summary()
        if args.json:
            _emit(out, summary)
        else:
            out.write(f"{summary['total']} transitions\n")
            _table(out, ["SIGNAL", "COUNT"], sorted(summary["by_signal"].items()))
        return 0
    records = store.read(limit=args.limit)
    if args.json:
        _emit(out, records)
        return 0
    _table(
        out,
        ["TIME", "MARKET", "FROM", "TO", "PRICE", "SCORE"],
        [
            (
                r["timestamp"][:19],
                display_name(r["symbol"]),
                r["previous"],
                r["current"],
                format_price(r["symbol"], r["price"]),
                f"{r['score']:+d}",
            )
            for r in records
        ],
    )
    return 0
