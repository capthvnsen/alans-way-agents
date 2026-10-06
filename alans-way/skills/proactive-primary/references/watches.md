# Watches and open loops

A watch is a durable standing check kept in the ledger: "watch this flight", "check
this subscription before it renews", "alert me if this thread revives". Propose one
only when the user asks for the standing behavior (or accepts your offer). Never
create one speculatively to fill the schedule.

## Proposing, approving, editing

You may only propose. `record_task` saves the watch as `proposed`; it does not run
and `approved` is not yours to set. The tool also sends the user
Approve, Snooze and Dismiss buttons when it can. In your normal reply, say what the
watch will do and give the exact command it returns, `/watch approve <id> <code>`
(the code covers the text they read; an edited proposal needs a new one). Do not say
it is active before they approve. Give each proposal an optional short `source` tag
such as `inbox`; three dismissals from a source in two weeks stop further proposals
from it. Proposals expire after seven days.

On an approved watch you may slow it (a longer `cadence_seconds`, a later
`next_review_at` or `due_at`), retitle it, pause it (`finish_task` with `waiting`),
finish it or cancel it. A new `next_action`, a different owner, a changed `notify_when`, a faster schedule, or
reactivating a paused watch sends it back to proposed and needs `/watch approve`
again. Scope, kind, `execution_host` and any native task binding never change after
approval; use a new id.
You may return a watch to active only if you blocked it yourself; a watch the user
paused or blocked comes back with their `/watch resume <id>`.

```python
proactive_control(action="record_task", task={
    "id": "rent_due", "title": "Rent payment", "owner": "primary",
    "scope": "Check rent payment posts; remind if missing",
    "next_action": "Check bank feed on the 1st", "status": "active",
    "cadence_seconds": 86400, "due_at": "2026-02-02T00:00:00+00:00"})
proactive_control(action="record_task", task={
    "id": "loop_vendor", "kind": "loop", "title": "Vendor documents",
    "owner": "primary", "status": "active",
    "scope": "Waiting on the vendor for the requested documents (offered Sep 30)",
    "next_action": "Check inbox for reply; if still silent, draft a follow-up and offer to send it",
    "due_at": "2026-10-08T00:00:00+00:00", "notify_when": "reply arrives or due passes"})
proactive_control(action="report_signal", task_id="rent_due",
                  signal="payment posted 2026-02-01")
```

## Kinds and fields

- `watch` (default): a standing check on a thing: a price, a page, a thread state.
- `loop`: an outbound dependency awaiting a reply, delivery or artifact. `due_at` is
  the follow-up moment and `signal` the last known state.
- `sweep`: a scheduled broad pass over permitted sources (see `sweeps.md`).
- `next_review_at`: aware ISO timestamp; when it passes a wake fires.
- `cadence_seconds` (300 to 604800): fixed re-arm grid; missed slots are not replayed.
- `due_at`: a hard deadline. It escalates as it nears and nudges while overdue, for
  about a week, then stops.
- `notify_when`: the user's report rule ("only if the price drops"). It filters what
  reaches the conversation; it never widens scope or skips approvals.
- `signal` / `signal_at`: the last observation, written with `report_signal`. A
  changed signal wakes the watch; an identical one dedupes, so "nothing changed" stays
  silent.
- `execution_host`: `mac` is work only the Mac can do (local files, its screen); it
  blocks while the Mac is offline. Anything a browser can do stays `cloud`:
  `workspace_browser` uses the Mac's logged-in tab online and its own browser offline.

A blocked or waiting watch does not fire, deadline included. Quiet hours defer wakes.

## When a scheduled wake arrives

It is the user's approved contract firing, so it skips the opportunity appraiser. Run
the check with real tools inside the recorded scope and `execution_host`, then:

1. `report_signal` with what you observed so repeats dedupe.
2. Tell the user only if `notify_when` says it matters or a decision is needed.
   Otherwise reply exactly `[SILENT]`.
3. `finish_task` when the watch is satisfied, cancelled or blocked. Moving
   `next_review_at` later is allowed; a cadence re-arms itself.
4. `resolve` the event so the next wake can claim.

For a `[Companion open loop check]`: check the real signal (connector first,
`workspace_browser` when none is installed). If it resolved, `finish_task` with the
outcome and fold it into the next sweep unless it unblocks the user now. If it is
still waiting past `due_at`, draft the follow-up and ask before sending; a loop never
nudges on its own, and only once per checkpoint. Track a loop only when the user
asked, or offer it when they clearly sent something awaiting a response.

The user's direct surface is `/watch`: `list`, `show <id>`, `approve <id>`, `snooze <id>`, `dismiss <id>`,
`add {json}`, `pause <id>`, `resume <id>`, `done <id>`, `cancel <id>` and
`signal <id> <text>`. A collector (a Hermes `cronjob`, or the woken primary) performs
the check and writes `report_signal`; the observer wakes only on a real change.
