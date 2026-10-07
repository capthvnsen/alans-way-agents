# Idle Nudge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the alans-way proactivity stack with one small idle-nudge module. When the bound Telegram chat has been quiet, during the user's waking hours, it asks the primary bot to reach out once.

**Architecture:** `alans-way/proactivity.py` holds everything:
- pure schedule math (`due_at`, `next_active`, `validate`)
- a read-only `state.db` activity reader
- a small JSON state file
- a 60-second daemon thread that calls `ctx.inject_message` only inside a live gateway
- one `proactivity` tool and the `hermes proactivity` CLI

`__init__.py` shrinks to `register()`. The old modules, skill, hook and tests are deleted.

**Tech Stack:** Python 3.11 stdlib only (`zoneinfo`, `sqlite3`, `threading`, `dataclasses`), `unittest`, bash (`setup.sh`).

**Spec:** `docs/superpowers/specs/2026-10-07-idle-nudge-design.md`

## Global Constraints

- Work in `/Users/alex/orca/workspaces/alans-way-agents/idle-nudge` on branch `capthvnsen/idle-nudge`.
- Stdlib only. No new dependencies. `requires_hermes: ">=0.21.5"` is unchanged.
- **The active window is the USER's timezone**, never the server's. An unknown timezone is `""`, treated as UTC, and the nudge prompt asks the bot to learn it.
- Defaults:
  - `base_minutes=120`
  - levels `less=240`, `normal=120`, `more=60`
  - `active_start=8`, `active_end=22`
  - the wait is capped at 7 days
- `base_minutes` is 15-1440 from chat and 1-1440 from the operator CLI.
- Silence is the exact reply `[SILENT]`, which Hermes' gateway drops.
- Toolset name stays `proactivity`, so `hermes tools enable proactivity --platform telegram` keeps working. The tool name becomes `proactivity`.
- Don't touch `alans-way/scripts/`, `alans-way-computer/`, `setup-workspace.sh`, or the browser and host sections of `setup.sh`.
- Commit style: one plain-English sentence, as in `git log`. End every commit with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Test command: `python3 -m unittest discover -s tests` and `python3 scripts/check_publication.py`, both from the repo root.

## Review Focus

1. **User timezone different from the server's, across a DST change:** the 8:00 and 22:00 boundaries stay at local wall-clock time for the user. Tested in Task 1.
2. **Gateway back after a long outage or overnight:** exactly one nudge, at the next active-window start, never a burst. Tested in Task 3.
3. **Injection refused or raising** (for example `allow_gateway_injection` missing): no hot loop, the back-off still advances, and status shows the outcome. Tested in Task 3.
4. **Missing `state.db`, a bound chat that never had a message, or a corrupt `state.json`:** no crash, and the wait anchors at bind time. Tested in Tasks 2 and 3.
5. **A different chat or a CLI process:** a non-bound session can't `set`, and a CLI or TUI process never injects. Tested in Task 3.

---

### Task 1: Schedule math

**Files:**
- Create: `alans-way/proactivity.py` (pure functions only in this task)
- Test: `tests/test_proactivity.py`

**Interfaces:**
- Produces: `Settings` (frozen dataclass with fields `timezone: str = ""`, `base_minutes: int = 120`, `active_start: int = 8`, `active_end: int = 22`, `paused_until: str = ""`), `LEVELS: dict[str, int]`, `MAX_WAIT: timedelta`, `zone(s) -> tzinfo`, `in_window(s, t: datetime) -> bool`, `next_active(s, t) -> datetime (UTC)`, `due_at(s, anchor: datetime, nudges: int) -> datetime (UTC)`, `is_paused(s, now) -> bool`, `validate(s, changes: dict, *, min_base=15) -> Settings` (raises `ValueError`).

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_proactivity -v`
Expected: an ERROR at import with `ModuleNotFoundError: ... proactivity`, because the file doesn't exist yet.

- [ ] **Step 3: Write the implementation**

Create `alans-way/proactivity.py`:

```python
"""Idle nudge: when the bound chat has gone quiet during the user's waking hours,
ask the primary bot to reach out once. One rule, one state file, one tool."""
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

LEVELS = {"less": 240, "normal": 120, "more": 60}
MAX_WAIT = timedelta(days=7)


@dataclass(frozen=True)
class Settings:
    timezone: str = ""      # the USER's IANA zone; "" until known, treated as UTC
    base_minutes: int = 120
    active_start: int = 8
    active_end: int = 22
    paused_until: str = ""  # "", "off", or an ISO time with a UTC offset


def zone(s):
    return ZoneInfo(s.timezone) if s.timezone else timezone.utc


def in_window(s, t):
    hour = t.astimezone(zone(s)).hour
    if s.active_start < s.active_end:
        return s.active_start <= hour < s.active_end
    return hour >= s.active_start or hour < s.active_end


def next_active(s, t):
    """t itself inside the user's active hours, else their next active_start."""
    if in_window(s, t):
        return t
    local = t.astimezone(zone(s))
    start = local.replace(hour=s.active_start, minute=0, second=0, microsecond=0)
    if start <= local:
        start = (local + timedelta(days=1)).replace(hour=s.active_start, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc)


def due_at(s, anchor, nudges):
    """One rule: base wait, doubled per unanswered nudge, capped at a week."""
    wait = min(timedelta(minutes=s.base_minutes) * 2 ** min(nudges, 16), MAX_WAIT)
    return next_active(s, anchor + wait)


def is_paused(s, now):
    if s.paused_until == "off":
        return True
    return bool(s.paused_until) and now < datetime.fromisoformat(s.paused_until)


