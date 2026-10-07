"""Native gateway event hook; placement is an explicit opt-in, not a sandbox."""
from pathlib import Path
import importlib.util
import os
import sys


def _default_home():
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "hermes"
    return Path.home() / ".hermes"


def handle(event_type, context, *, home=None):
    if event_type != "gateway:startup":
        return
    source_home = Path(__file__).resolve().parents[2]
    actual_home = Path(os.environ.get("HERMES_HOME") or _default_home()).expanduser().resolve()
    # Under gateway.multiplex_profiles the one gateway:startup emit can land in
    # any served profile's hooks scope. A copy under <launch home>/profiles/<name>/hooks/
    # must still arm the launch home's plugin runtime, so it stamps both homes.
    # A copy under any other home stays inert.
    serves_launch_home = source_home.parent.name == "profiles" and source_home.parent.parent == actual_home
    if home is None and source_home != actual_home and not serves_launch_home:
        return
    bases = {source_home}
    if serves_launch_home:
        bases.add(actual_home)
    targets = set(bases) if home is None else {Path(home)}
    candidates = [
        base / suffix
        for base in bases
        for suffix in ("alans-way/gateway_guard.py",            # repo / copied layout
                       "plugins/alans-way/gateway_guard.py",    # installed ~/.hermes layout
                       "proactive-primary/gateway_guard.py",    # pre-rename repo layout
                       "plugins/proactive-primary/gateway_guard.py")
    ] + [
        Path(os.environ.get("HERMES_ALANS_WAY_PLUGIN") or os.environ.get("HERMES_PROACTIVE_PRIMARY_PLUGIN", "")).expanduser() / "gateway_guard.py"
        if os.environ.get("HERMES_ALANS_WAY_PLUGIN") or os.environ.get("HERMES_PROACTIVE_PRIMARY_PLUGIN") else None,
    ]
    path = next((c for c in candidates if c is not None and c.is_file() and not c.is_symlink()), None)
    if path is None:
        return
    spec = importlib.util.spec_from_file_location("companion_gateway_guard_hook", path)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for target in targets:
        module.mark_gateway_ready(target)
