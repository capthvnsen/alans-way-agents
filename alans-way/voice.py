"""The texting voice for the bot's own replies in its chats: one set of tone rules shared with
check-ins and the brief, a per-turn note for the model, and a minimal send-time polish that only
drops a leading assistant opener. Fixed Hermes messages (approvals, errors, progress) have no
hook and are never touched. On by default; `/tone default` turns it off for this profile. It
layers on top of SOUL.md and agent.system_prompt and never writes either."""
import re
import unicodedata

STATE_KEY = "voice"
MODES = ("texting", "default")
NOTE_MARKER = "[Texting voice]"

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

NOTE = (
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
    + " Casual replies: 1-3 short sentences; match their energy and length. " + RECAP
    + " For casual replies and recaps, use at most 3 sentences total, including any offer of detail;"
    " no lists unless asked. Keep recaps to headline outcomes, without per-item evidence or history."
    " If their own persona or instructions ask for a different style or more detail, theirs wins.")


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
    if not on or platform not in CHAT_PLATFORMS or str(user_message or "").startswith((MARKER, BRIEF_MARKER)):
        return None
    note = NOTE + (GROUP if chat_type in ("group", "forum", "channel") else "")
    return note + ("\n" + SHORT_REPLY if wants_short_reply(user_message) else "")


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
        """pre_llm_call: the texting note for a chat-surface turn. Reads plugin state only."""
        if not self.on():
            return None
        note = note_for(user_message, platform=platform, chat_type=session_env("HERMES_SESSION_CHAT_TYPE"))
        return {"context": note} if note else None

    def on_output(self, response_text="", platform="", **kwargs):
        """transform_llm_output: the polished final reply, or None to leave it as is."""
        if not self.on() or platform not in CHAT_PLATFORMS:
            return None
        out = polish(response_text)
        return out if out != response_text else None

    def set(self, mode):
        if mode not in MODES:
            raise ValueError("usage: /tone [texting|default|status]")
        self.ctx.state.set(STATE_KEY, {"mode": mode})

    def status_text(self):
        if self.on():
            return "Texting voice is on for your chats. Send /tone default to switch it off."
        return ("Your chats use Hermes' default voice. Check-ins and the morning brief keep their own"
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
