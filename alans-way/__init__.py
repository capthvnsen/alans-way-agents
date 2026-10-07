"""Hermes plugin entry point: idle check-ins from the primary bot, plus the workspace skills."""
from pathlib import Path
import os
import sys

from .proactivity import Proactivity, SCHEMA, cli_run, cli_setup


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
    if not _primary_profile(ctx):
        return None
    runtime = Proactivity(ctx, legacy_home=legacy_home or _owning_home())
    ctx.register_tool(name="proactivity", toolset="proactivity", schema=SCHEMA,
                      handler=runtime.tool, check_fn=lambda: True)
    ctx.register_hook("pre_llm_call", runtime.on_turn_start)
    ctx.register_hook("post_llm_call", runtime.on_turn_end)
    if background:
        ctx.register_platform_handler("telegram", runtime.on_telegram_connect)
    if hasattr(ctx, "register_cli_command"):
        ctx.register_cli_command("proactivity", "Idle check-ins from the primary bot", cli_setup,
                                 lambda args: cli_run(runtime, args))
    ctx.on_unload(runtime.close)
    return runtime
