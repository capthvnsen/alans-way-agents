"""Alan's Way computer-use provider (`computer_use.backend: alans-way-computer`).

Hermes registers this through ctx.register_computer_use_provider; the ComputerUseProvider API only exists in Hermes
builds after PR #133556, so on older Hermes register() logs and does nothing (the class markers above stay in the
first 8 KB, which is how Hermes classifies this directory as a provider and keeps it out of the general plugin load).

Transport: the same workspace router the profile already runs as its `workspace_browser` MCP server
(mcp_servers.workspace_browser in config.yaml, written by setup-workspace.sh). One router child per backend, JSON-RPC
over its stdio, so host-to-VM failover is the router's. Alan's Way never takes focus: input is delivered in the
background, focus_app only retargets, and the stock `type` (no field) has no equivalent; use set_value."""

from __future__ import annotations

import collections
import concurrent.futures
import itertools
import json
import logging
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
_SAFE_ENV = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "SHELL", "TMPDIR", "ALLUSERSPROFILE", "APPDATA",
             "COMSPEC", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "PATHEXT", "PROGRAMDATA", "PROGRAMFILES",
             "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "TMP", "USERNAME", "USERPROFILE", "WINDIR"}
_CODES = {"stale_ref", "unsupported_action", "off_limits", "in_front", "no_window", "not_found", "bad_request", "failed"}
_INFER = (("off limits", "off_limits"), ("in front", "in_front"), ("no window", "no_window"), ("no control at that point", "not_found"),
          ("not found", "not_found"), ("stale", "stale_ref"))
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
                # The provider is the approval-gated desktop path (Hermes asks
                # before every action), so its private router child may still
                # serve workspace_computer_action; the agent-facing managed
                # block excludes it unless the operator opted in.
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
        # The cua driver's permission modes do not apply; the app's own policy (no focus, no keychains) always does.
        self.permission_mode = permission_mode
        self._router = _Router(self._reset)
        self._reset()

    def _reset(self):
        self._pid = self._app = self._host = None
        self._tree = None  # {"pid", "gen", "els"}: the elements the model's indexes refer to
        self._shot = None  # window geometry of the last screenshot; None means coordinates are screen pixels
        self._last_target = self._last_app = None

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
        return [{"name": a.get("name", ""), "bundle_id": a.get("bundleId", ""), "pid": a.get("pid"),
                 "frontmost": bool(a.get("frontmost"))} for a in _json(texts[0] if texts else "").get("apps", [])]

    def _resolve(self, app):
        wanted = app.strip().lower()
        apps = self.list_apps()
        hits = [a for a in apps if wanted in (a["name"].lower(), a["bundle_id"].lower())] or [
            a for a in apps if wanted in a["name"].lower() or wanted in a["bundle_id"].lower()]
        if len(hits) != 1:
            names = ", ".join(f"{a['name']} (pid {a['pid']})" for a in (hits or apps))
            raise LookupError(f"{'Several apps match' if hits else 'No running app matches'} {app!r}: {names}")
        return hits[0]["pid"], hits[0]["name"]

    def _target(self, pid, name):
        if pid != self._pid:
            self._tree = self._shot = None
        self._pid, self._app = pid, name
        self._last_target, self._last_app = {"pid": pid, "window_id": 0}, name

    # -- capture

    def capture(self, mode="som", app=None, pid=None, window_id=None):
        for attempt in (0, 1):
            try:
                return self._capture(mode, app, pid)
            except _Unavailable as e:
                raise RuntimeError(f"workspace router unavailable: {e}") from e
            except _HostChanged as e:
                if attempt or not app:  # only a name can be re-resolved on the other machine
                    raise RuntimeError(f"{e}. Call list_apps, then capture with app=<name>.") from e
            except _Dead as e:
                if attempt:
                    raise RuntimeError(f"workspace router: {e}") from e
            except (_ToolError, LookupError) as e:
                raise RuntimeError(str(e)) from e

    def _gather(self, jobs):
        """Results of (tool, args) jobs, run concurrently over the one router; a failed job is its exception."""
        def one(job):
            try:
                return _unpack(self._call(*job))
            except (_ToolError, _Dead) as e:
                return e
        if len(jobs) == 1:
            return [one(jobs[0])]
        with concurrent.futures.ThreadPoolExecutor(len(jobs)) as pool:
            return list(pool.map(one, jobs))

    def _checked(self, out, before):
        if isinstance(out, Exception):
            raise out
        if self._seen(out[2]):
            raise _HostChanged(f"The workspace switched from {before} to {out[2]}, so app ids and element numbers changed")
        return out

    def _capture(self, mode, app, pid):
        if pid is not None:
            name = app or (self._app if pid == self._pid else f"pid {pid}")
        elif app:
            pid, name = self._resolve(app)
        elif self._pid is not None:
            pid, name = self._pid, self._app
        else:
            raise LookupError("capture needs app= (a name from list_apps) or pid=; the focused app is off limits")
        since = self._tree["gen"] if self._tree and self._tree["pid"] == pid else None
        jobs = []
        if mode != "vision":
            jobs.append(("workspace_computer_snapshot", {"pid": pid, **({"since": since} if since is not None else {})}))
        if mode != "ax":
            jobs.append(("workspace_computer_screenshot", {"pid": pid}))
        before, outs = self._host, self._gather(jobs)
        tree_out = self._checked(outs.pop(0), before) if mode != "vision" else None
        notes = [t for t in (tree_out[1][1:] if tree_out else []) if t]
        els, gen = (self._tree["els"], self._tree["gen"]) if mode == "vision" and self._tree and self._tree["pid"] == pid else ([], None)
        if tree_out:
            body = _json(tree_out[1][0] if tree_out[1] else "")
            if body.get("unchanged") and since is not None:
                els, gen = self._tree["els"], self._tree["gen"]
            else:
                els, gen = body.get("elements") or [], body.get("generation")
            if body.get("truncated"):
                notes.append("The element list was cut at the app's cap; some controls are missing.")
        png = mime = shot = None
        width = height = 0
        if mode != "ax":
            try:
                items, shot_texts, _ = self._checked(outs.pop(0), before)
                image = next(i for i in items if i.get("type") == "image")
                geo = _json(shot_texts[0] if shot_texts else "")
                win = geo["window"]
                png, mime = image["data"], image.get("mimeType", "image/jpeg")
                width, height = int(geo["imageWidth"]), int(geo["imageHeight"])
                if win["width"] > 0 and win["height"] > 0 and width > 0 and height > 0:
                    shot = {"wx": win["x"], "wy": win["y"], "ww": win["width"], "wh": win["height"], "iw": width, "ih": height}
            except (_ToolError, StopIteration, KeyError, TypeError, ValueError) as e:
                if mode == "vision":
                    raise RuntimeError(f"screenshot failed: {e}") from e
                png = mime = None
                width = height = 0
                notes.append(f"Screenshot unavailable ({e}); use the element list.")
        self._target(pid, name)
        self._tree, self._shot = ({"pid": pid, "gen": gen, "els": els} if mode != "vision" else self._tree), shot
        if shot:
            notes.insert(0, "No numbered overlays are drawn: use the element numbers listed. Coordinates are screenshot pixels."
                         if mode != "vision" else "Coordinates are screenshot pixels.")
        elif mode == "ax":
            notes.insert(0, "No screenshot: element bounds and coordinate= are screen pixels.")
        elements = [] if mode == "vision" else [
            UIElement(index=i, role=e.get("role", ""), label=_label(e), bounds=self._bounds(e), app=name, pid=pid,
                      window_id=0, attributes={"value": e["value"]} if e.get("value") else {})
            for i, e in enumerate(els, 1)]
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
        return els[index - 1] if isinstance(index, int) and 1 <= index <= len(els) else None

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
        if delivery_mode == "foreground" or bring_to_front:
            return self._fail(action, "unsupported_action", "Alan's Way never takes the focused window, so foreground delivery is not available. Input is delivered in the background.")
        if modifiers:
            return self._fail(action, "unsupported_action", "Modifier keys are not available with pointer actions. Use key for shortcuts.")
        return None

    def _error(self, action, text, code=None):
        if any(marker in text for marker in _LOST):
            self._reset()
            return self._fail(action, "host_changed", f"{text} App ids and element numbers are gone: call list_apps and capture again.")
        m = re.match(r"([a-z_]+): (.*)", text, re.S)
        if code:
            message = m.group(2) if m and m.group(1) == code else text
        elif m and m.group(1) in _CODES:
            code, message = m.group(1), m.group(2)
        else:
            code, message = next((c for needle, c in _INFER if needle in text.lower()), "failed"), text
        if code == "stale_ref":
            message += " Capture again for fresh element numbers: the last action changed the app."
        return self._fail(action, code, message)

    def _run(self, action, step):
        if self._pid is None:
            return self._no_target(action)
        if "ref" in step:
            step["generation"] = self._tree["gen"]
        before = self._host
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
        message = f"{action} sent to {self._app}."
        if body.get("unchanged"):
            message += " The app's element tree did not change."
        message = " ".join([message, *[t for t in texts[1:] if t]])
        return ActionResult(ok=True, action=action, message=message, meta={k: v for k, v in (("host", host), ("generation", body.get("generation"))) if v is not None})

    def _by_element_or_point(self, action, step, element, x, y):
        if self._pid is None:
            return self._no_target(action)
        if element is not None:
            e = self._element(element)
            if e is None:
                return self._fail(action, "no_such_element", f"Element {element} is not in the last capture. Capture again.")
            return self._run(action, {**step, "ref": e["ref"]})
        if x is not None and y is not None:
            return self._run(action, {**step, **self._point(x, y)})
        return self._fail(action, "bad_request", f"{action} needs an element or a coordinate.")

    def click(self, *, element=None, x=None, y=None, button="left", click_count=1, modifiers=None, delivery_mode=None, bring_to_front=False):
        action = {2: "double_click"}.get(click_count, "right_click" if button == "right" else "click")
        if bad := self._limits(action, delivery_mode, bring_to_front, modifiers):
            return bad
        if button == "middle" or click_count not in (1, 2) or (button == "right" and click_count != 1):
            return self._fail(action, "unsupported_action", "Only single left clicks, double clicks and single right clicks are available.")
        verb = action if action != "click" or element is None else "press"
        return self._by_element_or_point(action, {"action": verb}, element, x, y)

    def drag(self, *, from_element=None, to_element=None, from_xy=None, to_xy=None, button="left", modifiers=None, delivery_mode=None, bring_to_front=False):
        if bad := self._limits("drag", delivery_mode, bring_to_front, modifiers):
            return bad
        if button != "left":
            return self._fail("drag", "unsupported_action", "Only the left button can drag.")
        start = self._center(from_element) if from_element is not None else self._point(*from_xy) if from_xy else None
        end = self._center(to_element) if to_element is not None else self._point(*to_xy) if to_xy else None
        if not start or not end:
            return self._fail("drag", "bad_request", "drag needs two elements that have a position in the last capture, or two coordinates.")
        return self._run("drag", {"action": "drag", "x": start["x"], "y": start["y"], "x2": end["x"], "y2": end["y"]})

    def scroll(self, *, direction, amount=3, element=None, x=None, y=None, modifiers=None, delivery_mode=None, bring_to_front=False):
        if bad := self._limits("scroll", delivery_mode, bring_to_front, modifiers):
            return bad
        step = {"action": "scroll", "direction": direction, "amount": round(min(max(amount * PAGES_PER_TICK, 0.1), 10), 2)}
        if element is None and (x is None or y is None):
            return self._run("scroll", step)
        return self._by_element_or_point("scroll", step, element, x, y)

    # A VM desktop the agent owns types at the focused window; a host whose
    # apps never take focus refuses in its helper and points to set_value.
    def type_text(self, text, *, delivery_mode=None, bring_to_front=False):
        if bad := self._limits("type", delivery_mode, bring_to_front):
            return bad
        result = self._run("type", {"action": "type", "text": text})
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
        return self._run("key", {"action": "hotkey", "keys": keys} if "+" in keys and len(keys) > 1 else {"action": "key", "key": keys})

    def focus_app(self, app, raise_window=False):
        try:
            pid, name = self._resolve(app)
        except LookupError as e:
            return self._fail("focus_app", "not_found", str(e))
        except RuntimeError as e:
            return self._fail("focus_app", "unavailable", str(e))
        self._target(pid, name)
        return ActionResult(ok=True, action="focus_app", message=f"Targeting {name} (pid {pid}). Alan's Way never raises or focuses windows; "
                            "input is delivered in the background.")


def _label(e):
    name = e.get("name", "")
    return f"{name} = {e['value']}" if e.get("value") else name


class AlansWayComputerProvider(ComputerUseProvider):
    name = NAME
    display_name = "Alan's Way (your computer, VM desktop as fallback)"

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
