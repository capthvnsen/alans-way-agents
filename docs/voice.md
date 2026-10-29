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

### Length and pacing

Two more per-bot settings sit next to the switch, in the same state file. Turning
the voice off and on again keeps them.

| Setting | Default | In the chat | On the server |
|---|---|---|---|
| Character target for casual replies (50-4096, or off) | 280 | `/tone length 200`, `/tone length off` | `hermes tone length 200` |
| Pacing for Telegram replies (cap in ms, 0-10000, or off) | 2500 (`natural`) | `/tone pace 1500`, `/tone pace natural`, `/tone pace off` | `hermes tone pace off` |

`/tone` shows both. The character target is part of the note: the model is asked
to keep casual replies under it. It is guidance, not a limit: nothing is cut,
and code, plans and research stay complete. Pacing holds a Telegram reply until
it could plausibly have been typed: 0.6 seconds plus 15 ms a character, minus
the time the turn already took, and never more than the cap. Most turns already
take longer than that, so only quick replies wait. The wait runs before Hermes
sends the reply, while Telegram still shows "typing…". Desktop, TUI and bot-room
chats are not paced, and neither is a reply that won't be sent (`SILENT`).

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
   - 1-3 short sentences for casual replies, under the character target (280
     by default; see [Length and pacing](#length-and-pacing)), matching your
     energy and length;
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
2. **A send-time cleanup** (`transform_llm_output` on the final reply). It is
   deterministic, makes no model call and only ever removes characters. It:
   - drops known assistant openers from the very start ("Certainly!",
     "Absolutely!", "Of course!", "Sure thing!", "Great question.", "I'd be happy
     to help with that."), with the blank space after them but never the
     indentation of the next line;
   - drops generic sign-offs from the very end ("Hope this helps!", "Let me know
     if you have any other questions.", "Feel free to reach out…", "Is there
     anything else I can help you with?"). A specific offer such as "Let me know
     if you want me to book it." stays;
   - turns markdown headings (`## Plan`) into plain lines. Hermes would
     otherwise send them to Telegram as bold lines;
   - unwraps a line that is only bold (`**Next steps**`, a stand-in heading);
   - unwraps every bold span once a reply has three or more (a wall of bold).
     One or two bold words in a sentence are real emphasis and stay.

   It never edits fenced code (closed or not), inline code (an unmatched
   backtick protects the rest of the message), any line that starts with
   whitespace (indented code, nested list items), links, images, reference
   definitions or URLs. List markers stay, and so does a quoted line (`>`).
   `2**3**4` and `a ** b` are not bold. A reply that mentions a silence word
   (`SILENT`, `NO_REPLY`, `静默`, `沉默`) is never changed, and neither is one
   with a line break other than `\n` (CR, VT, FF, NEL, U+2028 or U+2029). The
   cleanup never empties a reply: an opener or sign-off that is the whole
   message stays. A seeded property test generates 300 messages mixing code,
   links, URLs, quotes, lists and every heading and bold shape. For each one it
   checks that every code and link span comes back verbatim, that the output is
   the input with characters removed, and that a second pass changes nothing.
3. **Check-ins and the morning brief** already carry the same rules
   (`alans-way/voice.py` holds the shared wording `proactivity.py` uses), so the
   note is not added on top of them; the cleanup still applies while the voice
   is on. They are injected turns with no user waiting, so they aren't paced.

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
| First message and every later model turn in a Telegram DM, group, forum topic or channel, including groups with several bots | note + polish |
| Mid-task follow-up, status question, approval continuation or media-only Telegram turn | note + polish; no first-turn or nonempty-message requirement |
| A chat turn on desktop, TUI or a hosted bot room | note + polish |
| Check-ins and the morning brief (injected turns) | their own prompt (same rules) + polish |
| Agent-notify / async-completion turns | note + polish |
| Cron jobs, including ones that deliver only to Telegram | nothing for now (see below) |
| Interim lines the model writes alongside tool calls (how a CAPTCHA or handback ping usually goes out mid-task) | the turn's note shapes them; the polish can't reach them |
| Streaming (off by default) | early chunks show raw text; the final edit shows the polished reply |

`tests/test_voice.py` exercises the registered hook across repeated turns with
tool history in the same session, on both primary and secondary bot profiles,
in all four Telegram chat types. It covers the first request, mid-task
additions, status questions, approval continuations, async notifications and
empty text, plus turning `/tone default` off and back on in that conversation.
These are offline hook tests, not generated-message or Telegram transport tests.

Hermes calls `pre_llm_call` at the start of a conversational turn and retains
its injected context for the model's subsequent calls in that turn. A tool
result or an interim assistant line is not a separate turn that needs a new
note. A busy-mode steer joins the current run with its existing note; a
follow-up that starts a new run receives a fresh note. Interim lines therefore
have the quiet policy in model context, but only the final reply gets the
deterministic polish. Alongside source inspection, a local disposable-Hermes
contract check exercised the actual hook collector and API request builder:
the quiet note survived nine requests across three turns, tool results and
synthetic steering text. It also checked raw interim delivery and the internal
hook bypass below. Those three checks passed without a real model or Telegram
connection; they are separate from the repository's offline hook harness.
[Hermes turn context](https://github.com/NousResearch/hermes-agent/blob/1fd18277267152893a8a24792b79213e7ca3f899/agent/turn_context.py),
[Hermes interim delivery](https://github.com/NousResearch/hermes-agent/blob/1fd18277267152893a8a24792b79213e7ca3f899/agent/stream_delivery.py)

The Telegram model turns without the added note are check-ins and morning
briefs, which already embed the shared quiet rules. `/tone default` disables
the added note on ordinary chat turns. Cron uses platform `cron` even when
delivering to Telegram, so it receives neither the note nor the polish.
Hermes also bypasses this hook for persistence-disabled internal agents, such
as background self-improvement review; those are not ordinary chat replies.
Fixed gateway messages and direct sends are outside the model-turn path.
[Hermes hook dispatch](https://github.com/NousResearch/hermes-agent/blob/1fd18277267152893a8a24792b79213e7ca3f899/agent/turn_context.py),
[Hermes background review](https://github.com/NousResearch/hermes-agent/blob/1fd18277267152893a8a24792b79213e7ca3f899/agent/background_review.py)

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

Telegram mechanics: Hermes already shows "typing…" for the whole turn
(`platforms.telegram.typing_indicator`, on by default) and sends a line the
model writes before a tool call as its own message
(`display.interim_assistant_messages`, on by default for Telegram). The plugin
relies on both. Its only pacing is the wait described in
[Length and pacing](#length-and-pacing). Hermes' own `human_delay` setting
paces only images and files sent with a reply, not the text. Hermes can't split
one final reply into several messages except at Telegram's 4096-character
limit, so neither can the voice.

### Fewer Hermes messages in Telegram

The guided setup skill's **Make Telegram feel right** option in
[`workspace-setup/SKILL.md`](../alans-way/skills/workspace-setup/SKILL.md)
offers these presentation choices together. It reads current effective values,
preserves existing choices and applies only the user's answered choices through
the profile-scoped Hermes CLI, with readback. Nothing in this voice feature
changes those settings or a profile automatically.

| Setting offered by guided setup | Effect and messages that remain |
|---|---|
| `display.platforms.telegram.tool_progress: off` | Hides mechanical tool-start breadcrumbs, including tool names and argument previews. This is already Telegram's built-in default; an existing override can enable them. It does not hide model-written interim lines, long-work reminders, approval prompts or failures. |
| `display.platforms.telegram.interim_assistant_messages: true` | Keeps the model's mid-task messages visible, including a needed question, blocker, approval or handback. The quiet note asks the model to omit routine narration; this setting does not enforce that request. |
| `display.platforms.telegram.long_running_notifications: generic` | Keeps Hermes's periodic long-work status, using plain wording without internal tool details. It does not reduce the heartbeat cadence or silence it. For fewer messages, an explicitly chosen `display.platforms.telegram.long_running_notifications: off` disables these reminders; the interval can also disable them when set to zero. Guided setup recommends `generic`, not `off`. |
| `display.platforms.telegram.busy_steer_ack_enabled: false` | Hides Hermes's separate steer acknowledgment when new guidance joins an active task. The model can still acknowledge the addition in its own next short line. This does not change busy-input mode or other fixed notices. |
| `display.memory_notifications: off` | Hides memory-update and self-improvement review bookkeeping across every platform in that profile. Background review still runs. |
| `display.platforms.telegram.notifications: important` | Makes routine updates silent while finals and approval prompts remain eligible for sound. It changes notification sound, not the number of visible messages; visual notifications can still appear. |
| `platforms.telegram.typing_indicator: true` and `platforms.telegram.reactions: true` | Show activity and processing success/failure without a narration bubble. A success reaction does not verify the user's goal. Hermes ships reactions off. Setup turns them on when you accept its recommendations, or when you change other choices without naming reactions. Bots set up under the older acknowledgment-only question get one reactions-only question. An earlier answer and a `TELEGRAM_REACTIONS` override are kept. |
| `cron.wrap_response: false` | Removes the scheduled-message header, job IDs and management footer across all delivery targets in the profile. The scheduled result or failure itself still arrives. |

For tool progress, the effective value resolves in this order: Telegram
platform override, legacy `display.tool_progress_overrides.telegram`, global
`display.tool_progress`, Telegram default, global default. A global `off`
does not override a legacy Telegram `all`. Guided setup writes the explicit
`display.platforms.telegram.tool_progress off` after consent and checks the
effective result while preserving the older keys. Other platform display
settings resolve without that legacy tool-progress fallback.
[Hermes display resolver](https://github.com/NousResearch/hermes-agent/blob/1fd18277267152893a8a24792b79213e7ca3f899/gateway/display_config.py)

With those recommendations, model-written essential interruptions and the
final reply remain, as do generic long-work reminders. Hermes's fixed approval
cards, MCP elicitation, CAPTCHA handbacks, errors, failure notices and command
responses also remain when triggered. `tool_progress: off` is not a global
mute: failure notices have a separate path, and `generic` still sends or edits
a heartbeat. The plugin cannot rewrite these messages. This documentation
records the existing controls; it changes no defaults or profiles.
[Hermes progress and failure delivery](https://github.com/NousResearch/hermes-agent/blob/1fd18277267152893a8a24792b79213e7ca3f899/gateway/run_turn_runner.py),
[Hermes long-work reminders](https://github.com/NousResearch/hermes-agent/blob/1fd18277267152893a8a24792b79213e7ca3f899/gateway/run_turn.py),
[Hermes steer acknowledgment](https://github.com/NousResearch/hermes-agent/blob/1fd18277267152893a8a24792b79213e7ca3f899/gateway/run_busy.py)

## Upstream gaps (Hermes)

- No hook on the outbound Telegram send path. A per-platform `pre_send` hook
  (one that never receives approval or elicitation payloads) would cover fixed
  error, status and progress text and direct sends. Today `register_locale`
  rewords fixed text for every platform at once, so the plugin leaves it alone.
- Interim assistant messages skip `transform_llm_output`, and
  `on_interim_message` can only observe.
- No way to split a final reply into 2-3 messages (for example at blank lines)
  other than the length limit, and `human_delay` paces only attachments. With
  both, the voice could send a long reply as a few paced texts. Until then it
  asks for short replies and waits before quick ones.
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
