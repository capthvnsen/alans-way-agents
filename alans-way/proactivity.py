"""Idle nudge: when the bound chat has gone quiet during the user's waking hours,
ask the primary bot to reach out once; plus an opt-in morning brief. One rule,
one state file, one tool."""
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import sqlite3
import threading
import zlib

from .voice import FORMAT, INTERNALS, NEXT, PLAIN, RECAP, REPORT, TEXTING

LEVELS = {"less": 240, "normal": 120, "more": 60}
MAX_WAIT = timedelta(days=7)
BUSY_CAP = timedelta(hours=3)
BRIEF_QUIET = timedelta(hours=2)
BRIEF_LATE = timedelta(hours=2)   # past brief time plus this, it's no longer a morning brief


@dataclass(frozen=True)
class Settings:
    timezone: str = ""      # the USER's IANA zone; "" until known, treated as UTC
    base_minutes: int = 120
    active_start: int = 8
    active_end: int = 22
    paused_until: str = ""  # "", "off", or an ISO time with a UTC offset
    morning_brief: bool = False


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


def day_start(s, day):
    return datetime.combine(day, time(s.active_start), zone(s)).astimezone(timezone.utc)


def brief_at(s, day):
    """The local day's brief time: active_start plus 0-20 minutes of jitter, fixed per date
    so a restart or a status call agrees with the timer."""
    jitter = zlib.crc32(day.isoformat().encode()) % 21
    return day_start(s, day) + timedelta(minutes=jitter)


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
    # ponytail: the caller's floor only applies when this change sets the base;
    # a stored sub-15 base (the operator CLI allows 1) needs the 1-1440 check.
    floor = min_base if "base_minutes" in changes else 1
    if type(out.base_minutes) is not int or not floor <= out.base_minutes <= 1440:
        raise ValueError(f"base_minutes must be a whole number from {floor} to 1440")
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
    if type(out.morning_brief) is not bool:
        raise ValueError("morning_brief must be true or false")
    return out


def _window_hours(s):
    """The local hours a check-in may fire in, as a set: 8-22 -> {8..21}."""
    if s.active_start < s.active_end:
        return set(range(s.active_start, s.active_end))
    return set(range(s.active_start, 24)) | set(range(s.active_end))


def loosens(current, new, now):
    """The operator command for a change that makes check-ins reach further,
    else None: the model tool may only make them quieter. Never a no-op."""
    if new.base_minutes < current.base_minutes:
        below = {k: v for k, v in LEVELS.items() if v < current.base_minutes}
        if below:
            near = min(below, key=lambda k: (abs(below[k] - new.base_minutes), below[k]))
            return f"/proactivity {near}"
        return ("hermes proactivity set --settings "
                f"'{json.dumps({'base_minutes': new.base_minutes})}'")
    if is_paused(current, now):
        if not is_paused(new, now):
            return "/proactivity resume"
        if new.paused_until not in ("", "off"):
            earlier = (current.paused_until == "off" or
                       datetime.fromisoformat(new.paused_until)
                       < datetime.fromisoformat(current.paused_until))
            if earlier:
                return "/proactivity resume"
    if _window_hours(new) - _window_hours(current):
        return f"/proactivity hours {new.active_start}-{new.active_end}"
    if new.morning_brief and not current.morning_brief:
        return "/proactivity brief on"
    return None


MARKER = "[Proactive check-in]"
BRIEF_MARKER = "[Morning brief]"
STATE_KEY = "idle"
USAGE = ("usage: /proactivity [status|now|less|normal|more|pause [until]|resume|"
         "hours <start>-<end>|tz <IANA zone>|brief on|off]")
SAFETY = (" This is not new authorization: never send external messages, spend money, change"
          " credentials or permissions, touch production, or delete anything without asking first.")
