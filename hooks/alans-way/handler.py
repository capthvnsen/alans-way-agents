"""Native gateway event hook; placement is an explicit opt-in, not a sandbox."""
from pathlib import Path
import importlib.util
import os


def handle(event_type, context, *, home=None):
    if event_type != "gateway:startup":
        return
    source_home = Path(__file__).resolve().parents[2]
    target_home = Path(home) if home is not None else source_home
    actual_home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser().absolute()
    if home is None and target_home.absolute() != actual_home:
        return
    candidates = [
        source_home / "alans-way/gateway_guard.py",                    # repo / copied layout
        source_home / "plugins/alans-way/gateway_guard.py",            # installed ~/.hermes layout
        source_home / "proactive-primary/gateway_guard.py",            # pre-rename repo layout
        source_home / "plugins/proactive-primary/gateway_guard.py",    # pre-rename installed layout
        Path(os.environ["HERMES_ALANS_WAY_PLUGIN"] or os.environ.get("HERMES_PROACTIVE_PRIMARY_PLUGIN", "")).expanduser() / "gateway_guard.py"
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
    module.mark_gateway_ready(target_home)
