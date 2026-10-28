"""The texting voice for the bot's own replies in its chats: one set of tone rules shared with
check-ins and the brief, a per-turn note for the model (with a character target for casual
replies), a remove-only send-time cleanup (openers, sign-offs, headings, walls of bold; code and
links untouched) and typing-time pacing for fast Telegram replies. Fixed Hermes messages
(approvals, errors, progress) have no hook and are never touched. On by default; `/tone default`
turns it off for this profile. It layers on top of SOUL.md and agent.system_prompt and never
writes either."""
import re
import time

STATE_KEY = "voice"
MODES = ("texting", "default")
NOTE_MARKER = "[Texting voice]"
# Grok-style defaults: casual replies about a tweet long, and a Telegram reply never lands
# sooner than a quick typist could have written it (capped, so long answers aren't held back).
DEFAULT_LENGTH = 280
LENGTH_RANGE = (50, 4096)
DEFAULT_PACE_MS = 2500
PACE_RANGE = (0, 10000)
USAGE = "usage: /tone [texting|default|status] | /tone length <chars>|off | /tone pace <ms>|natural|off"

# Surfaces that reach a person in a chat view: the Telegram bot plus every session source the
# `serve` backend reports for a chat (the desktop app under HERMES_DESKTOP, a TUI or standalone
# serve session, and a hosted bot room). Cron, api_server, webhook and cli turns keep the
# default voice.
CHAT_PLATFORMS = frozenset({"telegram", "desktop", "tui", "bot_room"})

# Shared by proactivity.py's check-ins and the reply note, so both sound like one person.
TEXTING = "Write like a sharp, warm friend texting them on Telegram"
PLAIN = ("Use plain words and contractions. Skip greetings, preambles and filler such as"
         " 'Certainly!', 'Great question' or 'I'd be happy to'. Mild warmth is fine; use a short"
         " opener sparingly.")
FORMAT = ("Plain text or light formatting Telegram renders (bold, italic, code), never headings,"
          " tables or walls of bold; emoji only if they use them.")
REPORT = ("Lead with the concrete status, then evidence or a caveat. Mid-task, stay quiet through routine steps;"
          " interrupt for a decision, approval or handback they own, a blocker or failed"
          " step, information you can't safely guess (never invent it), or a side effect or"
          " scope bigger than they asked. Finish with one concise verified result and any real"
          " caveat, not a step-by-step log. Own limits, failures and side effects plainly."
          " Use the tools you're given before saying you can't; never invent tool errors, output"
          " or a blocker that didn't happen. Claim an exact result only when the results show it:"
          " line numbers and other marks in read output are display decoration, not the file's"
          " bytes, and a write's verified confirmation means the text you sent landed, not that"
          " it matched the source."
          " Never narrate loading skills, instructions, memory or tools."
          " Narrate only actions in the user's world.")
RECAP = ("Recaps: 2-3 headline outcomes in 1-3 sentences total, including any offer of detail;"
         " no bullets. Keep material unfinished work or failures in those headlines."
         " Drop resolved blockers and omit old blockers unless recent evidence confirms they still apply."
         " Offer detail ('want the details on any of these?') within that total, never as an extra sentence."
         " Before sending, count all sentences and combine or cut until at most 3 remain.")
INTERNALS = ("In user-facing text, use task words, never tool names, tool calls, file paths, scripts,"
             " job or session IDs unless they ask for technical detail.")
NEXT = ("Ask only when the user owns a decision; name the choice or needed detail. After completing"
        " the requested work, give a next step or caveat when useful, then stop.")
SAFE = ("Keep the same safeguards: approvals, CAPTCHA handbacks and safety checks work exactly as"
        " before, and say plainly when something failed. Where their own persona or instructions"
        " ask for a different style, theirs wins.")

def _note(length):
    cap = f", under {length} characters" if length else ""
    return (
        f"{NOTE_MARKER} {TEXTING}."
        f" {PLAIN} {REPORT} {INTERNALS} {FORMAT} Use a list only when they ask for steps or the content really is a list."
        " Light, dry humor is fine when the moment invites it, never at their expense and never with"
        " bad news. Asked what you think, pick one and say why ('I'd go with X, because Y') instead"
        " of surveying options. Prices, availability and policies come only from a page read live"
        " this turn; never recommend using an unconfirmed number."
        " Long answers (code, plans, research) stay complete: lead with a"
        " one-line answer, then the detail in short paragraphs, code in code blocks."
        " " + NEXT + " " + SAFE
        # Keep the short-answer default after the general completeness/list guidance. The offer
        # of detail fits inside the cap; the user's persona or request can still override it.
        + f" Casual replies: 1-3 short sentences{cap}; match their energy and length. " + RECAP
        + " For casual replies and recaps, use at most 3 sentences total, including any offer of detail;"
        " no lists unless asked. Keep recaps to headline outcomes, without per-item evidence or history."
        " If their own persona or instructions ask for a different style or more detail, theirs wins.")


