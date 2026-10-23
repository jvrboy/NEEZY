"""``neezy-cli sessions``: the UTC trading-session clock (offline)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TextIO

from ..sessions import SESSIONS, session_state, sessions_report, summarize
from ..ui_style import progress_bar, state_dot
from .common import _emit


def cmd_sessions(args, fetch, out: TextIO) -> int:
    del fetch

    moment = (
        datetime.now(timezone.utc)
        if getattr(args, "now", None) is None
        else _parse_now(args.now)
    )
    report = sessions_report(moment)
    if args.json:
        _emit(out, report)
        return 0

    out.write(summarize(moment) + "\n\n")
    for session in SESSIONS:
        state = session_state(session, moment)
        marker = state_dot("open" if state.open else "closed")
        progress = progress_bar(state.progress, width=18)
        timing = (
            f"closes in {state.closes_in_minutes} min"
            if state.open
            else f"opens in {state.opens_in_minutes} min"
        )
        out.write(f"  {marker} {session.name:<9} {timing:<22} {progress}\n")
    overlaps = report["overlaps"]
    if overlaps:
        out.write("\nLive overlaps (deepest liquidity windows):\n")
        for overlap in overlaps:
            out.write(
                f"  {state_dot('open')} {overlap['sessions']} "
                f"- {overlap['minutes_remaining']} min remaining\n"
            )
    out.write("\nSession windows are stable UTC approximations used for\n")
    out.write("liquidity context only, not legal trading hours.\n")
    return 0


def _parse_now(text: str) -> datetime:
    """``YYYY-MM-DDTHH:MM`` (UTC assumed) for reproducible output."""
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(
            "--now expects an ISO timestamp like 2026-01-15T13:30"
        ) from error
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
