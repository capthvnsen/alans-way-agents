"""Public Hermes plugin entry point; registration alone never injects."""
from datetime import datetime, timezone
from pathlib import Path
import json

from .gateway_guard import gateway_ready, hermes_home
from .proactive_context import (SourceSuppressed, StaleProposal, TASK_FIELDS, TASK_KINDS, approval_fresh,
                                pending_view)


# The gateway drops a turn whose whole reply is this marker, so a wake with
# nothing to say costs the user no message.
SILENT_LINE = ("Your final reply is delivered to the user. If nothing here is worth "
               "their attention, reply with exactly [SILENT] and nothing else.")


class Runtime:
    def __init__(self, ctx, home: Path, *, background=False, store=None, appraiser=None):
        self.ctx, self.home = ctx, home
        self.registered_at = datetime.now(timezone.utc)
        self._store = store
        self._appraiser = appraiser
        self.closed = False
        import threading
        self._stop = threading.Event()
        self._store_lock = threading.Lock()
        self._tick_lock = threading.Lock()
        self.worker = None
        self.observer_error = None
        self.appraisal_error = None
        self.telegram = None
        self.telegram_handler = False

    def _inject(self, message, session_key):
        """One injection attempt → tri-state outcome.

        Only the adapter can inspect acceptance (``is True``); a queued
        request proves nothing about the turn, so anything else stays
        honest about not knowing.
        """
        try:
            accepted = self.ctx.inject_message(message, role="user",
                                               session_key=session_key)
            return ("accepted_unverified" if accepted is True
                    else "rejected" if accepted is False else "uncertain")
        except Exception:
            return "uncertain"

    def _context_block(self, task_id=None):
        """What an isolated run cannot read for itself: it has no bound session, so
        the plugin's status tool is stripped there."""
        snapshot = self.ledger.snapshot()
        prefs = snapshot["preferences"]
        lines = ["[Live context from the plugin ledger]",
                 f"Focus: {', '.join(prefs.get('focus', [])[:8]) or 'none'}. "
                 f"Ignore: {', '.join(prefs.get('ignore', [])[:8]) or 'none'}. "
                 f"Max work minutes: {prefs.get('max_work_minutes', 20)}."]
        task = next((t for t in snapshot["tasks"] if t["id"] == task_id and t.get("approved") is True), None)
        if task:
            lines.append(f"Watch {task_id}: scope {task['scope'][:300]} Next action: {task['next_action'][:300]}")
        return "\n".join(lines) + "\n"

    def _send(self, event, message, *, isolate, kind, reason, task_id=None):
        """Deliver one wake; returns (store status, result status).

        Exploratory wakes try an isolated one-shot cron job first and fall
        back to the main session when cron is unusable. An isolated wake never
        holds the one-wake gate, so it is acknowledged here.
        """
        if isolate:
            from .proactive_isolated import launch
            job_id = launch(self.ctx, event["session_key"], event["id"], self._context_block(task_id) + message)
            if job_id:
                self.ledger.track_job(job_id, event["kind"])
                self.ledger.log(kind, reason, "queued", job_id=job_id)
                return "resolved", "isolated"
        status = self._inject(message, event["session_key"])
        self.ledger.log(kind, reason, "sent" if status == "accepted_unverified" else "rejected")
        return status, status

    def _record_appraisal_error(self, exc=None):
        """Status records that appraisal failed, never why — provider details
        and private context stay out of chat-visible status."""
        self.appraisal_error = "appraisal_failed; inspect locally before resuming"

    def start(self, *, interval=30.0):
        """A deterministic observer thread, not a second agent or scheduler."""
        import threading
        if self.closed or (self.worker and self.worker.is_alive()):
            return
        def run():
            while not self._stop.wait(interval):
                try:
                    policy = self.store.load_policy()
                    # A snoozed pause (resume_at set) must still reach claim()
                    # so the snooze can lift itself — a hard skip here would
                    # leave it paused forever.
                    if not self.gateway_ready() or (
                            policy.enabled is not True and not policy.resume_at):
                        continue
                    self.observe()
                    self.tick()
                    self.observer_error = None
                except Exception:
                    # Never put private context or provider exceptions in status.
                    self.observer_error = "observer_failed; inspect locally before resuming"
        self.worker = threading.Thread(target=run, name="companion-opportunity-observer", daemon=True)
        self.worker.start()

    @property
    def store(self):
        with self._store_lock:
            if self._store is None:
                from .proactive_core import Store
                self._store = Store(self.home / "companion" / "proactivity")
            return self._store

    @property
    def ledger(self):
        from .proactive_context import Ledger
        return Ledger(self.home / "companion" / "proactivity")

    def gateway_ready(self):
        return not self.closed and gateway_ready(self.home, self.registered_at)

    def observe(self):
        from .proactive_observe import observe
        from .proactive_isolated import reap
        admitted = observe(self)
        reap(self)
        self._ask_reapproval()
        return admitted

    def _ask_reapproval(self):
        """Watches approved over 30 days ago stop firing until the user approves them again.

        Every observer pass retries the ask until one channel takes it: buttons
        once Telegram is connected, or the text command where buttons are impossible."""
        from .proactive_telegram import offer
        for task_id in self.ledger.flag_expired_approvals():
            self.ledger.log("proposal", f"{task_id}: needs re-approval", "proposed")
        with self.ledger.transaction() as data:
            asked = dict(data["observations"].get("__reasked", {}))
        for task in self.ledger.snapshot()["tasks"]:
            if not (task.get("revision") or {}).get("reapproval"):
                continue
            view = pending_view(task)
            code = self.ledger.proposal_hash(view)
            if asked.get(task["id"]) == code:
                continue
            if offer(self, view, code, reapproval=True) or self._text_reapproval(view, code):
                with self.ledger.transaction() as data:
                    data["observations"].setdefault("__reasked", {})[task["id"]] = code

    def _text_reapproval(self, view, code):
        from .proactive_telegram import fits
        key = self.store.load_policy().session_key
        if not key or (self.telegram_handler and fits(view, code)):
            return False  # buttons will work once Telegram is connected
        message = (f"Tell the user: watch {view['id']} ({view.get('title') or view['scope'][:60]}) was last approved "
                   f"over 30 days ago and stopped running. Scope: {view['scope'][:300]} Next action: "
                   f"{view['next_action'][:200]} To keep it, they approve by sending exactly: "
                   f"/watch approve {view['id']} {code}")
        return self._inject(message, key) == "accepted_unverified"

    def review_context(self):
        from .proactive_observe import collect
        return collect(self.home, self.ledger, self.ctx)[0]

    def tick(self):
        # Only one appraisal/dispatch may be in flight in this gateway.
        if not self._tick_lock.acquire(blocking=False):
            return None
        try:
            return self._tick()
        finally:
            self._tick_lock.release()

    def _tick(self):
        if not self.gateway_ready():
            return None
        policy = self.store.load_policy()
        # While snoozed (enabled off but resume_at set), still fall through
        # to claim() — it owns the atomic snooze-lift decision.
        if (policy.enabled is not True and not policy.resume_at) \
                or not policy.session_key:
            return None
        # Expire stale unresolved dispatches before gating: a wake the session
        # could never acknowledge (e.g. the control toolset missing from its
        # platform) must not hold the one-wake gate open forever.
        if hasattr(self.store, "expire"):
            self.store.expire()
        if hasattr(self.store, "status"):
            counts = self.store.status()["counts"]
            if any(counts.get(status, 0) for status in ("dispatching", "accepted_unverified", "uncertain")):
                return None
        event = self.store.claim()
        if event is None:
            return None
        try:
            return self._dispatch(event)
        except BaseException:
            # Any escape between claim and finish must not strand the event in
            # 'dispatching': it would hold the one-wake gate open forever.
            try:
                self.store.finish(event["id"], "uncertain")
            except Exception:
                pass
            raise

    def _dispatch(self, event):
        event_id = event["id"]
        live = self.store.load_policy()
        if live.enabled is not True or event["session_key"] != live.session_key:
            self.store.finish(event_id, "rejected", refund=True)
            return {"id": event_id, "status": "rejected"}
        if event["kind"] == "watch_due":
            return self._dispatch_watch_due(event)
        if event["kind"] == "first_run":
            return self._dispatch_first_run(event)
        context = {"tasks": []}
        try:
            self.appraisal_error = None
            context = self.review_context()
            if self._appraiser is None:
                from .proactive_review import review
                appraisal = review(self.ctx, context, event["kind"],
                                   record_error=self._record_appraisal_error)
            else:
                appraisal = self._appraiser(self.ctx, context, event["kind"])
        except Exception:
            self._record_appraisal_error()
            appraisal = {"useful": False}
        if not isinstance(appraisal, dict) or appraisal.get("useful") is not True:
            self.store.finish(event_id, "rejected", refund=True, appraised=True)
            self.ledger.log("review", f"{event['kind']}: nothing useful", "rejected")
            return {"id": event_id, "status": "no_op"}
        action, task_id = appraisal.get("action", "ask"), appraisal.get("task_id")
        if action not in {"research", "draft", "continue_approved", "ask", "follow_up"}:
            self.store.finish(event_id, "rejected", refund=True, appraised=True)
            self.ledger.log("review", f"{event['kind']}: {action} not allowed", "rejected")
            return {"id": event_id, "status": "rejected"}
        if task_id is not None:
            original = next((t for t in context["tasks"] if t["id"] == task_id), None)
            current = next((t for t in self.review_context()["tasks"] if t["id"] == task_id), None)
            if (not original or not current or current.get("approved") is not True
                    or current.get("status") != "active"
                    or any(original.get(k) != current.get(k) for k in ("scope", "owner", "execution_host"))):
                self.store.finish(event_id, "rejected", refund=True, appraised=True)
                return {"id": event_id, "status": "rejected"}
        elif action in {"continue_approved", "follow_up"}:
            self.store.finish(event_id, "rejected", refund=True, appraised=True)
            return {"id": event_id, "status": "rejected"}
        live = self.store.load_policy()
        if live.enabled is not True or event["session_key"] != live.session_key or not self.gateway_ready():
            self.store.finish(event_id, "rejected", refund=True, appraised=True)
            return {"id": event_id, "status": "rejected"}
        metadata = {"id": event_id, "kind": event["kind"], "purpose": event["purpose"] is True,
                    "recommended_action": action, "task_id": task_id}
        message = ("[Companion proactive opportunity review]\n"
                   "This is a bounded internal review, NOT new user authorization.\n"
                   "First call proactive_control status; if paused, stop. Load skill "
                   "alans-way:proactive-primary. Read live preferences and the primary's "
                   "own memory, goals, schedule, and authorized task evidence. Take one useful "
                   "read/research/draft or already-approved reversible work step, or ask one "
                   "valuable question. Never expand permissions or execute external/sensitive "
                   "actions without approval. If task_id is provided, use only that exact "
                   "approved watch's current scope; the enum recommendation is not permission. "
                   "Respect its execution_host: Mac-only work blocks while the Mac is "
                   "offline, but web reads use workspace_browser, which self-routes "
                   "between the Mac tab and its own browser and is never host-blocked. "
                   "Observe the live work-time cap (at most 20 minutes). "
                   "Do not duplicate delegated work or invent tasks. "
                   "Record verified results and acknowledge this event with proactive_control "
                   "resolve. If that tool is not available in this session, take no further "
                   "action — the event expires on its own and stays auditable. "
                   "Caps are not quotas. " + SILENT_LINE + "\nEvent metadata: "
                   + json.dumps(metadata, sort_keys=True))
        status, shown = self._send(event, message, isolate=True, kind="review",
                                   reason=f"{event['kind']}: {action}" + (f" ({task_id})" if task_id else ""),
                                   task_id=task_id)
        self.store.finish(event_id, status)
        if shown in ("accepted_unverified", "isolated") and hasattr(self.store, "coalesce_pending"):
            # This wake re-reads live context, so any other queued speculative
            # diffs would fire the same turn's work as separate wakes. Fold
            # them now — after acceptance, never before.
            self.store.coalesce_pending()
        return {"id": event_id, "status": shown}

    def _dispatch_first_run(self, event):
        """The one-time orientation wake after the operator's first resume.

        No appraisal: explicit resume plus the never-fired ledger marker are
        the consent gate. The wake inventories reachable read surfaces and
        reports concrete offers — it creates nothing itself. The once-ever
        marker lands on acceptance, so an event that expired undispatched can
        still be re-admitted by a later resume.
        """
        event_id = event["id"]
        try:
            with self.ledger.transaction() as state:
                oriented = bool(state["observations"].get("first_run_done"))
        except Exception:
            oriented = False
        if oriented:
            # A duplicate admission queued before an earlier wake landed —
            # orientation already happened; retire this one quietly.
            self.store.finish(event_id, "resolved", refund=True)
            return {"id": event_id, "status": "stale"}
        if any(info.get("kind") == "first_run" for info in self.ledger.tracked_jobs().values()):
            self.store.finish(event_id, "resolved", refund=True)
            return {"id": event_id, "status": "stale"}
        live = self.store.load_policy()
        if live.enabled is not True or event["session_key"] != live.session_key \
                or not self.gateway_ready():
            self.store.finish(event_id, "rejected", refund=True)
            return {"id": event_id, "status": "rejected"}
        metadata = {"id": event_id, "kind": "first_run", "purpose": True}
        message = "\n".join([
            "[Companion first-run orientation]",
            "Proactivity was just enabled on this conversation. This is a",
            "one-time orientation wake, not new authorization: first call",
            "proactive_control status; if paused, stop. Load skill",
            "alans-way:proactive-primary.",
            "Inventory only installed and reachable read surfaces (skills,",
            "connectors, managed-browser reachability, schedules, approved",
            "watches) with a few bounded metadata reads — no bulk content.",
            "Then send ONE consolidated reply: at most five concrete",
            "watch/loop/sweep offers with cadences, or one clarifying",
            "question if priorities are unclear. High-value sources with no",
            "connector or reachable login may be offered once as connector",
            "suggestions. Create nothing without an explicit yes. If no",
            "useful source is reachable, say so plainly and suggest the",
            "smallest start. Resolve this event with proactive_control",
            "resolve when done; do not generate a second orientation wake.",
            SILENT_LINE,
            "Event metadata: " + json.dumps(metadata, sort_keys=True),
        ])
        status, shown = self._send(event, message, isolate=True, kind="first-run", reason="orientation")
        self.store.finish(event_id, status)
        if shown == "accepted_unverified":
            try:
                with self.ledger.transaction() as state:
                    state["observations"]["first_run_done"] = \
                        datetime.now(timezone.utc).isoformat()
            except Exception:
                pass
        return {"id": event_id, "status": shown}

    def _dispatch_watch_due(self, event):
        """Dispatch a user-approved scheduled watch without an LLM appraisal.

        A watch is a standing contract the user opted into — dedupe, budgets,
        quiet hours and route checks already ran in claim(); the appraiser's
        job is to gate *inferred* opportunities, not to veto scheduled work.
        The fired instance's epoch is embedded in the evidence, so a watch
        that was re-armed or moved since admission is recognized as stale.
        """
        event_id = event["id"]
        parts = event["evidence"].split(":")
        watch_id = parts[1] if len(parts) >= 3 and parts[0] == "watchdue" else None
        marker = parts[2] if len(parts) >= 3 else ""
        epoch = None
        if marker[:1] in ("r", "d") and marker[1:].isdigit():
            epoch = int(marker[1:])
        watch = next(
            (t for t in self.ledger.snapshot()["tasks"] if t.get("id") == watch_id),
            None,
        )
        if watch_id is None or epoch is None or watch is None \
                or watch.get("approved") is not True or watch.get("status") != "active" \
                or not approval_fresh(watch):
            self.store.finish(event_id, "rejected", refund=True)
            self.ledger.log("watch", f"{watch_id}: no longer active", "rejected")
            return {"id": event_id, "status": "rejected"}
        # Stale-instance check: the watch was re-armed or its deadline moved
        # since this event was admitted — the scheduled moment it names is
        # already handled, so retire it instead of double-waking. A cadence
        # watch whose grid rolled on while the wake sat queued is stale too:
        # the fresher slot becomes its own event.
        from .proactive_observe import _parse_time, _due_instance
        now_ts = datetime.now(timezone.utc).timestamp()
        cadence = watch.get("cadence_seconds")
        if marker[0] == "r":
            current = _due_instance(_parse_time(watch.get("next_review_at")),
                                    cadence, now_ts)
        else:
            current = _parse_time(watch.get("due_at"))
        if current is None or int(current) != epoch:
            self.store.finish(event_id, "resolved", refund=True)
            self.ledger.log("watch", f"{watch_id}: already handled", "rejected")
            return {"id": event_id, "status": "stale"}
        # A cadence watch re-arms on its fixed grid as it fires — whether or
        # not the wake succeeds — so one failed dispatch can never strand the
        # routine. Skipped slots are not replayed; the next grid point wins.
        if marker[0] == "r" and type(cadence) is int and 300 <= cadence <= 604800:
            nxt = epoch + (int((now_ts - epoch) // cadence) + 1) * cadence
            try:
                self.ledger.arm_review(
                    watch_id,
                    datetime.fromtimestamp(nxt, timezone.utc).isoformat())
            except ValueError:
                pass
        live = self.store.load_policy()
        if live.enabled is not True or event["session_key"] != live.session_key \
                or not self.gateway_ready():
            self.store.finish(event_id, "rejected", refund=True)
            return {"id": event_id, "status": "rejected"}
        # Missing or hand-corrupted kinds fall back to the plain watch
        # contract — a bad label must never crash a scheduled wake.
        kind = watch.get("kind", "watch")
        if kind not in TASK_KINDS:
            kind = "watch"
        metadata = {"id": event_id, "kind": "watch_due", "watch_kind": kind,
                    "purpose": True, "watch_id": watch_id,
                    "fired_instance": marker,
                    "execution_host": watch.get("execution_host", "cloud")}
        heading = {
            "watch": "[Companion scheduled watch]",
            "loop": "[Companion open loop check]",
            "sweep": "[Companion scheduled sweep]",
        }[kind]
        contract = {
            "watch": "a standing watch",
            "loop": "an open loop reaching its follow-up moment",
            "sweep": "a consolidated source sweep",
        }[kind]
        lines = [
            heading,
            f"This is a user-approved {contract} firing on schedule — bounded",
            "contracted work, not a new opportunity and not new scope.",
            f'Watch "{watch_id}": {watch.get("title", "")}'.rstrip(),
            f"Scope: {watch.get('scope', '')}",
            f"Next action: {watch.get('next_action', '')}",
        ]
        if watch.get("due_at"):
            lines.append(f"Deadline: {watch['due_at']} (escalates if unhandled)")
        if watch.get("notify_when"):
            lines.append(f"Report only when: {watch['notify_when']}")
        if watch.get("signal"):
            lines.append(f"Last reported signal: {watch['signal']}")
        if kind == "sweep":
            lines.append(
                "Run one bounded metadata-first pass over installed, reachable "
                "read surfaces and open loops — load alans-way:proactive-primary "
                "and follow its references/sweeps.md (skill_view with file_path). "
                "Reachable surfaces "
                "include the managed browser: workspace_browser serves the Mac "
                "tab when it is online and its own browser when it is not, and "
                "a logged-in page counts as a source. Missing connectors are "
                "reported and offered once, never provisioned silently or "
                "faked. At most five ranked items with evidence and why they "
                "matter now; nothing actionable means a quiet, successful "
                "sweep — silence, not filler. Draft, never send, anything "
                "external without approval. Write report_signal with a short "
                "digest, then resolve this event via proactive_control resolve."
            )
        elif kind == "loop":
            lines.append(
                "Follow references/watches.md of alans-way:proactive-primary. "
                "Check the real signal now (inbox, thread, board) with real "
                "tools — connector first, workspace_browser when no connector "
                "is installed — honoring execution_host (web reads are never "
                "host-blocked). If the dependency resolved, "
                "finish_task with the outcome and fold quiet mentions into the "
                "next sweep rather than a standalone message. If it is still "
                "unanswered past its moment, draft the follow-up and ask before "
                "sending — a loop never nudges on its own, and only once per "
                "checkpoint. Then resolve this event via proactive_control "
                "resolve."
            )
        else:
            lines.append(
                "Follow references/watches.md of alans-way:proactive-primary. "
                "Run the check now with real tools, honoring execution_host "
                "(mac means work only the Mac can do — blocked while offline; "
                "web reads go through workspace_browser, which serves the Mac "
                "tab online or its own browser when the Mac is unreachable, "
                "so web work is never host-blocked). "
                "Write what you observed via proactive_control report_signal so "
                "unchanged findings dedupe durably. Re-arm with record_task "
                "(new next_review_at) unless cadence_seconds already advances "
                "it, or finish_task when the watch is satisfied. Report to this "
                "conversation only when the outcome is meaningful or needs a "
                "decision — silence is a valid result. Then resolve this event "
                "via proactive_control resolve. Native approvals still gate "
                "external or sensitive actions; unverified work is not complete."
            )
        lines.append(SILENT_LINE)
        lines.append("Event metadata: " + json.dumps(metadata, sort_keys=True))
        status, shown = self._send(event, "\n".join(lines), isolate=kind in ("sweep", "loop"),
                                   kind=kind, reason=f"{watch_id}: {watch.get('title', '')}"[:100])
        self.store.finish(event_id, status)
        if shown in ("accepted_unverified", "isolated") and kind == "sweep" \
                and hasattr(self.store, "coalesce_pending"):
            # The sweep reads live context anyway, so queued speculative diffs
            # are its input — fold them into this one turn instead of
            # waking again. Only after acceptance; a failed dispatch loses
            # nothing.
            self.store.coalesce_pending()
        return {"id": event_id, "status": shown}

    def close(self):
        import threading
        self.closed = True
        self._stop.set()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=1.0)

    # A model-called configure may narrow the envelope the operator set,
    # never widen it: caps do not rise and intervals do not shrink. Resume and
    # loosening changes belong to /proactivity or ``hermes proactivity``.
    _CAPS = ("max_daily_wakes", "max_low_purpose_wakes", "max_daily_watch_wakes",
             "max_pending", "event_ttl_seconds")
    _INTERVALS = ("min_interval_seconds", "min_watch_interval_seconds",
                  "debounce_seconds")

    def tool_control(self, args, **kwargs):
        """Tool entry: mutating actions belong to the bound route.

        The CLI operator and slash commands call ``control`` themselves (the
        slash path checks the route first), so gating here would lock the
        operator out of a shell that has no session key. Status stays open —
        it answers health for any session — but a foreign caller gets the
        disclosure-free view: watch scopes and preferences stay bound.
        """
        action = args.get("action", "status") if isinstance(args, dict) else "status"
        if action != "status" and not self._bound_route_only() and not self._cron_bookkeeping(action, kwargs.get("task_id")):
            return json.dumps({"ok": False, "error": "Proactivity controls are only available on the bound conversation."})
        if action == "resume":
            return json.dumps({"ok": False, "error": "Resume is operator-only: the user turns proactivity back on with /proactivity resume or hermes proactivity resume."})
        if action == "configure" and isinstance(args, dict):
            relaxed = self._loosening(args.get("changes", args.get("settings", {})))
            if relaxed:
                return json.dumps({"ok": False, "error": f"That change widens {relaxed}: an operator applies it with /proactivity configure or hermes proactivity configure."})
        if action == "level" and isinstance(args, dict):
            from .proactive_core import LEVELS
            level = args.get("level")
            preset = LEVELS.get(level) if isinstance(level, str) else None
            if preset is not None and self._loosening(preset):
                return json.dumps({"ok": False, "error": "Raising the level is operator-only: the user applies it with /proactivity level or hermes proactivity level."})
        if action == "pause" and isinstance(args, dict) and args.get("resume_at") is not None:
            # A bound session may tighten an active snooze (lift lands later)
            # but never impose or hasten a lift over a paused policy — either
            # way the pause boundary moves earlier, which is a resume and
            # therefore operator-only, exactly like a loosening configure.
            policy = self.store.load_policy()
            if not policy.enabled:
                try:
                    proposed = datetime.fromisoformat(args["resume_at"])
                    current = datetime.fromisoformat(policy.resume_at) if policy.resume_at else None
                    sooner = current is None or proposed < current
                except (TypeError, ValueError):
                    sooner = True
                if sooner:
                    return json.dumps({"ok": False, "error": "Adjusting a paused snooze is operator-only: the operator applies it with /proactivity pause <timestamp>."})
        if action == "record_task" and isinstance(args, dict):
            return self._propose(args.get("task"))
        result = self.control(args, **kwargs)
        if action == "status" and not self._bound_route_only():
            try:
                state = json.loads(result)
                for private in ("tasks", "preferences", "audit"):
                    state.pop(private, None)
                return json.dumps(state)
            except (ValueError, TypeError):
                pass
        return result

    def _cron_bookkeeping(self, action, task_id=None):
        """An isolated wake runs in a cron session with no route: it may feed
        signals and finish watches (both only tighten), nothing else. Only the
        wake jobs this plugin created count: Hermes names that session's
        task_id ``cron:<job id>:<run>``, and the job must still be tracked."""
        if action not in ("report_signal", "finish_task"):
            return False
        try:
            from gateway.session_context import get_session_env
            from utils import is_truthy_value
            cron = is_truthy_value(get_session_env("HERMES_CRON_SESSION", ""))
        except Exception:
            import os
            cron = os.environ.get("HERMES_CRON_SESSION", "").lower() in ("1", "true", "yes")
        parts = str(task_id or "").split(":")
        return cron and parts[0] == "cron" and len(parts) > 1 and parts[1] in self.ledger.tracked_jobs()

    def _propose(self, task):
        """The model may only propose a watch; the user approves it themselves."""
        try:
            pending = self.ledger.propose_task(task)
        except SourceSuppressed as exc:
            return json.dumps({"ok": False, "error": f"The user dismissed three {exc.args[0]} proposals "
                               "in the last two weeks. Do not propose more of that kind unless they ask for one."})
        except Exception:
            return json.dumps({"ok": False, "error": "Invalid or unsupported watch; no success is claimed"})
        result = {"ok": True, **self.store.status()}
        if pending:
            saved = pending_view(next(t for t in self.ledger.snapshot()["tasks"] if t["id"] == task["id"]))
            code = self.ledger.proposal_hash(saved)
            self.ledger.log("proposal", f"{task['id']}: {task.get('title', '')}", "proposed")
            from .proactive_telegram import offer
            offer(self, saved, code)
            result["awaiting_approval"] = task["id"]
            result["tell_user"] = (f"Watch {task['id']} is only proposed and will not run yet. In your reply, "
                                   f"say what it will do and tell the user to approve it by sending exactly: "
                                   f"/watch approve {task['id']} {code}")
        return json.dumps(result)

    def _loosening(self, changes):
        """Name the first limit a configure call would loosen, or None.

        Caps stay at or below the operator's values, intervals at or above,
        and the quiet window only grows — every direction beyond that is the
        operator's, exactly like binding. A non-dict payload fails later in
        ``control``'s own validation, so it returns no limit here.
        """
        if not isinstance(changes, dict):
            return None
        policy = self.store.load_policy()
        for name in self._CAPS:
            value = changes.get(name)
            if type(value) is int and value > getattr(policy, name):
                return name
        for name in self._INTERVALS:
            value = changes.get(name)
            if type(value) is int and value < getattr(policy, name):
                return name
        if "timezone" in changes and changes["timezone"] != policy.timezone:
            return "timezone"
        if "quiet_start" in changes or "quiet_end" in changes:
            start = changes.get("quiet_start", policy.quiet_start)
            end = changes.get("quiet_end", policy.quiet_end)
            if type(start) is int and type(end) is int:
                def quiet(first, last):
                    if first <= last:
                        return {h for h in range(24) if first <= h < last}
                    return {h for h in range(24) if h >= first or h < last}
                if not quiet(start, end) >= quiet(policy.quiet_start, policy.quiet_end):
                    return "quiet hours"
        preferences = changes.get("preferences")
        if isinstance(preferences, dict) and type(preferences.get("max_work_minutes")) is int:
            current = self.ledger.snapshot()["preferences"].get("max_work_minutes", 0)
            if preferences["max_work_minutes"] > current:
                return "max_work_minutes"
        return None

    def control(self, args, **kwargs):
        try:
            if not isinstance(args, dict):
                raise ValueError("control requires an object")
            action = args.get("action", "status")
            if action == "status":
                return json.dumps({"ok": True, **self.store.status(), **self.ledger.snapshot(),
                                   "gateway_ready": self.gateway_ready(),
                                   "observer_running": bool(self.worker and self.worker.is_alive()),
                                   "observer_error": self.observer_error,
                                   "appraisal_error": self.appraisal_error})
            if action == "configure":
                changes = args.get("changes", args.get("settings", {}))
                if (not isinstance(changes, dict) or not changes
                        or {"primary_profile", "session_key", "enabled"}.intersection(changes)):
                    raise ValueError("binding is operator-only")
                if "level" in changes:
                    raise ValueError("set the level with the level action")
                changes = dict(changes)
                if {"max_daily_wakes", "max_low_purpose_wakes", "max_daily_watch_wakes",
                        "min_interval_seconds"} & set(changes):
                    changes["level"] = "custom"
                preferences = changes.pop("preferences", None)
                if preferences is not None:
                    if changes:
                        raise ValueError("change policy and preferences in separate verified calls")
                    self.ledger.preferences(preferences)
                elif changes:
                    if "resume_at" in changes:
                        raise ValueError("snooze through pause, not configure")
                    self.store.update_policy(changes)
            elif action == "level":
                from .proactive_core import LEVELS
                self.store.update_policy({**LEVELS[args["level"]], "level": args["level"]})
            elif action == "report_signal":
                self.ledger.report_signal(args.get("task_id", ""), args.get("signal", ""))
            elif action == "finish_task":
                self.ledger.finish_task(args.get("task_id"), args.get("status", "done"), by="model",
                                        artifact=args.get("artifact"), verification=args.get("verification"))
            elif action == "pause":
                # resume_at turns a pause into a durable snooze; a bare pause
                # clears any pending snooze rather than inheriting one.
                resume_at = args.get("resume_at")
                if resume_at is not None and type(resume_at) is not str:
                    raise ValueError("resume_at must be an aware ISO timestamp")
                self.store.update_policy({"enabled": False,
                                          "resume_at": resume_at or ""})
            elif action == "resume":
                if not self.store.load_policy().session_key:
                    raise ValueError("bind an existing route first")
                self.store.update_policy({"enabled": True})
                self._admit_first_run()
            elif action == "review":
                # Interactive review is read-only and immediate, including while
                # automatic work is paused. It never queues a later surprise turn.
                from .proactive_operator import probe
                return json.dumps(probe(self))
            elif action == "resolve":
                self.store.finish(args.get("event_id", ""), "resolved")
            else:
                raise ValueError("unsupported action")
            return json.dumps({"ok": True, **self.store.status()})
        except Exception:
            return json.dumps({"ok": False, "error": "Invalid or unsupported proactivity control; no success is claimed"})

    def _admit_first_run(self):
        """Admit an orientation wake on each resume until one is accepted.

        The ``first_run_done`` marker lands only on dispatch acceptance, so a
        wake lost to expiry or rejection can be re-admitted; each admission
        carries a fresh evidence timestamp, and dispatch rejects any wake
        arriving after the marker — keeping the visible result once-ever.
        """
        try:
            with self.ledger.transaction() as state:
                if state["observations"].get("first_run_done"):
                    return
            evidence = "firstrun:" + datetime.now(timezone.utc).strftime(
                "%Y%m%dT%H%M%S.%f")
            self.store.record_event("first_run", evidence, purpose=True)
        except Exception:
            pass

    def _caller_session_key(self):
        """The route Hermes bound around this command handler's session.

        The gateway binds HERMES_SESSION_* as contextvars while dispatching a
        plugin slash command; ``get_session_env`` reads them with an
        os.environ fallback for hosts where Hermes is not importable.
        """
        try:
            from gateway.session_context import get_session_env
            return get_session_env("HERMES_SESSION_KEY") or ""
        except Exception:
            import os
            return os.environ.get("HERMES_SESSION_KEY", "")

    def _bound_route_only(self):
        """Mutating or disclosing chat controls belong to the bound route.

        Plugin slash commands bypass the gateway's slash access check, so any
        session that can message the bot could otherwise pause, retune or read
        private watch scopes. An unbound install stays open so setup works.
        A multiplexed gateway dispatches slash commands on the launch profile's
        runtime only; other profiles reach this store through the tool.
        """
        bound = self.store.load_policy().session_key
        return not bound or self._caller_session_key() == bound

    def command(self, raw_args):
        parts = raw_args.strip().split(maxsplit=1)
        action = parts[0] if parts else "status"
        if action != "status" and not self._bound_route_only():
            return "Proactivity controls are only available on the bound conversation."
        if action in self._KNOBS:
            try:
                return self.operate(action, parts[1] if len(parts) > 1 else "")
            except ValueError as exc:
                return str(exc)
        args = {"action": action}
        if action == "pause" and len(parts) > 1:
            args["resume_at"] = parts[1]
        if action == "configure":
            try:
                args["changes"] = json.loads(parts[1])
            except (IndexError, ValueError):
                return 'Use /proactivity configure with a JSON object, for example {"quiet_start":23}.'
        result = json.loads(self.control(args))
        if result.get("ok") is not True:
            return "Proactivity control failed. No success is claimed; check the installed tool settings."
        if action == "review":
            appraisal = result["appraisal"]
            if appraisal["useful"] is not True:
                return "Review complete: no useful opportunity found. No background turn queued."
            return ("Review suggests " + appraisal["action"] +
                    (" for approved watch " + appraisal["task_id"] if appraisal["task_id"] else "") +
                    ". Verify current scope and consent before acting. No background turn queued.")
        return self._status_text()

    _KNOBS = ("level", "quiet", "timezone", "snooze", "log")

    def operate(self, action, value=""):
        """The operator's plain-language knobs, shared by /proactivity and the CLI.

        Raises ValueError carrying the usage line; mutations answer with the
        read-back status. Never reachable from the model tool.
        """
        from .proactive_core import LEVELS
        policy = self.store.load_policy()
        if action == "log":
            return self._log_text(policy.timezone)
        if action == "level":
            name = (value or "").strip().lower()
            if name not in LEVELS:
                raise ValueError("Use /proactivity level quiet, normal or eager.")
            result = self.control({"action": "level", "level": name})
        elif action == "quiet":
            from .proactive_knobs import parse_quiet
            start, end = parse_quiet(value)
            result = self.control({"action": "configure", "changes": {"quiet_start": start, "quiet_end": end}})
        elif action == "timezone":
            try:
                self.store.update_policy({"timezone": (value or "").strip()})
            except ValueError:
                raise ValueError("Use /proactivity timezone <IANA name>, for example America/Chicago.") from None
            result = json.dumps({"ok": True})
        else:
            from .proactive_knobs import SNOOZE_USAGE, parse_snooze
            if (value or "").strip().lower() == "off":
                if not policy.resume_at:
                    return "No snooze is active."
                self.store.update_policy({"enabled": True})
                result = json.dumps({"ok": True})
            else:
                result = self.control({"action": "pause", "resume_at": parse_snooze(value, policy.timezone)})
        if json.loads(result).get("ok") is not True:
            raise ValueError("Proactivity control failed. No success is claimed; check the installed tool settings.")
        return self._status_text()

    def _log_text(self, tz):
        from zoneinfo import ZoneInfo
        entries = self.ledger.recent_log(10)
        if not entries:
            return "No proactive activity yet."
        lines = []
        for entry in reversed(entries):
            when = datetime.fromisoformat(entry["at"]).astimezone(ZoneInfo(tz)).strftime("%b %d %H:%M")
            lines.append(f"{when}  {entry['kind']}  {entry['reason']}  [{entry['outcome']}]")
        return "Recent proactive activity (newest first):\n" + "\n".join(lines)

    def _status_text(self):
        state = json.loads(self.control({"action": "status"}))
        if state.get("ok") is not True:
            return "Control was requested, but its effective state could not be verified."
        policy, counts = state["policy"], state["counts"]
        unresolved = sum(counts.get(name, 0) for name in ("dispatching", "accepted_unverified", "uncertain"))
        attention = [state.get("observer_error"), state.get("appraisal_error")]
        if state.get("storage_full"):
            attention.append("event storage full, new wakes refused")
        flagged = "\nAttention: " + "; ".join(item for item in attention if item) if any(attention) else ""
        snoozed = ("" if state["enabled"] or not policy.get("resume_at")
                   else f" until {policy['resume_at']}")
        quiet = ("off" if policy["quiet_start"] == policy["quiet_end"]
                 else f"{policy['quiet_start']:02}:00-{policy['quiet_end']:02}:00")
        return (f"Proactivity: {'enabled' if state['enabled'] else 'paused' + snoozed}\n"
                f"Level: {policy['level']}\n"
                f"Quiet hours: {quiet} ({policy['timezone']})\n"
                f"Limits: up to {policy['max_daily_wakes']} reviews/day plus "
                f"{policy['max_daily_watch_wakes']} scheduled-watch wakes; "
                f"{policy['min_interval_seconds'] // 60} minutes between automatic reviews\n"
                f"Telegram route: {'bound' if state['route_bound'] else 'unbound'}\n"
                f"Gateway: {'ready' if state['gateway_ready'] else 'not armed in this process'}\n"
                f"Observer: {'running' if state.get('observer_running') else 'stopped'}; "
                f"last pass {state.get('observed_at') or 'none yet'}\n"
                f"Pending: {counts.get('pending', 0)}; unresolved: {unresolved}"
                + flagged + "\n"
                "Limits are ceilings; nothing useful means silence.")

    def decide_watch(self, action, task_id, code=None):
        """The operator's decision on a proposal, shared by /watch and the buttons.

        Returns (reply text, outcome) with outcome approved, dismissed or
        stale, or None when there is nothing pending for that id.
        """
        try:
            if action == "approve":
                try:
                    task = self.ledger.approve_task(task_id, code)
                except StaleProposal as stale:
                    task = stale.task
                    return (f"Watch {task_id} changed since you read it, so nothing was approved. Now: {task['scope']} "
                            f"Next action: {task['next_action']} To approve this version send "
                            f"/watch approve {task_id} {self.ledger.proposal_hash(task)}"), "stale"
                return (f"Watch {task_id} is approved and active. Scope: {task['scope']} "
                        f"Next action: {task['next_action']}"), "approved"
            kind = self.ledger.dismiss_task(task_id)
            return (f"Dismissed {task_id}. Proposals of kind {kind} pause after three dismissals "
                    "in two weeks."), "dismissed"
        except ValueError:
            return None

    def watch_command(self, raw_args):
        """/watch — the operator's direct surface over standing watches.

        A typed slash command is explicit consent in itself, and the only way
        a watch becomes active: the model's tool can just propose one.
        Mutation output always reads back live state.
        """
        if not self._bound_route_only():
            return "Watch controls are only available on the bound conversation."
        parts = raw_args.strip().split(maxsplit=1)
        action, rest = parts[0] if parts else "list", parts[1] if len(parts) > 1 else ""
        try:
            tasks = self.ledger.snapshot()["tasks"]
            if action in ("list", ""):
                if not tasks:
                    return "No standing watches. Add one with /watch add {\"id\": ..., \"scope\": ...}."
                def line(t):
                    fire = t.get("next_review_at") or ("due " + t["due_at"] if t.get("due_at") else "manual")
                    cadence = f" every {t['cadence_seconds']}s" if t.get("cadence_seconds") else ""
                    kind = t.get("kind") if t.get("kind") in TASK_KINDS else "watch"
                    ask = (f" (approve with /watch approve {t['id']} {self.ledger.proposal_hash(t)})"
                           if t["status"] == "proposed" or t.get("revision") else "")
                    ask = " (needs re-approval)" + ask if (t.get("revision") or {}).get("reapproval") else ask
                    return f"- {t['id']} [{kind}:{t['status']}]{cadence} next: {fire} - {t.get('title') or t['scope'][:60]}{ask}"
                return "Standing watches:\n" + "\n".join(line(t) for t in tasks)
            if action == "show":
                task = next((t for t in tasks if t["id"] == rest), None)
                if task is None:
                    return f"No watch {rest!r}."
                return json.dumps(task, indent=2, sort_keys=True)
            if action == "add":
                payload = json.loads(rest)
                if isinstance(payload, dict):
                    payload["approved"] = True  # a typed /watch add is the consent
                self.ledger.record_task(payload)
                saved = next((t for t in self.ledger.snapshot()["tasks"]
                              if t["id"] == payload["id"]), {})
                fire = saved.get("next_review_at") or saved.get("due_at") or "manual"
                return f"Watch {payload['id']} recorded ({saved.get('status')}); next: {fire}."
            if action in ("cancel", "done", "pause", "blocked"):
                status = {"cancel": "cancelled", "done": "done",
                          "pause": "waiting", "blocked": "blocked"}[action]
                task_id = rest.split()[0] if rest else ""
                self.ledger.finish_task(task_id, status)
                return f"Watch {task_id} is now {status}."
            if action in ("approve", "dismiss"):
                words = rest.split()
                decision = self.decide_watch(action, words[0] if words else "", words[1] if len(words) > 1 else None)
                if decision is None:
                    raise ValueError("no proposed watch")
                return decision[0]
            if action == "resume":
                task_id = rest.split()[0] if rest else ""
                task = next((t for t in tasks if t["id"] == task_id), None)
                if task is None:
                    return f"No watch {task_id!r}."
                if task["status"] == "proposed":
                    return f"Watch {task_id} is only proposed. Approve it with /watch approve {task_id}."
                if task["status"] in {"done", "cancelled"}:
                    return f"Watch {task_id} is {task['status']}; terminal watches need a new id."
                task = dict(task, status="active")
                task = {k: v for k, v in task.items()
                        if k in TASK_FIELDS and k not in {"signal", "signal_at"}}
                self.ledger.record_task(task)
                return f"Watch {task_id} is active again."
            if action == "signal":
                task_id, _, signal = rest.partition(" ")
                if not signal.strip():
                    return "Use /watch signal <id> <observed state>."
                self.ledger.report_signal(task_id, signal.strip())
                return f"Signal recorded on {task_id}."
            return ("Use /watch list, /watch show <id>, /watch add {json}, "
                    "/watch approve <id>, /watch dismiss <id>, /watch pause <id>, /watch resume <id>, /watch done <id>, "
                    "/watch cancel <id>, or /watch signal <id> <text>.")
        except (ValueError, KeyError, IndexError, TypeError):
            return "Watch command failed. Check the id or JSON payload. No change was claimed."


def _owning_home() -> Path:
    """The home Hermes bound for this plugin load, never the launch env.

    Under gateway multiplex one process serves every profile and
    ``os.environ['HERMES_HOME']`` keeps the launch profile's home, so the env
    would point a secondary runtime at the primary's store. ``register()``
    runs inside Hermes' plugin-load home scope, which ``get_hermes_home()``
    reads from a contextvar; the env is only a fallback for hosts without
    Hermes importable (offline tests, plain subprocesses).
    """
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home()).expanduser().absolute()
    except Exception:
        return hermes_home()


