"""PROTOTYPE (N6 spike, do not merge): a Hermes BrowserProvider that hands Hermes' browser tools,
and with them the credential vault, a scoped view of the workspace VPS Chromium.

Install as a user plugin: copy this directory to ~/.hermes/plugins/browser/alans-way-workspace/,
enable it, and set `browser.cloud_provider: alans-way-workspace`. `browser.cdp_url` must be unset:
a CDP override takes precedence over every provider.
"""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Dict

from agent.browser_provider import BrowserProvider

from .scoped_cdp_proxy import ScopedProxy


def _workspace_cdp_http() -> str:
    """The workspace Chromium's loopback CDP root, from the VPS browser host's own config."""
    if os.environ.get("ALANS_WAY_WORKSPACE_CDP"):
        return os.environ["ALANS_WAY_WORKSPACE_CDP"]
    data = os.environ.get("HERMES_VPS_BROWSER_DATA") or str(Path.home() / ".local/share/hermes-alans-way/browser")
    try:
        return json.loads((Path(data) / "config.json").read_text())["cdpUrl"]
    except (OSError, ValueError, KeyError):
        return ""


class WorkspaceBrowserProvider(BrowserProvider):
    def __init__(self) -> None:
        self._proxies: Dict[str, ScopedProxy] = {}

    @property
    def name(self) -> str:
        return "alans-way-workspace"

    @property
    def display_name(self) -> str:
        return "Alan's Workspace VPS browser (scoped, prototype)"

    def is_available(self) -> bool:
        return bool(_workspace_cdp_http())

    def create_session(self, task_id: str) -> Dict[str, object]:
        root = _workspace_cdp_http()
        if not root.startswith("http://127.0.0.1:"):
            raise ValueError("The workspace Chromium must be a loopback http CDP endpoint.")
        with urllib.request.urlopen(root.rstrip("/") + "/json/version", timeout=5) as response:
            upstream = json.load(response)["webSocketDebuggerUrl"]
        proxy = ScopedProxy(upstream).start()
        self._proxies[proxy.token] = proxy
        return {"session_name": f"alans-way-{task_id}", "bb_session_id": proxy.token,
                "cdp_url": proxy.ws_url, "features": {"scoped": True}}

    def close_session(self, session_id: str) -> bool:
        proxy = self._proxies.pop(session_id, None)
        if proxy is not None:
            proxy.stop()
        return True

    def emergency_cleanup(self, session_id: str) -> None:
        self.close_session(session_id)


def register(ctx) -> None:
    ctx.register_browser_provider(WorkspaceBrowserProvider())
