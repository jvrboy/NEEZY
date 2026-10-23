"""Trading-session clock: Sydney, Tokyo, London, and New York in UTC.

Pure clock arithmetic over fixed UTC windows (no network, no DST tables).
FX convention approximates each session with a stable UTC band, which is
exactly what signal dashboards display: the point is *relative* liquidity,
not legal trading hours. Session boundaries:

- Sydney   21:00 - 06:00 UTC (wraps midnight)
- Tokyo    00:00 - 09:00 UTC
- London   07:00 - 16:00 UTC
- New York 12:00 - 21:00 UTC

The London/New York overlap (12:00-16:00 UTC) is the deepest liquidity
window of the day, so it gets first-class reporting here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_HOURS = 60


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """One session's stable UTC band."""

    name: str
    open_hour: int  # UTC hour, 0-23
    close_hour: int  # UTC hour, 0-23 (may be numerically smaller: wraps)

    @property
    def wraps_midnight(self) -> bool:
        return self.close_hour <= self.open_hour

    def contains(self, hour: float) -> bool:
        """Is ``hour`` (UTC, fractional) inside this window?"""
        if self.wraps_midnight:
            return hour >= self.open_hour or hour < self.close_hour
        return self.open_hour <= hour < self.close_hour


SESSIONS: tuple[SessionWindow, ...] = (
    SessionWindow("Sydney", 21, 6),
    SessionWindow("Tokyo", 0, 9),
    SessionWindow("London", 7, 16),
    SessionWindow("New York", 12, 21),
)

SESSION_NAMES = tuple(session.name for session in SESSIONS)

#: UTC hour windows where two sessions overlap (name pair -> shared band).
OVERLAPS: tuple[tuple[str, str, int, int], ...] = (
    ("Sydney", "Tokyo", 0, 6),
    ("London", "New York", 12, 16),
    ("Sydney", "London", 7, 8),  # Sydney's last hour meets London's first
)


@dataclass(frozen=True, slots=True)
class SessionState:
    """Snapshot of one session relative to a moment in time."""

    name: str
    open: bool
    opens_in_minutes: int | None  # None while open
    closes_in_minutes: int | None  # None while closed
    progress: float  # 0.0 - 1.0 through the window; 0.0 while closed


def _utc_hour_fraction(moment: datetime) -> float:
    moment = moment.astimezone(timezone.utc)
    return moment.hour + moment.minute / 60.0 + moment.second / 3600.0


def _minutes_until(moment: datetime, target_hour: float) -> int:
    """Whole minutes from ``moment`` until the next ``target_hour`` UTC.

    The target rolls to tomorrow automatically when today's slot has
    already passed (which is how wrapping sessions reach their close).
    """
    moment = moment.astimezone(timezone.utc)
    target_minute = int(target_hour * _HOURS)
    day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    target = day + timedelta(minutes=target_minute)
    if target <= moment:
        target += timedelta(days=1)
    return max(0, int((target - moment).total_seconds() // 60))


def session_state(session: SessionWindow, moment: datetime) -> SessionState:
    """Open/closed state of one session at ``moment`` (any tz, made UTC)."""
    hour = _utc_hour_fraction(moment)
    if session.contains(hour):
        if session.wraps_midnight and hour < session.close_hour:
            span = (24 - session.open_hour) + session.close_hour
            elapsed = (24 - session.open_hour) + hour
        else:
            span = session.close_hour - session.open_hour
            elapsed = hour - session.open_hour
        return SessionState(
            name=session.name,
            open=True,
            opens_in_minutes=None,
            closes_in_minutes=_minutes_until(moment, session.close_hour),
            progress=min(1.0, elapsed / span) if span else 0.0,
        )
    return SessionState(
        name=session.name,
        open=False,
        opens_in_minutes=_minutes_until(moment, session.open_hour),
        closes_in_minutes=None,
        progress=0.0,
    )


def active_sessions(moment: datetime) -> list[SessionState]:
    """Every open session at ``moment``, in SESSIONS order."""
    return [
        state for state in (session_state(s, moment) for s in SESSIONS) if state.open
    ]


def active_overlaps(moment: datetime) -> list[dict[str, object]]:
    """Overlap bands that contain ``moment`` (UTC)."""
    hour = _utc_hour_fraction(moment)
    live = []
    for first, second, start, end in OVERLAPS:
        if start <= hour < end:
            live.append(
                {
                    "sessions": f"{first} + {second}",
                    "started_utc_hour": start,
                    "ends_utc_hour": end,
                    "minutes_remaining": _minutes_until(moment, end),
                }
            )
    return live


def next_event(moment: datetime) -> dict[str, object]:
    """The next session open or close after ``moment`` (UTC)."""
    states = [session_state(session, moment) for session in SESSIONS]
    candidates: list[tuple[int, str, str]] = []
    for state in states:
        if state.open and state.closes_in_minutes is not None:
            candidates.append((state.closes_in_minutes, state.name, "close"))
        elif state.opens_in_minutes is not None:
            candidates.append((state.opens_in_minutes, state.name, "open"))
    if not candidates:
        return {"event": "none", "minutes_until": 0}
    minutes, name, action = min(candidates)
    return {"event": action, "session": name, "minutes_until": minutes}


def sessions_report(moment: datetime) -> dict[str, object]:
    """Full clock report: every session state, overlaps, and next event.

    Session entries are plain dicts (JSON-ready); use :func:`session_state`
    for the dataclass form.
    """
    states = [session_state(session, moment) for session in SESSIONS]
    return {
        "moment_utc": moment.astimezone(timezone.utc).isoformat(timespec="minutes"),
        "sessions": [
            {
                "name": state.name,
                "open": state.open,
                "opens_in_minutes": state.opens_in_minutes,
                "closes_in_minutes": state.closes_in_minutes,
                "progress": round(state.progress, 3),
            }
            for state in states
        ],
        "overlaps": active_overlaps(moment),
        "next_event": next_event(moment),
    }


def summarize(moment: datetime) -> str:
    """One human-readable line for dashboards and logs."""
    report = sessions_report(moment)
    open_names = [session["name"] for session in report["sessions"] if session["open"]]
    event = report["next_event"]
    when = event.get("minutes_until")
    what = f"{event.get('session', '')} {event.get('event', '')}".strip()
    clock = moment.astimezone(timezone.utc).strftime("%H:%M")
    if open_names:
        return (
            f"{clock} UTC | open: {', '.join(open_names)} | next: {what} in {when} min"
        )
    return f"{clock} UTC | all sessions closed | next: {what} in {when} min"
