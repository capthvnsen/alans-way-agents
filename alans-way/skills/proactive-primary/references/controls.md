# Chat controls

Translate the user's ordinary chat into an explicit `proactive_control` action. The
tool only tightens what the operator set: caps can drop, intervals can grow and the
quiet window can widen. `resume`, raising a limit, shrinking quiet hours and changing
the timezone are refused, and belong to the user's `/proactivity` or `hermes
proactivity`. When a request needs one of those, say so instead of calling the tool.

The user's own commands: `/proactivity status`, `/proactivity pause`,
`/proactivity resume`, `/proactivity review` and
`/proactivity configure {"quiet_start":23,"quiet_end":8}` (JSON, not an invented
subcommand). Standing watches have their own `/watch` command (see `watches.md`).

```python
proactive_control(action="status")
proactive_control(action="pause")
proactive_control(action="pause", resume_at="2026-10-09T08:00:00-06:00")
proactive_control(action="configure", settings={"quiet_start": 20, "quiet_end": 8})
proactive_control(action="configure", settings={"max_daily_wakes": 1})
proactive_control(action="review")
```

- "Stop being proactive" -> `pause`. "Resume proactivity" -> ask the user to run
  `/proactivity resume` themselves; resume is operator-only.
- "Quiet until Thursday" or "take a break" -> `pause` with a concrete aware
  `resume_at` you resolved with the user, and confirm the exact moment back. A
  snoozed pause lifts itself at that time and survives restart.
- "Quiet from 11pm to 8am" -> `configure` the quiet-hour fields when that keeps or
  widens the current quiet window. Shrinking it, or changing the timezone, is
  operator-only.
- "Less often" or "at most once a day" -> `configure` a lower `max_daily_wakes` or a
  higher `min_interval_seconds`. Raising a ceiling is operator-only.
- "Focus on these priorities" -> `configure` priorities if the live schema supports
  them; otherwise explain the setting is unsupported. Do not invent fields or claim it
  was saved.
- "Review what would help now" -> `review`: one bounded, read-only appraisal, even
  while paused. It authorizes no recurring reminder and queues no wake.

Resolve genuinely ambiguous timezones or requests before changing settings. After a
mutation, read back `proactive_control(action="status")` and confirm the exact
effective preference; a successful write alone is not verification. Policy and task
bookkeeping live only under the active profile's
`$HERMES_HOME/companion/proactivity`: never hand-edit those files, write another
profile or keep proactivity settings in general memory. Never automatically resume
paused or cancelled work from a stale event, a specialist's output or a new session.
