"""MetaTrader 5 CLI commands (local terminal bridge; live orders gated)."""

from __future__ import annotations

from .common import _emit


def _mt5_require_live(bridge) -> None:
    """Refuse MT5 reads unless the terminal is really connected (no simulated data)."""
    conn = bridge.connect()
    if not conn.get("success") or conn.get("mock"):
        reason = conn.get("error") or "terminal is simulated, not connected"
        raise RuntimeError(f"MT5 not connected ({reason}); no live data read")


def cmd_mt5(args, fetch, out) -> int:
    """Interact with local MetaTrader 5 terminal bridge."""
    del fetch
    from ..mt5_bridge import get_global_mt5_bridge, is_mt5_available
    from ..mt5_orders import check_live_terminal

    if args.action == "preflight":
        from ..mt5_preflight import checks_as_dicts, has_failures, run_preflight

        checks = run_preflight()
        if args.json:
            _emit(
                out, {"checks": checks_as_dicts(checks), "ok": not has_failures(checks)}
            )
        else:
            for check in checks:
                out.write(f"[{check.status.upper():4}] {check.name}: {check.detail}\n")
            verdict = "NOT READY" if has_failures(checks) else "READY (read-only check)"
            out.write(f"MT5 preflight: {verdict}\n")
        return 1 if has_failures(checks) else 0

    bridge = get_global_mt5_bridge()
    if args.action == "status":
        status = bridge.get_status()
        if args.json:
            _emit(out, status)
        else:
            out.write(f"MT5 Available: {is_mt5_available()}\nMT5 Status: {status}\n")
        return 0
    if args.action == "account":
        _mt5_require_live(bridge)
        acc = bridge.get_account_info()
        if args.json:
            _emit(out, acc)
        else:
            out.write(f"MT5 Account Info: {acc}\n")
        return 0
    if args.action == "quote":
        _mt5_require_live(bridge)
        quote = bridge.get_quote(args.symbol)
        if args.json:
            _emit(out, quote)
        else:
            out.write(f"MT5 Quote ({args.symbol}): {quote}\n")
        return 0
    if args.action == "candles":
        _mt5_require_live(bridge)
        candles = bridge.fetch_candles(
            args.symbol, timeframe=args.timeframe, count=args.count
        )
        if args.json:
            _emit(
                out, {"symbol": args.symbol, "count": len(candles), "candles": candles}
            )
        else:
            out.write(f"MT5 Candles ({args.symbol}): fetched {len(candles)} candles\n")
        return 0
    if args.action == "order":
        order_kwargs = {
            "order_type": args.type,
            "volume": args.volume,
            "price": args.price,
            "sl": args.sl,
            "tp": args.tp,
            "comment": args.comment,
        }
        if args.dry_run:
            preview = bridge.preview_order(args.symbol, **order_kwargs)
            if not preview["valid"]:
                raise ValueError("; ".join(preview["errors"]))
            if args.json:
                _emit(out, preview)
            else:
                out.write(f"MT5 Order DRY RUN (not sent): {preview}\n")
            return 0
        if not args.confirm:
            raise ValueError(
                "refusing to send a live order without --confirm "
                "(use --dry-run to preview)"
            )
        gate = check_live_terminal(bridge)
        if not gate["ok"]:
            raise RuntimeError(f"live order refused: {gate['reason']}")
        res = bridge.place_order(args.symbol, **order_kwargs)
        if not res.get("success"):
            raise RuntimeError(f"order failed: {res.get('error')}")
        if args.json:
            _emit(out, res)
        else:
            out.write(f"MT5 Order Result: {res}\n")
        return 0
    raise ValueError(f"unknown mt5 action {args.action!r}")