def validate(s, changes, *, min_base=15):
    """Apply chat or CLI changes to s, or raise ValueError naming the bad field."""
    if not isinstance(changes, dict):
        raise ValueError("settings must be an object")
    changes = dict(changes)
    level = changes.pop("level", None)
    if level is not None:
        if level not in LEVELS:
            raise ValueError("level must be less, normal or more")
        changes.setdefault("base_minutes", LEVELS[level])
    unknown = set(changes) - {f.name for f in fields(Settings)}
    if unknown:
        raise ValueError(f"unsupported setting: {', '.join(sorted(unknown))}")
    out = replace(s, **changes)
    if type(out.timezone) is not str:
        raise ValueError("timezone must be an IANA name such as America/Chicago")
    if out.timezone:
        try:
            ZoneInfo(out.timezone)
        except Exception:
            raise ValueError(f"unknown timezone: {out.timezone}") from None
    if type(out.base_minutes) is not int or not min_base <= out.base_minutes <= 1440:
        raise ValueError(f"base_minutes must be a whole number from {min_base} to 1440")
    for name in ("active_start", "active_end"):
        value = getattr(out, name)
        if type(value) is not int or not 0 <= value <= 23:
            raise ValueError(f"{name} must be an hour from 0 to 23")
    if out.active_start == out.active_end:
        raise ValueError("active_start and active_end must differ")
    if type(out.paused_until) is not str:
        raise ValueError("paused_until must be a string")
    if out.paused_until not in ("", "off"):
        try:
            aware = datetime.fromisoformat(out.paused_until).tzinfo is not None
        except ValueError:
            aware = False
        if not aware:
            raise ValueError("paused_until must be '', 'off', or an ISO time with a UTC offset")
    return out
```

(`asdict` is imported now because Task 2 uses it.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_proactivity -v`
Expected: all `ScheduleTests` and `ValidateTests` PASS.

- [ ] **Step 5: Commit**

```bash
git add alans-way/proactivity.py tests/test_proactivity.py
git commit -m "Add the idle-nudge schedule: one doubling wait inside the user's own waking hours.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Activity reader, route check and state file

**Files:**
- Modify: `alans-way/proactivity.py` (append)
- Test: `tests/test_proactivity.py` (append the classes below before `if __name__`)

**Interfaces:**
- Consumes: `Settings`, `validate` from Task 1; `write_private_json(path, dict)` from `alans-way/gateway_guard.py` (it already exists; leave it as it is).
- Produces:
  - `read_activity(home: Path, session_key: str) -> tuple[float|None, float|None]`, returning (newest real message from either side, newest real user message) as epoch seconds
  - `routing_entry(home, session_key) -> dict|None`
  - `is_dm_route(entry, session_key) -> bool`
  - `caller_session_key() -> str`
  - `class Proactivity(ctx, home, *, clock=None)` with `.path`, `.load() -> dict`, `.save(state)`, `.settings(state) -> Settings`, `.update(changes, *, min_base=15)`, `.bind(session_key)`

State file `<home>/companion/proactivity/state.json` holds these keys:
- `session_key`
- `bound_ts` (float)
- `settings` (dict)
- `nudges` (int)
- `last_user_ts` (float)
- `last_nudge_ts` (float)
- `last_result` (str)

- [ ] **Step 1: Write the failing tests**

```python
def make_db(home, rows, key="agent:main:telegram:dm:1"):
    """rows: (role, timestamp, platform_message_id or None)."""
    db = sqlite3.connect(home / "state.db")
    db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, session_key TEXT)")
    db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT,"
               " content TEXT, timestamp REAL, platform_message_id TEXT)")
    db.execute("CREATE TABLE gateway_routing (scope TEXT, session_key TEXT, entry_json TEXT, updated_at REAL)")
    db.execute("INSERT INTO sessions VALUES ('s1', ?)", (key,))
    db.execute("INSERT INTO sessions VALUES ('other', 'agent:main:telegram:dm:2')")
    for role, ts, pmid in rows:
        db.execute("INSERT INTO messages (session_id, role, content, timestamp, platform_message_id)"
                   " VALUES ('s1', ?, 'x', ?, ?)", (role, ts, pmid))
    db.execute("INSERT INTO messages (session_id, role, content, timestamp, platform_message_id)"
               " VALUES ('other', 'user', 'x', 9999999999, '7')")
    db.execute("INSERT INTO gateway_routing VALUES ('', ?, ?, 0)", (key, json.dumps(
        {"session_key": key, "platform": "telegram", "chat_type": "dm", "session_id": "s1"})))
    db.commit()
    db.close()


