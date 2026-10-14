---
name: integrations
description: "Connect email, calendar, contacts, files, tasks, home or social accounts from Telegram; use when a task needs an integration that isn't connected."
---

# Connect your stuff

Check access before promising a task that depends on an account. Reuse Hermes'
installed skills and catalog connectors first. This skill supplies recipes,
no new service, account, OAuth callback handler or Python module.

## Choose one route

Tool: `skills_list`. Tool: `skill_view`. Discover the installed skill by name
and load it; locate its actual script path rather than assuming the VM's layout.
If the native route is missing or incompatible, report that before proceeding.

| Need | Read only the matching recipe |
|---|---|
| Gmail, Google Calendar, Contacts, Drive, Docs or Sheets | [Hermes Google Workspace](references/hermes-native.md#recipe-google-workspace) |
| Other IMAP/SMTP mailbox | [Hermes Himalaya](references/hermes-native.md#recipe-himalaya) |
| Existing home automation | [Official Home Assistant plugin](references/hermes-native.md#recipe-home-assistant) |
| Existing cross-session memory backend | [Honcho catalog provider](references/hermes-native.md#recipe-honcho) |
| X/Twitter | [Hermes xurl](references/hermes-native.md#recipe-x) |
| OneDrive, Dropbox, WebDAV, S3 or other cloud files beyond Google | [rclone](references/rclone.md) |
| Personal tasks with due dates and recurrence | [Taskwarrior](references/taskwarrior.md) |
| Mastodon account | [Mastodon.py](references/mastodon.md) |

For local notes/files, use Hermes' file tools or Obsidian skill; no account is
needed. Agent execution plans stay in Hermes' todo/Kanban tools. For another
named API (Notion, CRM, device service), check Hermes' installed/catalog offerings
and their compatibility, license, credential entry and read probe. An API name
is not a working connector. If none exists, say a specific adapter is needed;
offer an authorized browser task through [web errands](../web-errands/SKILL.md)
when the service has a usable UI. Do not install a generic all-account bridge.

## Is it connected?

Tool: `terminal`. Before promising access, and again before a scheduled run:

1. Establish the owning Hermes profile and terminal backend. Commands must reach
   that profile's VM toolbox, with its credential scope, never a sibling bot's
   home or the user's computer by accident. A sandbox must have explicitly
   authorized access; do not copy credentials into it to make a probe pass.
2. Check the installed connector/version without reading secrets. Run its
   recipe's read-only Verify command with a 30-second execution bound. A config
   file or binary presence is not a connection.
3. Prove the requested account and requested scope with a small read of the
   specific resource. Confirm account identity from safe metadata or the user's
   selected provider account; when a CLI cannot identify it, ask the user to
   confirm the selected account and a familiar resource. An empty successful
   list is connected; it does not mean events/files/messages exist.
4. Report connected, missing software, missing auth, revoked/expired auth,
   denied scope, unreachable service, wrong account, or unsupported connector.
   On failure stop the dependent task and give one concrete next step. Do not
   promise a send capability from an inbox read, or home control from a sensor.

Use plain Telegram wording: “I can't see your calendar yet — want to connect
Google? If your Google client is already set up, approval takes about a minute.
I'll send the sign-in link; you'll finish the private step outside this chat.”
For first-time Google setup, explain the Cloud project/client work first.
For a revoked connection: “Google stopped accepting this connection. Want to
authorize it again?” For an unreachable home: “I can't reach your home server
from here. Let's check its connection before I promise a temperature report.”

## Connect, verify, resume

Ask before installing any package, plugin, binary, dependency or build tool,
including a native skill's dependency installer. Tell the user which VM,
version, license, estimated footprint, data destination and permissions change.
Consent to connecting one account does not authorize every service or an update
to an existing installation. Preserve compatible installed versions; explain an
incompatible version and get consent for its replacement. Follow the recipe only
after the answer; silence leaves installation/auth changes pending.

Never put secrets in Telegram, the repository, tool output, memory or logs.
Do not read credential files or dump the environment. Public consent URLs and
device-code user codes intended for display are shareable; bearer tokens,
app passwords, client secrets and returned OAuth redirect codes are private.
Use the native credential mechanism or the owning profile's `.env` / existing
Hermes secret source, entered by the human in a user-controlled terminal or
supported masked UI outside the agent session. The browser login vault is for
origin-bound page filling, not a generic CLI token exporter. If phone secure
entry/callback access is unavailable, pause setup with a specific handback;
there is no invented Telegram Secure Form or universal device grant here.

After the recipe's probe succeeds, report the account, tested capability and
remaining limit, then resume the original task. API writes do not inherit the
browser commit gate: show the exact action (recipient, content, event times,
audience, file destination/overwrite or entity/service) and obtain explicit
approval before sending, posting, deleting, sharing or actuating. Keep any native
approval controls intact; never retry an ambiguous write. Reconcile its receipt
or read-back first. For UI writes use the existing web-errands commit flow.
If a commit returns `declined`, `approval_timeout` or `approval_unavailable`,
never complete it through another tool, including a CLI/library/API; tell the
user what remains staged and let them finish. A later API post needs its own
fresh explicit approval in the live conversation; switching routes does not
carry approval forward. Follow the
[browser authorization policy](../workspace-operations/SKILL.md#browser-authorization-policy).

## Recurring outcomes

Tool: `cronjob_manage`. Only schedule after a successful read probe and agreement
on timing/timezone, account/resource, scope and Telegram delivery. Use a
self-contained prompt naming the recipe, owning profile, read probe, failure
receipt and pause route; store no secrets in it. Before scheduling, select a
dedicated profile-local status file for that job's consecutive failure count;
persist only the count and safe error category, and reset it after a successful
read. Include that file's path in the prompt. If that state cannot be persisted
or no pause route is available, leave scheduling pending. After creation, record
the owning cron job ID/name and include them in the prompt and every failure
receipt. Confirm the scheduler's actual delivery route.

Each run checks access again. On auth/scope failure report reauthorization is
needed and request immediate pause; back off transient network failures and
request pause after three consecutive failures. Cron scheduling tools are
disabled within cron runs by default; never enable recursive scheduling silently.
Arrange pausing through the owner conversation using `cronjob_manage` after
listing/matching the owning job ID and profile, or an explicitly authorized,
profile-scoped CLI step: `hermes -p "$OWNER_PROFILE" cron pause "$JOB_ID"`.
Do not assume the scheduled agent can pause itself. Confirm paused status before
claiming it stopped; if neither route is available, report pause pending with
the job ID and owner action needed. Scheduled runs remain read-only: stage
proposed writes for approval in a live conversation. Do not use this skill to
add a second reminder daemon or cross-profile coordinator.

Sources: [default cron tool restrictions:414–434](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/cron/scheduler.py#L414),
[CLI pause command:156–157](https://github.com/NousResearch/hermes-agent/blob/1f6c02c07c697026888f1c66e634534fa2aae358/hermes_cli/subcommands/cron.py#L156).
