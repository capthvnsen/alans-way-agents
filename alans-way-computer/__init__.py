"""Alan's Way computer-use provider (`computer_use.backend: alans-way-computer`).

Hermes registers this through ctx.register_computer_use_provider; the ComputerUseProvider API only exists in Hermes
builds after PR #133556, so on older Hermes register() logs and does nothing (the class markers above stay in the
first 8 KB, which is how Hermes classifies this directory as a provider and keeps it out of the general plugin load).

Transport: the same workspace router the profile already runs as its `workspace_browser` MCP server
(mcp_servers.workspace_browser in config.yaml, written by setup-workspace.sh). One router child per backend, JSON-RPC
over its stdio, so host-to-VM failover is the router's. The host enforces target-app and idle checks for foreground
input. Prefer set_value for a named field; free typing depends on the host's support."""

from __future__ import annotations

import collections
import itertools
import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading

log = logging.getLogger(__name__)

try:
    from tools.computer_use.backend import ActionResult, CaptureResult, ComputerUseBackend, ComputerUseProvider, UIElement
    _HAVE_API = True
except ImportError:
    ActionResult = CaptureResult = UIElement = None
    ComputerUseBackend = ComputerUseProvider = object
    _HAVE_API = False

NAME = "alans-way-computer"
START_TIMEOUT = 30
CALL_TIMEOUT = 110  # above the router's own hard caps (80s, batch 100s), so its answer wins
PAGES_PER_TICK = 0.25  # the stock tool scrolls in wheel ticks, the app in pages
# DISPLAY, XAUTHORITY and DBUS_SESSION_BUS_ADDRESS are not secrets: the router
# child's VM-desktop fallback needs the X display and session bus the gateway
# runs under (a dbus-daemon socket outside /run/user on hosts without one).
_SAFE_ENV = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR", "ALLUSERSPROFILE", "APPDATA",
             "COMSPEC", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "PATHEXT", "PROGRAMDATA", "PROGRAMFILES",
             "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERNAME", "USERPROFILE", "WINDIR",
             "DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"}
_CODES = {"stale_ref", "stale_window", "unsupported_action", "off_limits", "in_front", "no_window", "not_found", "bad_request", "failed",
          "locked", "permission", "timeout", "unresponsive", "focus_unverified"}
# The router passes the app's error text through without its code, so most codes are read back from the text.
_INFER = (("off limits", "off_limits"), ("in front", "in_front"), ("no window", "no_window"), ("no control at that point", "not_found"),
          ("not found", "not_found"), ("stale", "stale_ref"), ("screen is locked", "locked"), ("accessibility is off", "permission"),
          ("screen recording is off", "permission"), ("not responding", "unresponsive"), ("timed out", "timeout"),
          ("which field has focus", "focus_unverified"))
# What to do next, appended to every error with that code.
_NEXT = {
    "stale_window": "Capture the intended window again before acting; check its state before repeating an action.",
    "stale_ref": "That control changed since your element list: capture again for fresh element numbers.",
    "locked": "Nothing can be read or driven until the user unlocks it; then capture again.",
    "permission": "Ask the user to turn it on for alans-way-localapp in System Settings > Privacy & Security, then retry.",
    "in_front": "The user is using this app right now: wait a few seconds and retry once, then tell the user briefly if it still refuses. Never ask for approval per action.",
    "no_window": "Its windows are closed, minimized or on another Space: ask the user to open one on this Space, then capture again.",
    "off_limits": "It stays off limits: do not retry or work around it; tell the user.",
    "not_found": "Call list_apps if the app may have quit, otherwise capture again and use an element number from that list.",
    "unresponsive": "The app is hung: do not repeat the action; wait a moment, then capture to see whether it ran.",
    "timeout": "It may still have run: capture to see the app's state before retrying.",
    "focus_unverified": "Capture again, then retry once.",
}
CHANGES_SHOWN = 12
# The mac and Windows helpers keep a ref on its own control across generations and check each ref's identity; the
# Linux helper (the VM desktop, or a Linux computer) numbers refs by position and guards them with a whole-tree
# generation check, so there a reply is described, never folded in.
_STABLE_REFS = {"mac", "windows"}
# ponytail: one share and one reach for every app, tune them if real apps misjudge. Measured coverage: the bench
# fixture 0.41, Calculator 0.52, Messages 0.61, Finder 0.88, and Preview showing a PDF (pixels) 0.31.
MIN_COVERAGE = 0.35  # share of the window named controls must cover for som to leave the screenshot out
NEAR = 120  # screen points around the acted-on control in which a change counts as the action's effect
_LOST = ("NOT retried", "connection dropped")
_MANAGED = {"node", "npm", "npx", "uv", "uvx"}


def _router_block():
    try:
        from hermes_cli.config import load_config_readonly
        block = ((load_config_readonly() or {}).get("mcp_servers") or {}).get("workspace_browser")
    except Exception:
        return None
    return block if isinstance(block, dict) and block.get("command") else None