class ActivityTests(unittest.TestCase):
    def test_injected_and_compaction_turns_are_not_the_user(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            make_db(home, [("user", 100.0, "11"), ("assistant", 150.0, None),
                           ("user", 200.0, None), ("tool", 300.0, None)])
            self.assertEqual(P.read_activity(home, "agent:main:telegram:dm:1"), (150.0, 100.0))

    def test_missing_db_means_no_activity(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(P.read_activity(Path(d), "k"), (None, None))

    def test_route_check(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            make_db(home, [])
            key = "agent:main:telegram:dm:1"
            self.assertTrue(P.is_dm_route(P.routing_entry(home, key), key))
            self.assertFalse(P.is_dm_route(P.routing_entry(home, "agent:main:telegram:dm:9"), "agent:main:telegram:dm:9"))


class StateTests(unittest.TestCase):
    def test_bind_requires_an_existing_dm_route(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            make_db(home, [])
            p = P.Proactivity(SimpleNamespace(), home)
            with self.assertRaises(ValueError):
                p.bind("agent:main:telegram:dm:9")
            p.bind("agent:main:telegram:dm:1")
            state = p.load()
            self.assertEqual(state["session_key"], "agent:main:telegram:dm:1")
            self.assertEqual(state["nudges"], 0)
            self.assertIn("bound_ts", state)

    def test_update_validates_and_persists(self):
        with tempfile.TemporaryDirectory() as d:
            p = P.Proactivity(SimpleNamespace(), Path(d))
            p.update({"level": "less", "timezone": "Asia/Tokyo"})
            self.assertEqual(p.settings(p.load()), P.Settings(timezone="Asia/Tokyo", base_minutes=240))
            with self.assertRaises(ValueError):
                p.update({"base_minutes": 2})
            p.update({"base_minutes": 2}, min_base=1)
            self.assertEqual(p.settings(p.load()).base_minutes, 2)

    def test_corrupt_state_reads_as_unbound(self):
        with tempfile.TemporaryDirectory() as d:
            p = P.Proactivity(SimpleNamespace(), Path(d))
            p.path.parent.mkdir(parents=True)
            p.path.write_text("{not json", encoding="utf-8")
            self.assertEqual(p.load(), {})

    def test_imports_an_upgraders_binding_once(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            old = home / "companion" / "proactivity" / "proactivity.sqlite3"
            old.parent.mkdir(parents=True)
            db = sqlite3.connect(old)
            db.execute("CREATE TABLE policy (singleton INTEGER PRIMARY KEY, settings TEXT, revision INTEGER)")
            db.execute("INSERT INTO policy VALUES (1, ?, 3)", (json.dumps(
                {"session_key": "agent:main:telegram:dm:1", "timezone": "Europe/Berlin", "enabled": True}),))
            db.commit()
            db.close()
            p = P.Proactivity(SimpleNamespace(), home)
            state = p.load()
            self.assertEqual(state["session_key"], "agent:main:telegram:dm:1")
            self.assertEqual(p.settings(state).timezone, "Europe/Berlin")
            self.assertTrue(p.path.exists())
            self.assertTrue(old.exists())

    def test_imported_pause_stays_paused(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            old = home / "companion" / "proactivity" / "proactivity.sqlite3"
            old.parent.mkdir(parents=True)
            db = sqlite3.connect(old)
            db.execute("CREATE TABLE policy (singleton INTEGER PRIMARY KEY, settings TEXT, revision INTEGER)")
            db.execute("INSERT INTO policy VALUES (1, ?, 3)", (json.dumps(
                {"session_key": "k", "timezone": "UTC", "enabled": False}),))
            db.commit()
            db.close()
            p = P.Proactivity(SimpleNamespace(), home)
            self.assertEqual(p.settings(p.load()).paused_until, "off")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_proactivity -v`
Expected: `ActivityTests` and `StateTests` ERROR with `AttributeError: module ... has no attribute 'read_activity'` (or `'Proactivity'`).

- [ ] **Step 3: Write the implementation**

Add these imports at the top of `alans-way/proactivity.py`:

```python
from pathlib import Path
import json
import sqlite3
import threading

from .gateway_guard import write_private_json
```

Append:

```python
def read_activity(home, session_key):
    """(newest real message from either side, newest real user message) in epoch
    seconds. Real user turns carry the platform's message id; the plugin's own
    injected check-ins and compaction summaries don't, so they never count as
    the user talking."""
    path = Path(home) / "state.db"
    if not path.is_file():
        return None, None
    db = sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True, timeout=5)
    try:
        return tuple(db.execute(
            "SELECT MAX(m.timestamp), MAX(CASE WHEN m.role = 'user' THEN m.timestamp END)"
            " FROM messages m JOIN sessions s ON s.id = m.session_id"
            " WHERE s.session_key = ? AND (m.role = 'assistant'"
            " OR (m.role = 'user' AND m.platform_message_id IS NOT NULL))",
            (session_key,)).fetchone())
    finally:
        db.close()


def is_dm_route(entry, session_key):
    return (type(entry) is dict and entry.get("session_key") == session_key
            and entry.get("platform") == "telegram" and entry.get("chat_type") == "dm"
            and type(entry.get("session_id")) is str and bool(entry["session_id"])
            and entry.get("suspended") is not True)
```

Then copy `_routing_entry` from `alans-way/proactive_operator.py:17-58` **verbatim**, renamed `routing_entry`. Same body: `gateway_routing` first, scoped by the resolved sessions dir, then the `sessions/sessions.json` mirror, read-only. Then append:

```python
def caller_session_key():
    """The route Hermes bound around this tool call, or "" outside one."""
    try:
        from gateway.session_context import get_session_env
        return get_session_env("HERMES_SESSION_KEY") or ""
    except Exception:
        import os
        return os.environ.get("HERMES_SESSION_KEY", "")


class Proactivity:
    def __init__(self, ctx, home, *, clock=None):
        self.ctx, self.home = ctx, Path(home)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.path = self.home / "companion" / "proactivity" / "state.json"
        self.error = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.worker = None

    def load(self):
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._import_legacy()
        except (OSError, ValueError):
            return {}
        return state if type(state) is dict else {}

    def save(self, state):
        write_private_json(self.path, state)

    def settings(self, state):
        try:
            return validate(Settings(), state.get("settings") or {}, min_base=1)
        except ValueError:
            return Settings()

    def update(self, changes, *, min_base=15):
        with self._lock:
            state = self.load()
            state["settings"] = asdict(validate(self.settings(state), changes, min_base=min_base))
            self.save(state)

    def bind(self, session_key):
        if not session_key or not is_dm_route(routing_entry(self.home, session_key), session_key):
            raise ValueError("bind only an existing direct Telegram chat in this profile")
        with self._lock:
            state = self.load()
            state.update(session_key=session_key, bound_ts=self.clock().timestamp(), nudges=0)
            state.pop("last_nudge_ts", None)
            self.save(state)

    def _import_legacy(self):
        """Carry an upgrader's bound chat, timezone and pause over from the 0.6 store."""
        old = self.path.parent / "proactivity.sqlite3"
        if not old.is_file():
            return {}
        try:
            db = sqlite3.connect(f"{old.absolute().as_uri()}?mode=ro", uri=True, timeout=5)
            try:
                policy = json.loads(db.execute("SELECT settings FROM policy").fetchone()[0])
            finally:
                db.close()
        except Exception:
            return {}
        key = policy.get("session_key") if type(policy) is dict else None
        if type(key) is not str or not key:
            return {}
        changes = {"paused_until": "off"} if policy.get("enabled") is False else {}
        if type(policy.get("timezone")) is str:
            changes["timezone"] = policy["timezone"]
        try:
            settings = validate(Settings(), changes)
        except ValueError:
            settings = Settings(paused_until=changes.get("paused_until", ""))
        state = {"session_key": key, "bound_ts": self.clock().timestamp(), "nudges": 0,
                 "settings": asdict(settings)}
        self.save(state)
        return state
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_proactivity -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add alans-way/proactivity.py tests/test_proactivity.py
git commit -m "Read real chat activity from state.db and keep idle-nudge state in one JSON file.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The nudge loop, tool, CLI, and removing the old stack

**Files:**
- Modify: `alans-way/proactivity.py` (append)
- Rewrite: `alans-way/__init__.py`
- Trim: `alans-way/gateway_guard.py`
- Delete:
  - `alans-way/proactive_*.py` (every file matching)
  - `alans-way/gateway-hook/`
  - `alans-way/skills/proactive-primary/`
  - `tests/test_proactive_*.py`, `tests/test_board.py`, `tests/test_identity.py`
- Test: `tests/test_proactivity.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces:
  - `Proactivity.in_gateway() -> bool`
  - `Proactivity.tick() -> bool|None`, where `None` means no nudge was due and a bool is the inject result
  - `Proactivity.prompt(s, elapsed: timedelta, now) -> str`
  - `Proactivity.status() -> dict` with keys `bound`, `settings`, `level`, `timezone_known`, `paused`, `nudges_since_reply`, `next_check_in`, `in_gateway`, `last_result`, `last_error`
  - `Proactivity.tool(args, **kw) -> str` (JSON)
  - `Proactivity.start(interval=60.0)`, `Proactivity.close()`
  - `SCHEMA` (dict)
  - `cli_setup(parser)`, `cli_run(runtime, args) -> int`
  - `register(ctx, *, home=None, background=True) -> Proactivity|None`

- [ ] **Step 1: Write the failing tests**

```python
class FakeCtx(SimpleNamespace):
    def __init__(self, gateway=True, cli=None, accept=True):
        super().__init__(_manager=SimpleNamespace(_cli_ref=cli, has_gateway_message_injector=gateway),
                         sent=[], accept=accept)

    def inject_message(self, content, role="user", *, session_key=None):
        if isinstance(self.accept, Exception):
            raise self.accept
        self.sent.append((content, session_key))
        return self.accept


KEY = "agent:main:telegram:dm:1"


def runtime(home, ctx, now, rows=(), **settings):
    make_db(home, rows)
    clock = SimpleNamespace(now=now)
    p = P.Proactivity(ctx, home, clock=lambda: clock.now)
    p.bind(KEY)
    p.update({"timezone": "UTC", **settings}, min_base=1)
    return p, clock


class TickTests(unittest.TestCase):
    def test_quiet_chat_gets_one_nudge_then_doubles(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = FakeCtx()
            last = at("2026-10-07T09:00").timestamp()
            p, clock = runtime(Path(d), ctx, at("2026-10-07T10:59"), [("user", last, "1")])
            self.assertIsNone(p.tick())
            clock.now = at("2026-10-07T11:00")
            self.assertTrue(p.tick())
            self.assertEqual(len(ctx.sent), 1)
            self.assertEqual(ctx.sent[0][1], KEY)
            self.assertIn("[SILENT]", ctx.sent[0][0])
            clock.now = at("2026-10-07T14:59")   # 4h after the nudge not yet reached
            self.assertIsNone(p.tick())
            clock.now = at("2026-10-07T15:00")
            self.assertTrue(p.tick())
            self.assertEqual(p.load()["nudges"], 2)

    def test_user_reply_resets_the_backoff(self):
        with tempfile.TemporaryDirectory() as d:
            home, ctx = Path(d), FakeCtx()
            p, clock = runtime(home, ctx, at("2026-10-07T11:00"), [("user", at("2026-10-07T09:00").timestamp(), "1")])
            p.tick()
            db = sqlite3.connect(home / "state.db")
            db.execute("INSERT INTO messages (session_id, role, content, timestamp, platform_message_id)"
                       " VALUES ('s1', 'user', 'hi', ?, '2')", (at("2026-10-07T12:00").timestamp(),))
            db.commit()
            db.close()
            clock.now = at("2026-10-07T13:59")
            self.assertIsNone(p.tick())
            self.assertEqual(p.load()["nudges"], 0)
            clock.now = at("2026-10-07T14:00")
            self.assertTrue(p.tick())

    def test_nothing_outside_the_users_window(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = FakeCtx()
            p, clock = runtime(Path(d), ctx, at("2026-10-07T23:30", "Asia/Tokyo"),
                               [("user", at("2026-10-07T12:00", "Asia/Tokyo").timestamp(), "1")],
                               timezone="Asia/Tokyo")
            self.assertIsNone(p.tick())
            self.assertEqual(ctx.sent, [])

    def test_long_outage_sends_one_nudge_at_the_window_start(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = FakeCtx()
            p, clock = runtime(Path(d), ctx, at("2026-10-10T03:00"), [("user", at("2026-10-07T09:00").timestamp(), "1")])
            self.assertIsNone(p.tick())
            clock.now = at("2026-10-10T08:00")
            self.assertTrue(p.tick())
            clock.now = at("2026-10-10T08:01")
            self.assertIsNone(p.tick())
            self.assertEqual(len(ctx.sent), 1)

    def test_never_chatted_anchors_at_bind_time(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = FakeCtx()
            p, clock = runtime(Path(d), ctx, at("2026-10-07T09:00"))
            clock.now = at("2026-10-07T10:59")
            self.assertIsNone(p.tick())
            clock.now = at("2026-10-07T11:00")
            self.assertTrue(p.tick())

    def test_refused_or_failing_injection_still_backs_off(self):
        for accept in (False, RuntimeError("boom")):
            with self.subTest(accept=accept), tempfile.TemporaryDirectory() as d:
                ctx = FakeCtx(accept=accept)
                p, clock = runtime(Path(d), ctx, at("2026-10-07T11:00"), [("user", at("2026-10-07T09:00").timestamp(), "1")])
                p.tick()
                self.assertEqual(p.load()["nudges"], 1)
                self.assertNotEqual(p.status()["last_result"], "accepted")
                clock.now = at("2026-10-07T11:01")
                self.assertIsNone(p.tick())

    def test_cli_tui_or_paused_never_inject(self):
        for ctx, settings in ((FakeCtx(gateway=False), {}), (FakeCtx(cli=object()), {}),
                              (FakeCtx(), {"paused_until": "off"})):
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as d:
                p, clock = runtime(Path(d), ctx, at("2026-10-08T11:00"),
                                   [("user", at("2026-10-07T09:00").timestamp(), "1")], **settings)
                self.assertIsNone(p.tick())
                self.assertEqual(ctx.sent, [])

    def test_unknown_timezone_prompt_asks_the_bot_to_learn_it(self):
        p = P.Proactivity(FakeCtx(), Path("/nonexistent"))
        text = p.prompt(P.Settings(), timedelta(hours=3), at("2026-10-07T11:00"))
        self.assertIn("timezone", text)
        self.assertIn("3 hours", text)
        self.assertNotIn("timezone yet", p.prompt(P.Settings(timezone="UTC"), timedelta(hours=3), at("2026-10-07T11:00")))


class ToolTests(unittest.TestCase):
    def test_only_the_bound_chat_can_change_settings(self):
        with tempfile.TemporaryDirectory() as d:
            p, _ = runtime(Path(d), FakeCtx(), at("2026-10-07T11:00"))
            with unittest.mock.patch.object(P, "caller_session_key", return_value="agent:main:telegram:dm:2"):
                out = json.loads(p.tool({"action": "set", "settings": {"level": "less"}}))
            self.assertFalse(out["ok"])
            with unittest.mock.patch.object(P, "caller_session_key", return_value=KEY):
                out = json.loads(p.tool({"action": "set", "settings": {"level": "less"}}))
            self.assertTrue(out["ok"])
            self.assertEqual(out["level"], "less")

    def test_chat_cannot_go_below_15_minutes(self):
        with tempfile.TemporaryDirectory() as d:
            p, _ = runtime(Path(d), FakeCtx(), at("2026-10-07T11:00"))
            with unittest.mock.patch.object(P, "caller_session_key", return_value=KEY):
                out = json.loads(p.tool({"action": "set", "settings": {"base_minutes": 2}}))
            self.assertFalse(out["ok"])

    def test_status_reports_next_check_in_in_user_time(self):
        with tempfile.TemporaryDirectory() as d:
            p, _ = runtime(Path(d), FakeCtx(), at("2026-10-07T11:00"),
                           [("user", at("2026-10-07T10:00").timestamp(), "1")], timezone="Asia/Tokyo")
            status = json.loads(p.tool({"action": "status"}))
            self.assertTrue(status["bound"])
            self.assertTrue(status["next_check_in"].endswith("+09:00"))


class RegisterTests(unittest.TestCase):
    def test_register_wires_tool_cli_and_skills_without_starting_in_tests(self):
        calls = []
        ctx = SimpleNamespace(profile_name="default",
                              register_tool=lambda **kw: calls.append(("tool", kw["name"], kw["toolset"])),
                              register_skill=lambda name, path: calls.append(("skill", name)),
                              register_cli_command=lambda name, *a: calls.append(("cli", name)),
                              on_unload=lambda fn: calls.append(("unload",)))
        package = sys.modules["alans_way_idle_test"]
        with tempfile.TemporaryDirectory() as d:
            package.register(ctx, home=d, background=False)
        self.assertIn(("tool", "proactivity", "proactivity"), calls)
        self.assertIn(("cli", "proactivity"), calls)
        self.assertIn(("skill", "workspace-operations"), calls)
        self.assertIn(("skill", "workspace-setup"), calls)
        self.assertNotIn(("skill", "proactive-primary"), calls)
```

Also add `import unittest.mock` to the test file's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_proactivity -v`
Expected: the new classes ERROR with `AttributeError` (`tick`, `tool`, ...). `RegisterTests` fails on `proactive-primary` or the missing `proactivity` tool.

- [ ] **Step 3: Append the loop, prompt, status, tool and CLI to `proactivity.py`**

Add these methods to `class Proactivity`:

```python
    def in_gateway(self):
        """Only a live messaging gateway may nudge. CLI, doctor and TUI loads run
        register() too; Hermes sets the manager's gateway injector only in a
        gateway. These are private host attributes, so any surprise fails closed."""
        manager = getattr(self.ctx, "_manager", None)
        return (manager is not None and getattr(manager, "_cli_ref", None) is None
                and getattr(manager, "has_gateway_message_injector", False) is True)

    def _schedule(self, state):
        """(anchor datetime or None, nudges) after folding in any new user reply."""
        last_any, last_user = read_activity(self.home, state["session_key"])
        if last_user and last_user > state.get("last_user_ts", 0):
            state.update(last_user_ts=last_user, nudges=0)
        anchor = max([t for t in (last_any, state.get("last_nudge_ts"), state.get("bound_ts")) if t],
                     default=None)
        return (datetime.fromtimestamp(anchor, timezone.utc) if anchor else None,
                state.get("nudges", 0))

    def tick(self):
        if not self.in_gateway():
            return None
        with self._lock:
            state = self.load()
            s, now = self.settings(state), self.clock()
            if not state.get("session_key") or is_paused(s, now):
                return None
            before = dict(state)
            anchor, nudges = self._schedule(state)
            if anchor is None:
                state["bound_ts"] = now.timestamp()
            if anchor is None or now < due_at(s, anchor, nudges) or not in_window(s, now):
                if state != before:
                    self.save(state)
                return None
            try:
                accepted = self.ctx.inject_message(self.prompt(s, now - anchor, now),
                                                   role="user", session_key=state["session_key"])
                result = "accepted" if accepted is True else "refused"
            except Exception as exc:
                accepted, result = False, f"failed: {type(exc).__name__}"
            # ponytail: a refused nudge still advances the back-off, so a missing
            # injection permission costs one attempt per wait, not one per minute.
            state.update(last_nudge_ts=now.timestamp(), nudges=nudges + 1, last_result=result)
            self.save(state)
            return accepted is True

    def prompt(self, s, elapsed, now):
        hours = elapsed.total_seconds() / 3600
        ago = (f"{round(hours * 60)} minutes" if hours < 1.5 else
               f"{round(hours)} hours" if hours < 48 else f"{round(hours / 24)} days")
        local = now.astimezone(zone(s))
        learn = ("" if s.timezone else
                 " You don't know their timezone yet: ask for it when it fits naturally and save it"
                 " with the proactivity tool.")
        return (f"[Proactive check-in] It has been {ago} since your last exchange with the user;"
                f" it is {local:%A %H:%M} for them.{learn} Like a thoughtful employee, pick exactly one:"
                " (a) do one safe, reversible thing that moves their goals forward, then report briefly;"
                " (b) suggest something specific you could do for them; or (c) ask one useful question."
                " Draw on your memory of their goals and open threads, and don't repeat a recent check-in."
                " This is not new authorization: never send external messages, spend money, change"
                " credentials or permissions, touch production, or delete anything without asking first."
                " If nothing is worth their attention, reply with exactly [SILENT] and nothing else.")

    def status(self):
        with self._lock:
            state = self.load()
            s, now = self.settings(state), self.clock()
            out = {"bound": bool(state.get("session_key")), "settings": asdict(s),
                   "level": next((k for k, v in LEVELS.items() if v == s.base_minutes), "custom"),
                   "timezone_known": bool(s.timezone), "paused": is_paused(s, now),
                   "nudges_since_reply": state.get("nudges", 0), "next_check_in": None,
                   "in_gateway": self.in_gateway(), "last_result": state.get("last_result"),
                   "last_error": self.error}
            if out["bound"] and not out["paused"]:
                try:
                    anchor, nudges = self._schedule(state)
                    out["nudges_since_reply"] = nudges
                    if anchor:
                        out["next_check_in"] = due_at(s, anchor, nudges).astimezone(zone(s)).isoformat(timespec="minutes")
                except (OSError, sqlite3.Error):
                    pass
            return out

    def tool(self, args, **kwargs):
        args = args if isinstance(args, dict) else {}
        if args.get("action") == "set":
            bound = self.load().get("session_key")
            if not bound or caller_session_key() != bound:
                return json.dumps({"ok": False, "error": "Check-in settings can only be changed from the bound chat."})
            try:
                self.update(args.get("settings") or {})
            except ValueError as exc:
                return json.dumps({"ok": False, "error": str(exc)})
        return json.dumps({"ok": True, **self.status()})

    def start(self, interval=60.0):
        if self.worker and self.worker.is_alive():
            return
        def run():
            while not self._stop.wait(interval):
                try:
                    self.tick()
                    self.error = None
                except Exception as exc:
                    self.error = type(exc).__name__
        self.worker = threading.Thread(target=run, name="alans-way-idle-nudge", daemon=True)
        self.worker.start()

    def close(self):
        self._stop.set()
```

Append these module-level definitions:

```python
SCHEMA = {
    "name": "proactivity",
    "description": (
        "Read or change how you proactively check in with the user. You check in after the chat has"
        " been quiet for base_minutes, doubling the wait after each check-in they don't answer (capped"
        " at a week), and only between active_start and active_end in the USER's timezone. Map requests:"
        " 'check in less/more' -> level less|more (normal is the default); 'quiet until Monday' ->"
        " paused_until as ISO with their UTC offset; 'stop checking in' -> paused_until 'off';"
        " 'start again' -> paused_until ''; 'I'm in Tokyo' -> timezone 'Asia/Tokyo'; 'not before 9am'"
        " -> active_start 9. After set, confirm the change from the returned status in plain words."),
    "parameters": {
        "type": "object", "additionalProperties": False, "required": ["action"],
        "properties": {
            "action": {"type": "string", "enum": ["status", "set"]},
            "settings": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "level": {"type": "string", "enum": list(LEVELS)},
                    "base_minutes": {"type": "integer", "minimum": 15, "maximum": 1440},
                    "active_start": {"type": "integer", "minimum": 0, "maximum": 23},
                    "active_end": {"type": "integer", "minimum": 0, "maximum": 23},
                    "timezone": {"type": "string"},
                    "paused_until": {"type": "string"},
                },
            },
        },
    },
}


def cli_setup(parser):
    parser.add_argument("action", nargs="?", default="status", choices=["status", "bind", "set"])
    parser.add_argument("--session-key", help="Existing Telegram DM route to check in on (bind only)")
    parser.add_argument("--timezone", help="The user's IANA timezone, such as America/Chicago")
    parser.add_argument("--settings", help='JSON such as {"level": "less"} or {"paused_until": "off"}')


def cli_run(runtime, args):
    try:
        changes = json.loads(args.settings) if args.settings else {}
        if args.timezone:
            changes["timezone"] = args.timezone
        if changes:
            runtime.update(changes, min_base=1)
        if args.action == "bind":
            runtime.bind(args.session_key or "")
        print(json.dumps(runtime.status(), indent=2))
        return 0
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
```

Before relying on `print` plus a return code, check how the current `proactive_operator.execute` reports output and exit status (`alans-way/proactive_operator.py`, from about line 128 to the end), and match it.

- [ ] **Step 4: Rewrite `alans-way/__init__.py`**

```python
"""Hermes plugin entry point: idle check-ins from the primary bot, plus the workspace skills."""
from pathlib import Path

from .gateway_guard import hermes_home
from .proactivity import Proactivity, SCHEMA, cli_run, cli_setup
```

Then copy `_owning_home()` and `_primary_profile(ctx)` **verbatim** from the current file (`alans-way/__init__.py:966-995`), and finish with:

```python
def register(ctx, *, home=None, background=True):
    skills = Path(__file__).parent / "skills"
    ctx.register_skill("workspace-operations", skills / "workspace-operations" / "SKILL.md")
    ctx.register_skill("workspace-setup", skills / "workspace-setup" / "SKILL.md")
    if not _primary_profile(ctx):
        return None
    runtime = Proactivity(ctx, Path(home) if home is not None else _owning_home())
    ctx.register_tool(name="proactivity", toolset="proactivity", schema=SCHEMA,
                      handler=runtime.tool, check_fn=lambda: True)
    if hasattr(ctx, "register_cli_command"):
        ctx.register_cli_command("proactivity", "Idle check-ins from the primary bot", cli_setup,
                                 lambda args: cli_run(runtime, args))
    ctx.on_unload(runtime.close)
    if background:
        runtime.start()
    return runtime
```

- [ ] **Step 5: Delete the old stack and trim the guard**

```bash
git rm -q alans-way/proactive_*.py
git rm -rq alans-way/gateway-hook alans-way/skills/proactive-primary
git rm -q tests/test_proactive_*.py tests/test_board.py tests/test_identity.py
grep -rn "gateway_guard\|proactive_" alans-way alans-way-computer scripts tests --include=*.py --include=*.cjs
```

In `alans-way/gateway_guard.py`, keep `default_hermes_home`, `hermes_home`, `write_private_json` and whatever imports they need. Delete `_process_started_at`, `mark_gateway_ready`, `gateway_ready`, the tolerance constants and the file-lock helpers, unless the grep above shows another user. Update its module docstring to say it holds the home and private-write helpers.

- [ ] **Step 6: Run the full suite**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -30`
Expected:
- `tests.test_proactivity` passes.
- `tests/test_setup_sh.py` (hook and guard tests at about lines 980-1110, and the probe and pause binding tests) and `tests/test_workspace_mac.py:44-124` (`MacStateReaderTests`, which imports `proactive_observe`) fail. Task 4 handles `test_setup_sh`.
- In this task, delete `MacStateReaderTests` from `tests/test_workspace_mac.py` (it tested the deleted observer), then re-run.
- Only `test_setup_sh` failures should remain.

- [ ] **Step 7: Commit**

```bash
git add -A alans-way tests
git commit -m "Replace the proactivity stack with the idle nudge: one loop, one tool, one CLI.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Setup, docs and manifest

**Files:**
- Modify: `setup.sh` (flags and help text about proactivity; `--verify` at about lines 402-436; toolsets at about 825-841; hook section at about 904-934; timezone text at about 733-758; binding at about 1646-1767; done text at about 1849-1853)
- Modify: `tests/test_setup_sh.py`, `tests/test_workspace_setup_skill.py`
- Modify: `alans-way/plugin.yaml`, `README.md`, `SECURITY.md`, `CONTRIBUTING.md`, `alans-way/README.md`, `alans-way/skills/workspace-setup/SKILL.md`, `alans-way/skills/workspace-operations/SKILL.md`
- Rewrite: `docs/proactivity.md`

**Interfaces:**
- Consumes: the CLI from Task 3: `hermes proactivity bind --session-key K [--timezone TZ]`, `hermes proactivity set --settings JSON`, `hermes proactivity status`.

- [ ] **Step 1: Update the setup tests first (they fail until Step 2)**

In `tests/test_setup_sh.py`:
- Delete the tests that exercise the hook, the guard or the startup marker (`grep -n "hook\|gateway_guard\|gateway-owner" tests/test_setup_sh.py`; about lines 980-1110).
- Delete the hook-stub `mkdir`/`write_text` lines in the verify tests.
- Replace `test_proactive_no_pauses_before_the_probe` with:

```python
    def test_proactive_no_binds_paused(self):
        # same fixture setup as the test it replaces
        ...
        self.assertIn('proactivity set --settings {"paused_until": "off"}', calls)
        self.assertNotIn("proactivity probe", calls)
```

  Keep the original test's fixture lines exactly. Only the assertions change.
- In the bind tests, replace `assertIn("-p delta proactivity probe", calls)` with `assertNotIn("proactivity probe", calls)`.
- Keep `assertIn("proactivity on by default", ...)`, which Step 2 preserves.
- Add a test that a stale `hooks/alans-way` containing a `HOOK.yaml` with `name: alans-way-gateway` is removed by a setup run, and that an unrelated `hooks/other` is left alone. Use the existing fixture style from the verify tests.

Run: `python3 -m unittest tests.test_setup_sh -v 2>&1 | tail -20`. Expected: the new and changed tests FAIL.

- [ ] **Step 2: Edit `setup.sh`**

1. **Hook section:** replace the whole `step "Gateway hook"` block with a stale-hook removal:

```bash
# ---------------------------------------------------------------- old hook
# 0.6 armed proactivity with a gateway:startup hook; the idle nudge detects the
# gateway itself, so remove only the hook this plugin installed.
for hook_dir in "$HERMES_HOME/hooks/$PLUGIN_NAME" "$HERMES_HOME"/profiles/*/hooks/"$PLUGIN_NAME"; do
  [ -f "$hook_dir/HOOK.yaml" ] && grep -q "alans-way-gateway" "$hook_dir/HOOK.yaml" \
    && rm -rf "$hook_dir" && ok "removed the old proactivity hook from $hook_dir"
done
```

2. **`--verify`:** delete the hook checks. Keep the toolset check.
3. **`enable_proactivity_toolsets`:** loop over `telegram` only. Delete the cron line and its comment.
4. **Timezone text:** change "for quiet hours" to "for check-in hours" in the `ok` and `ask` strings.
5. **Binding:** keep route listing and selection unchanged. Replace everything from `if [ "$BOUND" = 1 ]; then` through the probe `fi` with:

```bash
         if [ "$BOUND" = 1 ]; then
           ok "bound primary route: $SEL_AGENT"
           if [ -z "$TIMEZONE" ]; then
             warn "no timezone known: the bot will ask you for it. Or set it with: hermes -p $BIND_PROF proactivity set --timezone <IANA zone>"
           elif [ "$TZ_SET" != 1 ]; then
             hermes -p "$BIND_PROF" proactivity set --timezone "$TIMEZONE" >/dev/null 2>&1 \
               && ok "check-in hours use $TIMEZONE" \
               || warn "could not set timezone $TIMEZONE"
           else
             ok "check-in hours use $TIMEZONE"
           fi
           if [ "${PROACTIVE:-yes}" = no ]; then
             hermes -p "$BIND_PROF" proactivity set --settings '{"paused_until": "off"}' >/dev/null 2>&1 \
               && say "  check-ins bound but paused: tell your bot \"start checking in\" to turn them on" \
               || warn "could not pause: check-ins stay on"
           else
             ok "proactivity on by default: tell your bot \"stop checking in\" to pause"
           fi
```

6. Update `--help` and done text that mention `/proactivity`, `/watch`, probe or the hook: one line saying check-ins are tuned by talking to the bot.

Run: `bash -n setup.sh && python3 -m unittest tests.test_setup_sh -v 2>&1 | tail -20`. Expected: PASS.

- [ ] **Step 3: Manifest and docs**

`alans-way/plugin.yaml`:

```yaml
name: alans-way
version: "0.7.0"
description: "Idle check-ins from your primary Hermes bot, plus the workspace browser skills. The desktop app is a separate repo; the workspace-setup skill walks the agent through it."
author: "capthvnsen, Hermes Agent"
license: MIT
homepage: "https://github.com/capthvnsen/alans-way-agents"
requires_hermes: ">=0.21.5"
tags:
  - proactivity
  - workspace
provides_tools:
  - proactivity
```

Rewrite `docs/proactivity.md`:

````markdown
# Proactive check-ins

Your primary Telegram bot reaches out on its own when you've gone quiet, like a
proactive employee: it does something useful and tells you, suggests something it
could do, or asks a good question. If nothing is worth saying it stays silent.

## When it checks in

- After **2 hours** of quiet in the bound chat (from you or the bot).
- Each check-in you don't answer doubles the next wait: about 2h, 6h, 14h, 1.3
  days, 2.6 days, 5.3 days, then roughly weekly. Replying resets it.
- Only between **8:00 and 22:00 in your timezone**, not the server's. Setup reads
  your timezone from your computer; if it can't, the bot asks you.
- Never mid-conversation or while the bot is working.

It never sends external messages, spends money, changes credentials or
permissions, touches production, or deletes anything without asking.

## Tune it by talking to your bot

| Say | Effect |
| --- | --- |
| "Check in less" / "more" | Wait 4h / 1h instead of 2h |
| "Quiet until Monday" | Pause until then |
| "Stop checking in" / "Start again" | Pause / resume |
| "I'm in Tokyo this week" | Use Asia/Tokyo for check-in hours |
| "Not before 9am" | Start the day at 9:00 |
| "When will you check in next?" | Shows the next check-in time |

Only the bound chat can change these.

## Setup

`setup.sh` binds the primary bot (pick its Telegram chat from the list) and sets
your timezone. To do it by hand:

```sh
hermes plugins enable alans-way
hermes config set plugins.entries.alans-way.allow_gateway_injection true
hermes tools enable proactivity --platform telegram
hermes proactivity bind --session-key '<telegram dm session key>' --timezone America/Chicago
hermes gateway restart
hermes proactivity status
```

`hermes proactivity set --settings '{"base_minutes": 2}'` makes a test check-in
arrive two minutes after you stop chatting. Set it back with
`'{"level": "normal"}'`.

## How it works

A 60-second timer inside the gateway reads the bound chat's last real message
from Hermes' `state.db` (your messages carry a Telegram id; the plugin's own
prompts don't). When a check-in is due it injects one internal prompt into that
chat; the bot decides what to do with its own memory and tools. A `[SILENT]`
reply is never delivered. State lives in
`$HERMES_HOME/companion/proactivity/state.json`.

Upgrading from 0.6 keeps your bound chat, timezone and pause. Watches, sweeps
and `/watch` are gone.
````

Other docs:
- **README.md, SECURITY.md, CONTRIBUTING.md, alans-way/README.md:** replace each proactivity passage (find them with `grep -n -i "proactiv\|/watch\|hook\|appraiser\|ledger" <file>`) with one or two sentences matching `docs/proactivity.md`. Keep every browser, workspace and security statement that isn't about proactivity.
- **`workspace-setup/SKILL.md`:** replace the binding and `/watch` instructions (about lines 3, 31-44 and 103-115) with the three commands from the Setup section above. Keep `--bind --proactive yes|no`.
- **`workspace-operations/SKILL.md`:** delete the sentences at about lines 130-134 about the observer's offline-to-online event.
- **`tests/test_workspace_setup_skill.py:59`:** update to match.

- [ ] **Step 4: Run everything**

Run: `python3 -m unittest discover -s tests 2>&1 | tail -5 && python3 scripts/check_publication.py && grep -rn -i "proactive_control\|proactive-primary\|/watch\|gateway-hook" --include=*.md --include=*.py --include=*.sh --include=*.yaml . | grep -v docs/superpowers`
Expected: `OK`, the publication check passes, and the grep prints nothing.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Point setup, docs and the manifest at the idle nudge and remove the old hook on upgrade.

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Live acceptance on the author's Hermes (clawbot)

This runs against Alex's live Hermes, which Alex has authorized: `ssh clawbot-root`, Hermes as root at `/root/.hermes`. Not a code task. It's driven by the `/loop`. Any bug found goes back through a fix, a review and a redeploy.

- [ ] **Step 1: Back up the live install**

```bash
ssh clawbot-root 'cd /root/.hermes && tar czf /root/alans-way-backup-$(date +%Y%m%d%H%M).tgz plugins/alans-way hooks/alans-way companion/proactivity config.yaml && ls -la /root/alans-way-backup-*'
```

- [ ] **Step 2: Deploy the branch**

Check how `/root/.hermes/plugins/alans-way` was installed (`ls -la`, `git -C ... remote -v`). If it's a git checkout, fetch and check out `capthvnsen/idle-nudge` after pushing the branch. Otherwise copy `alans-way/` over it with `rsync -a --delete`, excluding `__pycache__`. Then:

```bash
ssh clawbot-root 'rm -rf /root/.hermes/hooks/alans-way; export PATH=$HOME/.local/bin:$PATH; hermes tools enable proactivity --platform telegram; hermes gateway restart; sleep 20; hermes proactivity status'
```

Expected:
- `bound: true` (imported from 0.6)
- `timezone_known: true`
- after restart, a gateway log line showing no plugin load errors (`hermes logs` or `journalctl`, whichever the install uses)
- `in_gateway` in CLI status reads `false`. That's correct: the CLI isn't the gateway.

- [ ] **Step 3: Acceptance checks** (spec items 1-7)

1. `hermes proactivity set --settings '{"base_minutes": 2}'`. Stop chatting, and confirm a check-in reaches Telegram within about 3 minutes. Read the delivered text back from `state.db` (assistant row after the injected prompt).
2. Ignore it. The next one should arrive about 4 minutes after the first reply or anchor. Confirm with timestamps.
3. Send a real reply from Alex's Telegram (ask Alex, or use the companion app's Telegram Web), and confirm `nudges_since_reply` returns to 0.
4. Say "check in less" in chat, and confirm via `status` that `level` is `less`. Say "quiet till tomorrow" and confirm `paused` is true. Then "start again".
5. Set the timezone to one where it's currently night. Confirm nothing is sent for 5+ minutes, then restore the real timezone.
6. Check that a `[SILENT]` choice, if one happens, isn't delivered and still raises `nudges`. Look in `state.db` for an assistant `[SILENT]` row with no Telegram message.
7. Run `hermes proactivity status` and `hermes doctor`, and confirm neither injects (no new injected user rows).

- [ ] **Step 4: Restore real settings**

`hermes proactivity set --settings '{"level": "normal"}'` with Alex's real timezone, and leave it running.
