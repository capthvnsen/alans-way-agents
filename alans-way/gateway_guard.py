"""Gateway-only arming marker; no messages or native state modification."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sys
import tempfile


# gateway:startup can legitimately fire before or after plugin registration
# inside the same gateway process, so arming must not depend on that order.
# Where process start is unprobeable the env falls back to registration time,
# and this window only needs to cover startup ordering, not admit a stale
# same-pid file left behind by a dead earlier owner.
_GRACE_SECONDS = 600
# Process start derived from /proc ticks can trail the wall clock by a second
# or two (whole-second btime plus jiffy rounding); the slack covers that, not
# a marker a dead earlier owner wrote before this process ever existed.
_START_TOLERANCE_SECONDS = 30


# Reads of state files refuse symlinks where the OS can, and stay byte-exact on
# Windows, where an fd opened without O_BINARY translates CRLF and stops at ^Z.
SAFE_OPEN = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)

try:
    import fcntl

    def lock_file(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def unlock_file(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
except ImportError:  # native Windows: lock the first byte instead
    import msvcrt

    def lock_file(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def unlock_file(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


def default_hermes_home() -> Path:
    """Hermes' own default: %LOCALAPPDATA%\\hermes on native Windows, else ~/.hermes."""
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "hermes"
    return Path.home() / ".hermes"


def hermes_home() -> Path:
    """Honor the profile's explicit environment, with Hermes' default home."""
    return Path(os.environ.get("HERMES_HOME") or default_hermes_home()).expanduser().absolute()


def _process_started_at() -> datetime | None:
    """Wall-clock start of this process, or None where unprobeable.

    Freshness must anchor to process start: the marker is stamped once at
    gateway:startup, so a plugin reload that re-registers inside the same
    long-running gateway must still arm — comparing against registration
    time would disarm it silently once registration outlived the window.
    """
    # Hermes ships psutil on every OS; /proc and ps below are for hosts without it.
    try:
        import psutil
        return datetime.fromtimestamp(psutil.Process(os.getpid()).create_time(), timezone.utc)
    except Exception:
        pass
    try:
        # Linux: field 22 of /proc/self/stat is starttime in clock ticks since
        # boot; everything after the comm ')' splits positionally from state.
        tail = Path("/proc/self/stat").read_bytes().rsplit(b")", 1)[-1]
        ticks = int(tail.split()[19])
        for line in Path("/proc/stat").read_bytes().splitlines():
            if line.startswith(b"btime "):
                boot = int(line.split()[1])
                break
        else:
            return None
        return datetime.fromtimestamp(
            boot + ticks / os.sysconf("SC_CLK_TCK"), timezone.utc)
    except (OSError, ValueError, IndexError):
        pass
    try:
        return datetime.fromtimestamp(os.stat("/proc/self").st_ctime, timezone.utc)
    except OSError:
        pass
    # macOS has no /proc. etime is elapsed clock time ([[dd-]hh:]mm:ss), so
    # the result is UTC regardless of the machine's zone. BSD ps has no etimes.
    try:
        import subprocess
        out = subprocess.check_output(
            ["ps", "-o", "etime=", "-p", str(os.getpid())],
            text=True, timeout=2, stderr=subprocess.DEVNULL).strip()
        days, _, clock = out.partition("-")
        if not clock:
            clock, days = days, "0"
        parts = [int(part) for part in clock.split(":")]
        weights = (1, 60, 3600)
        if not parts or len(parts) > 3:
            return None
        seconds = int(days) * 86400 + sum(part * weights[index] for index, part in enumerate(reversed(parts)))
        return datetime.now(timezone.utc) - timedelta(seconds=seconds)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def write_private_json(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("Companion state must not be symlinked")
    fd, temporary = tempfile.mkstemp(prefix=".proactive-", dir=path.parent)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def mark_gateway_ready(home: Path, *, now: datetime | None = None) -> None:
    """Called ONLY by the native gateway:startup hook in that gateway process."""
    now = now or datetime.now(timezone.utc)
    write_private_json(home / "companion" / "proactivity" / "gateway-owner.json",
                       {"pid": os.getpid(), "started_at": now.isoformat()})


def gateway_ready(home: Path, registered_at: datetime) -> bool:
    """A CLI process must never borrow another process's startup marker."""
    path = home / "companion" / "proactivity" / "gateway-owner.json"
    try:
        if path.is_symlink() or path.stat().st_size > 4096:
            return False
        value = json.loads(path.read_text(encoding="utf-8"))
        stamped = datetime.fromisoformat(value["started_at"])
        started = _process_started_at()
        # Anchored to process start a marker this gateway stamped at its own
        # startup stays valid across later plugin reloads; a marker predating
        # the process is a dead same-pid owner's. Without a probe the
        # registration-time window remains the fallback.
        fresh = (stamped >= started - timedelta(seconds=_START_TOLERANCE_SECONDS)
                 if started is not None
                 else stamped >= registered_at - timedelta(seconds=_GRACE_SECONDS))
        return (type(value.get("pid")) is int and value["pid"] == os.getpid()
                and stamped.tzinfo is not None
                and stamped <= datetime.now(timezone.utc)
                and fresh)
    except (OSError, ValueError, KeyError, TypeError):
        return False
