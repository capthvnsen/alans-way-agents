"""Private preferences and authorized task watches, not a task executor."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import copy
from hashlib import sha256
import json
import os
import re

from .gateway_guard import SAFE_OPEN, lock_file, unlock_file, write_private_json

DEFAULT_PREFERENCES = {
    "focus": [], "ignore": [], "max_work_minutes": 20,
    "autonomy": "read_research_draft_continue_approved",
}
TASK_FIELDS = {"id", "title", "scope", "next_action", "owner", "status", "approved",
               "kind", "native_task_id", "native_board", "next_review_at", "due_at",
               "notify_when", "cadence_seconds", "artifact", "verification",
               "consent_reference", "execution_host"}
TASK_KINDS = {"watch", "loop", "sweep"}
TERMINAL = {"done", "cancelled"}
TERMINAL_RETENTION_SECONDS = 14 * 86400
MAX_WATCHES = 64
MAX_PROPOSALS = 8
MAX_LOG = 20
DISMISSAL_LIMIT, DISMISSAL_WINDOW_SECONDS = 3, 14 * 86400
PROPOSAL_TTL_SECONDS = 7 * 86400
HASHED_FIELDS = ("title", "scope", "next_action", "owner", "kind", "execution_host", "cadence_seconds",
                 "next_review_at", "due_at", "notify_when", "native_task_id", "native_board")
APPROVAL_TTL_SECONDS = 30 * 86400

# Signal bookkeeping is written only through report_signal; record_task saves
# must carry it forward or re-arming a watch would erase its last observation.
SIGNAL_FIELDS = ("signal", "signal_at")


class SourceSuppressed(ValueError):
    """Three recent dismissals of one kind of proposal; args[0] is the kind."""


class StaleProposal(ValueError):
    def __init__(self, task):
        super().__init__("proposal changed")
        self.task = task


def pending_view(task):
    """The watch as the user would have it once a pending revision is approved."""
    revision = task.get("revision")
    return {**task, **{k: v for k, v in revision.items() if k in TASK_FIELDS}} if revision else task


def approval_fresh(task, now=None):
    """Approvals lapse after 30 days; a lapsed watch needs approving again."""
    approved = _moment(task.get("approved_at"))
    now = now or datetime.now(timezone.utc)
    return approved is not None and (now - approved).total_seconds() <= APPROVAL_TTL_SECONDS


def proposal_hash(task):
    """Eight hex digits over what the user reads when approving a watch."""
    body = {k: pending_view(task).get(k) for k in HASHED_FIELDS}
    body["kind"] = body["kind"] or "watch"
    body["execution_host"] = body["execution_host"] or "cloud"
    return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:8]


def _moment(value):
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo is not None else None


def _sooner(new, old):
    """True when a schedule value is added or moved earlier (more frequent)."""
    if new is None or new == old:
        return False
    if old is None:
        return True
    if type(new) is int:
        return new < old
    new, old = _moment(new), _moment(old)
    return new is not None and (old is None or new < old)


def _text(value, maximum=2000):
    if not isinstance(value, str) or not value or len(value) > maximum or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError("invalid task text")
    return value


class Ledger:
    def __init__(self, state_dir: Path):
        self.root = Path(state_dir)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "ledger.json"

    @contextmanager
    def transaction(self):
        if self.root.is_symlink() or self.path.is_symlink():
            raise ValueError("symlinked state is unsupported")
        fd = os.open(self.root / "ledger.lock", os.O_RDWR | os.O_CREAT | SAFE_OPEN, 0o600)
        try:
            lock_file(fd)
            if self.path.exists():
                if self.path.stat().st_size > 1048576:
                    raise ValueError("ledger exceeds bound")
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("schema") != 1:
                    raise ValueError("unsupported ledger")
            else:
                data = {"schema": 1, "preferences": copy.deepcopy(DEFAULT_PREFERENCES), "tasks": {}, "observations": {}}
            before = copy.deepcopy(data)
            yield data
            if data != before:
                write_private_json(self.path, data)
        finally:
            unlock_file(fd)
            os.close(fd)

    def snapshot(self):
        with self.transaction() as data:
            return {"preferences": copy.deepcopy(data["preferences"]),
                    "tasks": copy.deepcopy(list(data["tasks"].values())),
                    "observed_at": data["observations"].get("__heartbeat")}

    def preferences(self, changes):
        if not isinstance(changes, dict) or set(changes) - set(DEFAULT_PREFERENCES):
            raise ValueError("unsupported preferences")
        with self.transaction() as data:
            proposed = {**data["preferences"], **changes}
            for name in ("focus", "ignore"):
                if not isinstance(proposed[name], list) or len(proposed[name]) > 20:
                    raise ValueError("invalid preferences")
                for item in proposed[name]:
                    _text(item, 300)
            if (type(proposed["max_work_minutes"]) is not int or not 1 <= proposed["max_work_minutes"] <= 20
                    or proposed["autonomy"] != DEFAULT_PREFERENCES["autonomy"]):
                raise ValueError("autonomy cannot be expanded by preferences")
            data["preferences"] = proposed

    @staticmethod
    def _check_task(task):
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", task.get("id", "")) is None:
            raise ValueError("invalid watch id")
        for name in ("title", "scope", "next_action", "owner"):
            _text(task.get(name), 300 if name in ("title", "owner") else 2000)
        if task.get("status") not in {"active", "waiting", "blocked", "done", "cancelled"}:
            raise ValueError("unsupported task status")
        if task.get("kind", "watch") not in TASK_KINDS:
            raise ValueError("unsupported task kind")
        if task.get("execution_host", "cloud") not in {"cloud", "mac"}:
            raise ValueError("unsupported execution host")
        for name in ("native_task_id", "native_board", "artifact", "verification", "consent_reference"):
            if name in task:
                _text(task[name], 1000)
        if "notify_when" in task:
            _text(task["notify_when"], 300)
        if "cadence_seconds" in task:
            if type(task["cadence_seconds"]) is not int or not 300 <= task["cadence_seconds"] <= 604800:
                raise ValueError("cadence_seconds must be an integer in [300, 604800]")
        for name in ("next_review_at", "due_at"):
            if task.get(name):
                moment = datetime.fromisoformat(task[name])
                if moment.tzinfo is None:
                    raise ValueError(f"{name} needs timezone")

    @staticmethod
    def _prune(data):
        """Expire stale proposals and revisions; drop terminal watches two weeks after they closed.

        A pending revision never takes the approved watch down with it, and a
        re-approval request stays until the user answers it.
        """
        now = datetime.now(timezone.utc)
        for task_id, task in list(data["tasks"].items()):
            revision = task.get("revision")
            if revision and not revision.get("reapproval"):
                proposed = _moment(revision.get("proposed_at"))
                if proposed is None or (now - proposed).total_seconds() > PROPOSAL_TTL_SECONDS:
                    del task["revision"]
            if task.get("status") == "proposed":
                proposed = _moment(task.get("proposed_at"))
                if proposed is None:
                    task["proposed_at"] = now.isoformat()
                elif (now - proposed).total_seconds() > PROPOSAL_TTL_SECONDS:
                    del data["tasks"][task_id]
                continue
            if task.get("status") not in TERMINAL:
                continue
            closed = _moment(task.get("closed_at"))
            if closed is None:
                task["closed_at"] = now.isoformat()
            elif (now - closed).total_seconds() > TERMINAL_RETENTION_SECONDS:
                del data["tasks"][task_id]

    def record_task(self, task):
        """Operator path: a typed slash command or CLI call IS the approval.

        The model's ``record_task`` goes through ``propose_task`` instead.
        """
        if not isinstance(task, dict) or set(task) - TASK_FIELDS or task.get("approved") is not True:
            raise ValueError("record only explicitly authorized scope")
        self._check_task(task)
        with self.transaction() as data:
            self._prune(data)
            old = data["tasks"].get(task["id"])
            if old and (old["status"] in TERMINAL or (old["status"] != "proposed" and (old["scope"] != task["scope"]
                        or old.get("kind", "watch") != task.get("kind", old.get("kind", "watch"))
                        or old.get("execution_host", "cloud") != task.get("execution_host", old.get("execution_host", "cloud"))))):
                raise ValueError("terminal, changed scopes, kinds or hosts need a new authorized watch id")
            if old is None and sum(t["status"] not in TERMINAL for t in data["tasks"].values()) >= MAX_WATCHES:
                raise ValueError("watch limit reached")
            saved = copy.deepcopy(task)
            saved["kind"] = task.get("kind", old.get("kind", "watch") if old else "watch")
            saved["execution_host"] = task.get("execution_host", old.get("execution_host", "cloud") if old else "cloud")
            saved["approved_at"] = datetime.now(timezone.utc).isoformat()  # an operator save is a fresh approval
            for key in SIGNAL_FIELDS:
                if old is not None and key in old:
                    saved[key] = old[key]
            data["tasks"][task["id"]] = saved
            data.get("dismissals", {}).pop(saved["kind"], None)

    def propose_task(self, task):
        """Model path: the bot may only propose. Returns True when something awaits approval.

        A new or still-proposed watch is saved as ``proposed`` and never fires.
        An approved watch keeps running as approved. Changes that cannot widen
        it (slower cadence or review, later deadline, pause, retitling) apply at
        once; anything wider (a new next_action, owner, report rule, faster
        schedule or reactivation) is stored as a pending revision that replaces
        the watch only when approved, and expires on its own. Scope, kind, host
        and native binding stay immutable once approved.
        """
        if not isinstance(task, dict) or set(task) - TASK_FIELDS:
            raise ValueError("invalid watch")
        task = {k: v for k, v in task.items() if k not in ("approved", "approved_at")}
        self._check_task(task)
        with self.transaction() as data:
            self._prune(data)
            old = data["tasks"].get(task["id"])
            approved = bool(old) and old.get("approved") is True and old["status"] != "proposed"
            if old and old["status"] in TERMINAL:
                raise ValueError("terminal watches need a new watch id")
            if approved and (old.get("native_task_id") != task.get("native_task_id")
                             or old.get("native_board") != task.get("native_board")):
                raise ValueError("native bindings need a new watch id")
            if approved and (old["scope"] != task["scope"]
                             or old.get("kind", "watch") != task.get("kind", old.get("kind", "watch"))
                             or old.get("execution_host", "cloud") != task.get("execution_host", old.get("execution_host", "cloud"))):
                raise ValueError("changed scopes, kinds or hosts need a new watch id")
            kind = task.get("kind", old.get("kind", "watch") if old else "watch")
            if not approved and self._suppressed(data, kind):
                raise SourceSuppressed(kind)
            if old is None:
                live = [t for t in data["tasks"].values() if t["status"] not in TERMINAL]
                if len(live) >= MAX_WATCHES or sum(t["status"] == "proposed" for t in live) >= MAX_PROPOSALS:
                    raise ValueError("watch limit reached")
            saved = copy.deepcopy(task)
            saved["kind"] = kind
            saved["execution_host"] = task.get("execution_host", old.get("execution_host", "cloud") if old else "cloud")
            if not approved:
                saved.update(approved=False, status="proposed", proposed_at=datetime.now(timezone.utc).isoformat())
                data["tasks"][task["id"]] = saved
                return True
            wider = (task["next_action"] != old["next_action"] or task["owner"] != old["owner"]
                     or task.get("notify_when") != old.get("notify_when")
                     or (task["status"] == "active" and old["status"] != "active"
                         and not (old["status"] == "blocked" and old.get("status_by") == "model"))
                     or _sooner(task.get("cadence_seconds"), old.get("cadence_seconds"))
                     or _sooner(task.get("next_review_at"), old.get("next_review_at"))
                     or _sooner(task.get("due_at"), old.get("due_at")))
            if wider:
                old["revision"] = {**saved, "proposed_at": datetime.now(timezone.utc).isoformat()}
                return True
            saved.update(approved=True, approved_at=old["approved_at"])
            if saved["status"] in ("waiting", "blocked"):
                # Only a status the model actually changed is the model's.
                saved["status_by"] = old.get("status_by") if old["status"] == saved["status"] else "model"
            for key in SIGNAL_FIELDS:
                if key in old:
                    saved[key] = old[key]
            data["tasks"][task["id"]] = saved
            return False

    def proposal_hash(self, task):
        return proposal_hash(task)

    def approve_task(self, task_id, expected=None):
        """Operator path: activate a proposed watch, or swap in its pending revision.

        Returns the watch as activated. With ``expected`` (the hash the user was
        shown) a proposal edited since is refused with StaleProposal instead of
        approving unseen text.
        """
        with self.transaction() as data:
            task = data["tasks"].get(task_id)
            if not task or (task["status"] != "proposed" and not task.get("revision")):
                raise ValueError("no proposed watch")
            if expected and expected != proposal_hash(task):
                raise StaleProposal(copy.deepcopy(pending_view(task)))
            now = datetime.now(timezone.utc).isoformat()
            if task["status"] == "proposed":
                task.update(status="active", approved=True, approved_at=now)
                saved = task
            else:
                revision = task["revision"]
                saved = {k: v for k, v in revision.items() if k not in ("proposed_at", "reapproval")}
                saved.update(approved=True, approved_at=now)
                for key in SIGNAL_FIELDS:
                    if key in task:
                        saved[key] = task[key]
                if saved["status"] in ("waiting", "blocked"):
                    saved["status_by"] = task.get("status_by") if task["status"] == saved["status"] else "model"
                data["tasks"][task_id] = saved
            data.get("dismissals", {}).pop(saved.get("kind", "watch"), None)
            return copy.deepcopy(saved)

    def flag_expired_approvals(self):
        """Ask for re-approval of active watches approved over 30 days ago; returns their ids."""
        flagged = []
        with self.transaction() as data:
            now = datetime.now(timezone.utc)
            for task_id, task in data["tasks"].items():
                if (task.get("approved") is True and task["status"] == "active" and not task.get("revision")
                        and not approval_fresh(task, now)):
                    keep = {k: v for k, v in task.items() if k in TASK_FIELDS and k != "approved"}
                    task["revision"] = {**keep, "proposed_at": now.isoformat(), "reapproval": True}
                    flagged.append(task_id)
        return flagged

    @staticmethod
    def _recent_dismissals(data, kind):
        cutoff = datetime.now(timezone.utc).timestamp() - DISMISSAL_WINDOW_SECONDS
        return [t for t in data.get("dismissals", {}).get(kind, [])
                if (_moment(t) or datetime.min.replace(tzinfo=timezone.utc)).timestamp() > cutoff]

    def _suppressed(self, data, kind):
        return len(self._recent_dismissals(data, kind)) >= DISMISSAL_LIMIT

    def dismiss_task(self, task_id):
        """Operator path: drop a proposal (counted against its kind) or just its pending revision.

        Dismissing a re-approval request retires the lapsed watch. Returns the kind.
        """
        with self.transaction() as data:
            task = data["tasks"].get(task_id)
            if not task or (task["status"] != "proposed" and not task.get("revision")):
                raise ValueError("no proposed watch")
            kind = task.get("kind", "watch")
            now = datetime.now(timezone.utc).isoformat()
            if task["status"] == "proposed":
                task.update(status="cancelled", closed_at=now)
                data.setdefault("dismissals", {})[kind] = self._recent_dismissals(data, kind) + [now]
            elif task["revision"].get("reapproval"):
                task.pop("revision")
                task.update(status="cancelled", closed_at=now)
            else:
                task.pop("revision")
            return kind

    def log(self, kind, reason, outcome, job_id=None):
        """Append one line to the activity log (newest last, bounded)."""
        with self.transaction() as data:
            entries = data["observations"].setdefault("__log", [])
            entries.append({"at": datetime.now(timezone.utc).isoformat(), "kind": kind[:24],
                            "reason": reason[:160], "outcome": outcome[:24],
                            **({"job_id": job_id} if job_id else {})})
            del entries[:-MAX_LOG]

    def track_job(self, job_id, kind):
        with self.transaction() as data:
            data["observations"].setdefault("__cron", {})[job_id] = {
                "at": datetime.now(timezone.utc).isoformat(), "kind": kind}

    def untrack_job(self, job_id):
        with self.transaction() as data:
            data["observations"].get("__cron", {}).pop(job_id, None)

    def tracked_jobs(self):
        with self.transaction() as data:
            return dict(data["observations"].get("__cron", {}))

    def set_outcome(self, job_id, outcome):
        with self.transaction() as data:
            for entry in data["observations"].get("__log", []):
                if entry.get("job_id") == job_id:
                    entry["outcome"] = outcome

    def recent_log(self, count=10):
        with self.transaction() as data:
            return list(data["observations"].get("__log", []))[-count:]

    def report_signal(self, task_id, signal):
        """Record a bounded observed state on an approved watch.

        The observer diffs the digest and wakes on change, so any authorized
        surface — the woken primary or a scheduled check — can feed a watch
        without touching dispatch internals. Unchanged signals stay silent.
        """
        if (type(task_id) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", task_id) is None):
            raise ValueError("invalid watch id")
        signal = _text(signal, 1000)
        with self.transaction() as data:
            task = data["tasks"].get(task_id)
            if not task or task.get("status") in {"done", "cancelled"}:
                raise ValueError("unknown or terminal watch")
            if task.get("signal") == signal:
                return
            task["signal"] = signal
            task["signal_at"] = datetime.now(timezone.utc).isoformat()

    def arm_review(self, task_id, next_review_at):
        """Advance a watch's next review time without touching consent fields."""
        moment = datetime.fromisoformat(next_review_at)
        if type(task_id) is not str or moment.tzinfo is None:
            raise ValueError("review time needs timezone")
        with self.transaction() as data:
            task = data["tasks"].get(task_id)
            if not task or task.get("status") in {"done", "cancelled"}:
                raise ValueError("unknown or terminal watch")
            task["next_review_at"] = next_review_at

    def finish_task(self, task_id, status, *, artifact=None, verification=None, by="user"):
        if status not in {"done", "cancelled", "waiting", "blocked"}:
            raise ValueError("invalid final status")
        with self.transaction() as data:
            task = data["tasks"].get(task_id)
            if not task or task["status"] in {"done", "cancelled"}:
                raise ValueError("unknown or terminal watch")
            if by == "model" and task["status"] == "proposed" and status in {"waiting", "blocked"}:
                raise ValueError("a proposal can only be finished or cancelled")
            for name, value in (("artifact", artifact), ("verification", verification)):
                if value is not None:
                    task[name] = _text(value, 1000)
            task["status"] = status
            task["status_by"] = by
            if status in TERMINAL:
                task["closed_at"] = datetime.now(timezone.utc).isoformat()
            self._prune(data)
