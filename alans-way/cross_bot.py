"""Opt-in owner-DM exports. Stage 1 never dispatches or injects shared text.

The shared root is explicit, POSIX-only, and opened through checked directory
handles. Every transaction has one bounded advisory lock; JSON replacement is
atomic. No Hermes history, auth/config files or private host APIs are read.
"""
from contextlib import contextmanager, ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
import unicodedata
import uuid

UTC = timezone.utc
DIGEST_BYTES = 2048
MAX_PROFILES = 16
TTL = timedelta(hours=24)
DEDUP_TTL = timedelta(hours=48)
MAX_DEDUP = 512
PROFILE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
OPAQUE = re.compile(r"[a-f0-9]{64}\Z")

EXCHANGE_BYTES = 8192
# Fixed alternatives and single character-class quantifiers: no overlapping or
# nested repetitions. Each search consumes O(n); the fixed number of searches
# and disjoint token matches keep the entire signal check linear in input size.
_KEYWORDS = re.compile(
    r"\b(?:passcode|cvv|cvc|password|passwd|secret|token|api key|private key|otp|"
    r"verification code|2fa|ssn|routing number|account number|passphrase|authorization|"
    r"cookie|your code|clientsecret|access key)\b")
_PREFIXES = ("sk_", "rk_", "pk_live", "ghp_", "gho_", "github_pat_", "xox", "akia", "aiza",
             "sk-ant-", "sk-", "eyj", "-----begin", "bearer ")
# "pin" is everyday map/pinning language; only a PIN followed closely by digits is a signal.
# Bounded {0,3} gaps (no open-ended quantifiers) keep this linear.
_PIN = re.compile(r"\bpin\b[ \t]{0,3}(?:is|code|number|no|#|:|=)?[ \t:.#]{0,3}\d{4,8}\b")
_USERINFO = re.compile(r"://[^\s/@:]*:[^\s/@]*@")
# A fixed first character class lets the engine skip non-digits in C.
_DIGITS = re.compile(r"[0-9]" * 12)
_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9_+\-/=])[A-Za-z0-9_+\-/=]{32,}")
_LETTER = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"[0-9]")
_NUMBER_SEPARATORS = str.maketrans("", "", " -")


def secret_signal(text):
    """Linear-time signal detection; called only after the raw byte-size gate."""
    digit = _DIGIT.search(text)
    if digit is not None:
        # Numeric/entropy signals short-circuit before scanning keyword labels.
        if len(text) - digit.start() >= 12 and _DIGITS.search(text.translate(_NUMBER_SEPARATORS)):
            return True
        for match in _LONG_TOKEN.finditer(text):
            start, end = match.span()
            if (end > digit.start() and _LETTER.search(text, start, end)
                    and (start <= digit.start() or _DIGIT.search(text, start, end))):
                return True
    folded = text.casefold()
    return bool(_KEYWORDS.search(folded.replace("_", " ")) or _PIN.search(folded)
                or any(prefix in folded for prefix in _PREFIXES) or _USERINFO.search(text))


def sanitize(text, *, max_bytes=700, redact_terms=()):
    """Skip signal-bearing text entirely; truncate unchanged safe text afterwards.

    Only bounded text is accepted, never attachments/history/tool dumps.
    Operator terms remain bounded literals and now also drop the whole exchange.
    Normalization is detection-only: kept excerpts preserve the original text.
    """
    try:
        if type(text) is not str or len(text) > EXCHANGE_BYTES:
            return None
        raw = text.encode("utf-8")
        if len(raw) > EXCHANGE_BYTES:
            return None
        if type(max_bytes) is not int or not 1 <= max_bytes <= 1024:
            return None
        if not isinstance(redact_terms, (list, tuple)) or len(redact_terms) > 32:
            return None
        if any(type(term) is not str or not 1 <= len(term) <= 128 for term in redact_terms):
            return None
        check = unicodedata.normalize("NFKC", text)
        check = "".join(ch for ch in check if unicodedata.category(ch) != "Cf")
        if secret_signal(check) or any(term.casefold() in check.casefold() for term in redact_terms):
            return None
        return raw[:max_bytes].decode("utf-8", errors="ignore")
    except Exception:
        return None


