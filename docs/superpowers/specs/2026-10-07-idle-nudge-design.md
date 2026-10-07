# Idle nudge: proactivity rewrite

Date: 2026-10-07. Status: approved in conversation, awaiting spec review.

## Goal

The bound primary bot should feel like a proactive employee. When the user and
the bot have been quiet for a while, during the user's waking hours, the bot
reaches out on its own: it does something useful, offers to, or asks a good
question. It must be simple, cheap, and tunable by talking to the bot.

Public open-source plugin: nothing user-specific is hard-coded.

## What gets replaced

Today's proactivity stack (`proactive_*.py`, about 2,200 lines; about 990 lines of
`__init__.py`; the `proactive-primary` skill and references; `/watch`; the ledger,
watches, loops, sweeps, the Kanban observer and the LLM appraiser) is deleted.
On the author's install it holds 56 stuck wakes and has resolved 3.

Untouched: `workspace-router.cjs`, mac-watch, `alans-way-computer/`, the
`workspace-operations` and `workspace-setup` skills (except for references to the
deleted parts), and the browser and host parts of `setup.sh` and
`setup-workspace.sh`.

## Behavior

### When a nudge is due

One rule, evaluated about every 60 seconds inside the gateway process:

```
last_activity = newest real message in the bound session (user or bot)
n             = nudges sent since the user's last real message
wait          = min(base * 2**n, 7 days)
due_at        = last_activity + wait, moved forward to the next active window
```

- `base` defaults to 120 minutes. The level presets are `less` = 240,
  `normal` = 120 and `more` = 60.
- With the default base, an ignored bot reaches out at about 2h, 6h, 14h,
  1.3 days, 2.6 days, 5.3 days and 10.6 days, then weekly. The same doubling
  gives both the back-off and the "come back after a few days or a week"
  re-engagement nudge. There is no separate feature for that.
- A real user message resets `n` to 0.
- **Active window:** `active_start` to `active_end` (default 08:00 to 22:00) in
  the **user's** timezone. Never the server's: the bot may live in a data
  center while the user is somewhere else. A nudge that comes due outside the
  window waits for the next `active_start`.
- **Not mid-task:** any recent message from the user or the bot pushes
  `last_activity` forward, so an active conversation or a working bot never
  gets nudged.
- "Real message" excludes the plugin's own injected prompts. Real Telegram
  turns carry a `platform_message_id`; injected ones don't. Verify this on a
  live gateway before relying on it.
- `paused_until` (an aware ISO timestamp, or `off` for indefinitely) suppresses
  nudges.

### What the bot does when nudged

The plugin calls `ctx.inject_message(prompt, session_key=bound_key)`. The
prompt is roughly:

> [Proactive check-in] It has been {elapsed} since you and {user} last talked
> ({local time and weekday for the user}). Like a thoughtful employee, pick
> exactly one: (a) do one safe, reversible thing that moves their goals forward,
> then report briefly; (b) suggest something specific you could do for them;
> (c) ask one useful question. Use your memory of their goals and open threads.
> Never send external messages, spend money, change credentials or permissions,
> touch production or delete anything without asking. Don't repeat a recent
> check-in. If nothing is worth saying, reply exactly `[SILENT]`.

- Hermes' gateway already drops `[SILENT]` replies from delivery
  (`gateway/response_filters.py`). A silent reply still counts as a nudge for
  the back-off.
- No appraiser model, no ledger, no task tracking. The bot's own memory and
  tools decide what's useful.
- The injected message carries `internal=True` and is re-authorized by the
  gateway. `plugins.entries.alans-way.allow_gateway_injection: true` is still
  required.

### Customizing by chat

One tool, `proactivity`, in the `proactivity` toolset:

| Action | Effect |
| --- | --- |
| `status` | Current settings, next due time in the user's timezone, nudges since the last reply |
| `set` | Any of `level`, `base_minutes`, `active_start`, `active_end`, `timezone`, `paused_until` |

