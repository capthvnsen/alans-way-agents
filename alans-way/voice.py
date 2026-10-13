"""The texting voice for the bot's own replies on Telegram: one set of tone rules shared with
check-ins and the brief, a per-turn note for the model, and a deterministic polish of the final
reply. Fixed Hermes messages (approvals, errors, progress) have no hook and are never touched.
On by default; `/tone default` turns it off for this profile. It layers on top of SOUL.md and
agent.system_prompt and never writes either."""
import re

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
    " of surveying options. Long answers (code, plans, research) stay complete: lead with a"
    " one-line answer, then the detail in short paragraphs, code in code blocks. Before a long"
    " multi-step task, say in one short line what you're doing first. " + NEXT + " " + SAFE)


# Hermes suppresses a reply that is (or starts/ends with) one of these; any reply mentioning
# one is left exactly as written.
_SILENCE = re.compile(r"silent|no[ _]?reply|静默|沉默", re.IGNORECASE)
# A known assistant opener, only as the message's very first sentence. "Absolutely." can answer
# a yes/no question, so the bare words count only with "!".
_OPENER = re.compile(
    r"\s*(?:(?:certainly|absolutely|of course|sure thing)!"
    r"|(?:great question|good question|what a great question)[!.]"
    r"|(?:as an ai(?: language model| assistant)?, )?i'?d be (?:happy|glad) to help"
    r"(?: you)?(?: with (?:that|this))?[!.])\s*", re.IGNORECASE)
# Anything that could be code, a link or a quotation turns off all flattening for the message.
_UNSAFE = re.compile(
    r"[`'\"«»‹›“”‘’„‚「」『』]|\]\(|\[[^\]\n]+\]:|[a-z][a-z0-9+.-]*://|\bwww\.|<[a-z/!]|\S@\S"
    r"|^(?: {4}|\t| {0,3}>|[ \t]*\||[ \t]*~~~)", re.IGNORECASE | re.MULTILINE)
_HEADING = re.compile(r"^( {0,3})#{1,6}[ \t]+(?=[^\d\s])(.*?)(?:[ \t]+#+)?[ \t]*$", re.MULTILINE)
_BOLD = re.compile(r"(?<!\w)\*\*(?=\S)(.+?)(?<=\S)\*\*(?!\w)")


def _unbold_wall(paragraph):
    spans = _BOLD.findall(paragraph)
    bolded = sum(len(s) for s in spans)
    visible = len(_BOLD.sub(r"\1", paragraph).strip())
    # ponytail: five spans, or one span over 80% of a 40+ char paragraph, is a wall; tune here.
    if len(spans) >= 5 or (spans and visible >= 40 and bolded >= 0.8 * visible):
        return _BOLD.sub(r"\1", paragraph)
    return paragraph


def polish(text):
    """The send-time safety net, minimal by design:
    1. drop a known assistant opener when it is the message's very first sentence;
    2. only in a message with no code, link or quotation character at all, turn markdown
       headings into plain lines and unbold walls of bold.
    Anything else is returned exactly as written."""
    if not isinstance(text, str) or not text.strip() or _SILENCE.search(text):
        return text
    try:
        out = text
        m = _OPENER.match(out)
        if m and out[m.end():].strip():
            out = out[m.end():]
        if not _UNSAFE.search(text) and not _UNSAFE.search(out):
            out = _HEADING.sub(r"\1\2", out)
            out = "".join(_unbold_wall(part) for part in re.split(r"(\n[ \t]*\n)", out))
    except Exception:   # a safety net must never block or drop a message
        return text
    return out if out.strip() and not _SILENCE.search(out) else text


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