def _launch(block, *, spawn=True):
    """(argv, env), resolved the way Hermes resolves an mcp_servers stdio command. spawn=False is the cheap
    availability check: for Hermes-managed launchers like node it never provisions anything."""
    env = {k: v for k, v in os.environ.items() if k.upper() in _SAFE_ENV or k.startswith("XDG_")}
    env.update({str(k): str(v) for k, v in (block.get("env") or {}).items()})
    try:
        from hermes_constants import get_hermes_home
        env["HERMES_HOME"] = str(get_hermes_home())
    except ImportError:
        if "HERMES_HOME" not in env and os.environ.get("HERMES_HOME"):
            env["HERMES_HOME"] = os.environ["HERMES_HOME"]
    command = os.path.expanduser(str(block["command"]).strip())
    try:
        if spawn or re.sub(r"\.(cmd|exe)$", "", command, flags=re.I) not in _MANAGED:
            from tools.mcp_tool_config import _resolve_stdio_command
            command, env = _resolve_stdio_command(command, env)
        elif not _managed_present(command, env):
            raise RuntimeError(f"{command!r} is not installed and Hermes cannot provide it")
    except ImportError:
        command = shutil.which(command, path=env.get("PATH")) or command
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"cannot resolve {command!r}: {e}") from e
    if not (os.path.isfile(command) or shutil.which(command, path=env.get("PATH"))):
        raise RuntimeError(f"{command!r} is not on PATH (the workspace router is a node script)")
    return [command, *map(str, block.get("args") or [])], env


def _managed_present(command, env):
    if shutil.which(command, path=env.get("PATH")):
        return True
    try:
        from hermes_constants import with_hermes_node_path
        if shutil.which(command, path=with_hermes_node_path({"PATH": ""})["PATH"]):
            return True
    except Exception:
        pass
    try:  # Hermes provisions it on first spawn
        import pm
        return pm.get_package("npm" if command.startswith(("node", "np")) else "uv").missing_reason(pm.current_target()) is None
    except Exception:
        return False


def _available():
    block = _router_block()
    if not block:
        return False
    try:
        _launch(block, spawn=False)
    except RuntimeError:
        return False
    return True


class _Dead(Exception):
    """The router died or stopped answering; it was killed and the next call starts a fresh one."""


class _Unavailable(_Dead):
    """The router could not be started."""


class _HostChanged(_Dead):
    """The router answered from a different machine than before; every pid and element number is void."""


class _ToolError(Exception):
    """The router answered with isError; args[0] is its text, .code a code it passed through, if any."""

    def __init__(self, text, code=None):
        super().__init__(text)
        self.code = code


class _Router:
    def __init__(self, on_reset):
        self._on_reset = on_reset
        self._lock = threading.RLock()
        self._wlock = threading.Lock()
        self._proc = None
        self._pending = {}
        self._ids = itertools.count(1)
        self._stderr = collections.deque(maxlen=10)

    def ensure(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return
            self.kill()
            block = _router_block()
            if not block:
                raise _Unavailable("this profile has no mcp_servers.workspace_browser block; run setup-workspace.sh")
            try:
                argv, env = _launch(block)
                # The private child uses Hermes's approval gate; the agent-facing
                # connector excludes desktop input unless the operator opted in.
                env["HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS"] = "1"
                proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        env=env, text=True, encoding="utf-8", errors="replace")
            except (OSError, RuntimeError) as e:
                raise _Unavailable(str(e)) from e
            self._proc = proc
            threading.Thread(target=self._read, args=(proc,), daemon=True).start()
            threading.Thread(target=lambda: [self._stderr.append(l.rstrip()) for l in proc.stderr], daemon=True).start()
            try:
                self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                         "clientInfo": {"name": NAME, "version": "0.1.0"}}, START_TIMEOUT)
                self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            except _Dead as e:
                tail = "; ".join(list(self._stderr))
                self.kill()
                raise _Unavailable(f"router did not start ({e}){': ' + tail if tail else ''}") from e

    def call(self, name, arguments, timeout):
        self.ensure()
        return self._rpc("tools/call", {"name": name, "arguments": arguments}, timeout)

    def kill(self):
        with self._lock:
            proc, self._proc = self._proc, None
            self._on_reset()
            if proc is None:
                return
            for stop in (proc.stdin.close, proc.terminate):
                try:
                    stop()
                except OSError:
                    pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    def _send(self, message):
        try:
            with self._wlock:
                self._proc.stdin.write(json.dumps(message) + "\n")
                self._proc.stdin.flush()
        except (OSError, ValueError, AttributeError) as e:
            raise _Dead(f"write failed: {e}") from e

    def _rpc(self, method, params, timeout):
        proc, rid, done, box = self._proc, next(self._ids), threading.Event(), {}
        self._pending[rid] = (done, box, proc)
        try:
            self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            if not done.wait(timeout):
                raise _Dead(f"no answer in {timeout}s")
        except _Dead:
            self._pending.pop(rid, None)
            self.kill()
            raise
        if "msg" not in box:
            self.kill()
            raise _Dead("router exited")
        if "error" in box["msg"]:
            raise _ToolError((box["msg"]["error"] or {}).get("message", "router error"))
        return box["msg"]["result"]

    def _read(self, proc):
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict) and "id" in msg and ("result" in msg or "error" in msg):
                slot = self._pending.pop(msg["id"], None)
                if slot:
                    slot[1]["msg"] = msg
                    slot[0].set()
        for rid, slot in list(self._pending.items()):
            if slot[2] is proc:
                self._pending.pop(rid, None)
                slot[0].set()


