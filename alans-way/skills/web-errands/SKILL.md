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

All page work uses the `cua_alans_way_*` tools under the rules in the
workspace-operations skill: open a tab you own, act from each reply's
`effect`, batch steps, snapshot only for refs no reply gave you. A step
that only exists inside a native app uses `computer_use`, which asks the
user per action. Nothing else drives a browser or a desktop.

## Pick the host

`cua_alans_way_open` takes an optional `host`. Run the errand on the
user's computer when their own session matters — a logged-in account, a
cart they built, member pricing, a checkout that needs their saved
details. That tab shares the user's real browser profile, so what you see
is what they would see. Run it on the VPS (`host:"vm"`) when their
computer is asleep or the errand must finish while they are away; the VPS
browser keeps its own profile, so expect to sign in once per site — ask
the user rather than working past a login wall. If the computer drops
mid-errand the connector carries the page to the VPS and names the new
tab id: keep working in it, and do not mark the errand blocked just
because the host changed.

## Compare before you commit

When price matters, check at least two sources and compare the real
total — price plus shipping, tax, fees and the delivery or travel dates —
never the headline number. The echo before a commit says what each source
costs, so the approval shows the comparison, not just the winner.

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
summary, amount, currency, counterparty}`. The summary and total are what
the user approves in Telegram, so make them accurate; one `commit` covers
the whole staged action. `declined`, `approval_timeout` and
`approval_unavailable` all mean it did not run: do not retry it, do not
reach the same result another way, and never work around the gate — say
what is staged and let the user finish. In a cron job nobody is there to
approve, so a scheduled errand stages everything, reports where it
stopped, and leaves the last click to the user.

## The walls you hand back

At a CAPTCHA, a sign-in or 2FA prompt, or a card-number field, hand the
tab to the human instead of working past it:
`{action:"release", reason:"captcha"}` — or `login`, `two_factor`,
`payment_details`, `review`, `other` — with a short `note` naming the
site and what you need, plus one chat message so the user knows to look.
A reasoned release marks the tab `awaiting_human` and your calls on it
are refused until the human gives it back; where a release cannot carry a
reason yet, a plain `release` still hands the tab over — the chat message
says why either way.

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
`cronjob_manage` (`create`, and later `update`, `pause` or `remove`), or
ask the operator for a `hermes cron` entry, delivering to Telegram. Poll
no more often than every 10 minutes — tighter polling is what gets
accounts rate-limited or suspended — and back off when a check fails.
Give the job its stop conditions in the prompt: stop on success, and stop
after a few consecutive failures; report either way. A cron run has no
one to answer an approval, so a watch that hits its target stages the
result and asks the user to finish it.
