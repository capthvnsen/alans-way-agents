# Web-errand recipes

The shared rules are in the skill: pick the host, compare at least two
sources when price matters, stage up to the commit control, echo the
decision, commit through the gate, verify the confirmation, receipt in
Telegram. These are the per-kind shapes.

## Shopping and cart comparison

1. Pin down the item, the constraints (size, model, condition, deadline)
   and the budget. Ask once for anything you cannot read off the page —
   never a question per field.
2. Search at least two merchants or marketplaces in tabs you own. Compare
   the real total — item, shipping, tax, delivery date — not list prices.
3. For a used or open-box listing, screenshot the listing photos and
   inspect them for condition: haze or fungus in optics, scratches,
   yellowing, missing parts, a mismatched serial. State what you saw in
   the echo and let it set the offer; skip listings whose photos you
   cannot see.
4. Build the cart and stage through checkout to the payment step. Echo
   the merchant, the line items, the total with shipping and tax, and the
   delivery estimate.
5. Commit `kind:"purchase"` on the order button. An offer or a message to
   a seller is `kind:"send"`: draft it, get it approved, then send it.
   Capture the order number and screenshot the confirmation.

## Booking and travel

1. Pin the dates, party size, origin and destination, and the budget; put
   flexibility ("±1 day", "any morning flight") in writing before
   searching.
2. Compare at least two options — two hotels, or the carrier's own site
   against an aggregator — on the final price with resort fees, baggage
   and taxes, not the teaser rate.
3. Read the cancellation policy and change fees before the commit screen;
   they go in the echo. Non-refundable vs. flexible is part of what the
   user approves.
4. Stage through to the payment step, then echo the dates, the party
   size, the room or fare class, the total with fees, and the provider
   taking the money.
5. A card-number field is a wall: release with `reason:"payment_details"`
   and let the user fill it. Commit `kind:"booking"` on the book/reserve
   control. Capture the confirmation code and screenshot the page.

## Job applications

1. Per posting, read the whole listing and draft the answers — cover
   note, screening questions, resume choice — tailored to it. Show the
   user the draft before anything is submitted; their review is part of
   the application.
2. Draft in batches when the user asked for volume: several drafts, one
   review round, then submit each with its own `commit` —
   `kind:"submit"`, the summary naming the company and role. "Easy Apply"
   and "Submit application" are commit controls, so the gate sees them
   either way.
3. Never message, connect with, or DM a recruiter or poster without a
   `kind:"send"` commit of its own. An application flow that asks for a
   sign-in or a code is a wall: release it.
4. Capture each submission's confirmation and record the application —
   company, role, date, posting URL — in memory, so interview replies and
   follow-ups have somewhere to land.

## Forms, permits and civic portals

1. Find the exact form or portal page and list every required field,
   document and asset number it wants before typing anything.
2. Ask the user once for everything you cannot read from the page or
   memory.
3. Fill the form, then read the portal's own review or summary page back
   before committing. Echo the agency or department receiving it, what is
   being filed, and any fee.
4. Commit `kind:"submit"` on the file/submit control — `kind:"purchase"`
   only if it takes payment. Capture the reference or case number and
   screenshot the receipt page; for a civic fix-it request, keep the
   asset or ticket number in the echo so the request can be tracked.
5. A portal that mails a code or calls back is a follow-up, not a wall:
   note the expected channel in the receipt.

## Cancellations and refunds

1. Find the real cancel path — account settings, a retention flow, a
   support chat, or a written request — and read the terms first: end
   date, final charge, proration, refund window.
2. Echo what will happen before committing: the service end date, the
   last charge, the refund amount and where it lands.
3. Commit `kind:"account_change"` on the cancel control, `kind:"send"` on
   a written cancellation request, `kind:"delete"` only for an actual
   deletion. A retention offer on the way out is the user's call — report
   it, do not accept or decline it yourself.
4. Capture the cancellation confirmation. A refund in flight or a pending
   cancellation is a watch: a cron job on the portal or the inbox,
   polling every 10 minutes or slower, stopping when the refund lands.

## Claims pipeline: receipt to resolution

1. Ingest the document — receipt photo, PDF, EOB, warranty — and extract
   the fields the claim needs: dates, amounts, merchant or provider,
   serial, policy or order numbers. Say what you extracted and flag what
   was unreadable; never invent a field.
2. Match the claim to the right portal or form and fill every field from
   the document. Attach the evidence the form accepts.
3. Echo the claim: who it goes to, the amount claimed, the evidence
   attached. Commit `kind:"submit"`, capture the claim or reference
   number, and screenshot the confirmation.
4. Claims resolve slowly, so set a cron watch on the claim status or the
   mailbox the portal writes to — polling every 10 minutes or slower,
   stopping on resolution or after a few consecutive failures — and
   report only on change. Each follow-up appeal or reply goes out as its
   own `kind:"send"` commit.
