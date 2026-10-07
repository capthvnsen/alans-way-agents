"""Public plugin CLI: explicit operator binding, controls and read-only probe."""
from pathlib import Path
from types import SimpleNamespace
import json
import sqlite3

from .proactive_context import StaleProposal


def _entry_is_dm_route(entry, session_key):
    return (type(entry) is dict and entry.get("session_key") == session_key
            and entry.get("platform") == "telegram" and entry.get("chat_type") == "dm"
            and type(entry.get("session_id")) is str and bool(entry["session_id"])
            and entry.get("suspended") is not True)


def _routing_entry(home: Path, session_key: str):
    """Resolve a routing record without ever writing to either store.

    Same read order Hermes uses at load time: state.db's ``gateway_routing``
    table is primary; ``sessions/sessions.json`` is the legacy import that
    fills keys the DB cannot confirm. Rows are namespaced by the resolved
    sessions dir (``scope``), with ``''`` covering pre-scoping databases. A
    missing or unreadable source falls through, never fabricates.
    """
    db_path = home / "state.db"
    try:
        scope = str((home / "sessions").resolve())
    except Exception:
        scope = str(home / "sessions")
    try:
        if db_path.is_file() and not db_path.is_symlink():
            db = sqlite3.connect(f"{db_path.absolute().as_uri()}?mode=ro", uri=True, timeout=5)
            try:
                rows = db.execute(
                    "SELECT entry_json FROM gateway_routing WHERE session_key=?"
                    " AND scope IN (?, '') ORDER BY CASE WHEN scope=? THEN 0 ELSE 1 END",
                    (session_key, scope, scope)).fetchall()
            finally:
                db.close()
            for (entry_json,) in rows:
                try:
                    entry = json.loads(entry_json)
                except ValueError:
                    continue
                if type(entry) is dict:
                    return entry
    except (OSError, ValueError, sqlite3.Error):
        pass
    index = home / "sessions" / "sessions.json"
    try:
        if index.is_file() and not index.is_symlink() and index.stat().st_size <= 16777216:
            data = json.loads(index.read_text(encoding="utf-8"))
            if type(data) is dict and type(data.get(session_key)) is dict:
                return data[session_key]
    except (OSError, ValueError):
        pass
    return None


def bind(runtime, session_key):
    """Read routing metadata only; never create or change a native session."""
    from .proactive_core import Policy
    Policy(session_key=session_key)
    if not session_key:
        raise ValueError("an existing route is required")
    entry = _routing_entry(runtime.home, session_key)
    if not _entry_is_dm_route(entry, session_key):
        raise ValueError("bind only a verified existing direct Telegram route in this profile")
    # Binding IS the consent step: the operator picks the chat that may be
    # messaged first, so a fresh install stays enabled (its default) and the
    # orientation wake is admitted here. A deliberately paused install keeps
    # its pause — re-binding never silently resumes it.
    runtime.store.update_policy({"primary_profile": "default",
                                 "session_key": session_key, "resume_at": ""})
    runtime._admit_first_run()


def probe(runtime):
    """Operator-requested model check; no event admission or injection."""
    from .proactive_review import review, _context_json, _validate_snapshot, _has_evidence
    context = runtime.review_context()
    context = json.loads(_context_json(context))
    _validate_snapshot(context)
    known = {task["id"] for task in context["tasks"] if task["approved"] is True and task["status"] == "active"}
    counters = {"call_count": 0, "provider_completion_returned": False,
                "json_result": False, "structured_result_valid": False}
    if not _has_evidence(context, known):
        return {"ok": True, **counters, "skipped_no_evidence": True,
                "appraisal": {"useful": False, "action": "ask", "task_id": None}, "injected": False}
    class ObservedFacade:
        def complete_structured(self, **kwargs):
            counters["call_count"] += 1
            result = runtime.ctx.llm.complete_structured(**kwargs)
            counters["provider_completion_returned"] = True
            counters["json_result"] = result.content_type == "json"
            parsed = result.parsed
            counters["structured_result_valid"] = (
                counters["json_result"] and type(parsed) is dict
                and set(parsed) == {"useful", "action", "task_id"}
                and type(parsed["useful"]) is bool
                and parsed["action"] in {"research", "draft", "continue_approved", "ask", "follow_up"}
                and (parsed["task_id"] is None or (type(parsed["task_id"]) is str and parsed["task_id"] in known))
                and (parsed["useful"] is False or parsed["action"] not in {"continue_approved", "follow_up"}
                     or parsed["task_id"] is not None))
            return result
    appraisal = review(SimpleNamespace(llm=ObservedFacade()), context, "manual_review",
                       record_error=runtime._record_appraisal_error)
    return {"ok": counters["structured_result_valid"], **counters, "appraisal": appraisal,
            "injected": False}


def setup(parser):
    parser.add_argument("action", nargs="?", default="status",
                        choices=["status", "pause", "resume", "configure", "review", "bind", "probe",
                                 "approve", "level", "quiet", "snooze", "timezone", "log"])
    parser.add_argument("value", nargs="?", help="level: quiet|normal|eager; quiet: 22-8|off; "
                        "snooze: 3d|until <time>|off; timezone: IANA name")
    parser.add_argument("--session-key", help="Exact existing private route; bind only, never echoed")
    parser.add_argument("--watch-id", help="Proposed watch to approve; approve only")
    parser.add_argument("--hash", help="Proposal code shown with the watch; refuses an edited proposal")
    parser.add_argument("--timezone", help="IANA timezone for quiet hours, such as America/Chicago")
    parser.add_argument("--settings", help="JSON policy/preferences object for configure")


def execute(runtime, args):
    try:
        value, tz = getattr(args, "value", None), getattr(args, "timezone", None)
        if args.action == "bind":
            bind(runtime, args.session_key)
            if tz:
                runtime.operate("timezone", tz)
            result = json.loads(runtime.control({"action": "status"}))
        elif args.action == "approve":
            try:
                runtime.ledger.approve_task(args.watch_id, getattr(args, "hash", None))
            except StaleProposal as stale:
                print(json.dumps({"ok": False, "error": "The proposal changed since you read it; nothing was approved.",
                                  "scope": stale.task["scope"], "next_action": stale.task["next_action"],
                                  "hash": runtime.ledger.proposal_hash(stale.task)}))
                return 1
            result = json.loads(runtime.control({"action": "status"}))
        elif args.action == "probe":
            result = probe(runtime)
        elif args.action in runtime._KNOBS:
            result = {"ok": True, "text": runtime.operate(args.action, value)}
            print(result["text"])
            return 0
        else:
            payload = {"action": args.action}
            if args.action == "configure":
                payload["settings"] = {**json.loads(args.settings or "{}"), **({"timezone": tz} if tz else {})}
            result = json.loads(runtime.control(payload))
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("ok") is True else 1
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    except Exception:
        print(json.dumps({"ok": False, "error": "Operator action failed; inspect locally without exposing routing or credentials"}))
        return 1
