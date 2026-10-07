"""Idle nudge: when the bound chat has gone quiet during the user's waking hours,
ask the primary bot to reach out once. One rule, one state file, one tool."""
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import sqlite3
import threading

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


MARKER = "[Proactive check-in]"
STATE_KEY = "idle"


def caller_session_key():
    """The session Hermes bound around this hook or tool call, or "" outside one."""
    try:
        from gateway.session_context import get_session_env
        return get_session_env("HERMES_SESSION_KEY") or ""
    except Exception:
        return ""


class Proactivity:
    def __init__(self, ctx, *, clock=None, legacy_home=None):
        self.ctx = ctx
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.legacy_home = Path(legacy_home) if legacy_home else None
        self.gateway = False   # set once Telegram connects inside the gateway process
        self.busy_since = None
        self.error = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self.worker = None

    def load(self):
        state = self.ctx.state.get(STATE_KEY)
        if state is None:
            return self._import_legacy()
        return state if type(state) is dict else {}

    def save(self, state):
        self.ctx.state.set(STATE_KEY, state)

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
        # ponytail: shape check only; setup.sh lists real routes, and a wrong key
        # just shows up as a refused check-in in status.
        if type(session_key) is not str or ":telegram:dm:" not in session_key:
            raise ValueError("bind a Telegram DM session key, such as agent:main:telegram:dm:<chat id>")
        with self._lock:
            state = self.load()
            state.update(session_key=session_key, bound_ts=self.clock().timestamp(), nudges=0)
            state.pop("last_nudge_ts", None)
            self.save(state)

    def _is_bound_chat(self, state, kwargs):
        bound = state.get("session_key")
        if not bound:
            return False
        key = caller_session_key()
        if key:
            return key == bound
        # In a Telegram DM the chat id is the sender's id.
        return (kwargs.get("platform") == "telegram"
                and str(kwargs.get("sender_id") or "") == bound.rsplit(":", 1)[-1])

    def on_turn_start(self, user_message="", **kwargs):
        """pre_llm_call. Always returns None: a value here would be injected as context."""
        with self._lock:
            state = self.load()
            if not self._is_bound_chat(state, kwargs):
                return None
            now = self.clock()
            self.busy_since = now
            state["last_activity_ts"] = now.timestamp()
            if not str(user_message or "").startswith(MARKER):
                state.update(last_user_ts=now.timestamp(), nudges=0)
            self.save(state)
        return None

    def on_turn_end(self, **kwargs):
        """post_llm_call."""
        with self._lock:
            state = self.load()
            if not self._is_bound_chat(state, kwargs):
                return None
            self.busy_since = None
            state["last_activity_ts"] = self.clock().timestamp()
            self.save(state)
        return None

    def _import_legacy(self):
        """Carry an upgrader's bound chat, timezone and pause over from the 0.6 store."""
        if self.legacy_home is None:
            return {}
        old = self.legacy_home / "companion" / "proactivity" / "proactivity.sqlite3"
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
