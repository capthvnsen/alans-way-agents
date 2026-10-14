# Proactive check-ins

Your primary Telegram bot reaches out on its own when you've gone quiet, like a
proactive employee: it does something useful and tells you, suggests something it
could do, or asks a good question. It writes like a person texting you: one to
three short sentences about one specific open thread, with no headings and no
talk of timers or check-ins. If nothing is worth saying it stays silent.

## When it checks in

- After **2 hours** of quiet in the bound chat (from you or the bot).
- Each check-in you don't answer doubles the next wait: about 2h, 6h, 14h, 1.3
  days, 2.6 days, 5.3 days, 10.6 days, then roughly weekly. Replying resets it.
- Only between **8:00 and 22:00 in your timezone**, not the server's. Setup reads
  your timezone from your computer; if it can't, the bot asks you.
- Never mid-conversation or while the bot is working in the bound chat.

It never sends external messages, spends money, changes credentials or
permissions, touches production, or deletes anything without asking.

## Tune it by talking to your bot

| Say | Effect |
| --- | --- |
| "Check in less" | Wait 4h instead of 2h |
| "Quiet until Monday" | Pause until then |
| "Stop checking in" | Pause |
| "I'm in Tokyo this week" | Use Asia/Tokyo for check-in hours |
| "Not before 9am" | Start the day at 9:00 |
| "When will you check in next?" | Shows the next check-in time |
| "Stop the morning brief" | Turns the morning brief off |

To check in more, start again, widen the hours or turn on the morning brief, send
`/proactivity more`, `/proactivity resume`, `/proactivity hours 9-21` or
`/proactivity brief on` yourself: the bot's tool can only make check-ins
quieter, because anything the model reads can be prompt-injected. Only the
bound chat can change these.

Want a check-in right now, say to see what the bot could take on? Send
`/proactivity now` from the bound chat. It runs one check-in immediately, even
when paused or outside your hours, and tells the bot not to stay silent. It
doesn't change your settings; the next automatic check-in is measured from this
reply. Only you can send it: the bot's tool can't.

## Morning brief

Off unless you turn it on with `/proactivity brief on` (or `hermes proactivity
set --settings '{"morning_brief": true}'`). Once a day, a few minutes after your
active hours start (8:00 to 8:20 by default, your timezone), the bot sends a
short brief: what it did or learned since you last talked, anything
time-sensitive today (from your calendar or email, read-only, if it has those
tools), anything that failed, and up to three decisions it needs from you as
numbered questions. If there's nothing, it stays silent.

It skips the day if you were chatting in the two hours before. If the bot is
busy, paused or offline at brief time, it still sends once that clears, up to two
hours late, then gives up for the day. It doesn't count as a check-in, so it
doesn't lengthen the doubling wait, but the next check-in is measured from the
brief. So once unanswered check-ins have stretched the wait past a day, the brief
is the one message you get each morning. `/proactivity status` shows when the
next one is due and `/proactivity brief off` stops it.

## Setup

`setup.sh` binds the primary bot (pick its Telegram chat from the list) and sets
your timezone. To do it by hand:

```sh
hermes plugins enable alans-way
hermes config set plugins.entries.alans-way.allow_gateway_injection true
hermes tools enable proactivity --platform telegram
hermes proactivity bind --session-key '<telegram dm session key>' --timezone America/Chicago
hermes gateway restart
hermes proactivity status
```

On a host where supervisord runs the gateway, `hermes gateway restart` does
not reach it: drain it through the supervisor instead — `supervisorctl signal
USR1 <program>` on the program whose command runs `hermes gateway run`, then
wait for the new pid. `supervisorctl restart`/`stop` escalates SIGTERM to
SIGKILL after `stopwaitsecs` and can corrupt `state.db` mid-checkpoint.

`hermes proactivity set --settings '{"base_minutes": 2}'` makes a test check-in
arrive two minutes after you stop chatting. Set it back with
`'{"level": "normal"}'`.

## Weekly time-saved report

Optional. A plain Hermes cron job, separate from check-ins, that sends a short
weekly recap of what the bot did and roughly how much time it saved you:

