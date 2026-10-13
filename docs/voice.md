# Texting voice

Everything your bots send on Telegram should read like a text from a sharp,
warm friend who happens to be very capable: short by default, plain words, an
opinion when you ask for one, and complete when the job needs detail. The
plugin does this for every profile it is enabled in, which with `setup.sh` is
every profile that has a Telegram bot.

## Turn it off or on

It is on by default, including for existing installs once they update the
plugin. Each profile (each bot) has its own switch. Where your SOUL.md or
`agent.system_prompt` asks for a different style, the note tells the model
yours wins.

| Where | Off | On | Check |
|---|---|---|---|
| In the chat | `/tone default` | `/tone texting` | `/tone` |
| On the server | `hermes tone default` | `hermes tone texting` | `hermes tone` |
| At setup | `setup.sh --tone default` | `setup.sh --tone texting` | |

Add `-p <profile>` to the `hermes` commands for a named profile. Without
`--tone`, setup leaves each profile's switch as it is. The switch lives in the
plugin's own state (`plugin-data/alans-way/state.json`), not in `config.yaml`.

Hermes already has `/voice` (voice mode) and `/personality`. The texting voice
uses neither. A Hermes personality replaces `agent.system_prompt` while it is
selected; this voice adds to whatever you already have instead.

## What it changes

Only messages bound for Telegram. CLI, desktop and other platforms are not
affected.

1. **A style note on every Telegram-bound turn** (`pre_llm_call`). Hermes appends
   it to that turn's user message, never to the system prompt. It asks for:
   - 1-4 sentences by default, matching your energy and length;
   - contractions and plain words, with no "Certainly!", "Great question" or "I'd
     be happy to";
   - no headings or walls of bold, and lists only when you ask for steps or the
     content really is a list;
   - emoji only if you use them;
   - dry humor only when it fits, never at your expense, never with bad news;
   - a real pick with a reason when you ask what it thinks;
   - long answers (code, plans, research) kept complete, led by a one-line answer;
   - a one-line heads-up before a long multi-step task;
   - a closing question only when there's a real next step.

   In groups it also keeps replies shorter and talks to whoever asked. In cron
   runs it treats the result as a Telegram message.
2. **A send-time polish** (`transform_llm_output` on the final reply, and
   `pre_tool_call` on `send_message` text addressed to Telegram). It is
   deterministic, with no model call. It:
   - drops leading filler such as "Certainly!", "Great question", "I'd be happy to
     help" and "As an AI,";
   - turns markdown headings into plain lines;
   - unbolds a paragraph that is mostly bold.

   It never touches code blocks, inline code, URLs, quoted text, blockquotes or
   numbers. It passes Hermes' silence markers (`[SILENT]`, `NO_REPLY`) through as
   they are, and never empties a reply.
3. **Check-ins and the morning brief** already carry the same rules
   (`alans-way/voice.py` holds the shared wording `proactivity.py` uses), so the
   note is not added on top of them; the polish still applies.

It never changes:
- SOUL.md, `agent.system_prompt`, `display.personality` or anything else in `config.yaml`;
- approvals and confirmations;
- CAPTCHA handbacks;
- safety checks;
- honesty about failures (the note says so explicitly).

## Every path to Telegram

Checked against the Hermes source this release targets.

| Path | Covered by |
|---|---|
| Replies in a DM, group, forum topic or channel, including groups with several bots | note + polish |
| Check-ins and the morning brief (injected turns) | their own prompt (same rules) + polish |
| Cron jobs delivering to Telegram | note + polish, when Telegram is the job's first delivery target |
| `send_message` to Telegram mid-turn, such as a CAPTCHA or handback ping | the turn's note + polish of the message |
| Agent-notify / async-completion turns | note + polish |
| Interim lines sent alongside tool calls | the note shapes them; the polish can't reach them |
| Streaming (off by default) | live edits show raw text; the final edit shows the polished reply |
| Approval cards, gateway errors, tool-progress lines, cron failure notices | not changed: fixed Hermes text from its locale catalog |

Telegram mechanics: Hermes already shows "typing…" for the whole turn
(`platforms.telegram.typing_indicator`, on by default) and sends a line the
model writes before a tool call as its own message
(`display.interim_assistant_messages`, on by default for Telegram). The plugin
relies on both and fakes nothing. Hermes can't split one final reply into
several messages except at Telegram's 4096-character limit, so neither can
the voice.

## Upstream gaps (Hermes)

- No hook can reach fixed outbound text per platform: approval cards, gateway
  errors, tool progress and cron failure notices. `register_locale` rewords
  them for every platform at once, so the plugin leaves them alone.
- Interim assistant messages skip `transform_llm_output`, and `on_interim_message`
  can only observe.
- No way to split a final reply into 2-3 messages (for example at blank lines)
  other than the length limit.
- Cron hooks see only the first delivery target (`HERMES_CRON_AUTO_DELIVER_PLATFORM`).
- `pre_llm_call` has no `chat_type` kwarg or group member count. The plugin reads
  the chat type from the session context and treats every Telegram group alike.
- With streaming split across several messages, the polished final edit lands
  on the last message only.

## Measuring it

`scripts/voice_eval.py` answers 20 fixed Telegram scenarios twice:
- **before:** Hermes' default SOUL.md and Telegram hint;
- **after:** the same plus this plugin's note and polish.

The scenarios include:
- casual messages and thanks;
- bad news;
- a technical deep dive;
- a purchase approval;
- a CAPTCHA ping;
- a cron report;
- a multi-bot group;
- an error;
- a check-in and the brief.

A judge model scores every reply blind against a written rubric: short, human,
opinionated when asked, complete when it must be, and safe. It calls a model,
so it is local only and never runs in CI:

```sh
pip install anthropic && ANTHROPIC_API_KEY=... python3 scripts/voice_eval.py
python3 scripts/voice_eval.py --backend claude --out results.json   # through `claude -p`, no key
```
