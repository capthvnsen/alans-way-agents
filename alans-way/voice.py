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
_PH_OPEN, _PH_CLOSE = "", ""   # placeholder brackets (Unicode private use)
_PLACEHOLDER = re.compile(_PH_OPEN + r"(\d+)" + _PH_CLOSE)
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# Indented code, blockquotes and table rows are never rewritten.
_PROTECTED_LINE = re.compile(r"^(?: {4}|\t| {0,3}>|\s*\|)")
# Masked across the whole text, earliest match first, before any rewrite.
_SPAN = re.compile(
    r"(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)"            # code spans of any backtick count, any lines
    r"|\b(?:https?|ftp)://\S+|\bwww\.\S+"               # URLs
    r"|\]\([^)\n]*\)|<[^<>\n]+>"                        # link targets, autolinks, HTML tags
    r"|[\w.+-]+@[\w-]+\.[\w.-]+"                        # emails
    r"|\"[^\"]*\"|“[^”]*”|„[^“”]*[“”]|‚[^‘’]*[‘’]|‘[^’]*’"
    r"|«[^»]*»|‹[^›]*›|»[^«]*«|「[^」]*」|『[^』]*』"       # every quotation form
    r"|(?<![\w'])'[^'\n]+'(?![\w'])")                   # 'single quotes', not apostrophes
# Left over after masking, any of these opens something unclosed: the rest stays as written.
_UNCLOSED = re.compile(r"[`\"“„‚‘«‹「『]")
_HEADING = re.compile(r"^( {0,3})#{1,6}[ \t]+(?=[^\d\s])(.*?)(?:[ \t]+#+)?[ \t]*$")
_BOLD = re.compile(r"(?<!\w)\*\*(?=\S)(.+?)(?<=\S)\*\*(?!\w)")
_TIC = re.compile(
    # "Absolutely." can be the answer to a yes/no question, so the bare words go only with "!".
    r"^\s*(?:(?:certainly|absolutely|of course|sure thing)\s*!"
    r"|(?:great question|what a great question|good question)\s*[!.]"
    r"|i'?d be (?:happy|glad) to help(?: you)?(?: with (?:that|this))?\s*[!.]"
    r"|as an ai(?: language model| assistant)?,)\s*", re.IGNORECASE)


def _strip_tics(line):
    out = line
    while (m := _TIC.match(out)) and out[m.end():].strip():
        out = out[m.end():]
    if out is line or not re.match(r"[a-z][a-z' ]", out):   # leave iPhone, `git`, 3pm as written
        return out
    return out[:1].upper() + out[1:]


def _unbold_wall(paragraph):
    spans = _BOLD.findall(paragraph)
    bolded = sum(len(s) for s in spans)
    visible = len(_BOLD.sub(r"\1", paragraph).strip())
    # ponytail: five spans, or one span over 80% of a 40+ char paragraph, is a wall; tune here.
    if len(spans) >= 5 or (spans and visible >= 40 and bolded >= 0.8 * visible):
        return _BOLD.sub(r"\1", paragraph)
    return paragraph


def polish(text):
    """The send-time safety net: drop leading assistant tics, turn markdown headings into
    plain lines and unbold walls of bold. Everything that could be code, a link or a quotation
    is masked first and comes back byte for byte; when in doubt the text is left alone."""
    if (not isinstance(text, str) or not text.strip() or _SILENCE.search(text)
            or _PH_OPEN in text or _PH_CLOSE in text or re.search(r"<(?:pre|code)\b", text, re.I)):
        return text
    try:
        out = _polish(text)
    except Exception:   # a safety net must never block or drop a message
        return text
    return out if out.strip() and not _SILENCE.search(out) else text


def _polish(text):
    masks = []

    def mask(value):
        masks.append(value)
        return f"{_PH_OPEN}{len(masks) - 1}{_PH_CLOSE}"

    lines, fence = text.split("\n"), None
    for i, line in enumerate(lines):
        m = _FENCE.match(line)
        if fence is None and m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            fence = m.group(1)   # an unclosed fence protects everything after it
        elif fence and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
            fence = None
        elif fence is None and not _PROTECTED_LINE.match(line):
            continue
        lines[i] = mask(line)
    masked = _SPAN.sub(lambda m: mask(m.group()), "\n".join(lines))
    if leftover := _UNCLOSED.search(masked):
        masked = masked[:leftover.start()] + mask(masked[leftover.start():])

    lines = masked.split("\n")
    first = next(i for i, line in enumerate(lines) if line.strip())
    lines[first] = _strip_tics(lines[first])
    lines = [_HEADING.sub(r"\1\2", line) for line in lines]
    paragraphs = re.split(r"(\n[ \t]*\n)", "\n".join(lines))
    out = "".join(_unbold_wall(part) for part in paragraphs)
    while _PLACEHOLDER.search(out):   # a mask can hold earlier masks
        out = _PLACEHOLDER.sub(lambda m: masks[int(m.group(1))], out)
    return out


GROUP = (" This is a group chat, maybe with other bots: answer whoever addressed you, keep it"
         " shorter still, and don't repeat what others already said.")
CRON = " This run's result is sent to them as a Telegram message, so write it as one."


def session_env(name):
    try:
        from gateway.session_context import get_session_env
        return get_session_env(name) or ""
    except Exception:
        return ""


_CRON_SESSION = re.compile(r"cron_(.+)_\d{8}_\d{6}")


def cron_platforms(session_id):
    """Every platform a cron run's result goes to, from Hermes' own resolver; [] when unknown."""
    m = _CRON_SESSION.fullmatch(str(session_id or ""))
    if not m:
        return []
    try:
        from cron.jobs import get_job
        from cron.scheduler_delivery import _resolve_delivery_targets
        job = get_job(m.group(1))
        return [str(t.get("platform") or "").lower() for t in _resolve_delivery_targets(job)] if job else []
    except Exception:
        return []


def all_telegram(platforms):
    # Hermes delivers one shared cron result to every target, so a job that also goes to
    # Discord or email keeps the default voice everywhere.
    return bool(platforms) and all(p == "telegram" for p in platforms)


def note_for(user_message, *, platform, chat_type="", cron_targets=(), on=True):
    """The context a texting turn gets, or None. Pure, so the eval runs exactly this."""
    from .proactivity import BRIEF_MARKER, MARKER
    telegram = platform == "telegram" or (platform == "cron" and all_telegram(cron_targets))
    # Check-ins and the brief carry the same rules in their own prompts, with their own length.
    if not on or not telegram or str(user_message or "").startswith((MARKER, BRIEF_MARKER)):
        return None
    return NOTE + (CRON if platform == "cron" else GROUP if chat_type in ("group", "forum", "channel") else "")


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

    def on_turn_start(self, user_message="", platform="", session_id="", **kwargs):
        """pre_llm_call: the texting note for a Telegram-bound turn. Reads plugin state only."""
        if not self.on():
            return None
        note = note_for(user_message, platform=platform, chat_type=session_env("HERMES_SESSION_CHAT_TYPE"),
                        cron_targets=cron_platforms(session_id) if platform == "cron" else ())
        return {"context": note} if note else None

    def on_output(self, response_text="", platform="", session_id="", **kwargs):
        """transform_llm_output: the polished final reply, or None to leave it as is."""
        if not self.on():
            return None
        if platform != "telegram" and not (platform == "cron" and all_telegram(cron_platforms(session_id))):
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