def _unpack(result):
    items = result.get("content") or []
    texts = [i.get("text", "") for i in items if i.get("type") == "text"]
    if result.get("isError"):
        code = result.get("code") or (result.get("structuredContent") or {}).get("code")
        raise _ToolError(texts[0] if texts else "failed", code if isinstance(code, str) and re.fullmatch(r"[a-z_]+", code) else None)
    host = ((result.get("_meta") or {}).get("workspace") or {}).get("host")
    return items, texts, host


def _json(text):
    try:
        body = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


class AlansWayComputerBackend(ComputerUseBackend):
    def __init__(self, permission_mode="standard"):
        # The cua driver's permission modes do not apply; the host's target, idle and secure-field checks always do.
        self.permission_mode = permission_mode
        self._router = _Router(self._reset)
        self._reset()

    def _reset(self):
        self._pid = self._app = self._host = None
        self._window_id = None
        self._tree = None  # {"pid", "gen", "els"}: the elements the model's indexes refer to
        self._shot = None  # window geometry of the last screenshot; None means coordinates are screen pixels
        self._last_target = self._last_app = None
        self._os = None  # the apps reply's host: mac, windows, linux or vps; None until list_apps answers

    def _seen(self, host):
        """Note which machine answered. True when it is not the one the current state came from (state is dropped)."""
        changed = host is not None and self._host is not None and host != self._host
        if changed:
            self._reset()
        if host is not None:
            self._host = host
        return changed

    def start(self):
        try:
            self._router.ensure()
        except _Dead as e:
            raise RuntimeError(f"workspace router unavailable: {e}") from e

    def stop(self):
        self._router.kill()

    def is_available(self):
        return _available()

    # -- transport

    def _call(self, name, args, *, retry=False):
        for attempt in (0, 1):
            try:
                return self._router.call(name, args, CALL_TIMEOUT)
            except _Unavailable:
                raise
            except _Dead:
                if attempt or not retry:
                    raise

    def list_apps(self):
        try:
            _, texts, host = _unpack(self._call("workspace_computer_apps", {}, retry=True))
            self._seen(host)
        except _ToolError as e:
            raise RuntimeError(str(e)) from e
        except _Dead as e:
            raise RuntimeError(f"workspace router: {e}") from e
        body = _json(texts[0] if texts else "")
        self._os = body.get("host") if isinstance(body.get("host"), str) else None
        return [{"name": a.get("name", ""), "bundle_id": a.get("bundleId", ""), "pid": a.get("pid"),
                 "frontmost": bool(a.get("frontmost"))} for a in body.get("apps", [])]

    def _resolve(self, app, *, launch=False):
        wanted = app.strip().lower()
        apps = self.list_apps()
        hits = [a for a in apps if wanted in (a["name"].lower(), a["bundle_id"].lower())] or [
            a for a in apps if wanted in a["name"].lower() or wanted in a["bundle_id"].lower()]
        if len(hits) != 1:
            names = ", ".join(f"{a['name']} (pid {a['pid']})" for a in (hits or apps))
            missing = f"{'Several apps match' if hits else 'No running app matches'} {app!r}: {names}"
            if not hits and launch:
                try:
                    _, status, _ = self._read("cua_alans_way_status", {}, self._host)
                    capabilities = _json(status[0] if status else "").get("capabilities")
                    if not isinstance(capabilities, list) or "computer-launch-v1" not in capabilities:
                        raise LookupError(missing)
                    args = {"app": app}
                    if self._host:
                        args["expect_host"] = "vm" if self._host in ("vps", "vm") else "computer"
                    _, texts, _ = self._read("workspace_computer_launch", args, self._host)
                except _ToolError as e:
                    if _coded(str(e), e.code)[0] in ("unsupported_action", "bad_request") or any(
                            marker in str(e).lower() for marker in ("unknown tool", "unknown browser tool", "cannot open apps by name")):
                        raise LookupError(missing) from e
                    raise
                body = _json(texts[0] if texts else "")
                if type(body.get("pid")) is not int or body["pid"] <= 0:
                    raise LookupError(missing)
                return body["pid"], body.get("name") or app
            raise LookupError(missing)
        return hits[0]["pid"], hits[0]["name"]

    def _target(self, pid, name):
        if pid != self._pid:
            self._tree = self._shot = None
            self._window_id = None
        self._pid, self._app = pid, name
        self._last_target, self._last_app = {"pid": pid, "window_id": self._window_id or 0}, name

    # -- capture

    def capture(self, mode="som", app=None, pid=None, window_id=None):
        for attempt in (0, 1):
            try:
                return self._capture(mode, app, pid, window_id)
            except _Unavailable as e:
                raise RuntimeError(f"workspace router unavailable: {e}") from e
            except _HostChanged as e:
                if attempt or not app:  # only a name can be re-resolved on the other machine
                    raise RuntimeError(f"{e}. Call list_apps, then capture with app=<name>.") from e
            except _Dead as e:
                if attempt:
                    raise RuntimeError(f"workspace router: {e}") from e
            except _ToolError as e:
                if e.code == "stale_window" or str(e).startswith("stale_window:"):
                    self._reset()
                code, message = _coded(str(e), e.code)
                raise RuntimeError(f"{code}: {message}" if code != "failed" else message) from e
            except LookupError as e:
                raise RuntimeError(str(e)) from e

    def _read(self, tool, args, before):
        out = _unpack(self._call(tool, args))
        if self._seen(out[2]):
            raise _HostChanged(f"The workspace switched from {before} to {out[2]}, so app ids and element numbers changed")
        return out

    def _window(self, body, expected):
        window_id = body.get("windowId", expected)
        if ("windowId" in body or window_id is not None) and (
                type(window_id) is not int or not 1 <= window_id <= 0xffffffff
                or expected is not None and window_id != expected):
            self._reset()
            raise _ToolError("stale_window: The reply does not identify the observed window.", "stale_window")
        return window_id

    def _capture(self, mode, app, pid, window_id=None):
        if window_id is not None and (type(window_id) is not int or not 0 <= window_id <= 0xffffffff):
            raise _ToolError("bad_request: window_id must be a positive window number.", "bad_request")
        if pid is not None:
            name = app or (self._app if pid == self._pid else f"pid {pid}")
        elif app:
            pid, name = self._resolve(app)
        elif self._pid is not None:
            pid, name = self._pid, self._app
        else:
            raise LookupError("capture needs app= (a name from list_apps) or pid=; the focused app is off limits")
        bound = self._window_id if pid == self._pid else None
        window_id = window_id or bound
        if pid == self._pid and window_id != bound:
            self._tree = self._shot = None
        since = self._tree["gen"] if self._tree and self._tree["pid"] == pid and window_id == bound else None
        before, notes, kept = self._host, [], [] if since is None else self._tree["notes"]
        els, gen = (self._tree["els"], self._tree["gen"]) if mode == "vision" and since is not None else ([], None)
        window = None
        if mode != "vision":
            args = {"pid": pid, "delta": True, **({"since": since} if since is not None else {}),
                    **({"windowId": window_id} if window_id is not None else {})}
            _, texts, _ = self._read("workspace_computer_snapshot", args, before)
            body = _json(texts[0] if texts else "")
            window_id = self._window(body, window_id)
            if "windowId" not in body and bound is None:
                window_id = None
            if (not _snapshot_valid(body, self._tree if since is not None else None)
                    or window_id != bound and not isinstance(body.get("elements"), list)):
                args.pop("since", None)
                if window_id is not None:
                    args["windowId"] = window_id
                _, texts, _ = self._read("workspace_computer_snapshot", args, before)
                body = _json(texts[0] if texts else "")
                window_id = self._window(body, window_id)
                if not _snapshot_valid(body, None) or not isinstance(body.get("elements"), list):
                    self._reset()
                    raise _ToolError("failed: Could not read a full snapshot; capture again.")
            notes = [t for t in texts[1:] if t]
            window = body.get("selectedWindow", body.get("window"))
            if body.get("unchanged") and since is not None:
                els, gen = self._tree["els"], self._tree["gen"]
            elif "changed" in body:
                self._merge(body)
                els, gen, kept = self._tree["els"], self._tree["gen"], self._tree["notes"]
            else:
                els, gen, kept = body.get("elements") or [], body.get("generation"), _tree_notes(body)
        named = any(map(_readable, els))
        coverage = None
        if (mode == "som" and named and isinstance(window, dict)
                and all(type(window.get(k)) in (int, float) and math.isfinite(window[k]) for k in ("x", "y", "width", "height"))
                and window["width"] > 0 and window["height"] > 0):
            coverage = _coverage(els, {"wx": window["x"], "wy": window["y"], "ww": window["width"], "wh": window["height"]})
        png = mime = shot = None
        width = height = 0
        if mode != "ax" and (coverage is None or coverage < MIN_COVERAGE):
            try:
                items, shot_texts, _ = self._read("workspace_computer_screenshot", {
                    "pid": pid, **({"windowId": window_id} if window_id is not None else {})}, before)
                image = next(i for i in items if i.get("type") == "image")
                geo = _json(shot_texts[0] if shot_texts else "")
                window_id = self._window(geo, window_id)
                if mode == "vision" and bound is None and "windowId" not in geo:
                    window_id = None
                win = geo["window"]
                png, mime = image["data"], image.get("mimeType", "image/jpeg")
                width, height = int(geo["imageWidth"]), int(geo["imageHeight"])
                if win["width"] > 0 and win["height"] > 0 and width > 0 and height > 0:
                    shot = {"wx": win["x"], "wy": win["y"], "ww": win["width"], "wh": win["height"], "iw": width, "ih": height}
            except (_ToolError, StopIteration, KeyError, TypeError, ValueError) as e:
                if isinstance(e, _ToolError) and e.code == "stale_window":
                    raise
                why = _coded(str(e), e.code)[1] if isinstance(e, _ToolError) else str(e)
                if mode == "vision":
                    raise RuntimeError(f"screenshot failed: {why}") from e
                if not named:
                    notes.append(f"Screenshot unavailable: {why}")
        # Older snapshots omit window geometry; their screenshot still supplies it.
        coverage = _coverage(els, shot) if mode == "som" and png and named and shot else None
        if coverage is not None and coverage >= MIN_COVERAGE:
            png = mime = shot = None
            width = height = 0
        self._target(pid, name)
        self._window_id = window_id
        self._last_target["window_id"] = window_id or 0
        self._tree, self._shot = ({"pid": pid, "gen": gen, "els": els, "notes": kept} if mode != "vision" else self._tree), shot
        if png:
            space = ("Coordinates are screenshot pixels" + ("; bounds in earlier element lists were screen pixels." if mode == "vision" else ".")
                     if shot else "The window size is unknown, so bounds and coordinate= are screen pixels.")
            notes.insert(0, space if mode == "vision" else f"No numbered overlays are drawn: use the element numbers listed. {space}")
            if coverage is not None:
                notes.insert(0, f"Named controls cover only {coverage:.0%} of the window, so the screenshot is attached.")
            elif mode == "som" and named:
                notes.insert(0, "The window size is unknown, so the screenshot is attached.")
        elif mode == "som" and named:
            notes.insert(0, "No screenshot is attached: act on element numbers. Bounds and coordinate= are screen pixels. "
                         "capture(mode='vision') shows the window if you need to see it.")
        elif mode == "ax":
            notes.insert(0, "No screenshot: element bounds and coordinate= are screen pixels.")
        if mode != "vision":
            notes += kept
        elements = [] if mode == "vision" else [
            UIElement(index=i, role=e.get("role", ""), label=_label(e), bounds=self._bounds(e), app=name, pid=pid,
                      window_id=window_id or 0, attributes={"value": e["value"]} if e.get("value") else {})
            for i, e in enumerate(els, 1) if e is not None]
        return CaptureResult(mode=mode, width=width, height=height, png_b64=png, elements=elements, app=name,
                             png_bytes_len=len(png) * 3 // 4 if png else 0, image_mime_type=mime, note=" ".join(notes))

    def _bounds(self, e):
        if not all(k in e for k in ("x", "y", "width", "height")):
            return (0, 0, 0, 0)
        x, y, w, h = e["x"], e["y"], e["width"], e["height"]
        s = self._shot
        if not s:
            return (round(x), round(y), round(w), round(h))
        fx, fy = s["iw"] / s["ww"], s["ih"] / s["wh"]
        return (round((x - s["wx"]) * fx), round((y - s["wy"]) * fy), round(w * fx), round(h * fy))

    def _point(self, x, y):
        s = self._shot
        return {"x": round(s["wx"] + x * s["ww"] / s["iw"]), "y": round(s["wy"] + y * s["wh"] / s["ih"])} if s else {"x": round(x), "y": round(y)}

    def _element(self, index):
        els = self._tree["els"] if self._tree and self._tree["pid"] == self._pid else []
        return els[index - 1] if isinstance(index, int) and 1 <= index <= len(els) else None  # a gone slot is None

    def _center(self, index):
        e = self._element(index)
        if e is None or not all(k in e for k in ("x", "y", "width", "height")):
            return None
        return {"x": round(e["x"] + e["width"] / 2), "y": round(e["y"] + e["height"] / 2)}

    # -- actions

    @staticmethod
    def _fail(action, code, message):
        return ActionResult(ok=False, action=action, code=code, message=message)

    def _no_target(self, action):
        return self._fail(action, "no_target", "No app is targeted. Call capture(app=...) first.")

    def _limits(self, action, delivery_mode, bring_to_front, modifiers=None):
        if modifiers:
            return self._fail(action, "unsupported_action", "Modifier keys are not available with pointer actions. Use key for shortcuts.")
        return None

    def _error(self, action, text, code=None):
        if code == "host_changed" or text.startswith("host_changed:") or any(marker in text for marker in _LOST):
            self._reset()
            return self._fail(action, "host_changed", f"{text} App ids and element numbers are gone: call list_apps and capture again.")
        if code == "stale_window" or text.startswith("stale_window:"):
            self._reset()
        return self._fail(action, *_coded(text, code))

    def _merge(self, body):
        """Fold an action reply into the element list the model's numbers refer to; returns [(number, element)] that
        are new or changed, and [(number, element)] that disappeared. A gone element leaves a None slot so no number
        ever shifts. Only for hosts in _STABLE_REFS."""
        tree = self._tree if self._tree and self._tree["pid"] == self._pid else None
        if tree is None or body.get("unchanged") or not isinstance(body.get("generation"), int):
            return [], []
        els = tree["els"]
        at = {e["ref"]: i for i, e in enumerate(els) if e is not None}
        if isinstance(body.get("elements"), list):
            now = {e["ref"]: e for e in body["elements"]}
            gone = [ref for ref in at if ref not in now]
            changed = [e for ref, e in now.items() if ref not in at or els[at[ref]] != e]
        else:
            gone = [ref for ref in body.get("removed") or [] if ref in at]
            changed = body.get("changed") or []
        if body.get("truncated"):
            gone = []  # the app's walk hit its cap: a control missing from a cut list may still be there
        lost = []
        for ref in gone:
            i = at.pop(ref)
            lost.append((i + 1, els[i]))
            els[i] = None
        out = []
        for e in changed:
            if e["ref"] in at:
                els[at[e["ref"]]] = e
            else:
                els.append(e)
                at[e["ref"]] = len(els) - 1
            out.append((at[e["ref"]] + 1, e))
        tree["gen"], tree["notes"] = body["generation"], _tree_notes(body)
        return out, lost

    def _diff(self, body):
        """For hosts whose refs follow position: ([appeared], [vanished]) by role and label against the held list,
        which stays as it is, generation included, so the helper's whole-tree check still refuses an old number."""
        tree = self._tree if self._tree and self._tree["pid"] == self._pid else None
        if tree is None or body.get("unchanged") or not isinstance(body.get("generation"), int):
            return [], []
        old = [e for e in tree["els"] if e is not None]
        if isinstance(body.get("elements"), list):
            new = body["elements"]
        else:
            by_ref = {e["ref"]: e for e in old}
            for ref in body.get("removed") or []:
                by_ref.pop(ref, None)
            by_ref.update((e["ref"], e) for e in body.get("changed") or [])
            new = list(by_ref.values())
        was, now = collections.Counter(map(_key, old)), collections.Counter(map(_key, new))
        return _pick(new, now - was), [] if body.get("truncated") else _pick(old, was - now)

    def _run(self, action, step, *, bring_to_front=False):
        if self._pid is None:
            return self._no_target(action)
        if self._window_id is not None:
            step["windowId"] = self._window_id
        tree = self._tree if self._tree and self._tree["pid"] == self._pid else None
        if tree and tree["gen"] is not None:
            step["generation"] = tree["gen"]  # every action, not just ref ones: the reply is then a delta against it
        target_ref = step.get("ref")
        acted = next((e for e in tree["els"] if e and e["ref"] == target_ref), None) if tree and target_ref else None
        box = _box(acted) if acted else (step["x"], step["y"], step["x"], step["y"]) if "x" in step else None
        if bring_to_front:
            binding = {k: step[k] for k in ("windowId", "generation") if k in step}
            step = {"action": "batch", "steps": [{"action": "activate"}, step], **binding}
        before = self._host
        if before is not None:
            step["expect_host"] = "vm" if before in ("vps", "vm") else "computer"
        try:
            _, texts, host = _unpack(self._call("workspace_computer_action", {"pid": self._pid, **step}))
        except _ToolError as e:
            return self._error(action, str(e), e.code)
        except _Unavailable as e:
            return self._fail(action, "unavailable", f"The workspace router is unavailable: {e}")
        except _Dead as e:
            return self._fail(action, "host_changed", f"The workspace connection dropped ({e}) and was restarted, possibly on another machine. "
                              "App ids and element numbers are gone, and the action may not have happened. Call list_apps and capture again.")
        if self._seen(host):
            return self._fail(action, "host_changed", f"The workspace switched from {before} to {host} before this action ran, so it was aimed "
                              "at an app that no longer exists there and may not have happened. App ids and element numbers are gone: "
                              "call list_apps and capture again.")
        body = _json(texts[0] if texts else "")
        try:
            self._window(body, self._window_id)
        except _ToolError as e:
            return self._fail(action, "stale_window", _coded(str(e), e.code)[1])
        if bring_to_front:
            failed = next((r for r in body.get("results", []) if r.get("error") or r.get("ok") is False), None)
            if failed:
                return self._error(action, f"{failed.get('error') or 'The action failed.'} Capture before continuing; earlier steps may have run.", failed.get("code"))
        held = tree["notes"] if tree else []
        parts, effect = [f"{action} sent to {self._app}."], None
        if self._os in _STABLE_REFS:
            changed, gone = self._merge(body)
            if changed or gone:
                parts.append("The element list is updated, so no capture is needed to read the result.")
                parts += [f"Changed: {_listed(changed)}." if changed else "", f"Gone: {_listed(gone)}." if gone else ""]
                # A ticking clock elsewhere also changes: only a change at or near the target confirms the action.
                if any(e.get("ref") == target_ref or _near(e, box) for _, e in changed + gone):
                    effect = "confirmed"
        else:
            appeared, vanished = self._diff(body)
            if appeared or vanished:
                parts += [f"Now shown: {_listed(appeared)}." if appeared else "", f"Gone: {_listed(vanished)}." if vanished else "",
                          "Element numbers here follow position and may now point at other controls: capture before acting by number."]
        if body.get("unchanged"):
            parts.append("The app's element tree did not change. If the effect only shows in pixels, capture(mode='vision') to check before retrying.")
        parts += [*(n for n in _tree_notes(body) if n not in held), *texts[1:]]
        return ActionResult(ok=True, action=action, message=" ".join(p for p in parts if p), effect=effect,
                            meta={k: v for k, v in (("host", host), ("generation", body.get("generation"))) if v is not None})

    def _by_element_or_point(self, action, step, element, x, y, *, bring_to_front=False):
        if self._pid is None:
            return self._no_target(action)
        if element is not None:
            e = self._element(element)
            if e is None:
                gone = isinstance(element, int) and self._tree and 1 <= element <= len(self._tree["els"])
                return self._fail(action, "no_such_element", f"Element {element} " + (
                    "disappeared after an earlier action. Use a number from the latest list, or capture again." if gone
                    else "is not in the last capture. Capture again."))
            return self._run(action, {**step, "ref": e["ref"]}, bring_to_front=bring_to_front)
        if x is not None and y is not None:
            return self._run(action, {**step, **self._point(x, y)}, bring_to_front=bring_to_front)
        return self._fail(action, "bad_request", f"{action} needs an element or a coordinate.")

    def click(self, *, element=None, x=None, y=None, button="left", click_count=1, modifiers=None, delivery_mode=None, bring_to_front=False):
        action = {2: "double_click"}.get(click_count, "right_click" if button == "right" else "click")
        if bad := self._limits(action, delivery_mode, bring_to_front, modifiers):
            return bad
        if button == "middle" or click_count not in (1, 2) or (button == "right" and click_count != 1):
            return self._fail(action, "unsupported_action", "Only single left clicks, double clicks and single right clicks are available.")
        verb = action if action != "click" or element is None else "press"
        return self._by_element_or_point(action, {"action": verb}, element, x, y, bring_to_front=bring_to_front or delivery_mode == "foreground")

    def drag(self, *, from_element=None, to_element=None, from_xy=None, to_xy=None, button="left", modifiers=None, delivery_mode=None, bring_to_front=False):
        if bad := self._limits("drag", delivery_mode, bring_to_front, modifiers):
            return bad
        if button != "left":
            return self._fail("drag", "unsupported_action", "Only the left button can drag.")
        start = self._center(from_element) if from_element is not None else self._point(*from_xy) if from_xy else None
        end = self._center(to_element) if to_element is not None else self._point(*to_xy) if to_xy else None
        if not start or not end:
            return self._fail("drag", "bad_request", "drag needs two elements that have a position in the last capture, or two coordinates.")
        return self._run("drag", {"action": "drag", "x": start["x"], "y": start["y"], "x2": end["x"], "y2": end["y"]},
                         bring_to_front=bring_to_front or delivery_mode == "foreground")

    def scroll(self, *, direction, amount=3, element=None, x=None, y=None, modifiers=None, delivery_mode=None, bring_to_front=False):
        if bad := self._limits("scroll", delivery_mode, bring_to_front, modifiers):
            return bad
        step = {"action": "scroll", "direction": direction, "amount": round(min(max(amount * PAGES_PER_TICK, 0.1), 10), 2)}
        if element is None and (x is None or y is None):
            return self._run("scroll", step, bring_to_front=bring_to_front or delivery_mode == "foreground")
        return self._by_element_or_point("scroll", step, element, x, y, bring_to_front=bring_to_front or delivery_mode == "foreground")

    # Hosts without free typing refuse in their helper and point to set_value.
    def type_text(self, text, *, delivery_mode=None, bring_to_front=False):
        if bad := self._limits("type", delivery_mode, bring_to_front):
            return bad
        result = self._run("type", {"action": "type", "text": text}, bring_to_front=bring_to_front or delivery_mode == "foreground")
        if not result.ok and "needs a ref" in (result.message or ""):
            return self._fail("type", result.code, result.message + " Use set_value(element=<field number>, value=<text>) to replace a field's text, or key for shortcuts.")
        return result

    def set_value(self, value, element=None):
        if element is None:
            return self._fail("set_value", "unsupported_action", "set_value needs an element number.")
        return self._by_element_or_point("set_value", {"action": "type", "text": value}, element, None, None)

    def key(self, keys, *, delivery_mode=None, bring_to_front=False):
        if bad := self._limits("key", delivery_mode, bring_to_front):
            return bad
        return self._run("key", {"action": "hotkey", "keys": keys} if "+" in keys and len(keys) > 1 else {"action": "key", "key": keys},
                         bring_to_front=bring_to_front or delivery_mode == "foreground")

    def focus_app(self, app, raise_window=False):
        try:
            pid, name = self._resolve(app, launch=True)
        except LookupError as e:
            return self._fail("focus_app", "not_found", str(e))
        except RuntimeError as e:
            return self._fail("focus_app", "unavailable", str(e))
        except _ToolError as e:
            return self._error("focus_app", str(e), e.code)
        except _Unavailable as e:
            return self._fail("focus_app", "unavailable", str(e))
        except _Dead as e:
            self._reset()
            return self._fail("focus_app", "host_changed", f"{e}. Call list_apps and capture again before continuing.")
        self._target(pid, name)
        if raise_window:
            return self._run("focus_app", {"action": "activate"})
        return ActionResult(ok=True, action="focus_app", message=f"Targeting {name} (pid {pid}). Capture before acting.")


def _snapshot_valid(body, tree):
    if isinstance(body.get("elements"), list):
        return True
    if not any(k in body for k in ("unchanged", "changed", "removed")):
        return True  # Older helpers can return only a note when there is no tree.
    if tree is None or type(body.get("generation")) is not int:
        return False
    if body.get("unchanged"):
        return body["generation"] == tree["gen"] and "changed" not in body and "removed" not in body
    changed, removed = body.get("changed"), body.get("removed")
    if body["generation"] == tree["gen"] or not isinstance(changed, list) or not isinstance(removed, list):
        return False
    refs = [e.get("ref") for e in changed if isinstance(e, dict)]
    if len(refs) != len(changed) or any(not isinstance(ref, str) or not ref for ref in refs + removed):
        return False
    known = {e["ref"] for e in tree["els"] if e is not None}
    return (len(set(refs)) == len(refs) and len(set(removed)) == len(removed)
            and not set(refs).intersection(removed) and set(removed) <= known)


def _coded(text, code=None):
    """(code, message with the next step) for an error text the router passed through."""
    m = re.match(r"([a-z_]+): (.*)", text, re.S)
    if code:
        message = m.group(2) if m and m.group(1) == code else text
    elif m and m.group(1) in _CODES:
        code, message = m.group(1), m.group(2)
    else:
        code, message = next((c for needle, c in _INFER if needle in text.lower()), "failed"), text
    return code, f"{message} {_NEXT[code]}" if code in _NEXT else message


def _readable(e):
    return bool(e and (e.get("name") or e.get("value")))


def _key(e):
    return e.get("role", ""), _label(e)


def _pick(els, extra):
    """The elements of els that account for the counts in extra, a Counter of _key."""
    out = []
    for e in els:
        if extra[_key(e)] > 0:
            extra[_key(e)] -= 1
            out.append(e)
    return out


def _box(e):
    return (e["x"], e["y"], e["x"] + e["width"], e["y"] + e["height"]) if all(k in e for k in ("x", "y", "width", "height")) else None


def _near(e, box):
    """True when e lies within NEAR screen points of the acted-on box."""
    b = _box(e)
    return bool(box and b) and b[0] < box[2] + NEAR and box[0] - NEAR < b[2] and b[1] < box[3] + NEAR and box[1] - NEAR < b[3]


def _coverage(els, shot):
    """Share of the window, sampled on a 40x40 grid, that readable elements cover; 0 without window geometry."""
    if not shot:
        return 0.0
    boxes = [b for b in (_box(e) for e in els if _readable(e)) if b]
    points = [(shot["wx"] + (i + .5) * shot["ww"] / 40, shot["wy"] + (j + .5) * shot["wh"] / 40) for i in range(40) for j in range(40)]
    return sum(any(x0 <= x < x1 and y0 <= y < y1 for x0, y0, x1, y1 in boxes) for x, y in points) / len(points)


def _listed(pairs_or_els):
    """'#3 AXRow 'name'; ...' for (number, element) pairs, or 'AXRow 'name'' for bare elements. Past CHANGES_SHOWN
    entries the remaining numbers are still named (a gone element is in no later capture); bare ones are counted."""
    items = [x if isinstance(x, tuple) else (None, x) for x in pairs_or_els]
    text = "; ".join(f"{'' if n is None else f'#{n} '}{e.get('role', '')} {_label(e)[:80]!r}" for n, e in items[:CHANGES_SHOWN])
    rest = items[CHANGES_SHOWN:]
    if not rest:
        return text
    return text + (f"; +{len(rest)} more" if rest[0][0] is None else "; also " + ", ".join(f"#{n}" for n, _ in rest))


def _tree_notes(body):
    """The app's own words about a tree: why it is empty, what is scrolled away, whether it was cut."""
    notes = [body["note"]] if isinstance(body.get("note"), str) and body["note"] else []
    if isinstance(body.get("hidden"), int) and body["hidden"] > 0:
        notes.append(f"{body['hidden']} more controls are scrolled out of view; scroll to reach them.")
    if body.get("truncated"):
        notes.append("The element list was cut at the app's cap; some controls are missing.")
    return notes


def _label(e):
    name = e.get("name", "")
    return f"{name} = {e['value']}" if e.get("value") else name


class AlansWayComputerProvider(ComputerUseProvider):
    name = NAME
    display_name = "Alan's Way native app control through Alan's Workspace (VM fallback)"

    def create_backend(self, *, permission_mode):
        return AlansWayComputerBackend(permission_mode)

    def is_available(self):
        return _available()

    def doctor(self):
        block = _router_block()
        if not block:
            print("FAIL no mcp_servers.workspace_browser block in this profile's config.yaml; run setup-workspace.sh")
            return 1
        try:
            argv, env = _launch(block)
            probe = subprocess.run([*argv, "--probe"], capture_output=True, text=True, timeout=40, env=env)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            print(f"FAIL router probe could not run: {e}")
            return 1
        print(f"ok   workspace_browser block: {' '.join(argv)}")
        lines = probe.stdout.strip().splitlines()
        line = lines[-1] if lines else ""
        if line.startswith("vps"):
            print(f"warn your computer is unreachable, so the VM desktop answers ({line})")
            return 0
        if re.match(r"[a-z]+: ", line):
            print(f"ok   your computer is reachable ({line})")
            return 0
        print(f"FAIL router probe printed no decision: {probe.stderr.strip()[-300:]}")
        return 1


def register(ctx):
    register_provider = getattr(ctx, "register_computer_use_provider", None)
    if not _HAVE_API or register_provider is None:
        log.info("%s: this Hermes has no computer-use provider API (register_computer_use_provider); not registering.", NAME)
        return
    register_provider(AlansWayComputerProvider())
