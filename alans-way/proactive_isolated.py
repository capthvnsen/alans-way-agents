"""Exploratory wakes as one-shot stock cron jobs, so they never grow the main transcript.

A cron job runs in a fresh session, honors [SILENT], delivers to the bound
Telegram chat and, with attach_to_session, mirrors what it sent into that chat's
session so a "yes" reply has context. The plugin creates the job and removes it
once it has run; Hermes would otherwise keep a finished one-shot for a week.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
import re

NAME_PREFIX = "aw-wake-"
TOOLS = ("cronjob_manage", "cronjob")
STUCK_SECONDS = 7200
NOTE = ("[Isolated run] This is a one-shot background run, not the main conversation. The event is "
        "already acknowledged: do not call proactive_control resolve. report_signal and finish_task "
        "still work here; you cannot create watches or change settings. If a watch is worth offering, describe it in your reply; the "
        "user's answer reaches the main conversation, where it can be proposed.\n")


def telegram_chat(session_key):
    match = re.search(r":telegram:dm:(\d+)$", session_key or "")
    return match[1] if match else None


def _call(ctx, args):
    """Parsed result of the cron tool, or None when it is missing or unusable."""
    dispatch = getattr(ctx, "dispatch_tool", None)
    if dispatch is None:
        return None
    for tool in TOOLS:
        try:
            result = dispatch(tool, args)
            result = json.loads(result) if isinstance(result, str) else result
        except Exception:
            return None
        if isinstance(result, dict) and "Unknown tool" in str(result.get("error", "")):
            continue
        return result if isinstance(result, dict) and result.get("success") is True else None
    return None


def launch(ctx, session_key, event_id, prompt):
    """Job id of a one-shot isolated run delivering to the bound DM, or None."""
    chat = telegram_chat(session_key)
    if chat is None:
        return None
    result = _call(ctx, {"action": "create", "schedule": "in 1m", "prompt": NOTE + prompt,
                         "name": NAME_PREFIX + event_id[:8], "deliver": f"telegram:{chat}",
                         "attach_to_session": True})
    job_id = result.get("job_id") if result else None
    return job_id if isinstance(job_id, str) and job_id else None


def _response(home, job_id):
    try:
        newest = max((Path(home) / "cron" / "output" / job_id).glob("*.md"), key=lambda p: p.stat().st_mtime)
        return newest.read_text(encoding="utf-8").rpartition("## Response")[2].strip()
    except (OSError, ValueError):
        return ""


def _outcome(home, job):
    if job.get("last_status") != "ok":
        return "failed"
    return "silent" if _response(home, job["job_id"]).upper().startswith("[SILENT]") else "delivered"


def reap(runtime):
    """Log the outcome of finished wake jobs and remove them; stuck ones expire."""
    tracked = runtime.ledger.tracked_jobs()
    if not tracked:
        return
    listing = _call(runtime.ctx, {"action": "list", "include_disabled": True})
    if listing is None:
        return
    jobs = {job.get("job_id"): job for job in listing.get("jobs", []) if isinstance(job, dict)}
    now = datetime.now(timezone.utc)
    for job_id, started in tracked.items():
        job = jobs.get(job_id)
        if job is None:
            outcome = "gone"
        elif job.get("state") in ("completed", "error"):
            outcome = _outcome(runtime.home, job)
        elif (now - datetime.fromisoformat(started)).total_seconds() > STUCK_SECONDS:
            outcome = "expired"
        else:
            continue
        if job is not None:
            _call(runtime.ctx, {"action": "remove", "job_id": job_id})
        runtime.ledger.set_outcome(job_id, outcome)
        runtime.ledger.untrack_job(job_id)