```sh
hermes cron create '0 18 * * 0' --name weekly-time-saved --deliver telegram \
  "Write my weekly time-saved report. Use session_search and memory to find what you actually did for me in the last 7 days: tasks finished, messages drafted, research done, problems fixed. Skip chatter and anything you only offered or planned. List each item on one line with your estimate of the minutes it saved me compared with doing it by hand, then a total in hours. Keep estimates conservative and say they are estimates. Under 15 lines. If you did nothing useful this week, reply exactly [SILENT]."
```

It runs Sundays at 18:00 in the configured Hermes timezone (or the server's
local time), and goes to your Telegram home channel. The minutes are the
bot's estimates, not measurements. `hermes cron list` shows the job's ID;
`hermes cron run <id>` queues one for the next tick and `hermes
cron remove <id>` turns it off.

## How it works

The plugin's `pre_llm_call` and `post_llm_call` hooks note when the bound chat
was last active and whether the bot is mid-turn. A 60-second timer, started
only when the gateway connects Telegram, checks whether a check-in or brief is
due. When one is, it injects one internal prompt into that chat, and the bot decides what
to do with its own memory and tools. A `[SILENT]` reply is never delivered.
State lives in Hermes' plugin state (`ctx.state`).

Upgrading from 0.6 keeps your bound chat, timezone and pause. Watches, sweeps
and `/watch` are gone.

## Cross-bot export and receiver (stage 2)

Optional and **off by default**. Each enrolled profile exports only completed
exchanges from its locally bound owner Telegram DM. Groups, other chats, cron,
check-ins, morning briefs, child turns and imported cross-bot turns are excluded.
There is no historical backfill. Only the user message and final assistant text
are exported; attachments, reasoning, tool history and configuration files are
not collected. All eligible bots may participate; enrollment beyond 16 profiles
produces a clear error. Snapshot aggregation is deferred to the primary-reader stage.

This stage adds the target queue and receiver, with an internal/test enqueue
helper. **Primary dispatch is disabled**: there is no model ask tool, snapshot
reader or automatic primary selection. Secondary bots still do not run spontaneous
check-ins. An enabled receiver can schedule a queued read/research/draft request
in its own existing bound Telegram DM through public Hermes injection. The target
needs operator-configured `allow_gateway_injection: true`; missing routes or
permission can prevent delivery even after scheduling.

An operator configures each profile through Hermes' CLI. Use the **same explicit
absolute directory and primary designation** in every participating profile:

```sh
hermes -p <profile> config set plugins.entries.alans-way.settings.cross_bot.primary <primary-profile>
hermes -p <profile> config set plugins.entries.alans-way.settings.cross_bot.shared_root /absolute/gateway/companion/alans-way-cross-bot/v1
hermes -p <profile> proactivity bind --session-key 'agent:<profile>:telegram:dm:<owner-chat-id>'
hermes -p <profile> tools enable proactivity --platform telegram
```

Select an existing owner DM route for that profile; `default`/`custom` uses
`agent:main`, and a profile literally named `main` uses `agent:main~`.
Hermes' public binding hooks do not expose a DM's persisted receiving-bot identity.
The receiver therefore refuses enabled Telegram `profile_routes` into this profile
when `bot_profile` names another bot (including the implicit default bot for a
named profile). This conservative check covers the entire profile, even routes
for another chat. It reads launch-gateway routing policy through public configuration
and home-scope APIs; unavailable policy fails closed. Routes explicitly owned by
this bot, disabled routes and other platforms do not prevent receiving. Opt-out
remains available from the bound DM even when route verification fails. Collector
checks use the exact bound session key, never just the human's ID. Shared-root
changes take effect on plugin reload under the normal operator update/drain
procedure. Set the primary before the root when creating a store; all profiles
must match its recorded designation. Changing the designation requires a fresh shared root to
replace the existing store's designation. No installer changes or automatic enrollment are added.
The approved future live test uses `alansway` as primary and `utd` as target.

From each bot's bound owner DM, send:

- `/proactivity cross on` to enable that bot's exports and receiver.
- `/proactivity cross off` to disable sharing/receiving, cancel its receiver and delete its digest and pending asks.
- `/proactivity cross status` to show enrollment and exchange count, with
  “Primary dispatch disabled.” A body-free `sent` status means injection was
  scheduled, never proof of delivery or completion. No message bodies or DM addresses appear in status.

