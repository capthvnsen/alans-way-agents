"""Fixed own-profile context sources, hashed locally and bounded for review."""
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import stat

SOURCES = ("memories/MEMORY.md", "memories/USER.md", "cron/jobs.json")
DOCUMENTS = ("SOUL.md", "AGENTS.md", "IDENTITY.md")
MAC_STATE_FILE = "/var/lib/hermes-alans-way/mac-state.json"


def mac_state():
    try:
        path = Path(os.environ.get("HERMES_MAC_STATE_FILE") or MAC_STATE_FILE)
        if path.is_symlink() or path.stat().st_size > 4096:
            return None
        doc = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("state") not in ("online", "offline"):
        return None
    def field(key):
        value = doc.get(key)
        return value[:64] if isinstance(value, str) else None
    return {"state": doc["state"], "since": field("since"),
            "lastSeenOnline": field("lastSeenOnline")}


def read_source(home: Path, relative: str):
    if relative not in SOURCES + DOCUMENTS:
        raise ValueError("unsupported observation source")
    path = home / relative
    try:
        if path.parent.is_symlink() or path.is_symlink():
            return None
        path.resolve(strict=True).relative_to(home.resolve(strict=True))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > 65536 or before.st_nlink != 1:
                return None
            body = os.read(fd, 65537)
            after = os.fstat(fd)
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                return None
        finally:
            os.close(fd)
        text = body.decode("utf-8")
        if any(ord(c) < 32 and c not in "\n\t\r" for c in text):
            return None
        return {"digest": sha256(body).hexdigest(), "text": text,
                "modified": datetime.fromtimestamp(before.st_mtime, timezone.utc).isoformat()}
    except (OSError, UnicodeError, ValueError):
        return None


def capabilities(home: Path):
    try:
        root = home / "skills"
        if root.is_symlink() or not root.is_dir():
            return None
        names = []
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            if len(names) >= 48:
                break
            if entry.is_symlink() or not entry.is_dir() or entry.name.startswith("."):
                continue
            if entry.name == entry.name.encode("ascii", "ignore").decode() and \
                    entry.name.replace("-", "").replace("_", "").replace(".", "").isalnum():
                names.append(entry.name[:64])
        return names
    except OSError:
        return None


def collect(home: Path, ledger, ctx=None):
    memory, schedule, documents, signatures = [], [], [], {}
    for source in SOURCES + DOCUMENTS:
        value = read_source(home, source)
        if value is None:
            continue
        signatures[source] = value["digest"]
        if source.startswith("memories/"):
            memory.append({"source": Path(source).name, "text": value["text"][:3072]})
        elif source in DOCUMENTS:
            documents.append({"source": source, "text": value["text"][:3072],
                              "modified": value["modified"]})
        else:
            try:
                document = json.loads(value["text"])
                jobs = document.get("jobs", []) if isinstance(document, dict) else document
                if isinstance(jobs, list):
                    for job in jobs[:12]:
                        if not isinstance(job, dict):
                            continue
                        row = {}
                        for key in ("name", "enabled", "schedule", "next_run", "status"):
                            v = job.get(key)
                            if isinstance(v, (str, bool, int, float)):
                                row[key] = v[:160] if isinstance(v, str) else v
                        if row:
                            schedule.append(row)
            except (ValueError, TypeError):
                pass
    snapshot = ledger.snapshot()
    from .proactive_native import collect as collect_native
    native = collect_native(ctx, snapshot["tasks"]) if ctx is not None else {}
    for watch_id, value in native.items():
        signatures["task:" + watch_id] = sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    mac = mac_state()
    if mac is not None:
        # since identifies the transition, not just the direction, so a repeat
        # offline->online flip is a new event rather than a deduped replay.
        signatures["mac"] = mac["since"] or mac["state"]
    from .proactive_board import collect_board, board_signature
    board = collect_board(home)
    if board:
        signatures["board"] = board_signature(board)
    skills = capabilities(home)
    if skills is not None:
        signatures["skills"] = sha256("\n".join(skills).encode()).hexdigest()
    tasks = []
    now = datetime.now(timezone.utc)
    for task in snapshot["tasks"]:
        try:
            approved_at = datetime.fromisoformat(task["approved_at"])
            if (task.get("approved") is not True or task.get("status") in {"done", "cancelled"}
                    or approved_at.tzinfo is None or (now - approved_at).total_seconds() > 2592000):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        allowed = {"id", "title", "scope", "next_action", "status", "owner", "approved",
                   "native_task_id", "next_review_at", "execution_host"}
        tasks.append({k: (v[:300] if isinstance(v, str) and k not in {"id", "native_task_id"} else v)
                      for k, v in task.items() if k in allowed})
        if task.get("native_task_id"):
            current = native.get(task["id"])
            if current is None or current["status"] == "blocked":
                tasks[-1]["status"] = "blocked"
            elif current["status"] in {"done", "archived"}:
                tasks[-1]["status"] = "done"
        if len(tasks) == 4:
            break
    preferences = dict(snapshot["preferences"])
    for key in ("focus", "ignore"):
        preferences[key] = [value[:100] for value in preferences[key][:8]]
    preferences["reviewed_at_utc"] = now.isoformat()
    preferences["native_task_status"] = native
    preferences["workspace_mac"] = mac
    by_id = {task["id"]: task for task in snapshot["tasks"]}
    goals = [{"source": "approved-watch", "summary": task["scope"], "watch_id": task["id"],
              "approved_at": by_id[task["id"]]["approved_at"], "status": task["status"]}
             for task in tasks]
    return {"memory": memory, "schedule": schedule, "tasks": tasks,
            "preferences": preferences, "goals": goals, "board": board,
            "documents": documents, "capabilities": skills or []}, signatures


def observe(runtime):
    context, signatures = collect(runtime.home, runtime.ledger, runtime.ctx)
    purposeful = bool(context["tasks"])
    counts = runtime.store.status()["counts"]
    active = any(counts.get(name, 0) for name in ("dispatching", "accepted_unverified", "uncertain"))
    admitted = 0
    with runtime.ledger.transaction() as state:
        previous = state["observations"]
        for source, digest in signatures.items():
            old = previous.get(source)
            if old is not None and old != digest and not active:
                evidence = sha256((source + ":" + digest).encode()).hexdigest()
                kind = "task_changed" if source.startswith("task:") else "context_changed"
                admitted += int(runtime.store.record_event(kind, evidence, purpose=purposeful))
            previous[source] = digest
    return admitted
