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


class LoosensTests(unittest.TestCase):
    """Pure check: which changes only the operator may make, and the command for each."""
    NOW = at("2026-10-07T12:00")

    def test_table(self):
        s = P.Settings()
        for new, expected in (
            (P.Settings(base_minutes=60), "/proactivity more"),
            (P.Settings(base_minutes=240), None),
            (P.Settings(paused_until="off"), None),
            (P.Settings(paused_until="2026-10-09T00:00:00+00:00"), None),
            (P.Settings(timezone="Asia/Tokyo"), None),
            (P.Settings(active_start=9, active_end=21), None),
            (P.Settings(active_start=7), "/proactivity hours 7-22"),
            (P.Settings(active_end=23), "/proactivity hours 8-23"),
        ):
            with self.subTest(new=new):
                self.assertEqual(P.loosens(s, new, self.NOW), expected)

    def test_a_lower_base_suggests_the_nearest_level(self):
        self.assertEqual(P.loosens(P.Settings(base_minutes=240), P.Settings(),
                                   self.NOW), "/proactivity normal")

    def test_a_lower_base_never_suggests_a_no_op_level(self):
        # 120->100: "normal" is already the level; the nearest preset strictly
        # below the current base is "more".
        self.assertEqual(P.loosens(P.Settings(), P.Settings(base_minutes=100),
                                   self.NOW), "/proactivity more")
        self.assertEqual(P.loosens(P.Settings(base_minutes=240), P.Settings(base_minutes=200),
                                   self.NOW), "/proactivity normal")
        self.assertEqual(P.loosens(P.Settings(base_minutes=240), P.Settings(base_minutes=60),
                                   self.NOW), "/proactivity more")

    def test_a_base_below_every_preset_suggests_the_operator_cli(self):
        self.assertEqual(
            P.loosens(P.Settings(base_minutes=60), P.Settings(base_minutes=30), self.NOW),
            """hermes proactivity set --settings '{"base_minutes": 30}'""")

    def test_resume_and_earlier_resume_need_the_operator(self):
        off = P.Settings(paused_until="off")
        late = P.Settings(paused_until="2026-10-09T00:00:00+00:00")
        early = P.Settings(paused_until="2026-10-08T00:00:00+00:00")
        self.assertEqual(P.loosens(off, P.Settings(), self.NOW), "/proactivity resume")
        self.assertEqual(P.loosens(off, early, self.NOW), "/proactivity resume")
        self.assertEqual(P.loosens(late, early, self.NOW), "/proactivity resume")
        self.assertIsNone(P.loosens(early, late, self.NOW))
        self.assertIsNone(P.loosens(early, off, self.NOW))


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
        for bad in ("", "agent:main:discord:dm:1", "agent:main:telegram:group:1",
                    "agent:main:telegram:dm:", None):
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

    def test_a_stored_test_sized_base_does_not_block_unrelated_chat_sets(self):
        p = P.Proactivity(FakeCtx())
        p.update({"base_minutes": 2}, min_base=1)
        p.update({"paused_until": "off"})
        self.assertEqual(p.settings(p.load()).base_minutes, 2)
        with self.assertRaises(ValueError):
            p.update({"base_minutes": 5})
        p.update({"level": "less"})
        self.assertEqual(p.settings(p.load()).base_minutes, 240)

    def test_corrupt_stored_settings_fall_back_to_defaults(self):
        p = P.Proactivity(FakeCtx())
        for corrupt in ({"active_start": {}}, {"level": {}}, {"level": []}):
            with self.subTest(corrupt=corrupt):
                state = p.load()
                state["settings"] = corrupt
                p.save(state)
                self.assertEqual(p.settings(p.load()), P.Settings())

    def test_corrupt_settings_still_honour_a_valid_pause(self):
        p = P.Proactivity(FakeCtx())
        state = p.load()
        state["settings"] = {"active_start": {}, "paused_until": "off"}
        p.save(state)
        self.assertEqual(p.settings(p.load()), P.Settings(paused_until="off"))
        self.assertEqual(p.error, "corrupt settings: using defaults")
        state["settings"] = {"active_start": {}, "paused_until": "never"}
        p.save(state)
        self.assertEqual(p.settings(p.load()), P.Settings())

    def test_the_corrupt_settings_error_clears_once_settings_validate(self):
        p = P.Proactivity(FakeCtx())
        state = p.load()
        state["settings"] = {"active_start": {}, "paused_until": "off"}
        p.save(state)
        self.assertEqual(p.status()["last_error"], "corrupt settings: using defaults")
        p.update({"active_start": 8})
        self.assertIsNone(p.status()["last_error"])

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

    def test_legacy_import_skips_a_non_dm_key(self):
        for bad in ("agent:main:telegram:group:1", "agent:main:telegram:dm:", "nonsense"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as d:
                write_legacy(Path(d), {"session_key": bad, "timezone": "UTC", "enabled": True})
                p = P.Proactivity(FakeCtx(), legacy_home=Path(d))
                self.assertEqual(p.load(), {})


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


class TickTests(unittest.TestCase):
    def test_quiet_chat_gets_one_nudge_then_doubles(self):
        ctx = FakeCtx()
        p, clock = runtime(ctx, at("2026-10-07T08:30"))
        turn(p, clock, at("2026-10-07T09:00"))
        clock.now = at("2026-10-07T10:59")
        self.assertIsNone(p.tick())
        clock.now = at("2026-10-07T11:00")
        self.assertTrue(p.tick())
        self.assertEqual(ctx.sent[0][1], KEY)
        self.assertTrue(ctx.sent[0][0].startswith(P.MARKER))
        self.assertIn("[SILENT]", ctx.sent[0][0])
        clock.now = at("2026-10-07T14:59")
        self.assertIsNone(p.tick())
        clock.now = at("2026-10-07T15:00")
        self.assertTrue(p.tick())
        self.assertEqual(p.load()["nudges"], 2)

    def test_bot_reply_to_a_check_in_moves_the_anchor_not_the_count(self):
        ctx = FakeCtx()
        p, clock = runtime(ctx, at("2026-10-07T08:30"))
        turn(p, clock, at("2026-10-07T09:00"))
        clock.now = at("2026-10-07T11:00")
        p.tick()
        turn(p, clock, at("2026-10-07T11:01"), text=ctx.sent[0][0])
        clock.now = at("2026-10-07T15:00")
        self.assertIsNone(p.tick())
        clock.now = at("2026-10-07T15:01")
        self.assertTrue(p.tick())

    def test_user_reply_resets_the_backoff(self):
        ctx = FakeCtx()
        p, clock = runtime(ctx, at("2026-10-07T08:30"))
        turn(p, clock, at("2026-10-07T09:00"))
        clock.now = at("2026-10-07T11:00")
        p.tick()
        turn(p, clock, at("2026-10-07T12:00"))
        clock.now = at("2026-10-07T13:59")
        self.assertIsNone(p.tick())
        clock.now = at("2026-10-07T14:00")
        self.assertTrue(p.tick())

    def test_nothing_outside_the_users_window(self):
        ctx = FakeCtx()
        p, clock = runtime(ctx, at("2026-10-07T11:00", "Asia/Tokyo"), timezone="Asia/Tokyo")
        turn(p, clock, at("2026-10-07T12:00", "Asia/Tokyo"))
        clock.now = at("2026-10-07T23:30", "Asia/Tokyo")
        self.assertIsNone(p.tick())
        self.assertEqual(ctx.sent, [])

    def test_long_outage_sends_one_nudge_at_the_window_start(self):
        ctx = FakeCtx()
        p, clock = runtime(ctx, at("2026-10-07T08:30"))
        turn(p, clock, at("2026-10-07T09:00"))
        clock.now = at("2026-10-10T03:00")
        self.assertIsNone(p.tick())
        clock.now = at("2026-10-10T08:00")
        self.assertTrue(p.tick())
        clock.now = at("2026-10-10T08:01")
        self.assertIsNone(p.tick())
        self.assertEqual(len(ctx.sent), 1)

    def test_never_chatted_anchors_at_bind_time(self):
        p, clock = runtime(FakeCtx(), at("2026-10-07T09:00"))
        clock.now = at("2026-10-07T10:59")
        self.assertIsNone(p.tick())
        clock.now = at("2026-10-07T11:00")
        self.assertTrue(p.tick())

    def test_refused_or_failing_injection_still_backs_off(self):
        for accept in (False, RuntimeError("boom")):
            with self.subTest(accept=accept):
                p, clock = runtime(FakeCtx(accept=accept), at("2026-10-07T09:00"))
                clock.now = at("2026-10-07T11:00")
                self.assertFalse(p.tick())
                self.assertEqual(p.load()["nudges"], 1)
                self.assertNotEqual(p.status()["last_result"], "accepted")
                clock.now = at("2026-10-07T11:01")
                self.assertIsNone(p.tick())

    def test_the_backoff_is_saved_before_inject_and_the_result_after(self):
        ctx = FakeCtx()
        p, clock = runtime(ctx, at("2026-10-07T09:00"))
        seen = {}
        inject = ctx.inject_message
        def spy(content, role="user", *, session_key=None):
            seen.update(p.load())
            return inject(content, role=role, session_key=session_key)
        ctx.inject_message = spy
        clock.now = at("2026-10-07T11:00")
        self.assertTrue(p.tick())
        self.assertEqual((seen["nudges"], seen["last_result"]), (1, "pending"))
        self.assertEqual(p.load()["last_result"], "accepted")

    def test_outside_the_gateway_or_paused_never_injects(self):
        ctx = FakeCtx()
        p, clock = runtime(ctx, at("2026-10-07T09:00"))
        clock.now = at("2026-10-07T12:00")
        p.gateway = False
        self.assertIsNone(p.tick())
        p.gateway = True
        p.update({"paused_until": "off"})
        self.assertIsNone(p.tick())
        self.assertEqual(ctx.sent, [])

    def test_busy_turn_blocks_until_it_ends_or_goes_stale(self):
        ctx = FakeCtx()
        p, clock = runtime(ctx, at("2026-10-07T08:00"))
        turn(p, clock, at("2026-10-07T09:00"), finish=False)
        clock.now = at("2026-10-07T11:30")
        self.assertIsNone(p.tick())
        clock.now = at("2026-10-07T12:01")   # turn started over 3h ago: treat as dead
        self.assertTrue(p.tick())

    def test_unknown_timezone_prompt_asks_the_bot_to_learn_it(self):
        p = P.Proactivity(FakeCtx())
        text = p.prompt(P.Settings(), timedelta(hours=3), at("2026-10-07T11:00"))
        self.assertIn("timezone", text)
        self.assertIn("3 hours", text)
        known = p.prompt(P.Settings(timezone="UTC"), timedelta(hours=3), at("2026-10-07T11:00"))
        self.assertNotIn("timezone yet", known)


class ToolTests(unittest.TestCase):
    def test_only_the_bound_chat_can_change_settings(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        with patch.object(P, "caller_session_key", return_value="agent:main:telegram:dm:7"):
            self.assertFalse(json.loads(p.tool({"action": "set", "level": "less"}))["ok"])
        with patch.object(P, "caller_session_key", return_value=KEY):
            out = json.loads(p.tool({"action": "set", "level": "less"}))
        self.assertTrue(out["ok"])
        self.assertEqual(out["level"], "less")

    def test_set_takes_flat_fields_beside_action(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        with patch.object(P, "caller_session_key", return_value=KEY):
            out = json.loads(p.tool({"action": "set", "level": "less", "timezone": "Asia/Tokyo",
                                     "active_start": 9}))
        self.assertTrue(out["ok"])
        s = p.settings(p.load())
        self.assertEqual((s.base_minutes, s.timezone, s.active_start), (240, "Asia/Tokyo", 9))

    def test_a_set_with_no_fields_is_refused(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        with patch.object(P, "caller_session_key", return_value=KEY):
            out = json.loads(p.tool({"action": "set"}))
        self.assertEqual(out, {"ok": False, "error": "set needs at least one setting"})

    def test_schema_exposes_the_six_fields_beside_action(self):
        props = P.SCHEMA["parameters"]["properties"]
        self.assertNotIn("settings", props)
        for name in ("level", "base_minutes", "active_start", "active_end", "timezone", "paused_until"):
            self.assertIn(name, props)
        self.assertEqual(props["level"]["enum"], list(P.LEVELS))
        self.assertEqual((props["base_minutes"]["minimum"], props["base_minutes"]["maximum"]), (15, 1440))
        self.assertEqual(P.SCHEMA["parameters"]["required"], ["action"])
        self.assertFalse(P.SCHEMA["parameters"]["additionalProperties"])

    def test_chat_cannot_go_below_15_minutes(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        with patch.object(P, "caller_session_key", return_value=KEY):
            self.assertFalse(json.loads(p.tool({"action": "set", "base_minutes": 2}))["ok"])

    def test_an_unknown_action_is_an_error_not_a_status(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        out = json.loads(p.tool({"action": "pause"}))
        self.assertFalse(out["ok"])
        self.assertIn("unknown action", out["error"])

    def test_status_reports_next_check_in_in_user_time(self):
        p, clock = runtime(FakeCtx(), at("2026-10-07T09:00"), timezone="Asia/Tokyo")
        turn(p, clock, at("2026-10-07T10:00"))
        with patch.object(P, "caller_session_key", return_value=KEY):
            status = json.loads(p.tool({"action": "status"}))
        self.assertTrue(status["bound"])
        self.assertTrue(status["next_check_in"].endswith("+09:00"))

    def test_status_is_full_only_in_the_bound_chat(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        with patch.object(P, "caller_session_key", return_value=KEY):
            full = json.loads(p.tool({"action": "status"}))
        self.assertIn("settings", full)
        for other in ("agent:main:telegram:dm:7", ""):
            with self.subTest(other=other), patch.object(P, "caller_session_key", return_value=other):
                self.assertEqual(json.loads(p.tool({"action": "status"})), {"ok": True, "bound": True})

    def test_set_that_loosens_is_refused_and_asks_the_user(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        with patch.object(P, "caller_session_key", return_value=KEY):
            out = json.loads(p.tool({"action": "set", "level": "more"}))
        self.assertFalse(out["ok"])
        self.assertEqual(out["ask_user_to_send"], "/proactivity more")
        self.assertEqual(p.settings(p.load()).base_minutes, 120)

    def test_set_cannot_widen_the_active_window(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        with patch.object(P, "caller_session_key", return_value=KEY):
            out = json.loads(p.tool({"action": "set", "active_start": 7}))
        self.assertFalse(out["ok"])
        self.assertEqual(out["ask_user_to_send"], "/proactivity hours 7-22")
        self.assertEqual(p.settings(p.load()).active_start, 8)
        with patch.object(P, "caller_session_key", return_value=KEY):
            out = json.loads(p.tool({"action": "set", "active_start": 9}))
        self.assertTrue(out["ok"])
        self.assertEqual(p.settings(p.load()).active_start, 9)

    def test_set_cannot_resume_but_can_pause(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        with patch.object(P, "caller_session_key", return_value=KEY):
            out = json.loads(p.tool({"action": "set", "paused_until": "off"}))
        self.assertTrue(out["ok"])
        self.assertEqual(p.settings(p.load()).paused_until, "off")
        with patch.object(P, "caller_session_key", return_value=KEY):
            out = json.loads(p.tool({"action": "set", "paused_until": ""}))
        self.assertFalse(out["ok"])
        self.assertEqual(out["ask_user_to_send"], "/proactivity resume")
        self.assertEqual(p.settings(p.load()).paused_until, "off")


class CommandTests(unittest.TestCase):
    """`/proactivity ...`: the operator path inside the chat. Plain text, never raises."""
    OTHER = "agent:main:telegram:dm:7"

    def command(self, p, args, key=KEY):
        with patch.object(P, "caller_session_key", return_value=key):
            return p.command(args)

    def test_status_is_full_in_the_bound_chat_and_vague_elsewhere(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        full = self.command(p, "status")
        self.assertIn("8:00-22:00", full)
        for args in ("", "status"):
            out = self.command(p, args, key=self.OTHER)
            self.assertIn("bound chat", out)
            self.assertNotIn("22:00", out)

    def test_changes_apply_from_the_bound_chat_only(self):
        for args, prep, check in (
            ("more", {}, lambda s: s.base_minutes == 60),
            ("resume", {"paused_until": "off"}, lambda s: s.paused_until == ""),
            ("hours 9-21", {}, lambda s: (s.active_start, s.active_end) == (9, 21)),
            ("tz Asia/Tokyo", {}, lambda s: s.timezone == "Asia/Tokyo"),
            ("pause", {}, lambda s: s.paused_until == "off"),
        ):
            with self.subTest(args=args):
                p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
                if prep:
                    p.update(prep)
                before = p.settings(p.load())
                out = self.command(p, args, key=self.OTHER)
                self.assertEqual(out, "Check-in settings can only be changed from the bound chat.")
                self.assertEqual(p.settings(p.load()), before)
                out = self.command(p, args)
                self.assertTrue(out.startswith("Done."), out)
                self.assertTrue(check(p.settings(p.load())))

    def test_garbage_is_a_usage_line(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        for args in ("fly me to the moon", "hours", "hours nine-ten", "tz"):
            with self.subTest(args=args):
                self.assertIn("/proactivity", self.command(p, args))

    def test_pause_with_trailing_tokens_is_a_usage_line(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        out = self.command(p, "pause 2026-10-08T09:00:00+00:00 plus stuff")
        self.assertEqual(out, P.USAGE)
        self.assertEqual(p.settings(p.load()).paused_until, "")

    def test_status_says_the_next_check_in_in_plain_words(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T14:01", "America/Denver"),
                       timezone="America/Denver")
        out = self.command(p, "status")
        self.assertIn("next at 4:01 PM today", out)
        self.assertNotIn("2026-10-07", out)
        # the change confirmations say it the same way
        self.assertIn("next at 4:01 PM today", self.command(p, "hours 8-21"))

    def test_next_check_in_wording_across_days(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T23:00", "America/Denver"),
                       timezone="America/Denver")
        self.assertIn("next at 8:00 AM tomorrow", self.command(p, "status"))

        p, _ = runtime(FakeCtx(), at("2026-10-07T08:00", "America/Denver"),
                       timezone="America/Denver")
        state = p.load()
        state["nudges"] = 5   # the 64-hour wait lands Saturday morning
        p.save(state)
        self.assertIn("next at 8:00 AM Saturday", self.command(p, "status"))

        state["nudges"] = 8   # the 7-day cap lands the next Wednesday
        p.save(state)
        self.assertIn("next at 8:00 AM October 14", self.command(p, "status"))

    def test_bad_values_reply_with_the_error_and_change_nothing(self):
        p, _ = runtime(FakeCtx(), at("2026-10-07T11:00"))
        out = self.command(p, "tz Mars/Base")
        self.assertIn("unknown timezone", out)
        self.assertEqual(p.settings(p.load()).timezone, "UTC")
        out = self.command(p, "pause tomorrow")
        self.assertIn("paused_until", out)
        out = self.command(p, "hours 9-9")
        self.assertIn("differ", out)


class RegisterTests(unittest.TestCase):
    def test_register_wires_public_surfaces_only(self):
        calls, factories = [], {}
        ctx = SimpleNamespace(
            profile_name="default", state=FakeState(),
            register_tool=lambda **kw: calls.append(("tool", kw["name"], kw["toolset"])),
            register_hook=lambda name, fn: calls.append(("hook", name)),
            register_platform_handler=lambda platform, fn: factories.__setitem__(platform, fn),
            register_skill=lambda name, path: calls.append(("skill", name)),
            register_cli_command=lambda name, *a: calls.append(("cli", name)),
            register_command=lambda name, fn, **kw: calls.append(("command", name)),
            on_unload=lambda fn: calls.append(("unload",)))
        package = sys.modules["alans_way_idle_test"]
        with tempfile.TemporaryDirectory() as d:
            runtime_ = package.register(ctx, legacy_home=d)
        for expected in (("tool", "proactivity", "proactivity"), ("hook", "pre_llm_call"),
                         ("hook", "post_llm_call"), ("cli", "proactivity"),
                         ("command", "proactivity"),
                         ("skill", "workspace-operations"), ("skill", "workspace-setup")):
            self.assertIn(expected, calls)
        self.assertNotIn(("skill", "proactive-primary"), calls)
        self.assertFalse(runtime_.gateway)
        self.assertIsNone(runtime_.worker)
        factories["telegram"](None, None)
        try:
            self.assertTrue(runtime_.gateway)
            self.assertTrue(runtime_.worker.is_alive())
        finally:
            runtime_.close()

    def test_manifest_declares_what_register_registers(self):
        text = (PLUGIN / "plugin.yaml").read_text(encoding="utf-8")
        for name in ("proactivity", "pre_llm_call", "post_llm_call"):
            self.assertIn(f"- {name}", text)
        self.assertNotIn("proactive_control", text)


if __name__ == "__main__":
    unittest.main()
