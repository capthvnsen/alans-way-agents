---
name: web-errands
description: Run a web errand end to end in the workspace browser — shopping and cart comparison, booking and travel, job applications, form, permit and civic-portal filing, cancellations and refunds, and document-driven claims. Research, stage, commit through the approval gate, verify the confirmation, and report a receipt. Use when the user asks you to buy, book, apply, file, cancel, claim, or keep a price or status check running.
---

# Web errands

A web errand is real work on real sites in the user's name: buy, book,
apply, file, cancel, claim. Every errand runs the same loop — research,
stage, commit, verify, report — and the per-kind recipes live in
[references/recipes.md](references/recipes.md). Load it once the errand's
kind is clear.

Before page work, read [workspace-operations](../workspace-operations/SKILL.md)
for tool dispatch, tab ownership, reply-driven actions, batching and the
browser authorization policy. This skill uses its `cua_alans_way_*` tools;
native-app steps use its approval-gated `computer_use` path.

## Pick the host

`cua_alans_way_open` takes an optional `host`. Omit it for normal work,
including errands that continue while the user is away: the router starts
on the user's computer when it is reachable and uses the VM's own Workspace
browser when it is not. Pass `host:"vm"` only when the user explicitly asks
for your own computer or the VM, or the router reports the user's computer
unreachable. Login, CAPTCHA, approval and uncertain-action errors are not
outages and never switch browsers. Hermes's native browser is not a third tier.
The user's computer shares their Alan's Workspace browser profile; the VM
keeps its own profile, so ask the user rather than working past a login wall.
Finish an already-running VM task there even when the user's computer returns.
If the computer drops mid-errand, follow workspace-operations' continuation notice and new tab
id. Re-read the staged details on that host before committing. If a
commit's outcome is uncertain, inspect the page before doing anything
that could repeat it; a host switch is not evidence that it failed.

## Compare before you commit

When price matters, check at least two sources and compare the real
total — price plus shipping, tax, fees and the delivery or travel dates —
never the headline number. Tell the user the comparison in chat before
requesting approval. Put the deciding facts — the chosen source, the total
with fees and shipping, and the runner-up if it matters — in
`commit.summary` (at most 200 characters) so they appear on the approval
card.

For a used or marketplace listing, open its photos and inspect them on a
screenshot before pricing it: haze or fungus in a lens, scratches,
missing parts, a worn sole. Say what you saw and let the condition set
the offer or the go/no-go — never appraise from the title alone.

## Stage, then commit

Drive the flow up to the final commit control and stop there. Before the
commit call, echo the decision back to the user in chat, read off the
page and not from memory: the dates, the party size, the total with fees
and shipping, and the merchant, seller, agency or recipient getting it.
Then run the commit click as a `cua_alans_way_action` carrying a `commit`
object: `{kind: purchase|booking|send|post|submit|delete|account_change,
summary, amount?, currency?, counterparty?}`. `kind` and `summary` are
required; the summary is 1–200 characters. The optional amount, currency
and counterparty are strings; include the final total and recipient when
relevant. The summary and total are what the user approves in Telegram,
so make them accurate; one `commit` covers the whole staged action.
Never supply `approval`: the router adds its own request-bound receipt
only after the user approves.

