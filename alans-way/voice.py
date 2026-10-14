"""The texting voice for the bot's own replies on Telegram: one set of tone rules shared with
check-ins and the brief, a per-turn note for the model, and a minimal send-time polish that only
drops a leading assistant opener. Fixed Hermes messages (approvals, errors, progress) have no
hook and are never touched. On by default; `/tone default` turns it off for this profile. It
layers on top of SOUL.md and agent.system_prompt and never writes either."""
import re
import unicodedata

STATE_KEY = "voice"
MODES = ("texting", "default")
NOTE_MARKER = "[Texting voice]"

# Shared by proactivity.py's check-ins and the reply note, so both sound like one person.
TEXTING = "Write like a sharp, warm friend texting them on Telegram"
PLAIN = ("Use plain words and contractions, with no greeting, preamble or filler such as"
         " 'Certainly!', 'Great question' or 'I'd be happy to'.")
FORMAT = ("Plain text or light formatting Telegram renders (bold, italic, code), never headings,"
          " tables or walls of bold; emoji only if they use them.")
NEXT = ("End with a short question or offer only when there's a real next step; otherwise just"
        " stop.")
SAFE = ("This changes tone only: approvals, CAPTCHA handbacks and safety checks work exactly as"
        " before, and say plainly when something failed. Where their own persona or instructions"
        " ask for a different style, theirs wins.")

NOTE = (
    f"{NOTE_MARKER} {TEXTING}. Default to 1-4 sentences and match their energy and length. {PLAIN}"
    f" {FORMAT} Use a list only when they ask for steps or the content really is a list."
    " Light, dry humor is fine when the moment invites it, never at their expense and never with"
    " bad news. Asked what you think, pick one and say why ('I'd go with X, because Y') instead"
    " of surveying options. Prices, availability and policies come only from a page read live"
    " this turn; label anything else unconfirmed, and never recommend using an unconfirmed number."
    " Long answers (code, plans, research) stay complete: lead with a"
    " one-line answer, then the detail in short paragraphs, code in code blocks. Before each"
    " multi-step chunk, send one short plain sentence saying what you're doing now and what comes"
    " next. Before a step they'll notice (email sent, form submitted, or page they must act on),"
    " tell them what's about to happen; report side effects and mistakes right away, plainly."
    " Keep progress to at most one update per roughly two actions, except for a noticeable step"
    " or mistake; say nothing extra for one quick action. Progress has no tool names, headings"
    " or step counters. In user-facing text, use task words ('I'm checking the airline's prices"
    " now'), not implementation words like workflow, tool call, MCP or tab id, unless they ask"
    " for technical details. When a new user message arrives mid-task, acknowledge it in one line and"
    " fold it into the running task; don't restart. " + NEXT + " " + SAFE)


# Hermes suppresses a reply that is (or starts/ends with) one of these; any reply mentioning
# one is left exactly as written.
_SILENCE = re.compile(r"silent|no[ _]?reply|静默|沉默", re.IGNORECASE)
# A known assistant opener at the very start of the message. "Absolutely." can answer a yes/no
# question, so the bare words count only with "!". Openers with an apostrophe ("I'd be happy to
# help") can never pass the quote check below, so they are left to the voice note.
_OPENER = re.compile(
    r"(?:(?:certainly|absolutely|of course|sure thing)!"
    r"|(?:great question|good question|what a great question)[!.]) *\n?", re.IGNORECASE)
_CORNER_QUOTES = "「」『』﹁﹂﹃﹄"
# Every line break str.splitlines() honours except "\n": CR, VT, FF, FS, GS, RS, NEL, LS, PS.
_OTHER_LINE_BREAKS = ("\r\v\f"
                      "\x1c\x1d"  # file separator, group separator
                      "\x1e\x85"  # record separator, next line
                      "\u2028\u2029")  # line separator, paragraph separator


def _is_quote(ch):
    if ch in "'\"" or ch in _CORNER_QUOTES or unicodedata.category(ch) in ("Pi", "Pf"):
        return True
    name = unicodedata.name(ch, "")
    return "QUOTATION" in name or "APOSTROPHE" in name