NOTE = _note(DEFAULT_LENGTH)


SHORT_REPLY = ("This one wants a short answer: at most 3 sentences total, including any offer of detail."
               " Count before sending and combine or cut to fit; keep any material failure or unfinished work.")
# A closed set of whole-message recaps and social replies. Prefixes never
# imply short intent by themselves; unfamiliar wording is left uncapped.
_REPLY_SEPARATOR = (r"[\s,.!?;:\-\N{HORIZONTAL ELLIPSIS}\N{VARIATION SELECTOR-16}\N{ZERO WIDTH JOINER}"
                    r"\u2600-\u27bf"  # symbols, dingbats
                    r"\U0001f300-\U0001faff]")  # emoji
_GREETING = r"(?:hi|hey|hello|good morning|good afternoon|good evening)"
_RECAP_REQUEST = re.compile(
    _REPLY_SEPARATOR + r"*(?:" + _GREETING + _REPLY_SEPARATOR + r"+)?"
    r"(?:quick (?:one|question)" + _REPLY_SEPARATOR + r"+)?"
    r"(?:what did you get done(?: today)?|how's it going(?: today)?"
    r"|(?:can you |could you |please )?(?:give me a )?recap(?: today(?:'s work)?| the meeting)?"
    r"|tl;dr(?:[: ]+(?:what changed|what's the status))?)" + _REPLY_SEPARATOR + r"*")
_SOCIAL_REPLY = re.compile(
    _REPLY_SEPARATOR + r"*(?:" + _GREETING + _REPLY_SEPARATOR + r"+)?"
    r"(?:" + _GREETING + r"|thanks|thank you|ok|okay|got it|understood|sounds good)"
    r"(?:" + _REPLY_SEPARATOR + r"+that's helpful)?" + _REPLY_SEPARATOR + r"*")

_DETAIL_REQUEST = re.compile(
    r"\b(?:detail(?:ed|s)?|walk me through|step[ -]by[ -]step|in depth|thoroughly"
    r"|comprehensive|long|extensive(?:ly)?|everything|all of it|full|complete|with evidence)\b")


def wants_short_reply(user_message):
    """Cheap, conservative intent check on this turn only; no history or model call."""
    text = str(user_message or "")
    # Check the raw length before normalization; truncation could hide a task
    # after a recap, and whitespace/Unicode normalization must stay bounded too.
    if len(text) > 200:
        return False
    text = " ".join(text.casefold().replace("’", "'").split())
    return not _DETAIL_REQUEST.search(text) and bool(
        _RECAP_REQUEST.fullmatch(text) or _SOCIAL_REPLY.fullmatch(text))


# Hermes suppresses a reply that is (or starts/ends with) one of these; any reply mentioning
# one is left exactly as written.
_SILENCE = re.compile(r"silent|no[ _]?reply|静默|沉默", re.IGNORECASE)
# A known assistant opener at the very start of the message, with the blank space after it but
# never the indentation of the next line. "Absolutely." can answer a yes/no question, so the
# bare words count only with "!".
_OPENER = re.compile(
    r"(?:(?:certainly|absolutely|of course|sure thing)!"
    r"|(?:great question|good question|what a great question)[!.]"
    r"|(?:i['’]d be |i['’]m )?happy to help(?: with that)?[!.])[ \t]*(?:\n[ \t]*(?=\n))*\n?",
    re.IGNORECASE)
# Generic sign-offs at the very end of the message. A specific offer ("Let me know if you want
# me to book it.") is a real next step and stays.
_CLOSER = re.compile(
    r"(?:(?<=[.!?)\]\n*])|\A)\s*(?:(?:i )?hope (?:this|that) helps|let me know if (?:you have any (?:other |more |further )?questions"
    r"|you need anything else|there['’]s anything else(?: i can (?:help with|do))?)"
    r"|feel free to (?:ask|reach out)(?: if you have any (?:other |more |further )?questions)?"
    r"|is there anything else i can (?:help (?:you )?with|do(?: for you)?)"
    r"|happy to help(?: further| with anything else)?)" + _REPLY_SEPARATOR + r"*\Z",
    re.IGNORECASE)
# Every line break str.splitlines() honours except "\n": CR, VT, FF, FS, GS, RS, NEL, LS, PS.
_OTHER_LINE_BREAKS = ("\r\v\f"
                      "\x1c\x1d"  # file separator, group separator
                      "\x1e\x85"  # record separator, next line
                      "\u2028\u2029")  # line separator, paragraph separator