After activation, the model's `proactivity` tool can read `cross_status` or set
`cross_bot_enabled` to `false`. It can only turn this feature off; enabling,
rebinding or expanding scope requires the operator. A refused enable returns
`/proactivity cross on`, like other settings that would widen proactivity.

The plugin-owned POSIX store uses owner-only directories (0700) and files (0600),
checked directory handles, symlink/ownership checks, a bounded lock and atomic
replacement. Unsafe permissions, invalid schemas or mismatched primary settings
make exports unavailable. Custom shared roots are supported; the plugin never
infers one from the launch profile's environment or accesses Hermes' session DB.
Presence includes heartbeat, enabled/bound booleans, profile identity/generation
and captured timezone/window/pause/busy eligibility; it contains no DM address.
Before every claim, the scoped receiver rereads its owning profile's live binding
and pause/timezone/hours settings under the owner and shared-store locks. Commands,
tools and CLI changes apply to the next claim without reconnect/reload. A timer
outside its inherited owning scope refuses to claim; it never reads another
profile's state. Primary
snapshot freshness selection belongs to stage 3.

Each digest holds at most the last **four exchanges**, at most **2 KiB serialized**,
with a **24-hour TTL per exchange**. Sanitization runs before UTF-8 truncation;
credential-bearing lines, private-key blocks, recognizable tokens and credential
URLs are omitted. Failure drops the whole exchange. Operators may add literal
line-omission terms using the plugin setting `cross_bot.redact_terms` (up to 32
terms, 128 characters each). Arbitrary unlabeled secrets are not guaranteed
detectable, so avoid sharing sensitive material even with export enabled.

Activation is persisted as `cross_bot.enabled` through Hermes' public plugin
settings API. With no root or while off, cross-bot hooks do no state/store I/O,
start no task and add no model tool. The primary schema and prompts stay at their
base values. Off cancels the task, removes the extra tool surface and purges even
an unparseable digest or queued ask after restart.

Pruning runs on explicitly activated startup, before store reads/writes and every
60 seconds through Hermes' supervised profile-scoped task while Telegram is
connected. Expired text is never exported; offline files can physically remain
until an activated profile prunes them. Interrupted
atomic-write temporary files are removed under the store lock. Body-free hashed
turn IDs prevent duplicates for 48 hours (512 per profile; overflow refuses new
exports until expiry). Counts and IDs survive restart; turning off does not
remove these body-free records. Off revokes pending exports with an enrollment
generation change, so a turn staged before off cannot publish after re-enabling.

Queued asks contain at most 800 characters, expire after **two hours**, have depth
one and mode `read_only` or `draft_only`. At most one is pending per target and 64
across the gateway. The internal helper spends body-free attempt/check-in hashes
before enqueue: four attempts per rolling day gateway-wide, two per target, with
60-minute target spacing. These records survive restart for 48 hours. Receivers
wait for busy, paused or out-of-hours targets until expiry; an unbound target drops
the ask. Claims recheck enrollment/generation under the store lock and durably
delete the body **before injection**, so a crash can lose an ask but cannot replay
it. There is no receipt store, completion tracking or result polling.

Imported task text is untrusted and grants no routing or approval. The receiver
supplies its own captured key and a correlated prompt marker. Replies retain the
target's voice and show one “Primary asked me to …” attribution line without
removing task content. Hermes silence markers pass through unchanged. Restrictions
follow the immutable scheduled session key through rebinding and opt-out, including
other turns in that session while an import is pending or active. An expired or
uncorrelatable guard blocks tools rather than granting ordinary-turn authority;
only a matching session-end hook clears a correlated import. Missing hook IDs may
leave receiving blocked until host correlation is restored or the plugin reloads.
Imported turns cannot enter digests or chain into another bot. Their tool hook blocks
cross-bot asks, messaging/delegation, scheduler creation, general terminal/code
execution, desktop actions and unknown connectors. Only reviewed web/session and
workspace-browser reads plus existing gated workspace-browser actions are allowed;
consequential work is prepared for the human's existing approval path. Browser
commit, CAPTCHA and ownership gates are unchanged. Meaning and browser action
recognition remain model/gate policy, not universal read-only enforcement.

Expiry and opt-out apply to this plugin's digests and queued bodies. They do not
erase existing Hermes history, Honcho/memory-provider records or model-provider
retention. See the [staged design](design/cross-bot-proactivity.md).