Commit-name examples: "Place order", "Easy Apply", "Submit application".
These match the shared name patterns in
[scripts/commit-patterns.json](../../scripts/commit-patterns.json).
Every consequential action needs `commit`, even if its label is unusual;
follow the [browser authorization policy](../workspace-operations/SKILL.md#browser-authorization-policy)
for the full gate rules. `commit_required` means the call did not run:
add the accurate commit object and request approval. `commit_invalid`
means fix the object first. `snapshot_required` means read a full current
snapshot and use its fresh refs; follow the latest reply's names and refs.

`declined`, `approval_timeout` and
`approval_unavailable` all mean it did not run: do not retry it, do not
reach the same result another way, and never work around the gate — say
what is staged and let the user finish. In a cron job nobody is there to
approve, so a scheduled errand stages everything, reports where it
stopped, and leaves the last click to the user. `host_changed` and
`page_changed` also mean a pending approval did not run: re-read the page
and ask for fresh approval after confirming the staged decision. A lost
reply after an approved action can have an uncertain outcome; verify it
before repeating anything.

## The walls you hand back

For sign-in requests, including just opening a sign-in page, use the
[sign-in handback](../workspace-operations/SKILL.md#sign-in-handback) before reporting it ready.

At a sign-in or 2FA prompt, or a card-number field, hand the tab to the
human with `action:"release"`, `reason:"login"`, `reason:"two_factor"`
or `reason:"payment_details"` respectively; `review` and `other` cover
other human-only steps. Include a plain-text `note` of at most 140
characters naming the site and what you need, and send one chat message.
On the user's computer and on the VM alike, a reasoned release marks the
tab `awaiting_human` and refuses bot input until the person presses
Give back in Alan's Workspace or 30 minutes pass. The app shows a
banner and a notification for the handback. Read the current tab state
and fresh epoch on `human_returned`.

For a CAPTCHA, follow [CAPTCHA handback](../workspace-operations/SKILL.md#when-a-site-shows-a-captcha).
Release a needed widget with `{action:"release", reason:"captcha"}` and
a note; a blocking challenge is handed back automatically. A
`challenge_present` refusal calls for handback, never a commit approval.
The shared flow covers the safe viewer link, waiting via tab status,
automatic return, fresh epochs and backoff; follow it when resuming.

Never solve a CAPTCHA. Never ask the user to read a card number aloud or
paste it in chat, and never store a card number — not in memory, not in a
file, not in a message.

## Verify, then report

An approval is not a confirmation. After the commit runs, read the page
it lands on: capture the order, booking or reference number, and take a
`cua_alans_way_screenshot` of the confirmation. Then send one short
Telegram receipt — counterparty, total, confirmation number, and what
happens next: the delivery date, the cancellation deadline, or the
follow-up check you set. If the click ran but the page shows an error, a
held order, or a price that moved, report that instead; never claim
success the page did not show.

## A watch is a cron job

A price, restock, ticket, refund-status or appointment watch is a Hermes
cron job, not a loop inside this conversation: create it with
`cronjob_manage` (`create`, and later `update`, `pause` or `remove`; list
jobs before managing one by its id), or
ask the operator for a `hermes cron` entry. Save a watch only when the user asks
or accepts your offer. Set `attach_to_session` true and omit `deliver` so
results return to the originating chat and replies can continue there;
each check still runs in a fresh session. For an operator-created entry,
preserve that chat as the delivery destination. Poll
no more often than every 10 minutes to avoid rate limits or suspension,
and back off when a check fails.
Give the job a self-contained prompt with the URL, constraints and stop
conditions: stop on success, and stop after three consecutive failures;
report either way. Add `"continuity": true` so each run sees its own
previous completed output. Have the first check report a compact baseline;
continuity skips silent outputs. On later checks, compare the requested condition
with that output and reply exactly `[SILENT]` unless something meaningful
changed, a check failed or the target was reached.

Add `monitor` only for a safe, read-only deterministic probe that
matches the condition the user asked to watch. For example,
`"monitor": "https://example.com/status.json"` fits a watch on that endpoint's
stable status response. A script path is also supported, under the same
path restrictions as a cron script. Its output must contain only the relevant
state, with no timestamps or other changing noise. If the probe cannot capture
the requested condition reliably, omit `monitor` and let the scheduled check
compare results. The first tick runs the agent to establish a baseline;
unchanged output skips the agent and delivery, while changed output gives
the agent a diff to assess. A source failure is an error, not a change or
success; preserve failure reporting and backoff.

Cron scheduling tools are disabled within cron runs by
default; arrange the pause/remove with the operator unless they have
enabled `cron.allow_agent_scheduling: true`. A job must not assume it can
stop itself.
A cron run has no one to answer an approval, so a watch that hits its
target stages the result and asks the user to finish it.
