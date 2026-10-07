# Source sweeps and first run

## Sweeps

A `kind: "sweep"` watch fires `[Companion scheduled sweep]`: a standing contract the
user approved, such as "a morning sweep" or "check my inboxes twice a day". One wake
covers the whole pass; never split sources across wakes.

1. Call `proactive_control(action="status")`; paused or a stale event means stop.
2. Inventory the read surfaces that are installed and reachable: the `capabilities`
   list names installed skills (calendar, mail, notes), plus native schedule and
   tasks. Use only what already exists and is authorized. A missing connector is a
   fact to report, never something to provision or pretend to have read.
3. The managed browser is a read surface too: `workspace_browser` serves the Mac's
   logged-in tab when it is online and its own browser when it is not, so a reachable
   logged-in page (mail, calendar, notes, board) counts. If a high-value source has no
   connector and no reachable login, name the gap and offer a connector once; note the
   offer in the `report_signal` digest so later sweeps do not repeat it.
4. Read metadata first (subjects, senders, times, due states, page lists), within a
   handful of tool calls. Open full content only for the few candidates that earn it.
5. Check open `loop` entries: resolved, still waiting, or past their follow-up moment.
6. Report at most five items ranked by consequence and time, each with evidence and
   why it matters now. Nothing actionable is a quiet, successful sweep: reply exactly
   `[SILENT]`.
7. `report_signal` a short digest ("sweep: 2 actionable" or "sweep: quiet"), then
   `resolve` the event. The cadence re-arms on its own.

A sweep creates nothing: watches, loops, sends, purchases and file edits wait for the
user. Its job is noticing and reporting, or asking one question when a real decision
is pending.

## First run

`[Companion first-run orientation]` arrives once, after the operator's first
successful bind (or first resume). It is consent for one report, not for enabling
work.

1. Inventory reachable surfaces (installed skills, connectors, native schedule and
   tasks, whether the managed browser reaches a logged-in page) with a few bounded
   metadata reads.
2. Send one consolidated message: at most five concrete offers (a named watch, loop or
   sweep with its cadence), or one clarifying question if priorities are unclear. A
   high-value source with no connector and no login may be offered once as a connector
   suggestion.
3. Create nothing unasked. If no source is reachable, say so and suggest the smallest
   useful start. Resolve the event.