# Spans the cleanup never edits: fenced code (unclosed runs to the end), any line starting
# with whitespace (indented code, nested list items), inline code (an unmatched backtick
# protects the rest), links and images, reference definitions, autolinks and bare URLs.
_PROTECTED = re.compile(
    r"^ {0,3}(?P<fence>(?P<fc>[`~])(?P=fc){2,})[^\n]*(?:\n.*?(?:^ {0,3}(?P=fence)(?P=fc)*[ \t]*$|\Z)|\Z)"
    r"|^[ \t]+[^\n]*"
    r"|(?P<tick>`+)(?:.*?[^`](?P=tick)(?!`)|.*)"
    r"|!?\[[^\[\]\n]*\](?:\((?:[^()\n]|\([^()\n]*\))*\)|\[[^\[\]\n]*\])"
    r"|^ {0,3}\[[^\[\]\n]+\]:[^\n]*"
    r"|<(?:https?|mailto):[^>\s]*>|(?:https?://|www\.)[^\s<>]*",
    re.MULTILINE | re.DOTALL)
_HOLE = "\ue000"
_HEADING = re.compile(r"^(?:#{1,6}[ \t]+)+(.*?)(?:[ \t]+#+)?[ \t]*$", re.MULTILINE)
# Bold that opens and closes like real emphasis, so 2**3**4 and "a ** b" stay as they are.
_INNER = r"(?=[^\s*])((?:(?!\*\*)[^\n])*?[^\s*])"
_BOLD = re.compile(r"(?<![\w*])\*\*" + _INNER + r"\*\*(?![\w*])")
_BOLD_LINE = re.compile(r"^\*\*" + _INNER + r"\*\*(:?)[ \t]*$", re.MULTILINE)
WALL_OF_BOLD = 3


def polish(text):
    """The send-time cleanup, deterministic and remove-only: drops known assistant openers at
    the start and generic sign-offs at the end, turns markdown headings into plain lines,
    unwraps a line that is only bold (a pseudo-heading), and unwraps all bold once a message
    has WALL_OF_BOLD or more bold spans. Code, links, URLs and indented lines are never edited,
    list markers stay, and a message that would end up empty, mentions a silence word or uses
    a line break other than a plain newline comes back byte-identical."""
    if (not isinstance(text, str) or _SILENCE.search(text) or _HOLE in text
            or any(ch in _OTHER_LINE_BREAKS for ch in text)):
        return text
    kept = []

    def hole(m):
        kept.append(m.group())
        return _HOLE

    out = text
    # Openers go first: what follows one decides where code starts.
    while (m := _OPENER.match(out)) and out[m.end():].strip():
        out = out[m.end():]
    out = _PROTECTED.sub(hole, out)
    # A sign-off is short, so only the tail is searched; that keeps long blank runs linear.
    while True:
        body = out.rstrip()
        m = _CLOSER.search(body, max(0, len(body) - 300))
        if not m or not body[:m.start()].strip():
            break
        out = body[:m.start()].rstrip()
    out = _HEADING.sub(r"\1", out)
    out = _BOLD_LINE.sub(r"\1\2", out)
    if len(_BOLD.findall(out)) >= WALL_OF_BOLD:
        out = _BOLD.sub(r"\1", out)
    restored = iter(kept)
    out = re.sub(_HOLE, lambda m: next(restored), out)
    return out if out.strip() else text


GROUP = (" This is a group chat, maybe with other bots: answer whoever addressed you, keep it"
         " shorter still, and don't repeat what others already said.")


def session_env(name):
    try:
        from gateway.session_context import get_session_env
        return get_session_env(name) or ""
    except Exception:
        return ""


def note_for(user_message, *, platform, chat_type="", on=True, length=DEFAULT_LENGTH):
    """The context a texting turn gets, or None. Pure, so the eval runs exactly this.
    ponytail: cron runs keep the default voice; Hermes hands hooks no public way to see a job's
    destinations (upstream gap in docs/voice.md)."""
    from .proactivity import BRIEF_MARKER, MARKER
    # Check-ins and the brief carry the same rules in their own prompts, with their own length.
    if not on or platform not in CHAT_PLATFORMS or str(user_message or "").startswith((MARKER, BRIEF_MARKER)):
        return None
    note = _note(length) + (GROUP if chat_type in ("group", "forum", "channel") else "")
    return note + ("\n" + SHORT_REPLY if wants_short_reply(user_message) else "")


def pace_seconds(text, cap_ms, elapsed):
    """How much longer to hold a reply so it lands no sooner than typing it would take:
    0.6s plus 15ms a character, at most cap_ms, minus the time the turn already took."""
    return max(0.0, min(cap_ms, 600 + 15 * len(text)) / 1000 - elapsed)