VOICE = (f" {TEXTING}. {REPORT} {RECAP} {INTERNALS} {PLAIN} No bullet lists; a numbered list"
         f" only for decisions you need from them. {FORMAT} Never mention timers, schedules,"
         f" check-ins or being prompted. Open differently from your recent messages to them. {NEXT}")


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
            out = validate(Settings(), state.get("settings") or {}, min_base=1)
            if self.error == "corrupt settings: using defaults":
                self.error = None
            return out
        except Exception:
            # ponytail: a corrupt blob must not silently revive check-ins, so an
            # individually valid paused_until still applies on top of defaults.
            self.error = "corrupt settings: using defaults"
            blob = state.get("settings")
            try:
                return Settings(paused_until=validate(
                    Settings(), {"paused_until": blob.get("paused_until") if type(blob) is dict
                                 else None}).paused_until)
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
        if (type(session_key) is not str or ":telegram:dm:" not in session_key
                or session_key.endswith(":")):
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
        # In a Telegram DM the chat id is the sender's id. post_llm_call carries
        # no sender_id, so this fallback only matters for pre_llm_call;
        # HERMES_SESSION_KEY covers both hooks in the gateway.
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
            if not str(user_message or "").startswith((MARKER, BRIEF_MARKER)):
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
        if type(key) is not str or ":telegram:dm:" not in key or key.endswith(":"):
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

    def _anchor(self, state):
        ts = max(state.get("last_activity_ts") or 0, state.get("last_nudge_ts") or 0,
                 state.get("bound_ts") or 0)
        return datetime.fromtimestamp(ts, timezone.utc)

    @staticmethod
    def _last_brief(state, today):
        """The last briefed local date. ISO dates sort as strings, and callers use "<"
        rather than "!=" so flying west, which moves the local date back a day,
        can't earn a second brief. A date further ahead than that came from a clock
        jump and is ignored, so it can't stop briefs."""
        last = state.get("last_brief_date", "")
        return "" if last > (today + timedelta(days=1)).isoformat() else last

    def _busy(self, now):
        # ponytail: post_llm_call never fires for a crashed or stopped turn, so a
        # turn older than BUSY_CAP is treated as over.
        return self.busy_since is not None and now - self.busy_since < BUSY_CAP

    def tick(self):
        if not self.gateway:
            return None
        with self._lock:
            state = self.load()
            s, now = self.settings(state), self.clock()
            if not state.get("session_key") or is_paused(s, now) or self._busy(now):
                return None
            anchor, nudges = self._anchor(state), state.get("nudges", 0)
            day = now.astimezone(zone(s)).date()
            brief = (s.morning_brief and self._last_brief(state, day) < day.isoformat()
                     and in_window(s, now) and day_start(s, day) <= now < brief_at(s, day) + BRIEF_LATE)
            if brief and now < brief_at(s, day):
                return None   # the window-start check-in waits for the brief
            if brief:
                # ponytail: the date is spent before injecting, so a refused brief
                # isn't retried; the next check-in counts from it either way.
                state["last_brief_date"] = day.isoformat()
                if now.timestamp() - (state.get("last_user_ts") or 0) < BRIEF_QUIET.total_seconds():
                    state["last_result"] = "brief skipped: user active"
                    self.save(state)
                    return None
                # The brief's own turn may not start before the next tick, so move the
                # check-in anchor now; nudges and last_nudge_ts stay untouched.
                state.update(last_activity_ts=now.timestamp(), last_result="pending")
                text = self.brief_prompt(s, now)
            elif now < due_at(s, anchor, nudges) or not in_window(s, now):
                return None
            else:
                # ponytail: a refused check-in still advances the back-off, so a missing
                # injection permission costs one attempt per wait, not one per minute.
                state.update(last_nudge_ts=now.timestamp(), nudges=nudges + 1, last_result="pending")
                text = self.prompt(s, now - anchor, now)
            # Decide and persist before calling into Hermes: inject_message can run
            # the injected turn's hooks on another thread, so it must run unlocked.
            self.save(state)
            session_key = state["session_key"]
        try:
            accepted = self.ctx.inject_message(text, role="user", session_key=session_key)
            result = "accepted" if accepted is True else "refused"
        except Exception as exc:
            accepted, result = False, f"failed: {type(exc).__name__}"
        with self._lock:
            state = self.load()
            state["last_result"] = result
            self.save(state)
        return accepted is True

    def check_in_now(self):
        """`/proactivity now`: one check-in the user asked for. It skips the wait,
        pause and hours but leaves the back-off state untouched."""
        with self._lock:
            state = self.load()
            s, now = self.settings(state), self.clock()
            if self._busy(now):
                return "I'm mid-reply; send /proactivity now again once I'm done."
            text = self.prompt(s, now - self._anchor(state), now, asked=True)
            session_key = state["session_key"]
        try:
            accepted = self.ctx.inject_message(text, role="user", session_key=session_key)
        except Exception as exc:
            return f"Couldn't start a check-in: {type(exc).__name__}."
        return "Checking in now." if accepted is True else "Couldn't start a check-in: Hermes refused it."

    def prompt(self, s, elapsed, now, *, asked=False):
        hours = elapsed.total_seconds() / 3600
        ago = (f"{round(hours * 60)} minutes" if hours < 1.5 else
               f"{round(hours)} hours" if hours < 48 else f"{round(hours / 24)} days")
        lead = "The user just asked you to check in now. " if asked else ""
        end = (" They asked, so reply with one of these; don't answer [SILENT]." if asked else
               " If nothing is worth their attention, reply with exactly [SILENT] and nothing else.")
        return (f"{MARKER} {lead}It has been {ago} since your last exchange with the user;"
                f" {self._when(s, now)} Pick exactly one:"
                " (a) do one safe, reversible thing that moves their goals forward, then say what you did;"
                " (b) offer one specific thing you could do for them; or (c) ask about a decision they own."
                " Build it around one specific open thread from your memory of their goals and recent"
                " conversations, and name it." + VOICE + " Keep it to 1-3 short sentences." + SAFETY + end)

    def brief_prompt(self, s, now):
        return (f"{BRIEF_MARKER} The user's day is starting; {self._when(s, now)} Send a short morning"
                " brief with only what applies: what you did or learned since your last exchange;"
                " anything time-sensitive today (check their calendar and email read-only if you have"
                " tools for them); anything you tried that failed, and why; and up to 3 decisions you"
                " need from them as numbered questions. Name specific open threads from your memory."
                + VOICE + " Keep it to a few short lines." + SAFETY +
                " If nothing is worth their attention, reply with exactly [SILENT] and nothing else.")

    @staticmethod
    def _when(s, now):
        learn = ("" if s.timezone else
                 " You don't know their timezone yet: ask for it when it fits naturally and save it"
                 " with the proactivity tool.")
        return f"it is {now.astimezone(zone(s)):%A %H:%M} for them.{learn}"

    def status(self):
        with self._lock:
            state = self.load()
            s, now = self.settings(state), self.clock()
            out = {"bound": bool(state.get("session_key")), "settings": asdict(s),
                   "level": next((k for k, v in LEVELS.items() if v == s.base_minutes), "custom"),
                   "timezone_known": bool(s.timezone), "paused": is_paused(s, now),
                   "busy": self._busy(now), "nudges_since_reply": state.get("nudges", 0),
                   "next_check_in": None, "next_brief": None, "in_gateway": self.gateway,
                   "last_result": state.get("last_result"), "last_error": self.error}
            if out["bound"] and not out["paused"]:
                due = due_at(s, self._anchor(state), out["nudges_since_reply"])
                out["next_check_in"] = due.astimezone(zone(s)).isoformat(timespec="minutes")
                if s.morning_brief:
                    today = now.astimezone(zone(s)).date()
                    days = (today + timedelta(days=i) for i in range(3))
                    day = next((d for d in days if d.isoformat() > self._last_brief(state, today)
                                and brief_at(s, d) + BRIEF_LATE > now), None)
                    if day:
                        out["next_brief"] = brief_at(s, day).astimezone(zone(s)).isoformat(timespec="minutes")
            return out

    def tool(self, args, **kwargs):
        args = args if isinstance(args, dict) else {}
        cross = getattr(self, "cross_bot", None)
        if cross and (args.get("action") == "cross_status" or "cross_bot_enabled" in args):
            return cross.tool(args, **kwargs)
        try:
            bound = self.load().get("session_key")
            own = bool(bound) and caller_session_key() == bound
            action = args.get("action")
            if action == "set":
                if not own:
                    return json.dumps({"ok": False, "error": "Check-in settings can only be changed from the bound chat."})
                changes = {k: v for k, v in args.items() if k != "action"}
                if not changes:
                    return json.dumps({"ok": False, "error": "set needs at least one setting"})
                with self._lock:
                    state = self.load()
                    current = self.settings(state)
                    new = validate(current, changes, min_base=15)
                    hint = loosens(current, new, self.clock())
                    if hint:
                        return json.dumps({"ok": False,
                                           "error": "That change would make check-ins reach further; the tool can only make them quieter.",
                                           "ask_user_to_send": hint})
                    state["settings"] = asdict(new)
                    self.save(state)
            elif action == "status":
                if not own:
                    return json.dumps({"ok": True, "bound": bool(bound)})
            else:
                return json.dumps({"ok": False, "error": f"unknown action {action!r}"})
            return json.dumps({"ok": True, **self.status()})
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__})

    def command(self, raw_args=""):
        """`/proactivity ...`: the operator path inside the chat. Plain text, never raises."""
        try:
            words = str(raw_args or "").split()
            verb, rest = (words[0].lower(), words[1:]) if words else ("status", [])
            if verb == "cross" and getattr(self, "cross_bot", None):
                return self.cross_bot.command(" ".join(rest))
            bound = self.load().get("session_key")
            own = bool(bound) and caller_session_key() == bound
            if verb == "status":
                return self._status_text() if own else "Check-ins are configured from the bound chat."
            if verb == "now" and not rest:
                return self.check_in_now() if own else "Check-ins can only be started from the bound chat."
            changes = self._changes(verb, rest)
            if changes is None:
                return USAGE
            if not own:
                return "Check-in settings can only be changed from the bound chat."
            self.update(changes, min_base=15)
            return self._status_text(prefix="Done. ")
        except ValueError as exc:
            return str(exc)
        except Exception as exc:
            return f"proactivity: {type(exc).__name__}"

    @staticmethod
    def _changes(verb, rest):
        """The settings dict for a slash verb, or None for a usage reply."""
        if verb in LEVELS:
            return {"level": verb}
        if verb == "pause" and len(rest) <= 1:
            return {"paused_until": rest[0] if rest else "off"}
        if verb == "resume":
            return {"paused_until": ""}
        if verb == "hours" and len(rest) == 1:
            start, dash, end = rest[0].partition("-")
            if dash and start.isdigit() and end.isdigit():
                return {"active_start": int(start), "active_end": int(end)}
        if verb == "tz" and len(rest) == 1:
            return {"timezone": rest[0]}
        if verb == "brief" and len(rest) == 1 and rest[0].lower() in ("on", "off"):
            return {"morning_brief": rest[0].lower() == "on"}
        return None

    def _status_text(self, prefix=""):
        """One plain sentence: wait and level, hours and zone, pause and next check-in."""
        st = self.status()
        s = st["settings"]
        mins = s["base_minutes"]
        wait = (f"{mins} minutes" if mins % 60 else
                f"{mins // 60} hour" + ("s" if mins > 60 else ""))
        text = (f"{prefix}Check-ins after {wait} of quiet (level {st['level']}), "
                f"{s['active_start']}:00-{s['active_end']}:00 {s['timezone'] or 'UTC (timezone not set)'}")
        if st["paused"]:
            until = s["paused_until"]
            return text + ", paused" + (f" until {until}" if until not in ("", "off") else "") + "."
        text += (f", next {self._next_words(st['next_check_in'])}."
                 if st["next_check_in"] else ".")
        return text + (f" Morning brief next {self._next_words(st['next_brief'])}."
                       if st["next_brief"] else "")

    def _next_words(self, iso):
        """'at 4:01 PM today' — tomorrow, a weekday two to six days out, else the date."""
        due = datetime.fromisoformat(iso)
        days = (due.date() - self.clock().astimezone(due.tzinfo).date()).days
        when = ("today" if days <= 0 else "tomorrow" if days == 1 else
                f"{due:%A}" if days <= 6 else f"{due:%B} {due.day}")
        return f"at {due.hour % 12 or 12}:{due.minute:02d} {'AM' if due.hour < 12 else 'PM'} {when}"

    def on_telegram_connect(self, native=None, adapter=None, **kwargs):
        """register_platform_handler factory. Hermes calls it only when the gateway
        connects Telegram, so CLI, doctor and TUI loads never start the loop."""
        self.gateway = True
        self.start()

    def start(self, interval=60.0):
        def run():
            while not self._stop.wait(interval):
                self.error = None
                try:
                    self.tick()
                except Exception as exc:
                    self.error = type(exc).__name__
        with self._lock:
            if self.worker and self.worker.is_alive():
                return
            self.worker = threading.Thread(target=run, name="alans-way-idle-nudge", daemon=True)
            self.worker.start()

    def close(self):
        self._stop.set()