def profile_id(value):
    if type(value) is not str or not PROFILE.fullmatch(value):
        raise ValueError("invalid profile id")
    return value


def stamp(value):
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def utc(value):
    if type(value) is not str or len(value) > 40:
        raise ValueError("invalid UTC timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("invalid UTC timestamp")
    return parsed


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def keys(value, expected):
    if type(value) is not dict or set(value) != set(expected.split()):
        raise ValueError("invalid shared-store schema")


def generation(value):
    if type(value) is not int or not 1 <= value <= 2**53:
        raise ValueError("invalid generation")


def schema(value):
    if type(value.get("schema")) is not int or value["schema"] != 1:
        raise ValueError("unsupported shared-store schema")


def boolean(value):
    if type(value) is not bool:
        raise ValueError("invalid boolean")


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate shared-store key")
        result[key] = value
    return result


class SharedStore:
    def __init__(self, root, *, primary="default", clock=None, lock_timeout=0.25, prune=True):
        self.root = Path(root)
        if not self.root.is_absolute() or ".." in self.root.parts or self.root == Path("/"):
            raise ValueError("cross_bot.shared_root must be an explicit absolute directory")
        self.primary = profile_id(primary)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lock_timeout = min(max(lock_timeout, 0.0), 1.0)
        self._mutex = threading.RLock()
        with self.transaction() as root_fd:
            if self.read(root_fd, "control.json") is None:
                self.write(root_fd, "control.json", {"schema": 1, "primary": self.primary,
                           "enabled": False, "generation": 1})
            self.control(root_fd)
            if prune:
                with self.profiles(root_fd) as profiles:
                    self.prune_locked(root_fd, profiles)

    @staticmethod
    def checked(fd, *, directory=False, private=True):
        info = os.fstat(fd)
        expected = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected(info.st_mode) or (not directory and info.st_nlink != 1):
            raise ValueError("shared store requires regular private files/directories")
        owners = {os.geteuid()} if private else {0, os.geteuid()}
        mode = stat.S_IMODE(info.st_mode)
        if info.st_uid not in owners:
            raise ValueError("unsafe shared-store ownership")
        if private and mode != (0o700 if directory else 0o600):
            raise ValueError("unsafe shared-store permissions")
        if not private and mode & 0o022 and not info.st_mode & stat.S_ISVTX:
            raise ValueError("unsafe shared-store parent permissions")

    @classmethod
    @contextmanager
    def directory(cls, parent, name, *, create=True):
        if create:
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
            except FileExistsError:
                pass
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            cls.checked(fd, directory=True)
            yield fd
        finally:
            os.close(fd)

    def open_root(self):
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise ValueError("cross-bot private shared storage requires POSIX")
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
        try:
            for index, part in enumerate(self.root.parts[1:]):
                final = index == len(self.root.parts) - 2
                created = False
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except FileNotFoundError:
                    os.mkdir(part, 0o700, dir_fd=fd)
                    created = True
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                try:
                    self.checked(child, directory=True, private=final or created)
                except Exception:
                    os.close(child)
                    raise
                os.close(fd)
                fd = child
            return fd
        except Exception:
            os.close(fd)
            raise

    @contextmanager
    def transaction(self):
        import fcntl  # POSIX storage fails closed elsewhere
        # Protect both distinct process writers and threads sharing one instance.
        if not self._mutex.acquire(timeout=self.lock_timeout):
            raise ValueError("shared store busy")
        root_fd = lock_fd = None
        try:
            root_fd = self.open_root()
            lock_fd = os.open("store.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                              0o600, dir_fd=root_fd)
            self.checked(lock_fd)
            end = time.monotonic() + self.lock_timeout
            while True:
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= end:
                        raise ValueError("shared store busy") from None
                    time.sleep(0.01)
            yield root_fd
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
            if root_fd is not None:
                os.close(root_fd)
            self._mutex.release()

    @classmethod
    def checked_file(cls, fd, name):
        try:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except FileNotFoundError:
            return None
        try:
            cls.checked(handle)
        except Exception:
            os.close(handle)
            raise
        return handle

    @classmethod
    def read(cls, fd, name, limit=65536):
        handle = cls.checked_file(fd, name)
        if handle is None:
            return None
        try:
            if os.fstat(handle).st_size > limit:
                raise ValueError("shared-store file too large")
            with os.fdopen(handle, "rb", closefd=False) as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise ValueError("shared-store file too large")
            return json.loads(data, object_pairs_hook=strict_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))
        finally:
            os.close(handle)

    @classmethod
    def remove(cls, fd, name):
        handle = cls.checked_file(fd, name)
        if handle is None:
            return
        os.close(handle)
        os.unlink(name, dir_fd=fd)
        os.fsync(fd)

    @classmethod
    def write(cls, fd, name, value):
        # Validate an existing destination before replacing; never follow it.
        handle = cls.checked_file(fd, name)
        if handle is not None:
            os.close(handle)
        temporary = ".tmp-" + uuid.uuid4().hex
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=fd)
        try:
            with os.fdopen(handle, "wb") as stream:
                cls.checked(stream.fileno())
                stream.write(encode(value))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
            os.fsync(fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass

    def control(self, fd):
        value = self.read(fd, "control.json", 1024)
        keys(value, "schema primary enabled generation")
        schema(value)
        profile_id(value["primary"])
        boolean(value["enabled"])
        generation(value["generation"])
        if value["primary"] != self.primary:
            raise ValueError("cross_bot.primary differs from shared control")
        return value

    @staticmethod
    def names(fd):
        result = []
        with os.scandir(fd) as entries:
            for entry in entries:
                profile_id(entry.name)
                if not entry.is_dir(follow_symlinks=False):
                    raise ValueError("unsafe profile directory")
                result.append(entry.name)
                if len(result) > MAX_PROFILES:
                    raise ValueError("too many profiles (maximum 16)")
        return sorted(result)

    @contextmanager
    def profiles(self, root_fd, *, create=None):
        """Enumerate once and retain validated handles for the transaction."""
        with self.directory(root_fd, "profiles") as parent, ExitStack() as stack:
            names = self.names(parent)
            if create is not None and profile_id(create) not in names:
                if len(names) >= MAX_PROFILES:
                    raise ValueError("too many profiles (maximum 16)")
                names.append(create)
            yield {name: stack.enter_context(self.directory(parent, name, create=name == create)) for name in names}

    def get_presence(self, fd, name):
        value = self.read(fd, "presence.json", 2048)
        if value is None:
            return None
        keys(value, "schema profile generation enabled heartbeat bound")
        schema(value)
        if value["profile"] != name:
            raise ValueError("wrong presence profile")
        generation(value["generation"])
        boolean(value["enabled"])
        boolean(value["bound"])
        if utc(value["heartbeat"]) > self.clock():
            raise ValueError("future presence")
        return value

    def presence_value(self, old, name, bound):
        boolean(bound)
        return {"schema": 1, "profile": name, "generation": old["generation"] if old else 1,
                "enabled": old["enabled"] if old else False, "heartbeat": stamp(self.clock()),
                "bound": bound}

    def presence(self, name, *, bound=False):
        with self.transaction() as root_fd:
            self.control(root_fd)
            with self.profiles(root_fd, create=name) as profiles:
                self.prune_locked(root_fd, profiles)
                fd = profiles[name]
                old = self.get_presence(fd, name)
                value = self.presence_value(old, name, bound)
                if value != old:
                    self.write(fd, "presence.json", value)

    def set_enabled(self, name, enabled, *, bound=False):
        boolean(enabled)
        if enabled and not bound:
            raise ValueError("bind this profile's existing owner Telegram DM first")
        with self.transaction() as root_fd:
            control = self.control(root_fd)
            with self.profiles(root_fd, create=name) as profiles:
                if enabled:
                    self.prune_locked(root_fd, profiles)
                fd = profiles[name]
                old = self.get_presence(fd, name)
                value = self.presence_value(old, name, bound)
                value.update(enabled=enabled, generation=value["generation"] + 1)
                # Publish the disabling epoch before deleting text (crash-safe opt-out).
                self.write(fd, "presence.json", value)
                self.remove(fd, "digest.json")
                self.remove_temps(fd)
                control["generation"] += 1
                control["enabled"] = False
                for other, fd in profiles.items():
                    presence = self.get_presence(fd, other)
                    control["enabled"] |= bool(presence and presence["enabled"])
            self.write(root_fd, "control.json", control)
            return value

    def digest(self, fd, name, presence):
        value = self.read(fd, "digest.json", DIGEST_BYTES)
        if value is None:
            return None
        keys(value, "schema profile generation updated_at expires_at exchanges")
        schema(value)
        generation(value["generation"])
        if value["profile"] != name:
            raise ValueError("wrong digest profile")
        updated, expires = utc(value["updated_at"]), utc(value["expires_at"])
        if updated > self.clock() or expires != updated + TTL:
            raise ValueError("invalid digest lifetime")
        exchanges = value["exchanges"]
        if type(exchanges) is not list or not 1 <= len(exchanges) <= 4:
            raise ValueError("invalid exchange ring")
        seen = set()
        previous = None
        for exchange in exchanges:
            keys(exchange, "id at user assistant")
            if type(exchange["id"]) is not str or not OPAQUE.fullmatch(exchange["id"]) or exchange["id"] in seen:
                raise ValueError("invalid exchange id")
            seen.add(exchange["id"])
            at = utc(exchange["at"])
            if at > updated or (previous is not None and at < previous):
                raise ValueError("invalid exchange time")
            previous = at
            for field in ("user", "assistant"):
                if type(exchange[field]) is not str:
                    raise ValueError("nontext exchange")
        if not presence or not presence["enabled"] or not presence["bound"] or value["generation"] != presence["generation"]:
            return None
        return value

    def dedup(self, fd, name):
        value = self.read(fd, "dedup.json")
        if value is None:
            return []
        keys(value, "schema profile turns")
        schema(value)
        if value["profile"] != name or type(value["turns"]) is not list or len(value["turns"]) > MAX_DEDUP:
            raise ValueError("invalid dedup records")
        seen = set()
        for turn in value["turns"]:
            keys(turn, "id at")
            if type(turn["id"]) is not str or not OPAQUE.fullmatch(turn["id"]) or turn["id"] in seen or utc(turn["at"]) > self.clock():
                raise ValueError("invalid dedup record")
            seen.add(turn["id"])
        return value["turns"]

    def prune_locked(self, root_fd, profiles):
        self.remove_temps(root_fd)
        for name, fd in profiles.items():
            self.remove_temps(fd)
            presence = self.get_presence(fd, name)
            digest = self.digest(fd, name, presence)
            exchanges = [e for e in digest["exchanges"] if utc(e["at"]) + TTL > self.clock()] if digest else []
            if not exchanges:
                self.remove(fd, "digest.json")
            elif exchanges != digest["exchanges"]:
                digest["exchanges"] = exchanges
                self.write(fd, "digest.json", digest)
            old_turns = self.dedup(fd, name)
            turns = [t for t in old_turns if utc(t["at"]) + DEDUP_TTL > self.clock()]
            if turns and turns != old_turns:
                self.write(fd, "dedup.json", {"schema": 1, "profile": name, "turns": turns})
            elif not turns:
                self.remove(fd, "dedup.json")

    @classmethod
    def remove_temps(cls, fd):
        # The transaction lock excludes live writers, so every matching temp is
        # an orphan. Inspect metadata only; it may hold incomplete JSON.
        with os.scandir(fd) as entries:
            for count, entry in enumerate(entries, 1):
                if count > 64:
                    raise ValueError("too many shared-store files")
                if re.fullmatch(r"\.tmp-[a-f0-9]{32}", entry.name):
                    cls.remove(fd, entry.name)

    def prune(self):
        with self.transaction() as fd:
            self.control(fd)
            with self.profiles(fd) as profiles:
                self.prune_locked(fd, profiles)

    def append(self, name, turn_id, user, assistant, *, expected_generation=None):
        if type(turn_id) is not str or not turn_id or len(turn_id) > 256:
            return False
        if type(user) is not str or type(assistant) is not str:
            return False
        opaque = hashlib.sha256(turn_id.encode("utf-8")).hexdigest()
        with self.transaction() as root_fd:
            control = self.control(root_fd)
            with self.profiles(root_fd) as profiles:
                self.prune_locked(root_fd, profiles)
                fd = profiles[profile_id(name)]
                presence = self.get_presence(fd, name)
                if not control["enabled"] or not presence or not presence["enabled"] or not presence["bound"]:
                    return False
                if expected_generation is not None and expected_generation != presence["generation"]:
                    return False
                turns = self.dedup(fd, name)
                if any(t["id"] == opaque for t in turns) or len(turns) >= MAX_DEDUP:
                    return False
                updated = self.clock()
                now = stamp(updated)
                old = self.digest(fd, name, presence)
                exchanges = (old["exchanges"] if old else []) + [{"id": opaque, "at": now, "user": user, "assistant": assistant}]
                value = {"schema": 1, "profile": name, "generation": presence["generation"],
                         "updated_at": now, "expires_at": stamp(updated + TTL), "exchanges": exchanges[-4:]}
                while value["exchanges"] and len(encode(value)) > DIGEST_BYTES:
                    value["exchanges"].pop(0)
                if not value["exchanges"]:
                    return False
                # Spend before text publication: a crash can drop a turn, never replay it.
                turns.append({"id": opaque, "at": now})
                self.write(fd, "dedup.json", {"schema": 1, "profile": name, "turns": turns})
                self.write(fd, "digest.json", value)
                return True

    def status(self, name):
        with self.transaction() as root_fd:
            control = self.control(root_fd)
            with self.profiles(root_fd) as profiles:
                self.prune_locked(root_fd, profiles)
                fd = profiles[profile_id(name)]
                presence = self.get_presence(fd, name)
                digest = self.digest(fd, name, presence)
                return {"enabled": bool(presence and presence["enabled"]), "primary": control["primary"],
                        "generation": presence["generation"] if presence else 0,
                        "bound": bool(presence and presence["bound"]), "dispatch_enabled": False,
                        "exchanges": len(digest["exchanges"]) if digest else 0}


class CrossBot:
    """One captured profile's controls and three public collector hooks."""
    def __init__(self, ctx, owner, *, clock=None):
        self.ctx, self.owner = ctx, owner
        self.profile = profile_id(getattr(ctx, "profile_name", None) or "default")
        self.clock = clock or (lambda: datetime.now(UTC))
        self.store = self.error = self.task = None
        self._pending = {}
        self._lock = threading.RLock()
        self._bound_key = ""
        self.active = self.connected = self.closed = False
        self.on_activation = lambda: None
        self.redact_terms = ()
        self.configured = False
        try:
            get_config = getattr(ctx, "get_config", lambda key, default=None: default)
            self.root = get_config("cross_bot.shared_root", None)
            self.configured = self.root is not None
            if self.configured and (type(self.root) is not str or not self.root):
                raise ValueError("cross_bot.shared_root must be an explicit absolute directory")
            self.primary = get_config("cross_bot.primary", "default")
            self.redact_terms = get_config("cross_bot.redact_terms", [])
            if sanitize("", redact_terms=self.redact_terms) is None:
                raise ValueError("invalid cross_bot.redact_terms")
            if self.configured and get_config("cross_bot.enabled", False) is True:
                self.refresh_local()
                self.open_store()
                self.active = self.store.status(self.profile)["enabled"]
        except Exception as exc:
            self.error = self.error_text(exc)

    def open_store(self):
        if not self.configured:
            raise ValueError("configure cross_bot.shared_root with the operator CLI")
        if self.store is None:
            # Control/purge access must survive invalid digest JSON after restart.
            self.store = SharedStore(self.root, primary=self.primary, clock=self.clock, prune=False)

    def set_enabled(self, enabled):
        # Local opt-out must complete even when opening/locking the store fails.
        if not enabled:
            self.active = False
            self._pending.clear()
            if self.task is not None:
                self.task.cancel()
                self.task = None
            self.on_activation()
        else:
            self.open_store()
        getattr(self.ctx, "set_config", lambda *a: None)("cross_bot.enabled", enabled)
        try:
            self.open_store()
            self.store.set_enabled(self.profile, enabled, bound=bool(self._bound_key))
        except Exception as exc:
            if not enabled:
                raise ValueError("Local export off; shared digest purge failed: " + self.error_text(exc)
                                 + "; retry /proactivity cross off") from exc
            raise
        self.active = enabled
        self.error = None
        self._pending.clear()
        if enabled:
            self.on_activation()
        if enabled and self.connected:
            self.on_telegram_connect()

    @staticmethod
    def error_text(exc):
        return str(exc) if type(exc) is ValueError else type(exc).__name__

    def refresh_local(self):
        """Only in owning hook/command/connect scope; timers use the captured copy."""
        active = getattr(self.ctx, "profile_name", None) or "default"
        if active != self.profile:
            raise ValueError("wrong profile scope")
        state = self.owner.load()
        key = state.get("session_key", "")
        namespace = {"default": "main", "custom": "main", "main": "main~"}.get(self.profile, self.profile)
        prefix = f"agent:{namespace}:telegram:dm:"
        self._bound_key = key if (type(key) is str and key.startswith(prefix)
                                  and re.fullmatch(r"[^:\s]+(?::[^:\s]+)?", key[len(prefix):])) else ""

    def own_chat(self):
        from .proactivity import caller_session_key
        return bool(self._bound_key) and caller_session_key() == self._bound_key

    def tick(self):
        """Activated profiles prune every 60 seconds, using captured scope."""
        with self._lock:
            if not self.active or self.closed:
                return
            self.expire_pending()
            try:
                self.store.presence(self.profile, bound=bool(self._bound_key))
                self.error = None
            except Exception as exc:
                self.error = self.error_text(exc)
                self._pending.clear()

    def expire_pending(self):
        self._pending = {key: value for key, value in self._pending.items()
                         if value["at"] + timedelta(hours=3) > self.clock()}

    @staticmethod
    def correlation(kwargs):
        values = tuple(kwargs.get(field) for field in ("session_id", "task_id", "turn_id"))
        if any(type(v) is not str or not v or len(v) > 256 for v in values):
            return None
        return values

    def on_turn_start(self, user_message="", **kwargs):
        from .proactivity import MARKER, BRIEF_MARKER
        with self._lock:
            if not self.active or self.closed:
                return None
            try:
                self.expire_pending()
                correlation = self.correlation(kwargs)
                if correlation:
                    self._pending.pop(correlation, None)
                self.refresh_local()
                cron = getattr(self.ctx, "current_cron_execution", lambda: None)()
                if (not correlation or not self.own_chat()
                        or kwargs.get("platform") != "telegram" or kwargs.get("parent_session_id")
                        or kwargs.get("parent_task_id") or kwargs.get("is_child") or cron
                        or kwargs.get("imported") or kwargs.get("is_imported")
                        or kwargs.get("origin") in ("cross_bot", "cron", "child", "checkin", "brief")
                        or type(user_message) is not str or len(user_message) > EXCHANGE_BYTES
                        or user_message.lstrip().startswith((MARKER, BRIEF_MARKER, "[Cross-bot ask]"))):
                    return None
                status = self.store.status(self.profile)
                if not status["enabled"] or not status["bound"] or len(self._pending) >= 32:
                    return None
                user = sanitize(user_message, redact_terms=self.redact_terms)
                if user is not None:
                    self._pending[correlation] = {"at": self.clock(), "key": self._bound_key,
                        "generation": status["generation"], "user": user, "assistant": None,
                        "bytes": len(user_message.encode("utf-8"))}
            except Exception as exc:
                self.error = self.error_text(exc)
        return None

    def on_turn_end(self, user_message="", assistant_response="", **kwargs):
        with self._lock:
            if not self.active or self.closed or not self._pending:
                return None
            try:
                self.refresh_local()
                correlation = self.correlation(kwargs)
                pending = self._pending.get(correlation)
                if not pending:
                    return None
                if (not self.own_chat() or kwargs.get("platform") != "telegram"
                        or pending["key"] != self._bound_key):
                    self._pending.pop(correlation, None)
                    return None
                # Only the original pre-hook text is retained, never history/context.
                if (type(assistant_response) is not str or len(assistant_response) > EXCHANGE_BYTES
                        or pending["bytes"] + len(assistant_response.encode("utf-8")) > EXCHANGE_BYTES):
                    self._pending.pop(correlation, None)
                    return None
                assistant = sanitize(assistant_response, redact_terms=self.redact_terms)
                if assistant is None:
                    self._pending.pop(correlation, None)
                else:
                    pending["assistant"] = assistant
            except Exception as exc:
                self.error = self.error_text(exc)
                self._pending.pop(self.correlation(kwargs), None)
        return None

    def on_session_end(self, **kwargs):
        with self._lock:
            if not self.active or self.closed or not self._pending:
                return None
            pending = self._pending.pop(self.correlation(kwargs), None)
            try:
                self.refresh_local()
                if (not pending or not self.own_chat()
                        or pending["key"] != self._bound_key
                        or kwargs.get("platform") != "telegram" or kwargs.get("completed") is not True
                        or kwargs.get("failed") is not False or kwargs.get("interrupted") is not False
                        or pending["assistant"] is None or pending["at"] + timedelta(hours=3) <= self.clock()):
                    return None
                self.store.append(self.profile, kwargs["turn_id"], pending["user"], pending["assistant"],
                                  expected_generation=pending["generation"])
            except Exception as exc:
                self.error = self.error_text(exc)
        return None

    def status(self):
        result = {"profile": self.profile, "configured": self.configured, "enabled": False,
                  "bound": bool(self._bound_key), "dispatch_enabled": False}
        if self.store:
            try:
                result.update(self.store.status(self.profile))
            except Exception as exc:
                self.error = self.error_text(exc)
        result["error"] = self.error
        return result

    def command(self, raw_args=""):
        words = str(raw_args or "").lower().split()
        if words[:1] == ["cross"]:
            words = words[1:]
        if words not in (["on"], ["off"], ["status"], []):
            return "usage: /proactivity cross on|off|status"
        with self._lock:
            try:
                self.refresh_local()
                if not self.own_chat():
                    return "Cross-bot settings can only be changed or viewed from this bot's bound owner DM."
                action = words[0] if words else "status"
                if action in ("on", "off"):
                    self.set_enabled(action == "on")
                status = self.status()
                if status["error"]:
                    raise ValueError(status["error"])
                return ("Cross-bot export " + ("on" if status["enabled"] else "off") + "; "
                        + str(status.get("exchanges", 0)) + " recent exchanges. Dispatch disabled."
                        + (" Configure cross_bot.shared_root with the operator CLI." if not self.store else ""))
            except Exception as exc:
                self.error = self.error_text(exc)
                return "Cross-bot export unavailable: " + self.error + ". Dispatch disabled."

    def tool(self, args, **kwargs):
        """Like loosens(): expanded scope always returns the operator command."""
        with self._lock:
            try:
                self.refresh_local()
                if not self.own_chat():
                    return json.dumps({"ok": False, "error": "Use this bot's bound owner DM."})
                if type(args) is not dict:
                    raise ValueError("invalid cross-bot settings")
                if args.get("action") in ("status", "cross_status") and set(args) == {"action"}:
                    return json.dumps({"ok": True, **self.status()})
                if set(args) != {"action", "cross_bot_enabled"} or args["action"] != "set":
                    raise ValueError("use set with cross_bot_enabled only")
                boolean(args["cross_bot_enabled"])
                if args["cross_bot_enabled"]:
                    return json.dumps({"ok": False, "error": "Only the operator can enable cross-bot export.",
                                       "ask_user_to_send": "/proactivity cross on"})
                self.set_enabled(False)
                return json.dumps({"ok": True, **self.status()})
            except Exception as exc:
                return json.dumps({"ok": False, "error": self.error_text(exc)})

    def on_telegram_connect(self, native=None, adapter=None, **kwargs):
        self.connected = True
        if not self.active or self.closed:
            return
        with self._lock:
            self.refresh_local()
            self.tick()
            if self.task is not None and not self.task.done():
                return
            import asyncio

            async def run():
                while not self.closed:
                    await asyncio.sleep(60)
                    await asyncio.to_thread(self.tick)

            coro = run()
            try:
                self.task = self.ctx.spawn_task(coro, name="alans-way-cross-export-" + self.profile)
            except Exception as exc:
                coro.close()
                self.error = self.error_text(exc)

    def close(self):
        with self._lock:
            self.closed = True
            self._pending.clear()
            if self.task is not None:
                self.task.cancel()


CROSS_SCHEMA = {
    "name": "proactivity",
    "description": "Read cross-bot export status or turn it off. Only the operator may enable it with /proactivity cross on. Dispatch is disabled.",
    "parameters": {"type": "object", "additionalProperties": False, "required": ["action"],
                   "properties": {"action": {"type": "string", "enum": ["cross_status", "set"]},
                                  "cross_bot_enabled": {"type": "boolean"}}},
}