- The tool description teaches the mapping, for example: "check in less" sets
  `level=less`, "quiet till Monday" sets `paused_until`, "stop checking in" sets
  `paused_until=off`, "I'm in Tokyo this week" sets `timezone=Asia/Tokyo`.
- `set` validates every field (IANA timezone, hours 0-23, base 15 to 1440
  minutes from chat; the operator CLI `set` accepts down to 1 minute for
  testing) and works only from the bound conversation. Other sessions get
  `status` only.
- The bot reads `status` back before confirming a change to the user.

### Setup and binding

- Keep the CLI shape setup.sh already drives: `hermes proactivity bind
  --session-key K --timezone TZ`, `status`, and `set`.
- Binding still validates the key against `state.db` `gateway_routing` (or the
  `sessions.json` mirror) as a Telegram DM. Reuse the existing helper logic.
- setup.sh keeps its existing timezone detection: ask the user's computer over
  the companion ssh link, else prompt the user. It no longer falls back to a
  default zone silently.
- State (`session_key`, settings, `n`, `last_nudge_at`) lives in
  `$HERMES_HOME/companion/proactivity/state.json` (profile-scoped, written with
  the existing `write_private_json`).
- One-time import: if the old `companion/proactivity/proactivity.sqlite3` holds
  a bound key and timezone, copy them over so upgraders keep working. Leave the
  old file in place.

### Gateway-only execution

`register()` also runs in CLI and doctor processes, and those must never send
nudges. Every tick checks the plugin manager: no CLI REPL attached, and a live
gateway injector published (`has_gateway_message_injector`). Only a gateway
sets that, so the `gateway:startup` hook and its marker are deleted, and setup
removes the old installed hook. These are private host attributes, so any
surprise fails closed: no nudge.

## Files (target)

- `alans-way/proactivity.py`: settings, the `due_at` math, the tick loop,
  injection, the tool and the CLI. About 250 lines.
- `alans-way/__init__.py`: `register()` wires up proactivity and the two
  workspace skills.
- `gateway_guard.py`: keep only what's still used.
- `tests/test_proactivity.py`: the due-time math (doubling, 7-day cap, window
  deferral, user timezone different from the server, DST transitions, pause,
  reset on reply), tool permission (bound chat only), validation, the import.
- Delete the old proactive tests. Update `test_setup_sh.py` and
  `test_workspace_mac.py` where they cover deleted code.
- Docs: rewrite `docs/proactivity.md` as a short user guide. Update the README,
  SECURITY, CONTRIBUTING and the `workspace-setup` skill references.
- `plugin.yaml`: version bump, `provides_tools: proactivity`.

## Acceptance (live on the author's VPS Hermes)

1. With `base_minutes` set temporarily to 2 via the operator CLI, a real nudge
   reaches the bound Telegram chat within about 3 minutes of silence.
2. Ignored, the next nudge waits about twice as long.
3. A user reply resets the back-off.
4. Telling the bot "check in less" changes `level` (verified via `status`), and
   "quiet till tomorrow" pauses.
5. Outside the user's active window nothing is sent. Verify by setting a
   timezone where it is currently night.
6. A `[SILENT]` choice is not delivered and still advances the back-off.
7. CLI and doctor runs never inject.
8. The full test suite passes.

## Phase 2 (separate PR, after phase 1 ships)

1. Fix: non-root Linux installs never return from the VPS browser to the user's
   computer, because no watcher is installed.
2. Trim `workspace-operations/SKILL.md` (282 lines) to the essentials: no
   repeated rules, no unshipped handoff feature.
3. Retire the legacy single-page resume path in `workspace-router.cjs` and keep
   mirror restore.
4. Cleanup: stale wrappers, `deploy/` examples and pre-rename migration code;
   merge the three `--verify` paths; replace hand-written YAML edits with
   `hermes config` and `hermes mcp` commands where they exist.

## Process

- Implementation and review run as Devin SWE-2 sessions (`devin -p --model
  swe-2-high`), coordinated by Claude Code.
- A self-paced `/loop` runs build, live test, review and refine until the
  acceptance list passes.