def _setting(raw, rng, words):
    """A stored or typed setting as an int in rng; words maps names like "off" to values."""
    value = words.get(raw, raw) if isinstance(raw, str) else raw
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if type(value) is not int or not (value == 0 or rng[0] <= value <= rng[1]):
        raise ValueError(USAGE)
    return value


class Voice:
    def __init__(self, ctx):
        self.ctx = ctx
        self.sleep = time.sleep
        self._started = {}

    def _state(self):
        try:
            state = self.ctx.state.get(STATE_KEY)
        except Exception:
            state = None
        return dict(state) if isinstance(state, dict) else {}

    def mode(self):
        mode = self._state().get("mode")
        return mode if mode in MODES else "texting"

    def length(self):
        try:
            return _setting(self._state().get("length", DEFAULT_LENGTH), LENGTH_RANGE, {})
        except ValueError:
            return DEFAULT_LENGTH

    def pace_ms(self):
        try:
            return _setting(self._state().get("pace_ms", DEFAULT_PACE_MS), PACE_RANGE, {})
        except ValueError:
            return DEFAULT_PACE_MS

    def on(self):
        return self.mode() == "texting"

    def on_turn_start(self, user_message="", platform="", **kwargs):
        """pre_llm_call: the texting note for a chat-surface turn. Reads plugin state only."""
        if not self.on():
            return None
        note = note_for(user_message, platform=platform, chat_type=session_env("HERMES_SESSION_CHAT_TYPE"),
                        length=self.length())
        # Only a turn someone is waiting on gets paced; check-ins and the brief get no note.
        if note and platform == "telegram" and kwargs.get("session_id"):
            self._started[kwargs["session_id"]] = time.monotonic()
        return {"context": note} if note else None

    def on_output(self, response_text="", platform="", **kwargs):
        """transform_llm_output: the polished final reply, or None to leave it as is."""
        if not self.on() or platform not in CHAT_PLATFORMS or not isinstance(response_text, str):
            return None
        out = polish(response_text)
        started = self._started.pop(kwargs.get("session_id"), None)
        # Runs on the agent's worker thread, with Telegram's typing indicator still showing.
        if platform == "telegram" and started is not None and not _SILENCE.search(out):
            wait = pace_seconds(out, self.pace_ms(), time.monotonic() - started)
            if wait:
                self.sleep(wait)
        return out if out != response_text else None

    def _update(self, **values):
        self.ctx.state.set(STATE_KEY, {**self._state(), **values})

    def set(self, mode):
        if mode not in MODES:
            raise ValueError(USAGE)
        self._update(mode=mode)

    def set_length(self, raw):
        self._update(length=_setting(raw, LENGTH_RANGE, {"off": 0}))

    def set_pace(self, raw):
        self._update(pace_ms=_setting(raw, PACE_RANGE, {"off": 0, "natural": DEFAULT_PACE_MS}))

    def settings_text(self):
        length, pace = self.length(), self.pace_ms()
        return (("Casual replies aim for under %d characters" % length if length else "No character target")
                + ("; Telegram replies are paced like typing, up to %.1fs." % (pace / 1000) if pace
                   else "; Telegram replies aren't paced.")
                + " Change with /tone length <chars>|off and /tone pace <ms>|natural|off.")

    def status_text(self):
        if self.on():
            return "Texting voice is on for your chats. " + self.settings_text() + " Send /tone default to switch it off."
        return ("Your chats use Hermes' default voice. Check-ins and the morning brief keep their own"
                " short style (/proactivity controls them). Send /tone texting to switch the texting"
                " voice back on.")

    def command(self, raw_args=""):
        """`/tone [texting|default|status]`, `/tone length <chars>|off`, `/tone pace <ms>|natural|off`.
        Plain text, never raises."""
        words = str(raw_args or "").lower().split()
        try:
            if words[:1] in (["length"], ["pace"]) and len(words) == 2:
                (self.set_length if words[0] == "length" else self.set_pace)(words[1])
            elif words and words != ["status"]:
                if len(words) != 1:
                    raise ValueError(USAGE)
                self.set(words[0])
            return self.status_text()
        except ValueError as exc:
            return str(exc)
        except Exception as exc:
            return f"tone: {type(exc).__name__}"


def cli_setup(parser):
    parser.add_argument("mode", nargs="?", default="status", choices=["status", *MODES, "length", "pace"])
    parser.add_argument("value", nargs="?", help="for length: characters or off; for pace: ms, natural or off")


def cli_run(voice, args):
    try:
        if args.mode in ("length", "pace"):
            (voice.set_length if args.mode == "length" else voice.set_pace)(str(args.value or "").lower())
        elif args.mode != "status":
            voice.set(args.mode)
    except ValueError as exc:
        print(exc)
        return 2
    print(voice.mode(), "length=%d" % voice.length(), "pace_ms=%d" % voice.pace_ms())
    return 0
