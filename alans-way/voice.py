"""The texting voice for everything the bot sends to Telegram: one set of tone rules shared with
check-ins and the brief, a per-turn note for the model, and a deterministic polish at send time.
On by default; `/tone default` turns it off for this profile. It layers on top of SOUL.md and
agent.system_prompt and never writes either."""
import re

STATE_KEY = "voice"
MODES = ("texting", "default")
NOTE_MARKER = "[Texting voice]"
SILENT = ("[SILENT]", "SILENT", "NO_REPLY", "NO REPLY")   # Hermes' suppression markers, passed through

# Shared by proactivity.py's check-ins and the reply note, so both sound like one person.
TEXTING = "Write like a sharp, warm friend texting them on Telegram"
PLAIN = ("Use plain words and contractions, with no greeting, preamble or filler such as"
         " 'Certainly!', 'Great question' or 'I'd be happy to'.")
FORMAT = ("Plain text or light formatting Telegram renders (bold, italic, code), never headings,"
          " tables or walls of bold; emoji only if they use them.")
NEXT = ("End with a short question or offer only when there's a real next step; otherwise just"
        " stop.")
SAFE = ("This changes tone only: approvals, CAPTCHA handbacks and safety checks work exactly as"
        " before, and say plainly when something failed.")

NOTE = (
    f"{NOTE_MARKER} {TEXTING}. Default to 1-4 sentences and match their energy and length. {PLAIN}"
    f" {FORMAT} Use a list only when they ask for steps or the content really is a list."
    " Light, dry humor is fine when the moment invites it, never at their expense and never with"
    " bad news. Asked what you think, pick one and say why ('I'd go with X, because Y') instead"
    " of surveying options. Long answers (code, plans, research) stay complete: lead with a"
    " one-line answer, then the detail in short paragraphs, code in code blocks. Before a long"
    " multi-step task, say in one short line what you're doing first. " + NEXT + " " + SAFE)


_FENCE = re.compile(r"^\s*(```|~~~)")
_QUOTE = re.compile(r"^\s*>")
# Inline code, URLs and quoted text are masked before any rewrite and restored after.
_MASK = re.compile(r"`[^`\n]*`|\bhttps?://\S+|\"[^\"\n]*\"|“[^”\n]*”")
_HEADING = re.compile(r"^(\s*)#{1,6}\s+(.*?)(?:\s+#+)?\s*$")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_TIC = re.compile(
    r"^\s*(?:(?:certainly|absolutely|of course|sure thing|great question|what a great question"
    r"|good question)\s*[!.]"
    r"|i'?d be (?:happy|glad) to help(?: you)?(?: with (?:that|this))?\s*[!.]"
    r"|as an ai(?: language model| assistant)?,)\s*", re.IGNORECASE)


def _strip_tics(line):
    out = line
    while (m := _TIC.match(out)) and out[m.end():].strip():
        out = out[m.end():]
    if out is line:
        return line
    return out[:1].upper() + out[1:]


def _unbold_wall(paragraph):
    spans = _BOLD.findall(paragraph)
    bolded = sum(len(s) for s in spans)
    visible = len(_BOLD.sub(r"\1", paragraph).strip())
    # ponytail: three spans, or one span over 80% of a 40+ char paragraph, is a wall; tune here.
    if len(spans) >= 3 or (spans and visible >= 40 and bolded >= 0.8 * visible):
        return _BOLD.sub(r"\1", paragraph)
    return paragraph


def polish(text):
    """The send-time safety net: drop leading assistant tics, turn markdown headings into
    plain lines and unbold walls of bold. Code, quotes, URLs and quoted text are untouched."""
    if not isinstance(text, str) or not text.strip() or text.strip() in SILENT:
        return text
    lines, masks, fenced = text.split("\n"), [], False
    prose = []  # indexes of lines that may be rewritten
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced and not _QUOTE.match(line):
            prose.append(i)

    def mask(m):
        masks.append(m.group())
        return f"\x00{len(masks) - 1}\x00"

    for i in prose:
        lines[i] = _MASK.sub(mask, lines[i])
    if prose and prose[0] == next(i for i, line in enumerate(lines) if line.strip()):
        lines[prose[0]] = _strip_tics(lines[prose[0]])
    for i in prose:
        lines[i] = _HEADING.sub(r"\1\2", lines[i])
    # Paragraphs: runs of consecutive non-blank prose lines.
    run = []
    for i in prose + [None]:
        if i is not None and lines[i].strip() and (not run or run[-1] == i - 1):
            run.append(i)
            continue
        if run:
            block = _unbold_wall("\n".join(lines[j] for j in run)).split("\n")
            for j, new in zip(run, block):
                lines[j] = new
        run = [i] if i is not None and lines[i].strip() else []
    out = "\n".join(lines)
    return re.sub(r"\x00(\d+)\x00", lambda m: masks[int(m.group(1))], out)


GROUP = (" This is a group chat, maybe with other bots: answer whoever addressed you, keep it"
         " shorter still, and don't repeat what others already said.")
CRON = " This run's result is sent to them as a Telegram message, so write it as one."


def session_env(name):
    try:
        from gateway.session_context import get_session_env
        return get_session_env(name) or ""
    except Exception:
        return ""


def to_telegram(platform):
    """A gateway turn in a Telegram chat, or a cron run whose output is delivered to Telegram.
    ponytail: cron publishes only its first delivery target; a job whose first target is
    elsewhere stays in the default voice (upstream: expose every target to hooks)."""
    return platform == "telegram" or (
        platform == "cron" and session_env("HERMES_CRON_AUTO_DELIVER_PLATFORM").lower() == "telegram")


def note_for(user_message, *, platform, chat_type="", deliver="", on=True):
    """The context a texting turn gets, or None. Pure, so the eval runs exactly this."""
    from .proactivity import BRIEF_MARKER, MARKER
    telegram = platform == "telegram" or (platform == "cron" and deliver.lower() == "telegram")
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

    def on_turn_start(self, user_message="", platform="", **kwargs):
        """pre_llm_call: the texting note for a Telegram-bound turn. Reads plugin state only."""
        note = note_for(user_message, platform=platform, on=self.on(),
                        chat_type=session_env("HERMES_SESSION_CHAT_TYPE"),
                        deliver=session_env("HERMES_CRON_AUTO_DELIVER_PLATFORM"))
        return {"context": note} if note else None

    def on_output(self, response_text="", platform="", **kwargs):
        """transform_llm_output: the polished final reply, or None to leave it as is."""
        if not to_telegram(platform) or not self.on():
            return None
        out = polish(response_text)
        return out if out != response_text else None

    def on_tool_call(self, tool_name="", args=None, **kwargs):
        """pre_tool_call: polish a send_message the model addresses to Telegram (CAPTCHA and
        handback pings go out this way mid-turn)."""
        if tool_name != "send_message" or not isinstance(args, dict) or not self.on():
            return None
        if args.get("action", "send") != "send" or not isinstance(args.get("message"), str):
            return None
        if str(args.get("target") or "").split(":", 1)[0].strip().lower() != "telegram":
            return None
        out = polish(args["message"])
        return {"action": "modify", "args": {"message": out}} if out != args["message"] else None

    def set(self, mode):
        if mode not in MODES:
            raise ValueError("usage: /tone [texting|default|status]")
        self.ctx.state.set(STATE_KEY, {"mode": mode})

    def status_text(self):
        if self.on():
            return "Texting voice is on for Telegram. Send /tone default to switch it off."
        return "Telegram uses Hermes' default voice. Send /tone texting to switch the texting voice back on."

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