SCHEMA = {
    "name": "proactivity",
    "description": (
        "Read or change how you proactively check in with the user. You check in after the chat has"
        " been quiet for base_minutes, doubling the wait after each check-in they don't answer (capped"
        " at a week), and only between active_start and active_end in the USER's timezone. If"
        " morning_brief is on you also send one short brief a day near active_start. This tool"
        " can only make check-ins quieter: level 'less', a higher base_minutes, paused_until 'off' or"
        " a future ISO time, a later active_start or earlier active_end, or a new timezone. Anything"
        " that makes check-ins reach further — checking in more, resuming or wider hours — is refused"
        " with an ask_user_to_send command: tell the user to send that exact command. Map requests:"
        " 'check in less' -> level less; 'quiet until Monday' -> paused_until as ISO with their UTC"
        " offset; 'stop checking in' -> paused_until 'off'; 'I'm in Tokyo' -> timezone 'Asia/Tokyo';"
        " 'not before 9am' -> active_start 9; 'stop the morning brief' -> morning_brief false. Only the"
        " user can turn the morning brief on, with /proactivity brief on. After set, confirm the change"
        " from the returned status in plain words. Optional cross-bot export is default off and dispatch"
        " is disabled. cross_status reads its status; set cross_bot_enabled false turns it off and purges"
        " this bot's digest. Only the operator can turn it on with /proactivity cross on; use that setting"
        " alone, without other check-in settings."),
    "parameters": {
        "type": "object", "additionalProperties": False, "required": ["action"],
        "properties": {
            "action": {"type": "string", "enum": ["status", "set", "cross_status"]},
            "cross_bot_enabled": {"type": "boolean"},
            "level": {"type": "string", "enum": list(LEVELS)},
            "base_minutes": {"type": "integer", "minimum": 15, "maximum": 1440},
            "active_start": {"type": "integer", "minimum": 0, "maximum": 23},
            "active_end": {"type": "integer", "minimum": 0, "maximum": 23},
            "timezone": {"type": "string"},
            "paused_until": {"type": "string"},
            "morning_brief": {"type": "boolean"},
        },
    },
}


def cli_setup(parser):
    parser.add_argument("action", nargs="?", default="status", choices=["status", "bind", "set"])
    parser.add_argument("--session-key", help="Existing Telegram DM session key to check in on (bind only)")
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
        cross = getattr(runtime, "cross_bot", None)
        if cross:
            cross.refresh_local()
            cross.tick()
        status = runtime.status() if getattr(runtime, "primary", True) else cross.status()
        if cross and getattr(runtime, "primary", True):
            status["cross_bot"] = cross.status()
        print(json.dumps(status, indent=2))
        return 0
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
