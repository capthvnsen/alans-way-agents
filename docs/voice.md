# Texting voice

Your bot's replies in its chats should read like a text from a sharp, warm
friend who happens to be very capable: short by default, plain words, an
opinion when you ask for one, and complete when the job needs detail. The
plugin does this for every profile it is enabled in, which with `setup.sh` is
every profile that has a Telegram bot. It covers the bot's own model-written
replies; fixed Hermes messages are out of reach (see
[Not covered](#not-covered)).

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

Check-ins and the morning brief keep their own short texting style when the
voice is off: that style is part of their prompts (`/proactivity` controls
them), not this switch. With `/tone default` only the send-time polish stops for
them.

Hermes already has `/voice` (voice mode) and `/personality`. The texting voice
uses neither. A Hermes personality replaces `agent.system_prompt` while it is
selected; this voice adds to whatever you already have instead.

## What it changes

Only chat surfaces: the Telegram bot and the desktop app's remote Hermes chats
(the `serve` backend reports those sessions as `desktop`, `tui` or `bot_room`;
the same note and polish reach all of them, so a chat reads the same on the
phone and on the desktop). Cron, API, webhook and CLI turns are not affected.

1. **A style note on every chat turn** (`pre_llm_call`). Hermes appends
   it to that turn's user message, never to the system prompt. It asks for:
   - 1-3 short sentences for casual replies, matching your energy and length;
   - contractions and plain words, with no "Certainly!", "Great question" or "I'd
     be happy to";
   - no headings or walls of bold, and lists only when you ask for steps or the
     content really is a list;
   - emoji only if you use them;
   - dry humor only when it fits, never at your expense, never with bad news;
   - a real pick with a reason when you ask what it thinks;
   - long answers (code, plans, research) kept complete, led by a one-line answer;
   - **quiet by default while a task runs**: no play-by-play for routine reads,
     navigation, saving, retries that succeed or step transitions — the working
     indicator already shows it. The bot speaks mid-task only for a decision,
     approval or handback that is yours, a blocker or failed step, information it
     can't safely guess (it never invents it), or a side effect or scope bigger
     than you asked — then one short line, and at the end one concise verified
     result with any real caveat, not a step-by-step log. It narrates its steps
     only if you ask for live updates;
   - status first, followed by evidence or a caveat;
   - recaps as 2-3 headline outcomes in 1-3 sentences, without bullets, then an
     offer of detail;
   - task words in user-facing text, without tool names or calls, file paths,
     scripts, or job/session IDs unless you ask for technical detail;
   - plain ownership of limits, failures and side effects, reported right away —
     it uses the tools it is given before saying it can't, claims a blocker
     only when one actually happened, and never invents tool errors or output;
   - exact claims only on exact evidence: line numbers and other marks in read
     output are display decoration, not the file's bytes, and a write's
     "verified" confirmation means the text it sent landed, not that it matched
     your source;
   - mild warmth and short openers used sparingly;
   - questions only for decisions you own, naming the choice or needed detail.

   In groups it also keeps replies shorter and talks to whoever asked.
   The casual/recap length rule comes after the general detail and list
   guidance: at most three sentences total, including any offer of detail,
   with no lists unless asked. Recaps keep headline outcomes and leave out
   per-item evidence and history. Your own persona or request for a different
   style or more detail still wins; code, plans and research stay complete.
   A whole-message recap request (such as "what did you get done today?",
   "recap", "tl;dr", or "how's it going") or standalone greeting, thanks or
   acknowledgment also gets one short reminder at the very end of the turn's
   note, after any group guidance. Recaps can follow a greeting or "quick
   one/question:" prefix; social replies can include punctuation, emoji or
   "that's helpful". A prefix alone, another request, or an action such as
   booking, finding, sending or fixing gets no extra reminder. Explicit detail
   requests (including "long", "extensively", "everything", "all of it",
   "full", "complete", "explain in detail" or "walk me through") also suppress
   it. Local patterns check the whole current message, with no model call;
   messages over 200 characters are skipped before normalization, never
   truncated. Unmatched turns add no reminder tokens.
   This is model guidance, not an enforced output limit: long replies are
   never truncated or silently rewritten to meet the cap.
2. **A send-time polish** (`transform_llm_output` on the final reply). It is
   deterministic, with no model call, and does exactly one thing: it drops a
   known assistant opener ("Certainly!", "Absolutely!", "Of course!", "Sure
   thing!", "Great question.") from the very start of the message, taking with
   it only spaces on the same line and at most one newline. It does this only
   when the whole message has no line break other than `\n` (no CR, VT, FF,
   NEL, U+2028 or U+2029), no line starting with whitespace, no backtick, and
   no quotation mark: ASCII `'` and `"`, Unicode initial and final
   quotes (`“` `”` `‘` `’` `«` `»` `‹` `›` `⸂` `⸃` …), and any other character
   named a quotation mark or apostrophe (`„` `〝` `〟` `＂` …), plus corner
   brackets (`「」『』`).

   If the opener is followed by a blank line or other whitespace, or the reply
   is only the opener, it is left alone too. Otherwise the reply comes back
   byte-identical. Headings and bold are never rewritten; the note asks the
   model not to use them. A contraction counts as a quote, so openers like "I'd
   be happy to help" are left to the note too. A reply that mentions a silence
   word (`SILENT`, `NO_REPLY`, `静默`, `沉默`) is never changed, and the polish
   never empties a reply. A seeded property test generates 300 messages mixing
   code, links, every quote form and every line break. For the ones it checks,
   it requires the output to be an exact suffix of the input: the whole input
   whenever code, a quote, indentation or a non-`\n` line break is present.
3. **Check-ins and the morning brief** already carry the same rules
   (`alans-way/voice.py` holds the shared wording `proactivity.py` uses), so the
   note is not added on top of them; the polish still applies while the voice
   is on.

It never changes:
- SOUL.md, `agent.system_prompt`, `display.personality` or anything else in `config.yaml`;
- approvals and confirmations;
- CAPTCHA handbacks;
- safety checks;
- honesty about failures (the note says so explicitly).

## Every path to the chat surfaces

Checked against the Hermes source this release targets. A `serve` session's
`source` (what hooks see as `platform`) is `desktop` under `HERMES_DESKTOP=1`,
`tui` otherwise, `bot_room` for a hosted room, or an explicit value a caller
sets; all four get the same note and polish, so remote desktop Hermes and the
Telegram bot share one quiet default.

| Path | What applies |
|---|---|
| The bot's reply in a DM, group, forum topic or channel, including groups with several bots | note + polish |
| A chat turn on desktop, TUI or a hosted bot room | note + polish |
| Check-ins and the morning brief (injected turns) | their own prompt (same rules) + polish |
| Agent-notify / async-completion turns | note + polish |
| Cron jobs, including ones that deliver only to Telegram | nothing for now (see below) |
| Interim lines the model writes alongside tool calls (how a CAPTCHA or handback ping usually goes out mid-task) | the turn's note shapes them; the polish can't reach them |
| Streaming (off by default) | early chunks show raw text; the final edit shows the polished reply |

### Not covered

No supported Hermes hook reaches these, so the plugin does not touch them:
- approval cards and their buttons, and MCP elicitation prompts such as the
  commit gate's (fixed Hermes text; deliberately never altered);
- gateway error and failure messages, status and tool-progress lines, and cron
  failure notices (fixed Hermes text from its locale catalog);
- `hermes send` and other direct sends. Current Hermes has no model-callable
  `send_message` tool, and these paths run no plugin hook;
- cron results. Hermes sends one shared result to every destination of a job,
  and gives hooks no public way to see those destinations (the target list is
  only reachable through a private Hermes function, which this repo doesn't
  import). Cron runs keep the default voice until Hermes exposes it.

The setup skill can offer to switch off Hermes' extra steering acknowledgment
with `display.busy_steer_ack_enabled=false`, only after the user's explicit
answer. The model still acknowledges additions in its own short reply; setup
scripts do not change this setting. No Hermes message is rewritten.

Telegram mechanics: Hermes already shows "typing…" for the whole turn
(`platforms.telegram.typing_indicator`, on by default) and sends a line the
model writes before a tool call as its own message
(`display.interim_assistant_messages`, on by default for Telegram). The plugin
relies on both and fakes nothing. Hermes can't split one final reply into
several messages except at Telegram's 4096-character limit, so neither can
the voice.

## Upstream gaps (Hermes)

- No hook on the outbound Telegram send path. A per-platform `pre_send` hook
  (one that never receives approval or elicitation payloads) would cover fixed
  error, status and progress text and direct sends. Today `register_locale`
  rewords fixed text for every platform at once, so the plugin leaves it alone.
- Interim assistant messages skip `transform_llm_output`, and
  `on_interim_message` can only observe.
- No way to split a final reply into 2-3 messages (for example at blank lines)
  other than the length limit.
- Cron gives hooks no public view of a job's destinations, and delivers one
  result to all of them. Exposing the job id and its full target list in hook
  kwargs (or per-destination results) would let cron reports that go only to
  Telegram use the voice.
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
- a cron report (a control: cron keeps the default voice for now);
- a multi-bot group;
- an error;
- a check-in and the brief.

A judge model scores every reply blind against a written rubric: short, human,
opinionated when asked, complete when it must be, and safe. It calls a model,
so it is local only and never runs in CI:

```sh
pip install anthropic==0.87.0 && ANTHROPIC_API_KEY=... python3 scripts/voice_eval.py
python3 scripts/voice_eval.py --backend claude --out results.json   # through `claude -p`, no key
python3 scripts/voice_eval.py --dry-run    # print every request, call nothing
```

The SDK backend is checked against `anthropic` 0.87.0: `tests/test_voice_eval.py`
binds every request to that SDK's `messages.create` signature when it is
installed. The rubric shares vocabulary with the note, so read the scores as a
regression check, not proof. The `claude` backend runs inside Claude Code, which
can still slip the local account's name or email into a reply even with the
eval's fictional user in memory; use the SDK backend for runs you publish.

`scripts/voice_steps_eval.py` measures the quiet-workflow policy on whole turns:
each scenario drives a simulated multi-step task where the model emits one JSON
step at a time (`say` = an interim chat bubble, `calls` = fake tool calls answered
by scripted results, `done` = the final reply), and mid-run user messages land
between steps. It records every interim bubble and the final verbatim against
scenarios for routine work, retries, approvals, missing input, failures,
surprises, partial completion, status questions and explicit narration requests —
run with `--plugin-dir` pointed at a frozen copy of any plugin version to compare
policies on the same scenarios. Local only, like the single-shot eval:

```sh
python3 scripts/voice_steps_eval.py --plugin-dir alans-way --out steps.json
```
