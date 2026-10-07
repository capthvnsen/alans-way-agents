"""Idle nudge: schedule math, activity, runtime and tool contracts."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
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


class FakeState:
    """ctx.state stand-in: JSON round-trips like Hermes' file-backed facade."""
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return json.loads(json.dumps(self.data.get(key, default)))

    def set(self, key, value):
        self.data[key] = json.loads(json.dumps(value))


class FakeCtx(SimpleNamespace):
    def __init__(self, accept=True):
        super().__init__(state=FakeState(), sent=[], accept=accept)

    def inject_message(self, content, role="user", *, session_key=None):
        if isinstance(self.accept, Exception):
            raise self.accept
        self.sent.append((content, session_key))
        return self.accept


KEY = "agent:main:telegram:dm:42"


def runtime(ctx, now, **settings):
    clock = SimpleNamespace(now=now)
    p = P.Proactivity(ctx, clock=lambda: clock.now)
    p.gateway = True
    p.bind(KEY)
    p.update({"timezone": "UTC", **settings}, min_base=1)
    return p, clock


def turn(p, clock, when, text="hi", key=KEY, finish=True):
    """One agent turn in session `key`, as Hermes' pre/post_llm_call hooks see it."""
    clock.now = when
    with patch.object(P, "caller_session_key", return_value=key):
        assert p.on_turn_start(user_message=text, platform="telegram", sender_id="42") is None
        if finish:
            assert p.on_turn_end(platform="telegram", sender_id="42") is None


def write_legacy(home, policy):
    old = home / "companion" / "proactivity" / "proactivity.sqlite3"
    old.parent.mkdir(parents=True)
    db = sqlite3.connect(old)
    db.execute("CREATE TABLE policy (singleton INTEGER PRIMARY KEY, settings TEXT, revision INTEGER)")
    db.execute("INSERT INTO policy VALUES (1, ?, 3)", (json.dumps(policy),))
    db.commit()
    db.close()
    return old


class StateTests(unittest.TestCase):
    def test_bind_takes_only_a_telegram_dm_key(self):
        p = P.Proactivity(FakeCtx(), clock=lambda: at("2026-10-07T09:00"))
        for bad in ("", "agent:main:discord:dm:1", "agent:main:telegram:group:1", None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                p.bind(bad)
        p.bind(KEY)
        state = p.load()
        self.assertEqual((state["session_key"], state["nudges"]), (KEY, 0))
        self.assertEqual(state["bound_ts"], at("2026-10-07T09:00").timestamp())

    def test_update_validates_and_persists(self):
        p = P.Proactivity(FakeCtx())
        p.update({"level": "less", "timezone": "Asia/Tokyo"})
        self.assertEqual(p.settings(p.load()), P.Settings(timezone="Asia/Tokyo", base_minutes=240))
        with self.assertRaises(ValueError):
            p.update({"base_minutes": 2})
        p.update({"base_minutes": 2}, min_base=1)
        self.assertEqual(p.settings(p.load()).base_minutes, 2)

    def test_corrupt_state_reads_as_unbound(self):
        ctx = FakeCtx()
        ctx.state.data[P.STATE_KEY] = "junk"
        self.assertEqual(P.Proactivity(ctx).load(), {})

    def test_imports_an_upgraders_binding_once(self):
        with tempfile.TemporaryDirectory() as d:
            old = write_legacy(Path(d), {"session_key": KEY, "timezone": "Europe/Berlin", "enabled": True})
            ctx = FakeCtx()
            p = P.Proactivity(ctx, legacy_home=Path(d))
            state = p.load()
            self.assertEqual(state["session_key"], KEY)
            self.assertEqual(p.settings(state).timezone, "Europe/Berlin")
            self.assertIn(P.STATE_KEY, ctx.state.data)
            self.assertTrue(old.exists())

    def test_imported_pause_stays_paused(self):
        with tempfile.TemporaryDirectory() as d:
            write_legacy(Path(d), {"session_key": KEY, "timezone": "UTC", "enabled": False})
            p = P.Proactivity(FakeCtx(), legacy_home=Path(d))
            self.assertEqual(p.settings(p.load()).paused_until, "off")


class HookTests(unittest.TestCase):
    def test_real_user_message_resets_backoff(self):
        p, clock = runtime(FakeCtx(), at("2026-10-07T09:00"))
        state = p.load()
        state["nudges"] = 3
        p.save(state)
        turn(p, clock, at("2026-10-07T10:00"))
        state = p.load()
        self.assertEqual(state["nudges"], 0)
        self.assertEqual(state["last_user_ts"], at("2026-10-07T10:00").timestamp())
        self.assertEqual(state["last_activity_ts"], at("2026-10-07T10:00").timestamp())

    def test_own_check_in_turn_is_activity_not_the_user(self):
        p, clock = runtime(FakeCtx(), at("2026-10-07T09:00"))
        state = p.load()
        state["nudges"] = 1
        p.save(state)
        turn(p, clock, at("2026-10-07T11:00"), text=P.MARKER + " It has been 2 hours")
        state = p.load()
        self.assertEqual(state["nudges"], 1)
        self.assertNotIn("last_user_ts", state)
        self.assertEqual(state["last_activity_ts"], at("2026-10-07T11:00").timestamp())

    def test_other_sessions_are_ignored(self):
        p, clock = runtime(FakeCtx(), at("2026-10-07T09:00"))
        turn(p, clock, at("2026-10-07T10:00"), key="agent:main:telegram:dm:7")
        self.assertNotIn("last_activity_ts", p.load())

    def test_without_a_session_var_the_dm_sender_id_matches(self):
        p, clock = runtime(FakeCtx(), at("2026-10-07T09:00"))
        turn(p, clock, at("2026-10-07T10:00"), key="")
        self.assertIn("last_user_ts", p.load())
        clock.now = at("2026-10-07T10:30")
        with patch.object(P, "caller_session_key", return_value=""):
            p.on_turn_start(user_message="hi", platform="telegram", sender_id="7")
        self.assertEqual(p.load()["last_user_ts"], at("2026-10-07T10:00").timestamp())

    def test_busy_between_turn_start_and_end(self):
        p, clock = runtime(FakeCtx(), at("2026-10-07T09:00"))
        turn(p, clock, at("2026-10-07T10:00"), finish=False)
        self.assertEqual(p.busy_since, at("2026-10-07T10:00"))
        with patch.object(P, "caller_session_key", return_value=KEY):
            p.on_turn_end(platform="telegram", sender_id="42")
        self.assertIsNone(p.busy_since)


if __name__ == "__main__":
    unittest.main()
