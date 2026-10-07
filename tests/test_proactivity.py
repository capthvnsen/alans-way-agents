"""Idle nudge: schedule math, activity, runtime and tool contracts."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "alans-way"


def load():
    name = "alans_way_idle_test"
    if name + ".proactivity" in sys.modules:
        return sys.modules[name + ".proactivity"]
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py",
                                                  submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return importlib.import_module(name + ".proactivity")


P = load()
UTC = timezone.utc


def at(text, tz="UTC"):
    return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(tz)).astimezone(UTC)


class ScheduleTests(unittest.TestCase):
    def test_wait_doubles_per_unanswered_nudge(self):
        s = P.Settings(timezone="UTC", active_start=0, active_end=23)
        anchor = at("2026-10-07T09:00")
        self.assertEqual(P.due_at(s, anchor, 0), anchor + timedelta(hours=2))
        self.assertEqual(P.due_at(s, anchor, 1), anchor + timedelta(hours=4))
        self.assertEqual(P.due_at(s, anchor, 2), anchor + timedelta(hours=8))

    def test_wait_caps_at_a_week(self):
        s = P.Settings(timezone="UTC", active_start=0, active_end=23)
        anchor = at("2026-10-07T09:00")
        self.assertEqual(P.due_at(s, anchor, 30), P.next_active(s, anchor + timedelta(days=7)))

    def test_night_due_time_moves_to_the_users_morning(self):
        s = P.Settings(timezone="America/New_York")
        due = P.due_at(s, at("2026-10-07T21:30", "America/New_York"), 0)
        self.assertEqual(due, at("2026-10-08T08:00", "America/New_York"))

    def test_early_morning_due_time_moves_to_same_day_start(self):
        s = P.Settings(timezone="Asia/Tokyo")
        self.assertEqual(P.next_active(s, at("2026-10-08T05:00", "Asia/Tokyo")),
                         at("2026-10-08T08:00", "Asia/Tokyo"))

    def test_window_uses_the_users_zone_not_utc(self):
        s = P.Settings(timezone="Asia/Tokyo")
        # 23:00 UTC is 08:00 in Tokyo: inside the user's window.
        self.assertTrue(P.in_window(s, at("2026-10-07T23:00")))
        # 14:00 UTC is 23:00 in Tokyo: outside it.
        self.assertFalse(P.in_window(s, at("2026-10-07T14:00")))

    def test_dst_change_keeps_8am_local(self):
        s = P.Settings(timezone="America/Denver")
        # US DST ends 2026-11-01 at 02:00 local.
        self.assertEqual(P.next_active(s, at("2026-10-31T23:00", "America/Denver")),
                         at("2026-11-01T08:00", "America/Denver"))
        self.assertEqual(P.next_active(s, at("2026-11-01T23:00", "America/Denver")).astimezone(ZoneInfo("America/Denver")).hour, 8)

    def test_overnight_window_wraps(self):
        s = P.Settings(timezone="UTC", active_start=20, active_end=4)
        self.assertTrue(P.in_window(s, at("2026-10-07T02:00")))
        self.assertFalse(P.in_window(s, at("2026-10-07T12:00")))
        self.assertEqual(P.next_active(s, at("2026-10-07T12:00")), at("2026-10-07T20:00"))

    def test_unknown_timezone_is_utc(self):
        self.assertTrue(P.in_window(P.Settings(), at("2026-10-07T09:00")))

    def test_pause(self):
        now = at("2026-10-07T09:00")
        self.assertTrue(P.is_paused(P.Settings(paused_until="off"), now))
        self.assertTrue(P.is_paused(P.Settings(paused_until="2026-10-08T00:00:00+00:00"), now))
        self.assertFalse(P.is_paused(P.Settings(paused_until="2026-10-07T00:00:00+00:00"), now))
        self.assertFalse(P.is_paused(P.Settings(), now))


class ValidateTests(unittest.TestCase):
    def test_level_sets_base(self):
        self.assertEqual(P.validate(P.Settings(), {"level": "less"}).base_minutes, 240)
        self.assertEqual(P.validate(P.Settings(), {"level": "more"}).base_minutes, 60)

    def test_rejects_bad_values(self):
        for bad in ({"timezone": "Mars/Base"}, {"timezone": "../etc/passwd"}, {"timezone": 5},
                    {"base_minutes": 5}, {"base_minutes": True}, {"base_minutes": 2000},
                    {"active_start": 24}, {"active_start": 8, "active_end": 8},
                    {"paused_until": "tomorrow"}, {"paused_until": "2026-10-08T09:00"},
                    {"level": "max"}, {"nonsense": 1}, "not a dict"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                P.validate(P.Settings(), bad)

    def test_cli_floor_allows_test_sized_base(self):
        self.assertEqual(P.validate(P.Settings(), {"base_minutes": 2}, min_base=1).base_minutes, 2)

    def test_accepts_good_values(self):
        s = P.validate(P.Settings(), {"timezone": "Europe/Berlin", "active_start": 9,
                                      "paused_until": "2026-10-12T08:00:00+02:00"})
        self.assertEqual((s.timezone, s.active_start), ("Europe/Berlin", 9))


if __name__ == "__main__":
    unittest.main()