def polish(text):
    """The send-time safety net, minimal by design: drop a known assistant opener ("Certainly!",
    "Great question.") at the very start of the message, and only when the whole message has no
    line break other than "\n", no indented line, no backtick and no quotation mark. Everything
    else, including any message with code or quotes, comes back byte-identical. Headings and
    bold are left to the voice note."""
    if (not isinstance(text, str) or _SILENCE.search(text) or "`" in text
            or any(ch in _OTHER_LINE_BREAKS for ch in text)
            or any(line[:1].isspace() for line in text.splitlines())
            or any(_is_quote(ch) for ch in text)):
        return text
    m = _OPENER.match(text)
    rest = text[m.end():] if m else ""
    # The opener takes only spaces on its own line and at most one "\n"; anything else
    # after it (a blank line, a tab) means the message is left alone.
    if not rest.strip() or rest[:1].isspace():
        return text
    return rest


GROUP = (" This is a group chat, maybe with other bots: answer whoever addressed you, keep it"
         " shorter still, and don't repeat what others already said.")


def session_env(name):
    try:
        from gateway.session_context import get_session_env
        return get_session_env(name) or ""
    except Exception:
        return ""


def note_for(user_message, *, platform, chat_type="", on=True):
    """The context a texting turn gets, or None. Pure, so the eval runs exactly this.
    ponytail: cron runs keep the default voice; Hermes hands hooks no public way to see a job's
    destinations (upstream gap in docs/voice.md)."""
    from .proactivity import BRIEF_MARKER, MARKER
    # Check-ins and the brief carry the same rules in their own prompts, with their own length.
    if not on or platform != "telegram" or str(user_message or "").startswith((MARKER, BRIEF_MARKER)):
        return None
    return NOTE + (GROUP if chat_type in ("group", "forum", "channel") else "")


class Voice:
    def __init__(self, ctx):
        self.ctx = ctx

    def mode(self):
        try:
            mode = (self.ctx.state.get(STATE_KEY) or {}).get("mode")
        except Exception:
            mode = None
        return mode if mode in MODES else "texting"

    def on(self):
        return self.mode() == "texting"

    def on_turn_start(self, user_message="", platform="", **kwargs):
        """pre_llm_call: the texting note for a Telegram turn. Reads plugin state only."""
        if not self.on():
            return None
        note = note_for(user_message, platform=platform, chat_type=session_env("HERMES_SESSION_CHAT_TYPE"))
        return {"context": note} if note else None

    def on_output(self, response_text="", platform="", **kwargs):
        """transform_llm_output: the polished final reply, or None to leave it as is."""
        if not self.on() or platform != "telegram":
            return None
        out = polish(response_text)
        return out if out != response_text else None

    def set(self, mode):
        if mode not in MODES:
            raise ValueError("usage: /tone [texting|default|status]")
        self.ctx.state.set(STATE_KEY, {"mode": mode})

    def status_text(self):
        if self.on():
            return "Texting voice is on for Telegram. Send /tone default to switch it off."
        return ("Telegram uses Hermes' default voice. Check-ins and the morning brief keep their own"
                " short style (/proactivity controls them). Send /tone texting to switch the texting"
                " voice back on.")

    def command(self, raw_args=""):
        """`/tone [texting|default|status]`. Plain text, never raises."""
        words = str(raw_args or "").lower().split()
        try:
            if words and words[0] != "status":
                if len(words) != 1:
                    raise ValueError("usage: /tone [texting|default|status]")
                self.set(words[0])
            return self.status_text()
        except ValueError as exc:
            return str(exc)
        except Exception as exc:
            return f"tone: {type(exc).__name__}"


def cli_setup(parser):
    parser.add_argument("mode", nargs="?", default="status", choices=["status", *MODES])


def cli_run(voice, args):
    if args.mode != "status":
        voice.set(args.mode)
    print(voice.mode())
    return 0
