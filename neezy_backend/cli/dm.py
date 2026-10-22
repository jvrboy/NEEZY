"""Direct-message webhook notification CLI command."""

from __future__ import annotations

from .common import _emit


def cmd_dm(args, fetch, out) -> int:
    """Send direct message webhook notifications."""
    del fetch
    from ..dm import send_dm_notification

    if args.action == "send":
        res = send_dm_notification(args.url, args.title, args.message, level=args.level)
        if args.json:
            _emit(out, res)
        else:
            out.write(f"DM Send Result: {res}\n")
        return 0
    raise ValueError(f"unknown dm action {args.action!r}")
