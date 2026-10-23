"""Sessions engine: UTC window math, overlaps, and next-event tracking."""

import unittest
from datetime import datetime, timezone

from neezy_backend.sessions import (
    OVERLAPS,
    SESSIONS,
    SessionWindow,
    active_overlaps,
    active_sessions,
    next_event,
    session_state,
    sessions_report,
    summarize,
)


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 23, hour, minute, tzinfo=timezone.utc)


class WindowTests(unittest.TestCase):
    def test_every_session_declared(self):
        self.assertEqual(
            [session.name for session in SESSIONS],
            ["Sydney", "Tokyo", "London", "New York"],
        )

    def test_wrapping_detection(self):
        self.assertTrue(SessionWindow("X", 21, 6).wraps_midnight)
        self.assertFalse(SessionWindow("X", 7, 16).wraps_midnight)

    def test_contains_simple_window(self):
        london = SessionWindow("London", 7, 16)
        self.assertTrue(london.contains(7.0))
        self.assertTrue(london.contains(15.9))
        self.assertFalse(london.contains(16.0))
        self.assertFalse(london.contains(6.9))

    def test_contains_wrapping_window(self):
        sydney = SessionWindow("Sydney", 21, 6)
        self.assertTrue(sydney.contains(21.0))
        self.assertTrue(sydney.contains(23.5))
        self.assertTrue(sydney.contains(0.0))
        self.assertTrue(sydney.contains(5.9))
        self.assertFalse(sydney.contains(6.0))
        self.assertFalse(sydney.contains(20.9))


class StateTests(unittest.TestCase):
    def test_london_newyork_overlap_midday(self):
        open_names = [state.name for state in active_sessions(utc(13, 30))]
        self.assertEqual(open_names, ["London", "New York"])
        overlaps = active_overlaps(utc(13, 30))
        self.assertTrue(any("New York" in str(item["sessions"]) for item in overlaps))

    def test_asydney_tokyo_overlap_night(self):
        open_names = [state.name for state in active_sessions(utc(3))]
        self.assertEqual(open_names, ["Sydney", "Tokyo"])

    def test_progress_grows_through_session(self):
        early = session_state(SESSIONS[2], utc(7, 1)).progress  # London
        late = session_state(SESSIONS[2], utc(15, 30)).progress
        self.assertGreater(late, early)
        self.assertLess(late, 1.0)

    def test_closed_session_reports_next_open(self):
        state = session_state(SESSIONS[1], utc(12))  # Tokyo at noon UTC
        self.assertFalse(state.open)
        self.assertIsNotNone(state.opens_in_minutes)
        self.assertIsNone(state.closes_in_minutes)

    def test_next_event_before_london_close(self):
        event = next_event(utc(15))
        self.assertIn("minutes_until", event)
        self.assertGreater(event["minutes_until"], 0)

    def test_report_is_json_ready(self):
        report = sessions_report(utc(13, 30))
        for session in report["sessions"]:
            self.assertIsInstance(session, dict)
            self.assertIsInstance(session["open"], bool)
        self.assertIn("moment_utc", report)

    def test_summarize_mentions_open_sessions(self):
        line = summarize(utc(13, 30))
        self.assertIn("London", line)
        self.assertIn("UTC", line)

    def test_non_utc_input_converted(self):
        from datetime import timedelta

        johannesburg = timezone(timedelta(hours=2))
        moment = datetime(2026, 10, 23, 15, 30, tzinfo=johannesburg)  # 13:30 UTC
        self.assertEqual(
            [state.name for state in active_sessions(moment)],
            ["London", "New York"],
        )

    def test_overlaps_declared_for_every_pair(self):
        for first, second, start, end in OVERLAPS:
            self.assertLess(start, end)
            self.assertIn(first, {session.name for session in SESSIONS})
            self.assertIn(second, {session.name for session in SESSIONS})


if __name__ == "__main__":
    unittest.main()
