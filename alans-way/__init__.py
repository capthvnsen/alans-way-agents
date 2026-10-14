"""Hermes plugin entry point: the Telegram texting voice, idle check-ins from the primary bot,
plus the workspace skills."""
from pathlib import Path
import os
import sys

from . import voice as voice_mod
from .proactivity import Proactivity, SCHEMA, cli_run, cli_setup
from .cross_bot import CrossBot, CROSS_SCHEMA


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
    skills = Path(__file__).parent / "skills"
    ctx.register_skill("workspace-operations", skills / "workspace-operations" / "SKILL.md")
    ctx.register_skill("workspace-setup", skills / "workspace-setup" / "SKILL.md")
    ctx.register_skill("web-errands", skills / "web-errands" / "SKILL.md")
    ctx.register_skill("integrations", skills / "integrations" / "SKILL.md")
    # Every profile: each bot's voice is its own profile's plugin state, on by default.
    voice = voice_mod.Voice(ctx)
    ctx.register_hook("pre_llm_call", voice.on_turn_start)
    ctx.register_hook("transform_llm_output", voice.on_output)
    ctx.register_command("tone", voice.command,
                         description="Telegram voice: texting (default) or Hermes' default voice",
                         args_hint="[texting|default|status]")
    if hasattr(ctx, "register_cli_command"):
        ctx.register_cli_command("tone", "The Telegram texting voice: status, texting or default",
                                 voice_mod.cli_setup, lambda args: voice_mod.cli_run(voice, args))
    primary = _primary_profile(ctx)
    runtime = Proactivity(ctx, legacy_home=(legacy_home or _owning_home()) if primary else None)
    runtime.primary = primary
    cross = CrossBot(ctx, runtime)
    runtime.cross_bot = cross
    # Collector and narrowing controls belong to every profile, before the
    # primary scheduler gate. Secondary bots still get no spontaneous check-ins.
    ctx.register_hook("pre_llm_call", cross.on_turn_start)
    ctx.register_hook("post_llm_call", cross.on_turn_end)
    ctx.register_hook("on_session_end", cross.on_session_end)
    ctx.register_tool(name="proactivity", toolset="proactivity", schema=SCHEMA if primary else CROSS_SCHEMA,
                      handler=runtime.tool if primary else cross.tool, check_fn=lambda: True)
    if primary:
        ctx.register_hook("pre_llm_call", runtime.on_turn_start)
        ctx.register_hook("post_llm_call", runtime.on_turn_end)
    ctx.register_command("proactivity", runtime.command if primary else cross.command,
                         description="Check-ins and cross-bot export: cross on|off|status (dispatch disabled)",
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
