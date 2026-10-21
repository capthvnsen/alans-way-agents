"""Hermes plugin entry point: the Telegram texting voice, idle check-ins from the primary bot,
plus the workspace skills."""
from pathlib import Path
from copy import deepcopy
import os
import sys

from . import voice as voice_mod
from .proactivity import Proactivity, SCHEMA, cli_run, cli_setup
from .cross_bot import CrossBot, CROSS_SCHEMA, ASK_SCHEMA


TASK_NOTE = (
    "[Task completion] Work until every requested outcome is verified done or genuinely blocked."
    " For multi-step tasks, keep a short checklist of mini goals in Hermes's native todo tool"
    " when available, otherwise in working context. Verify each goal and mark it done, then continue to the next"
    " without waiting for 'keep going'. Real blockers require a user's login or CAPTCHA, approval"
    " or decision, information only they have, or a failure you cannot safely recover from with"
    " available tools. Finish independent authorized work before handing back. At a blocker,"
    " report what is done, what remains and exactly what is needed to resume."
    " Treat anything recalled from earlier chats or memory as history: before you present an old"
    " blocker, promise or pending task as current, check recent messages, and let a newer correction"
    " from them win. If you can't tell whether it still holds, say so."
    " When a task takes more than one quick step, start with one short line saying what you're"
    " doing, in task words. After that, send a one-line update only at a real milestone, when"
    " a step fails and you change course, or when a wait will be noticeable: say what you found"
    " or what comes next. Stay quiet through routine reads, navigation, saving and retries that"
    " succeed; add nothing for one quick action. Report side effects and mistakes right away,"
    " plainly. When a new user message arrives mid-task, confirm the change in one line in their"
    " words at your next step, then fold it into the running task; don't restart."
    " Before your final reply, check it against each thing they explicitly asked for (every filter,"
    " count, rating, deadline or format) and get any that are missing, trying the source's own page"
    " before saying a fact isn't available. If one truly can't be had, say which and why."
    " Never promise to message them later unless they asked or said yes and you saved a"
    " `cronjob_manage` job for this chat (`attach_to_session` true, no `deliver`); otherwise just answer now."
    " For a big multi-step job they want finished without check-ins, suggest starting it with /goal once;"
    " don't suggest it for small asks."
)


def task_context(**kwargs):
    return {"context": TASK_NOTE}


def _owning_home() -> Path:
    """The home Hermes bound for this plugin load, never the launch env.

    Under gateway multiplex one process serves every profile, and
    os.environ['HERMES_HOME'] keeps the launch profile's home. register() runs
    inside Hermes' plugin-load home scope, which get_hermes_home() reads."""
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home()).expanduser().absolute()
    except Exception:
        default = (Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "hermes"
                   if sys.platform == "win32" else Path.home() / ".hermes")
        return Path(os.environ.get("HERMES_HOME") or default).expanduser().absolute()


def _primary_profile(ctx) -> bool:
    """Only the launch (default/custom) profile's runtime may observe.

    A named secondary profile registers the same tools and commands against
    its own home, but proactivity belongs to the default/launch profile. A
    ctx without profile information (tests, non-gateway hosts) counts as
    primary.
    """
    try:
        name = getattr(ctx, "profile_name", None)
    except Exception:
        return True
    return name in (None, "", "default", "custom")


def register(ctx, *, legacy_home=None, background=True):
    ctx.register_hook("pre_llm_call", task_context)
    skills = Path(__file__).parent / "skills"
    ctx.register_skill("workspace-operations", skills / "workspace-operations" / "SKILL.md")
    ctx.register_skill("workspace-setup", skills / "workspace-setup" / "SKILL.md")
    ctx.register_skill("web-errands", skills / "web-errands" / "SKILL.md")
    ctx.register_skill("integrations", skills / "integrations" / "SKILL.md")
    # Every profile: each bot's voice is its own profile's plugin state, on by default.
    voice = voice_mod.Voice(ctx)
    ctx.register_hook("pre_llm_call", voice.on_turn_start)
    ctx.register_command("tone", voice.command,
                         description="Chat voice: texting (default) or Hermes' default voice",
                         args_hint="[texting|default|status]")
    if hasattr(ctx, "register_cli_command"):
        ctx.register_cli_command("tone", "The texting voice: status, texting or default",
                                 voice_mod.cli_setup, lambda args: voice_mod.cli_run(voice, args))
    primary = _primary_profile(ctx)
    runtime = Proactivity(ctx, legacy_home=(legacy_home or _owning_home()) if primary else None)
    runtime.primary = primary
    cross = CrossBot(ctx, runtime)
    if cross.active:
        primary = cross.profile == cross.primary
        runtime.primary = primary
    runtime.cross_bot = cross
    # First transform returning text wins; attribution must precede voice polish.
    ctx.register_hook("transform_llm_output", cross.on_output)
    ctx.register_hook("transform_llm_output", voice.on_output)
    ctx.register_hook("pre_tool_call", cross.on_tool_call)
    # Collector and narrowing controls belong to every profile, before the
    # primary scheduler gate. Secondary bots still get no spontaneous check-ins.
    ctx.register_hook("pre_llm_call", cross.on_turn_start)
    ctx.register_hook("post_llm_call", cross.on_turn_end)
    ctx.register_hook("on_session_end", cross.on_session_end)
    tool_handle = ask_handle = None
    def tools_after_activation():
        nonlocal tool_handle, ask_handle
        if ask_handle is not None:
            ask_handle.dispose()
            ask_handle = None
        if tool_handle is not None:
            tool_handle.dispose()
            tool_handle = None
        if not primary and not cross.active:
            return
        schema = SCHEMA if primary else CROSS_SCHEMA
        if primary and cross.active:
            schema = deepcopy(SCHEMA)
            schema["description"] += " " + CROSS_SCHEMA["description"]
            schema["parameters"]["properties"]["action"]["enum"].append("cross_status")
            schema["parameters"]["properties"]["cross_bot_enabled"] = {"type": "boolean"}
        if primary and cross.active and cross.profile == cross.primary:
            ask_handle = ctx.register_tool(name="cross_bot_ask", toolset="proactivity", schema=ASK_SCHEMA,
                                           handler=cross.ask, check_fn=lambda: cross.active and not cross.closed)
        tool_handle = ctx.register_tool(name="proactivity", toolset="proactivity", schema=schema,
                                        handler=runtime.tool if primary else cross.tool,
                                        check_fn=lambda: primary or cross.active)
    cross.on_activation = tools_after_activation
    tools_after_activation()
    if primary:
        ctx.register_hook("pre_llm_call", runtime.on_turn_start)
        ctx.register_hook("post_llm_call", runtime.on_turn_end)
    ctx.register_command("proactivity", runtime.command if primary else cross.command,
                         description="Check-ins and cross-bot export/receiver: cross on|off|status",
                         args_hint="[status|now|less|normal|more|pause|resume|hours|tz|brief|cross on|off|status]")
    if background:
        def connect(native=None, adapter=None, **kwargs):
            cross.on_telegram_connect(native, adapter, **kwargs)
            if primary:
                runtime.on_telegram_connect(native, adapter, **kwargs)
        ctx.register_platform_handler("telegram", connect)
    if hasattr(ctx, "register_cli_command"):
        ctx.register_cli_command("proactivity", "Local owner-DM binding, check-ins and cross-bot export", cli_setup,
                                 lambda args: cli_run(runtime, args))
    ctx.on_unload(runtime.close)
    ctx.on_unload(cross.close)
    return runtime if primary else None
