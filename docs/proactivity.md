# Proactive check-ins

Your primary Telegram bot reaches out on its own when you've gone quiet, like a
proactive employee: it does something useful and tells you, suggests something it
could do, or asks a good question. If nothing is worth saying it stays silent.

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

To check in more, start again or widen the hours, send `/proactivity more`,
`/proactivity resume` or `/proactivity hours 9-21` yourself: the bot's tool can
only make check-ins quieter, because anything the model reads can be
prompt-injected. Only the bound chat can change these.

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

`hermes proactivity set --settings '{"base_minutes": 2}'` makes a test check-in
arrive two minutes after you stop chatting. Set it back with
`'{"level": "normal"}'`.

## How it works

The plugin's `pre_llm_call` and `post_llm_call` hooks note when the bound chat
was last active and whether the bot is mid-turn. A 60-second timer, started
only when the gateway connects Telegram, checks whether a check-in is due. When
one is, it injects one internal prompt into that chat, and the bot decides what
to do with its own memory and tools. A `[SILENT]` reply is never delivered.
State lives in Hermes' plugin state (`ctx.state`).

Upgrading from 0.6 keeps your bound chat, timezone and pause. Watches, sweeps
and `/watch` are gone.
