"""Read-only kanban board sweep; oversight metadata, never task mutation.

Reads Hermes' kanban.db directly in SQLite read-only mode so the primary can
observe work other agents recorded on the shared board. Missing or differently
shaped schema degrades to an empty sweep — oversight is best-effort, never a
reason to fail the observation cycle.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import sqlite3

MAX_TASKS = 20
MAX_FIELD = 200
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")
_OPEN = ("triage", "todo", "ready", "running", "blocked")
_TERMINAL = ("done", "archived", "cancelled")


def _clean(value, limit=MAX_FIELD):
    if type(value) is not str:
        return ""
    text = value.strip()[:limit]
    return "" if any(ord(c) < 32 and c != "\n" for c in text) else text


def collect_board(home: Path, *, now: datetime | None = None) -> dict:
    """Summarize live board state; empty dict when the board is unavailable."""
    path = Path(home) / "kanban.db"
    now = now or datetime.now(timezone.utc)
    try:
        if not path.is_file() or path.is_symlink():
            return {}
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
        try:
            cols = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
            wanted = {"id", "title", "status", "assignee", "created_by", "created_at"}
            if not wanted <= cols:
                return {}
            rows = db.execute(
                "SELECT id, title, status, assignee, created_by, created_at"
                " FROM tasks ORDER BY created_at DESC LIMIT ?",
                (MAX_TASKS * 4,)).fetchall()
        finally:
            db.close()
    except Exception:
        return {}
    open_tasks, recent_done = [], []
    stale_after = now - timedelta(days=14)
    for task_id, title, status, assignee, creator, created in rows:
        if (type(task_id) is not str or _TASK_ID.fullmatch(task_id) is None
                or type(status) is not str
                or status not in _OPEN + _TERMINAL):
            continue
        entry = {"id": task_id, "title": _clean(title, 120), "status": status,
                 "assignee": _clean(assignee, 60), "created_by": _clean(creator, 60)}
        if type(created) in (int, float):
            entry["created_at"] = datetime.fromtimestamp(
                created, tz=timezone.utc).isoformat()
        if status in _OPEN:
            open_tasks.append(entry)
        elif type(created) in (int, float) and datetime.fromtimestamp(
                created, tz=timezone.utc) > stale_after:
            recent_done.append(entry)
        if len(open_tasks) + len(recent_done) >= MAX_TASKS:
            break
    return {"open": open_tasks, "recently_closed": recent_done}


def board_signature(board: dict) -> str:
    import hashlib
    if not board:
        return ""
    digest = {"open": [(t["id"], t["status"], t.get("assignee", ""))
                       for t in board.get("open", [])],
              "closed": [t["id"] for t in board.get("recently_closed", [])]}
    return hashlib.sha256(json.dumps(digest, sort_keys=True).encode()).hexdigest()