def _primary_profile(ctx) -> bool:
    """Only the launch (default/custom) profile's runtime may observe.

    A named secondary profile registers the same tools and commands against
    its own home, but proactivity belongs to the default primary — Policy
    already refuses any other ``primary_profile``. A ctx without profile
    information (tests, non-gateway hosts) counts as primary.
    """
    try:
        name = getattr(ctx, "profile_name", None)
    except Exception:
        return True
    return name in (None, "", "default", "custom")


def register(ctx, *, home=None, background=True):
    runtime = Runtime(ctx, Path(home) if home is not None else _owning_home(), background=background)
    from .proactive_schema import SCHEMA
    ctx.register_tool(name="proactive_control", toolset="proactivity", schema=SCHEMA,
                      handler=runtime.tool_control, check_fn=lambda: True)
    ctx.register_command("proactivity", runtime.command,
                         description="Status, pause, resume, and configure proactive work")
    ctx.register_command("watch", runtime.watch_command,
                         description="List, schedule, pause, or cancel standing proactive watches")
    skills_dir = Path(__file__).parent / "skills"
    ctx.register_skill("proactive-primary", skills_dir / "proactive-primary" / "SKILL.md")
    ctx.register_skill("workspace-operations", skills_dir / "workspace-operations" / "SKILL.md")
    ctx.register_skill("workspace-setup", skills_dir / "workspace-setup" / "SKILL.md")
    ctx.on_unload(runtime.close)
    if hasattr(ctx, "register_telegram_handler"):
        from .proactive_telegram import wire
        ctx.register_telegram_handler(wire(runtime))
        runtime.telegram_handler = True
    if hasattr(ctx, "register_cli_command"):
        from .proactive_operator import setup, execute
        ctx.register_cli_command("proactivity", "Manage the designated proactive primary", setup,
                                 lambda args: execute(runtime, args))
    if background and _primary_profile(ctx):
        runtime.start()
    return runtime
