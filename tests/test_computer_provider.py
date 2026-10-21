"""alans-way-computer provider: driven through Hermes main's own provider loader against a fake MCP router.

Hermes runs in a subprocess (HERMES_MAIN=<hermes checkout with .venv>), so the rest of the suite stays free of
Hermes internals. Without HERMES_MAIN the Hermes-backed tests skip; the static checks always run."""
from pathlib import Path
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "alans-way-computer"
NODE = shutil.which("node")  # absolute in the config: a bare `node` makes Hermes provision its own copy
HERMES_MAIN = Path(os.environ["HERMES_MAIN"]) if os.environ.get("HERMES_MAIN") else None
HERMES_PY = HERMES_MAIN and next((p for p in (HERMES_MAIN / ".venv/bin/python", HERMES_MAIN / ".venv/Scripts/python.exe") if p.exists()), None)
NEEDS_HERMES = unittest.skipUnless(HERMES_PY and NODE, "set HERMES_MAIN to a Hermes checkout with a .venv, and have node on PATH")

FAKE_ROUTER = r"""
const fs = require('fs');
const readline = require('readline');
if (process.argv.includes('--probe')) {
  process.stdout.write(fs.readFileSync(process.env.FAKE_PROBE, 'utf8') + '\n');
  process.exit(0);
}
const log = process.env.FAKE_LOG;
const ctlFile = process.env.FAKE_CTL;
const stateFile = process.env.FAKE_STATE;
const state = () => { try { return JSON.parse(fs.readFileSync(stateFile, 'utf8')); } catch { return { generation: 7 }; } };
const save = (s) => fs.writeFileSync(stateFile, JSON.stringify(s));
const out = (m) => process.stdout.write(JSON.stringify(m) + '\n');
const text = (o) => ({ content: [{ type: 'text', text: JSON.stringify(o) }] });
const fail = (message) => ({ isError: true, content: [{ type: 'text', text: message }] });
const APPS = [
  { name: 'Notes', bundleId: 'com.apple.Notes', pid: 101, frontmost: false },
  { name: 'Safari', bundleId: 'com.apple.Safari', pid: 102, frontmost: false },
  { name: 'Finder', bundleId: 'com.apple.finder', pid: 103, frontmost: true },
  { name: '1Password', bundleId: 'com.1password.1password', pid: 104, frontmost: false },
];
const tree = (generation) => ({ generation, elements: [
  { ref: 'c1', role: 'AXButton', name: 'Save', x: 300, y: 250, width: 100, height: 40 },
  { ref: 'c2', role: 'AXTextField', name: 'Title', value: 'hi', x: 100, y: 100, width: 200, height: 30 },
  { ref: 'c3', role: 'AXStaticText', name: 'No geometry' },
] });
const ctl = () => { try { const c = JSON.parse(fs.readFileSync(ctlFile, 'utf8')); fs.unlinkSync(ctlFile); return c; } catch { return {}; } };

readline.createInterface({ input: process.stdin }).on('line', (line) => {
  const msg = JSON.parse(line);
  if (msg.method === 'initialize') return out({ jsonrpc: '2.0', id: msg.id, result: { protocolVersion: '2024-11-05', capabilities: { tools: {} }, serverInfo: { name: 'fake-router', version: '0' } } });
  if (msg.method !== 'tools/call') return;
  const { name, arguments: args } = msg.params;
  fs.appendFileSync(log, JSON.stringify({ proc: process.pid, name, args, argv: process.argv.slice(2),
    allow: process.env.HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS || '' }) + '\n');
  const c = ctl();
  if (c.die_on === name) process.exit(1);
  const s = state();
  if (c.host) { s.host = c.host; save(s); }
  if (c.bump) { s.generation += 1; save(s); }
  if (c.noshot !== undefined) { s.noshot = c.noshot; save(s); }
  if (c.win0 !== undefined) { s.win0 = c.win0; save(s); }
  if (c.os) { s.os = c.os; save(s); }
  let result;
  if (name === 'workspace_computer_apps') result = text({ host: s.os || 'mac', apps: APPS });
  else if (c.error) result = fail(c.error);
  else if (args.pid === 103) result = fail('That app is the one in front. Leave it there; the pointer stays where it is.');
  else if (name === 'workspace_computer_snapshot') result = c.snap ? text({ ...tree(s.generation), ...c.snap })
    : args.since === s.generation ? text({ unchanged: true, generation: s.generation }) : text(tree(s.generation));
  else if (name === 'workspace_computer_screenshot' && s.noshot) result = fail('That app has no window to capture.');
  else if (name === 'workspace_computer_screenshot') result = { content: [{ type: 'image', data: Buffer.from('jpegbytes').toString('base64'), mimeType: 'image/jpeg' },
    { type: 'text', text: JSON.stringify({ imageWidth: 480, imageHeight: 300, window: { x: 100, y: 100, width: s.win0 ? 0 : 960, height: s.win0 ? 0 : 600 } }) }] };
  else if (name === 'workspace_computer_action') {
    if (c.lost) result = fail('This action was in flight when the Mac connection dropped. It may or may not have happened and was NOT retried. Check the page in the VPS tab before repeating it.');
    else if (c.nowindow) result = fail('That app has no window to send keys to.');
    else if (c.nocontrol) result = fail('No control at that point. Press a ref instead.');
    else if (c.coded) result = { isError: true, structuredContent: { code: 'off_limits' }, content: [{ type: 'text', text: 'Refused.' }] };
    else if (args.pid === 104) result = fail('off_limits: That app is off limits.');
    else if (args.ref !== undefined && args.generation !== s.generation) result = fail('stale_ref: The app changed since your snapshot. Take a fresh snapshot.');
    else if (args.action === 'drag' && args.x2 === undefined) result = fail('bad_request: drag needs x2 and y2.');
    else if (args.action === 'type' && args.ref === undefined && !c.desktop) result = fail('bad_request: type needs a ref.');
    else {
      if (!(c.reply && c.reply.unchanged)) { s.generation += 1; save(s); }
      result = text({ ok: true, generation: s.generation, ...(c.reply || { elements: tree(s.generation).elements }) });
    }
  } else result = fail('Unknown browser tool.');
  if (c.notice) result.content.push({ type: 'text', text: c.notice });
  result._meta = { workspace: { host: s.host || 'mac' } };
  out({ jsonrpc: '2.0', id: msg.id, result });
});
"""

# Runs inside Hermes' interpreter: real provider loader, real tool handler, scripted against the fake router.
DRIVER = r"""
import dataclasses, json, os, sys, time
from pathlib import Path
from hermes_constants import set_hermes_home_override

HOME, LOG, CTL = Path(os.environ["T_HOME"]), Path(os.environ["FAKE_LOG"]), Path(os.environ["FAKE_CTL"])
set_hermes_home_override(str(HOME))
R = {}

def calls(start=0):
    rows = [json.loads(l) for l in LOG.read_text().splitlines()] if LOG.exists() else []
    return rows[start:]

def mark():
    return len(calls())

def plain(x):
    return dataclasses.asdict(x) if dataclasses.is_dataclass(x) else x

def action_calls(since):
    return [c["args"] for c in calls(since) if c["name"] == "workspace_computer_action"]

from plugins.computer_use import discover_computer_use_providers, get_active_provider
from hermes_cli.plugins_manifest import _detect_kind_from_source

R["discovered"] = [n for n, _ in discover_computer_use_providers()]
R["kind"] = _detect_kind_from_source((HOME / "plugins/alans-way-computer/__init__.py").read_text()[:8192])
provider = get_active_provider()
R["provider"] = {"name": provider.name, "available": provider.is_available()}
(HOME / "empty").mkdir()
set_hermes_home_override(str(HOME / "empty"))
R["available_without_block"] = provider.is_available()
set_hermes_home_override(str(HOME))

be = provider.create_backend(permission_mode="standard")
be.start()
R["apps"] = be.list_apps()

m = mark()
cap = be.capture(mode="som", app="notes")
R["som"] = {"mode": cap.mode, "w": cap.width, "h": cap.height, "mime": cap.image_mime_type, "png": bool(cap.png_b64), "app": cap.app,
            "elements": [[e.index, e.role, e.label, list(e.bounds)] for e in cap.elements], "note": cap.note,
            "calls": [(c["name"], c["args"]) for c in calls(m)]}
R["target"] = [be._last_target, be._last_app]

m = mark()
ax = be.capture(mode="ax", app="Notes")
R["ax"] = {"png": ax.png_b64, "bounds": [list(e.bounds) for e in ax.elements], "n": len(ax.elements),
           "calls": [(c["name"], c["args"]) for c in calls(m)]}

# --- actions by element: every ref action carries the generation of the last capture
be.capture(mode="som", app="Notes")
m = mark()
R["click_el"] = plain(be.click(element=1)); R["click_el_call"] = action_calls(m)
m = mark(); R["after_click"] = plain(be.click(element=2)); R["after_click_call"] = action_calls(m)  # the reply's tree is held
CTL.write_text(json.dumps({"bump": True}))  # the app changes behind the provider's back
R["stale"] = plain(be.click(element=2))

be.capture(mode="som", app="Notes")
m = mark(); be.click(element=2, click_count=2); R["double"] = action_calls(m)
be.capture(mode="som", app="Notes")
m = mark(); be.click(element=2, button="right"); R["right"] = action_calls(m)
be.capture(mode="som", app="Notes")
m = mark(); R["no_geometry"] = plain(be.click(element=3)); R["no_geometry_call"] = action_calls(m)
R["bad_index"] = plain(be.click(element=99))

# --- coordinates: screenshot pixels in, screen pixels out
be.capture(mode="som", app="Notes")
be.capture(mode="vision", app="Notes")
m = mark(); be.click(x=100, y=75); R["click_xy"] = action_calls(m)
m = mark(); be.scroll(direction="down", amount=3, x=100, y=75); R["scroll_xy"] = action_calls(m)
m = mark(); be.scroll(direction="up"); R["scroll_plain"] = action_calls(m)
m = mark(); be.drag(from_xy=(0, 0), to_xy=(100, 75)); R["drag_xy"] = action_calls(m)
m = mark(); be.drag(from_element=1, to_element=2); R["drag_el"] = action_calls(m)
be.capture(mode="som", app="Notes")
m = mark(); be.set_value("hello", element=2); R["set_value"] = action_calls(m)
m = mark(); be.key("cmd+s"); R["key_combo"] = action_calls(m)
m = mark(); be.key("return"); R["key_plain"] = action_calls(m)
m = mark(); R["type_text_mac"] = plain(be.type_text("hi")); R["type_text"] = action_calls(m)

# --- som uses window coverage; the app's notes ride in the capture note
def captured(cap, m):
    return {"png": bool(cap.png_b64), "w": cap.width, "elements": [[e.index, e.label, list(e.bounds)] for e in cap.elements],
            "note": cap.note, "calls": [c["name"] for c in calls(m)]}
full = [{"ref": "c1", "role": "AXTextArea", "name": "Body", "x": 100, "y": 100, "width": 960, "height": 600}]
CTL.write_text(json.dumps({"snap": {"generation": 89, "elements": full,
                                    "window": {"x": 100, "y": 100, "width": 960, "height": 600}}}))
m = mark(); R["som_full"] = captured(be.capture(mode="som", pid=101), m)
unnamed = [{"ref": "c1", "role": "AXGroup", "name": "", "x": 300, "y": 250, "width": 100, "height": 40}]
CTL.write_text(json.dumps({"snap": {"generation": 90, "elements": unnamed, "hidden": 12}}))
m = mark(); R["som_unnamed"] = captured(be.capture(mode="som", pid=101), m)
CTL.write_text(json.dumps({"snap": {"generation": 91, "elements": [], "note": "No window of this app is readable: its windows are on another Space."}}))
m = mark(); R["som_empty"] = captured(be.capture(mode="som", pid=101), m)
CTL.write_text(json.dumps({"noshot": True, "snap": {"generation": 92, "elements": [], "note": "On another Space."}}))
R["som_noshot"] = captured(be.capture(mode="som", pid=101), mark())
CTL.write_text(json.dumps({"noshot": False, "win0": True, "snap": {"generation": 94}}))
R["som_win0"] = captured(be.capture(mode="som", pid=101), mark())
CTL.write_text(json.dumps({"win0": False, "snap": {"generation": 93}}))
be.capture(mode="ax", pid=101)

# --- action replies: a delta folds into the element list, gone numbers stay gone, nothing shifts
be.capture(mode="som", app="Notes")
gen = be._tree["gen"]
CTL.write_text(json.dumps({"reply": {"hidden": 4, "removed": ["c3"], "changed": [
    {"ref": "c2", "role": "AXTextField", "name": "Title", "value": "bye", "x": 100, "y": 100, "width": 200, "height": 30},
    {"ref": "c4", "role": "AXButton", "name": "Done", "x": 500, "y": 250, "width": 80, "height": 40}]}}))
m = mark(); R["delta"] = plain(be.click(element=1)); R["delta_call"] = action_calls(m)
R["delta_gone"] = plain(be.click(element=3))
CTL.write_text(json.dumps({"reply": {"changed": [], "removed": [], "hidden": 4}}))
m = mark(); be.click(element=4); R["delta_new_call"] = action_calls(m)
m = mark(); R["delta_capture"] = captured(be.capture(mode="ax"), m)
R["delta_gen"] = [gen, be._tree["gen"]]
CTL.write_text(json.dumps({"reply": {"removed": [], "changed": [
    {"ref": "c2", "role": "AXTextField", "name": "Title", "value": "tick", "x": 1000, "y": 650, "width": 50, "height": 20}]}}))
R["far"] = plain(be.click(element=1))
CTL.write_text(json.dumps({"reply": {"unchanged": True}}))
R["unchanged"] = plain(be.click(element=1))
CTL.write_text(json.dumps({"reply": {"elements": [
    {"ref": "c1", "role": "AXButton", "name": "Saved", "x": 300, "y": 250, "width": 100, "height": 40},
    {"ref": "c4", "role": "AXButton", "name": "Done", "x": 500, "y": 250, "width": 80, "height": 40}]}}))
R["whole"] = plain(be.click(element=4))
CTL.write_text(json.dumps({"reply": {"generation": None, "note": "unresponsive: the steps ran but the app stopped responding, so there is no tree."}}))
R["no_tree"] = plain(be.key("return"))

# --- error texts the router passes through become codes that say the next step
errors = {"locked": "The screen is locked, so apps cannot be read or driven. Ask the user to unlock it, then retry.",
          "permission": "Accessibility is off for this program. Turn it on in System Settings → Privacy & Security → Accessibility, then retry.",
          "unresponsive": "That app is not responding.", "timeout": "Computer helper timed out.",
          "no_window": "That app has no window to capture.", "stale": "stale_ref: c2 is gone or changed since your snapshot. Take a fresh snapshot."}
be.capture(mode="som", app="Notes")
for key, message in errors.items():
    CTL.write_text(json.dumps({"error": message}))
    R["err_" + key] = plain(be.key("return"))
CTL.write_text(json.dumps({"error": errors["locked"]}))
try:
    be.capture(mode="som", pid=101); R["err_capture"] = None
except Exception as e:
    R["err_capture"] = str(e)

def held():
    tree = be._tree or {}
    return [tree.get("gen"), [e and e.get("name") for e in tree.get("els", [])]]
rows = [{"ref": f"c{i}", "role": "AXRow", "name": n, "x": 100, "y": 100 + 30 * i, "width": 300, "height": 30}
        for i, n in enumerate(["a.txt", "b.txt", "c.txt", "d.txt"], 1)]

# --- the VM desktop numbers refs by position: a reply is described, the old generation is kept
try:
    CTL.write_text(json.dumps({"os": "vps"})); be.list_apps()
    CTL.write_text(json.dumps({"snap": {"elements": rows}})); be.capture(mode="ax", pid=101)
    win_gen = held()[0]
    CTL.write_text(json.dumps({"reply": {"elements": [dict(r, name=n) for r, n in zip(rows, ["a.txt", "c.txt", "d.txt"])]}}))
    m = mark()
    R["win_delete"] = plain(be.click(element=2))  # deletes b.txt: c.txt is now c2, d.txt is c3
    R["win_third"] = plain(be.click(element=3))  # the model's #3 was c.txt; c3 is now d.txt
    R["win_calls"] = action_calls(m)
    R["win_gen"] = [win_gen, *held()]
except Exception as e:
    R["win_error"] = repr(e)

# --- Windows keeps refs on their own controls: the same delete folds in and #3 still means c.txt
try:
    CTL.write_text(json.dumps({"os": "windows"})); be.list_apps()
    CTL.write_text(json.dumps({"snap": {"elements": rows}})); be.capture(mode="ax", pid=101)
    fold_gen = held()[0]
    CTL.write_text(json.dumps({"reply": {"changed": [], "removed": ["c2"]}}))
    m = mark()
    R["fold_delete"] = plain(be.click(element=2))
    CTL.write_text(json.dumps({"reply": {"changed": [], "removed": []}}))
    R["fold_third"] = plain(be.click(element=3))
    R["fold_calls"] = action_calls(m)
    R["fold_gen"] = [fold_gen, *held()]
except Exception as e:
    R["fold_error"] = repr(e)
CTL.write_text(json.dumps({"os": "mac"})); be.list_apps()

# --- unsupported actions never reach the router
m = mark()
R["unsupported"] = {
    "middle": plain(be.click(x=1, y=1, button="middle")),
    "modifier": plain(be.click(x=1, y=1, modifiers=["shift"])),
    "triple": plain(be.click(x=1, y=1, click_count=3)),
    "drag_right": plain(be.drag(from_xy=(0, 0), to_xy=(1, 1), button="right")),
    "set_value_no_el": plain(be.set_value("x")),
    "foreground": plain(be.click(x=1, y=1, delivery_mode="foreground")),
    "bring": plain(be.key("return", bring_to_front=True)),
}
R["unsupported_calls"] = action_calls(m)

# --- policy refusals
try:
    be.capture(mode="ax", app="Finder")
    R["in_front"] = None
except Exception as e:
    R["in_front"] = str(e)
R["focus_op"] = plain(be.focus_app("1Password"))
R["off_limits"] = plain(be.click(x=1, y=1))

# --- focus_app never focuses: it only retargets
m = mark()
R["focus"] = plain(be.focus_app("Safari", raise_window=True))
R["focus_calls"] = [c["name"] for c in calls(m)]
R["focus_target"] = [be._last_target, be._last_app]
R["focus_unknown"] = plain(be.focus_app("Nope"))
be.focus_app("Notes")

# --- host notice rides along
be.capture(mode="som", app="Notes")
CTL.write_text(json.dumps({"notice": "[workspace] Mac unreachable since now - routed to VPS browser."}))
R["notice"] = plain(be.click(element=1))

# --- child restart: read-only call retries once; an action reports host_changed and state is reset
procs_before = {c["proc"] for c in calls()}
CTL.write_text(json.dumps({"die_on": "workspace_computer_apps"}))
R["apps_after_death"] = [a["name"] for a in be.list_apps()]
R["procs_after_apps"] = len({c["proc"] for c in calls()} - procs_before)
be.capture(mode="som", app="Notes")
CTL.write_text(json.dumps({"die_on": "workspace_computer_action"}))
R["action_death"] = plain(be.click(element=1))
R["after_death_click"] = plain(be.click(element=1))
R["after_death_target"] = be._last_target
cap2 = be.capture(mode="ax", app="Notes")
R["recovered"] = len(cap2.elements)
last_proc = calls()[-1]["proc"]
be.stop()
time.sleep(0.5)
try:
    os.kill(last_proc, 0); R["stopped"] = False
except OSError:
    R["stopped"] = True


# --- host changes inside one router process: state must not survive them
b = provider.create_backend(permission_mode="standard"); b.start()
b.capture(mode="som", app="Notes")
CTL.write_text(json.dumps({"host": "vps"}))
R["flip_action"] = plain(b.click(element=1))
R["flip_state"] = [b._pid, b._last_target, b._tree, b._shot]
b.capture(mode="som", app="Notes")
R["flip_click_after"] = plain(b.click(element=1))
b.capture(mode="ax", app="Notes")
CTL.write_text(json.dumps({"host": "mac"}))
m = mark()
b.capture(mode="ax", app="Notes")  # apps answers from the other host: re-resolved, no stale pid reused
R["flip_read_calls"] = [c["name"] for c in calls(m)]
CTL.write_text(json.dumps({"host": "vps"}))
try:
    b.capture(mode="ax")  # cached pid, snapshot answers from the other host
    R["flip_cached_pid"] = None
except Exception as e:
    R["flip_cached_pid"] = str(e)
b.capture(mode="ax", app="Notes")
CTL.write_text(json.dumps({"lost": True}))
R["lost"] = plain(b.click(element=1))
R["lost_state"] = b._pid
b.capture(mode="ax", app="Notes")
for key in ("nowindow", "nocontrol", "coded"):
    CTL.write_text(json.dumps({key: True}))
    R["code_" + key] = plain(b.click(x=1, y=1))
CTL.write_text(json.dumps({"desktop": True}))
R["type_text_desktop"] = plain(b.type_text("hi"))

# --- vision is screenshot only; a cached pid skips apps
m = mark()
vis = b.capture(mode="vision", app="Notes")
R["vision"] = [[c["name"] for c in calls(m)], len(vis.elements), bool(vis.png_b64)]
b.stop()

# --- doctor
import contextlib, io
for label, probe in (("linux", "linux: /home/user/connector/browser-mcp.cjs"), ("vps", "vps (linux unreachable (ssh: timeout))"), ("junk", "")):
    Path(os.environ["FAKE_PROBE"]).write_text(probe)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = provider.doctor()
    R["doctor_" + label] = [rc, out.getvalue()]

# --- the command is resolved the way Hermes's MCP spawn resolves it
import shutil
from unittest import mock
import tools.mcp_tool_config as mcp_config
alias_home = HOME / "alias"
alias_home.mkdir(exist_ok=True)
(alias_home / "config.yaml").write_text((HOME / "config.yaml").read_text().replace("command: " + shutil.which("node"), "command: hermes-only-node"))
set_hermes_home_override(str(alias_home))
real_resolve = mcp_config._resolve_stdio_command
def resolve(command, env):
    return (shutil.which("node"), env) if command == "hermes-only-node" else real_resolve(command, env)
R["alias_unpatched"] = provider.is_available()
with mock.patch.object(mcp_config, "_resolve_stdio_command", resolve):
    R["alias_patched"] = provider.is_available()
    ab = provider.create_backend(permission_mode="standard"); ab.start()
    R["alias_apps"] = len(ab.list_apps()); ab.stop()
set_hermes_home_override(str(HOME))

# --- the real tool handler: capture_after uses the backend's sticky target
from tools.computer_use import tool as cu
os.environ["HERMES_INTERACTIVE"] = "1"
cu.set_approval_callback(lambda command, description, **kw: "once")
cu.reset_backend_for_tests()
cap_out = cu.handle_computer_use({"action": "capture", "app": "Notes"}, session_id="e2e")
R["e2e_capture"] = json.dumps(cap_out, default=str)[:3000]
m = mark()
click_out = cu.handle_computer_use({"action": "click", "element": 1, "capture_after": True}, session_id="e2e")
R["e2e_click_calls"] = [(c["name"], c["args"].get("pid")) for c in calls(m)]
R["e2e_click"] = json.dumps(click_out, default=str)[:3000]
type_out = cu.handle_computer_use({"action": "type", "text": "hi"}, session_id="e2e")
R["e2e_type"] = type_out if isinstance(type_out, str) else json.dumps(type_out, default=str)
cu.reset_backend_for_tests()

print("RESULT:" + json.dumps(R, default=str))
"""

INTEGRATION = r"""
import dataclasses, json, os
from pathlib import Path
from hermes_constants import set_hermes_home_override
HOME, CTL = Path(os.environ["T_HOME"]), Path(os.environ["FAKE_CTL"])
set_hermes_home_override(str(HOME))
from plugins.computer_use import get_active_provider
plain = dataclasses.asdict
R = {}
be = get_active_provider().create_backend(permission_mode="standard"); be.start()
cap = be.capture(mode="som", app="Notes")
R["first"] = [len(cap.elements), be._host]
CTL.write_text(json.dumps({"die_on": "workspace_computer_action"}))  # the host app dies under the next action
R["lost"] = plain(be.click(element=1))
R["lost_state"] = be._pid
cap = be.capture(mode="som", app="Notes")
R["again"] = [len(cap.elements), be._host]
R["click_after"] = plain(be.click(element=1))
be.stop()
print("RESULT:" + json.dumps(R, default=str))
"""

FAKE_SSH = """#!/bin/sh
for last in "$@"; do :; done
case "$last" in
  *"exit 97"*) exec node "$MAC_STUB" ;;
  *conn_script*) printf %s "/Users/user/Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs"; exit 0 ;;
  *) exec node "$MAC_STUB" ;;
esac
"""

OLD_HERMES = r"""
import importlib.util, json, logging, sys
from pathlib import Path
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
sys.modules["tools.computer_use.backend"] = None  # `import` of it raises ImportError, as on Hermes 0.21.5
init = Path(sys.argv[1]) / "__init__.py"
spec = importlib.util.spec_from_file_location("alans_way_computer_old", init, submodule_search_locations=[str(init.parent)])
mod = importlib.util.module_from_spec(spec); sys.modules[spec.name] = mod; spec.loader.exec_module(mod)

class OldContext:  # the general PluginContext has no register_computer_use_provider
    pass

class NewContext:
    registered = None
    def register_computer_use_provider(self, p): NewContext.registered = p

mod.register(OldContext())
mod.register(NewContext())
print("RESULT:" + json.dumps({"registered": NewContext.registered is not None}))
"""


def bare(actions):
    return [{k: v for k, v in a.items() if k not in ("generation", "expect_host")} for a in actions]


def last_result(proc):
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("RESULT:"):
            return json.loads(line[len("RESULT:"):])
    raise AssertionError(f"no result\nstdout: {proc.stdout[-3000:]}\nstderr: {proc.stderr[-3000:]}")


class StaticTests(unittest.TestCase):
    def test_manifest_name_matches_directory(self):
        manifest = (PLUGIN / "plugin.yaml").read_text()
        self.assertRegex(manifest, r'(?m)^name:\s*"?alans-way-computer"?\s*$')
        self.assertRegex(manifest, r'(?m)^requires_hermes:\s*"?>=0\.21\.5"?\s*$')

    def test_provider_markers_sit_in_the_first_8k_for_exclusive_classification(self):
        head = (PLUGIN / "__init__.py").read_text(encoding="utf-8-sig")[:8192]
        self.assertIn("register_computer_use_provider", head)
        self.assertIn("ComputerUseProvider", head)

    def test_readme_documents_the_provider_and_its_approval_config(self):
        readme = (PLUGIN / "README.md").read_text()
        for needle in ("computer_use.backend: alans-way-computer", "Tailscale", "command_allowlist", "plugins.isolation",
                       *(f"cua:{a}:background" for a in ("click", "double_click", "right_click", "drag", "scroll", "key", "set_value", "focus_app"))):
            self.assertIn(needle, readme)
        self.assertNotIn("\u2014", readme)

    def test_router_child_env_passes_the_desktop_session_vars(self):
        # The provider's private router child also serves the VM desktop
        # fallback, which needs the X display and the session bus the gateway
        # was started with; the env whitelist must not strip them. Tokens and
        # keys stay out either way.
        spec = importlib.util.spec_from_file_location("alans_way_computer_env", PLUGIN / "__init__.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        env = {"PATH": os.environ["PATH"], "HOME": "/tmp", "DISPLAY": ":99",
               "DBUS_SESSION_BUS_ADDRESS": "unix:path=/tmp/dbus-test", "XAUTHORITY": "/home/user/.Xauthority",
               "TELEGRAM_BOT_TOKEN": "11:secret", "AWS_SECRET_ACCESS_KEY": "secret"}
        with mock.patch.dict(os.environ, env, clear=True):
            _, child_env = mod._launch({"command": sys.executable, "args": []})
        for key in ("DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY"):
            self.assertEqual(child_env[key], env[key])
        self.assertNotIn("TELEGRAM_BOT_TOKEN", child_env)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", child_env)

    def test_catalog_draft_pins_docs_to_the_sha_and_lists_known_issues(self):
        entry = (ROOT / "docs/catalog/alans-way-computer.yaml").read_text()
        self.assertRegex(entry, r"(?m)^sha: (0{40}|[0-9a-f]{40})$")
        self.assertRegex(entry, r"(?m)^docs_url: https://github.com/capthvnsen/alans-way-agents/tree/(0{40}|[0-9a-f]{40})/alans-way-computer$")
        self.assertIn("known_issues:", entry)
        self.assertRegex(entry, r"(?m)^platforms: \[linux, macos\]$")


class ReplyFoldingTests(unittest.TestCase):
    """The pure parts of the provider, without Hermes: folding action replies and reading error texts."""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("alans_way_computer_fold", PLUGIN / "__init__.py")
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def backend(self, refs):
        be = self.mod.AlansWayComputerBackend()
        be._pid = 101
        be._tree = {"pid": 101, "gen": 1, "els": [{"ref": r, "role": "AXButton", "name": r.upper()} for r in refs], "notes": []}
        return be

    def test_actions_expect_the_last_seen_host(self):
        for host, expected in (("mac", "computer"), ("windows", "computer"), ("linux", "computer"), ("vps", "vm"), ("vm", "vm")):
            with self.subTest(host=host):
                be = self.backend(["a"])
                reply = {"content": [{"type": "text", "text": "{}"}], "_meta": {"workspace": {"host": host}}}
                with mock.patch.object(be, "_call", return_value=reply) as call, mock.patch.object(self.mod, "ActionResult", side_effect=lambda **kw: kw):
                    be.list_apps()
                    be._run("key", {"action": "key", "key": "a"})
                self.assertEqual(call.call_args.args, ("workspace_computer_action", {
                    "pid": 101, "action": "key", "key": "a", "generation": 1, "expect_host": expected}))

    def test_host_refusal_clears_the_old_target(self):
        be = self.backend(["a"])
        be._seen("mac")
        with mock.patch.object(be, "_call", return_value={"isError": True, "content": [{"type": "text", "text": "host_changed: The computer changed before this action started."}]}), mock.patch.object(self.mod, "ActionResult", side_effect=lambda **kw: kw):
            result = be._run("key", {"action": "key", "key": "a"})
        self.assertEqual(result["code"], "host_changed")
        self.assertEqual((be._pid, be._host, be._tree), (None, None, None))

    def test_a_delta_updates_in_place_appends_new_and_tombstones_gone(self):
        be = self.backend(["a", "b", "c"])
        changed, gone = be._merge({"generation": 2, "changed": [{"ref": "b", "role": "AXButton", "name": "B2"},
                                                                {"ref": "d", "role": "AXButton", "name": "D"}], "removed": ["a"]})
        self.assertEqual([(i, e["name"]) for i, e in changed], [(2, "B2"), (4, "D")])
        self.assertEqual([(i, e["name"]) for i, e in gone], [(1, "A")])
        self.assertEqual([e and e["name"] for e in be._tree["els"]], [None, "B2", "C", "D"])
        self.assertEqual(be._tree["gen"], 2)
        self.assertIsNone(be._element(1))
        self.assertEqual(be._element(4)["ref"], "d")

    def test_a_whole_tree_keeps_each_ref_at_its_number(self):
        be = self.backend(["a", "b", "c"])
        changed, gone = be._merge({"generation": 2, "elements": [{"ref": "c", "role": "AXButton", "name": "C"},
                                                                 {"ref": "a", "role": "AXButton", "name": "A!"},
                                                                 {"ref": "e", "role": "AXButton", "name": "E"}]})
        self.assertEqual([(i, e["name"]) for i, e in changed], [(1, "A!"), (4, "E")])
        self.assertEqual([i for i, _ in gone], [2])
        self.assertEqual([e and e["name"] for e in be._tree["els"]], ["A!", None, "C", "E"])

    def test_unchanged_a_missing_tree_or_another_app_leaves_the_list_alone(self):
        for body in ({"unchanged": True, "generation": 1}, {"note": "unresponsive: no tree"}):
            be = self.backend(["a"])
            self.assertEqual(be._merge(body), ([], []))
            self.assertEqual((be._tree["gen"], len(be._tree["els"])), (1, 1))
        be = self.backend(["a"])
        be._pid = 202
        self.assertEqual(be._merge({"generation": 2, "changed": [{"ref": "z", "name": "Z"}], "removed": []}), ([], []))

    def test_positional_hosts_get_a_label_diff_and_keep_their_list(self):
        be = self.backend(["c1", "c2", "c3", "c4"])
        for e, name in zip(be._tree["els"], ["a", "b", "c", "d"]):
            e["name"] = name
        shifted = [{"ref": r, "role": "AXButton", "name": n} for r, n in (("c1", "a"), ("c2", "c"), ("c3", "d"))]
        appeared, vanished = be._diff({"generation": 2, "elements": shifted})
        self.assertEqual((appeared, [e["name"] for e in vanished]), ([], ["b"]))
        self.assertEqual(([e["name"] for e in be._tree["els"]], be._tree["gen"]), (["a", "b", "c", "d"], 1))
        appeared, vanished = be._diff({"generation": 2, "changed": [{"ref": "c2", "role": "AXButton", "name": "B!"}], "removed": ["c4"]})
        self.assertEqual(([e["name"] for e in appeared], sorted(e["name"] for e in vanished)), (["B!"], ["b", "d"]))

    def test_a_cut_reply_marks_nothing_gone(self):
        be = self.backend(["a", "b", "c"])
        changed, gone = be._merge({"generation": 2, "truncated": True, "elements": [{"ref": "a", "role": "AXButton", "name": "A!"}]})
        self.assertEqual(([i for i, _ in changed], gone), ([1], []))
        self.assertEqual([e and e["name"] for e in be._tree["els"]], ["A!", "B", "C"])
        changed, gone = be._merge({"generation": 3, "truncated": True, "changed": [], "removed": ["b", "c"]})
        self.assertEqual(gone, [])
        self.assertEqual(len([e for e in be._tree["els"] if e]), 3)
        be = self.backend(["c1", "c2"])
        appeared, vanished = be._diff({"generation": 2, "truncated": True, "elements": [{"ref": "c1", "role": "AXButton", "name": "C1"}]})
        self.assertEqual((appeared, vanished), ([], []))

    def test_listed_names_every_number_past_the_shown_ones(self):
        pairs = [(i, {"role": "AXRow", "name": f"r{i}"}) for i in range(1, 16)]
        text = self.mod._listed(pairs)
        self.assertEqual(text.count("AXRow"), self.mod.CHANGES_SHOWN)
        self.assertTrue(text.endswith("; also #13, #14, #15"), text)
        bare = self.mod._listed([e for _, e in pairs])
        self.assertTrue(bare.endswith("; +3 more"), bare)
        self.assertEqual(self.mod._listed(pairs[:2]), "#1 AXRow 'r1'; #2 AXRow 'r2'")

    def test_coverage_and_nearness(self):
        shot = {"wx": 0, "wy": 0, "ww": 100, "wh": 100}
        half = [{"name": "Left", "x": 0, "y": 0, "width": 50, "height": 100}, {"name": "", "x": 50, "y": 0, "width": 50, "height": 100}]
        self.assertAlmostEqual(self.mod._coverage(half, shot), 0.5)
        self.assertEqual(self.mod._coverage(half, None), 0.0)
        near = self.mod._near
        self.assertTrue(near({"x": 200, "y": 0, "width": 10, "height": 10}, (0, 0, 100, 10)))
        self.assertFalse(near({"x": 300, "y": 0, "width": 10, "height": 10}, (0, 0, 100, 10)))
        self.assertFalse(near({"name": "no geometry"}, (0, 0, 100, 10)))

    def capture_fixture(self, body, mode="som", backend=None):
        be = backend or self.backend([])
        win = {"x": 100, "y": 100, "width": 960, "height": 600}
        shot = {"content": [{"type": "image", "data": "anBlZw==", "mimeType": "image/jpeg"},
                            {"type": "text", "text": json.dumps({"window": win, "imageWidth": 480, "imageHeight": 300})}]}
        def reply(tool, args):
            return {"content": [{"type": "text", "text": json.dumps(body)}]} if tool == "workspace_computer_snapshot" else shot
        with mock.patch.object(be, "_call", side_effect=reply) as call, \
                mock.patch.object(self.mod, "CaptureResult", side_effect=lambda **kw: kw), \
                mock.patch.object(self.mod, "UIElement", side_effect=lambda **kw: kw):
            cap = be.capture(mode=mode, pid=101)
        return be, cap, [c.args[0] for c in call.call_args_list]

    def test_som_skips_the_screenshot_rpc_when_snapshot_geometry_has_enough_coverage(self):
        win = {"x": 100, "y": 100, "width": 960, "height": 600}
        body = {"generation": 2, "selectedWindow": win,
                "elements": [{"ref": "body", "name": "Draft", "role": "AXTextArea", **win}]}
        be, _, _ = self.capture_fixture(body, mode="vision")
        be, cap, calls = self.capture_fixture(body, backend=be)
        self.assertEqual(calls, ["workspace_computer_snapshot"])
        self.assertEqual((cap["png_b64"], cap["width"], cap["height"], be._shot), (None, 0, 0, None))
        self.assertEqual(cap["elements"][0]["bounds"], (100, 100, 960, 600))
        self.assertEqual(be._point(120, 140), {"x": 120, "y": 140})
        self.assertEqual(be._tree["gen"], 2)
        self.assertIn("No screenshot is attached", cap["note"])
        body["window"] = body.pop("selectedWindow")
        _, _, calls = self.capture_fixture(body)
        self.assertEqual(calls, ["workspace_computer_snapshot"])

    def test_som_keeps_the_screenshot_rpc_for_unknown_or_sparse_geometry(self):
        win = {"x": 100, "y": 100, "width": 960, "height": 600}
        element = {"ref": "body", "name": "Draft", "role": "AXTextArea", **win}
        for geometry in (None, {}, [], "unknown", {**win, "width": 0}, {**win, "height": -1},
                         {**win, "x": "100"}, {**win, "y": True}, {**win, "x": float("nan")},
                         {**win, "width": float("inf")}, {**win, "width": 3000}):
            with self.subTest(geometry=geometry):
                _, _, calls = self.capture_fixture({"generation": 2, "selectedWindow": geometry, "elements": [element]})
                self.assertEqual(calls, ["workspace_computer_snapshot", "workspace_computer_screenshot"])
        for elements in ([], [{**element, "name": ""}], [{**element, "width": 100, "height": 40}]):
            with self.subTest(elements=elements):
                be, cap, calls = self.capture_fixture({"generation": 2, "selectedWindow": win, "elements": elements})
                self.assertEqual(calls, ["workspace_computer_snapshot", "workspace_computer_screenshot"])
                self.assertEqual(cap["png_b64"], "anBlZw==")
                self.assertEqual(be._point(100, 75), {"x": 300, "y": 250})

    def test_each_capture_uses_current_geometry_even_when_the_tree_is_unchanged(self):
        win = {"x": 100, "y": 100, "width": 960, "height": 600}
        body = {"generation": 2, "selectedWindow": win, "elements": [{"ref": "body", "name": "Draft", **win}]}
        be, _, _ = self.capture_fixture(body)
        for geometry, expected in ((win, 1), ({**win, "width": 3000}, 2), (None, 2)):
            with self.subTest(geometry=geometry):
                _, _, calls = self.capture_fixture({"generation": 2, "unchanged": True, "selectedWindow": geometry}, backend=be)
                self.assertEqual(len(calls), expected)
        for mode, expected in (("ax", ["workspace_computer_snapshot"]), ("vision", ["workspace_computer_screenshot"])):
            with self.subTest(mode=mode):
                _, cap, calls = self.capture_fixture(body, mode=mode, backend=be)
                self.assertEqual(calls, expected)
                self.assertEqual(bool(cap["png_b64"]), mode == "vision")

    def test_error_texts_map_to_codes_with_a_next_step(self):
        coded = self.mod._coded
        self.assertEqual(coded("The screen is locked, so apps cannot be read or driven.")[0], "locked")
        self.assertEqual(coded("Screen Recording is off for this program.")[0], "permission")
        self.assertEqual(coded("Could not verify which field has focus; retry or snapshot first.")[0], "focus_unverified")
        code, message = coded("stale_ref: c2 is gone or changed since your snapshot.")
        self.assertEqual(code, "stale_ref")
        self.assertTrue(message.startswith("c2 is gone"))
        self.assertIn("capture again", message)
        self.assertEqual(coded("Refused.", "off_limits"), ("off_limits", "Refused. " + self.mod._NEXT["off_limits"]))
        self.assertEqual(coded("Press failed."), ("failed", "Press failed."))

    def test_tree_notes_carry_the_apps_note_hidden_count_and_truncation(self):
        notes = self.mod._tree_notes({"note": "On another Space.", "hidden": 3, "truncated": True})
        self.assertEqual(notes[0], "On another Space.")
        self.assertIn("3 more controls are scrolled out of view", notes[1])
        self.assertIn("cut", notes[2])
        self.assertEqual(self.mod._tree_notes({"hidden": 0}), [])


@NEEDS_HERMES
class OldHermesTests(unittest.TestCase):
    def test_missing_provider_api_makes_register_a_logged_noop(self):
        env = {**os.environ, "PYTHONPATH": str(HERMES_MAIN)}
        proc = subprocess.run([str(HERMES_PY), "-c", OLD_HERMES, str(PLUGIN)], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(last_result(proc), {"registered": False})
        self.assertIn("provider API", proc.stderr)


@NEEDS_HERMES
class ProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        home = tmp / "home"
        shutil.copytree(PLUGIN, home / "plugins" / "alans-way-computer", ignore=shutil.ignore_patterns("__pycache__"))
        (tmp / "router.cjs").write_text(FAKE_ROUTER)
        env = {"FAKE_PROBE": str(tmp / "probe.txt"), "FAKE_LOG": str(tmp / "log.jsonl"), "FAKE_CTL": str(tmp / "ctl.json"), "FAKE_STATE": str(tmp / "state.json")}
        (home / "config.yaml").write_text(textwrap.dedent(f"""\
            computer_use:
              backend: alans-way-computer
            mcp_servers:
              workspace_browser:
                command: {NODE}
                args:
                  - {tmp / 'router.cjs'}
                  - --bot-id
                  - "4242"
                env:
                  FAKE_PROBE: {env['FAKE_PROBE']}
                  FAKE_LOG: {env['FAKE_LOG']}
                  FAKE_CTL: {env['FAKE_CTL']}
                  FAKE_STATE: {env['FAKE_STATE']}
            """))
        proc = subprocess.run([str(HERMES_PY), "-c", DRIVER], capture_output=True, text=True, timeout=300,
                              env={**os.environ, **env, "PYTHONPATH": str(HERMES_MAIN), "T_HOME": str(home), "HERMES_HOME": str(home)})
        try:
            cls.r = last_result(proc)
        except AssertionError:
            cls.tmp.cleanup()
            raise
        cls.log = [json.loads(line) for line in (tmp / "log.jsonl").read_text().splitlines()]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_discovered_as_exclusive_provider_and_available_only_with_the_block(self):
        r = self.r
        self.assertIn("alans-way-computer", r["discovered"])
        self.assertEqual(r["kind"], "exclusive")
        self.assertEqual(r["provider"], {"name": "alans-way-computer", "available": True})
        self.assertFalse(r["available_without_block"])

    def test_router_is_spawned_with_the_profile_blocks_args(self):
        self.assertEqual(self.log[0]["argv"], ["--bot-id", "4242"])

    def test_the_private_router_child_runs_with_the_desktop_action_marker(self):
        # The provider IS the approval gate (Hermes asks before each action),
        # so its own router child alone gets the env marker that lets
        # workspace_computer_action through the router's default refusal.
        self.assertTrue(self.log)
        self.assertTrue(all(c["allow"] == "1" for c in self.log), self.log[:2])

    def test_list_apps(self):
        self.assertEqual(self.r["apps"][0], {"name": "Notes", "bundle_id": "com.apple.Notes", "pid": 101, "frontmost": False})

    def test_som_capture_attaches_the_screenshot_when_named_controls_cover_little_of_the_window(self):
        som = self.r["som"]
        self.assertEqual((som["mode"], som["w"], som["h"], som["mime"], som["png"], som["app"]), ("som", 480, 300, "image/jpeg", True, "Notes"))
        # screen (300,250,100,40) in a window at (100,100) 960x600 shown at 480x300 is (100,75,50,20)
        self.assertEqual(som["elements"][0], [1, "AXButton", "Save", [100, 75, 50, 20]])
        self.assertEqual(som["elements"][2][3], [0, 0, 0, 0])
        self.assertEqual([name for name, _ in som["calls"]], ["workspace_computer_apps", "workspace_computer_snapshot", "workspace_computer_screenshot"])
        self.assertIn("Named controls cover only 2% of the window, so the screenshot is attached.", som["note"])
        self.assertEqual(self.r["target"], [{"pid": 101, "window_id": 0}, "Notes"])

    def test_som_capture_of_a_tree_that_fills_the_window_leaves_the_screenshot_out(self):
        som = self.r["som_full"]
        self.assertEqual((som["png"], som["w"]), (False, 0))
        self.assertEqual(som["elements"], [[1, "Body", [100, 100, 960, 600]]])
        self.assertEqual(som["calls"], ["workspace_computer_snapshot"])
        self.assertIn("No screenshot is attached", som["note"])
        self.assertIn("capture(mode='vision')", som["note"])

    def test_som_capture_of_an_unnamed_tree_adds_the_screenshot_and_converts_bounds(self):
        som = self.r["som_unnamed"]
        self.assertEqual((som["png"], som["w"]), (True, 480))
        self.assertEqual(som["calls"], ["workspace_computer_snapshot", "workspace_computer_screenshot"])
        # screen (300,250,100,40) in a window at (100,100) 960x600 shown at 480x300 is (100,75,50,20)
        self.assertEqual(som["elements"], [[1, "", [100, 75, 50, 20]]])
        self.assertIn("12 more controls are scrolled out of view", som["note"])

    def test_an_empty_tree_says_why_and_gets_the_screenshot(self):
        som = self.r["som_empty"]
        self.assertTrue(som["png"])
        self.assertEqual(som["elements"], [])
        self.assertIn("another Space", som["note"])
        noshot = self.r["som_noshot"]
        self.assertFalse(noshot["png"])
        self.assertIn("Screenshot unavailable: That app has no window to capture.", noshot["note"])
        self.assertIn("ask the user", noshot["note"])
        self.assertNotIn("Use the element list", noshot["note"])

    def test_a_zero_size_window_attaches_the_screenshot_and_says_so(self):
        som = self.r["som_win0"]
        self.assertTrue(som["png"])
        self.assertIn("The window size is unknown, so the screenshot is attached.", som["note"])
        self.assertIn("bounds and coordinate= are screen pixels", som["note"])
        self.assertNotIn("No screenshot is attached", som["note"])
        self.assertEqual(som["elements"][0][2], [300, 250, 100, 40])  # no geometry to convert with: screen pixels

    def test_a_delta_reply_folds_into_the_element_list_without_shifting_numbers(self):
        delta = self.r["delta"]
        self.assertTrue(delta["ok"])
        self.assertEqual(delta["effect"], "confirmed")
        self.assertIn("#2 AXTextField 'Title = bye'", delta["message"])
        self.assertIn("#4 AXButton 'Done'", delta["message"])
        self.assertIn("Gone: #3 AXStaticText 'No geometry'.", delta["message"])
        self.assertIn("4 more controls are scrolled out of view", delta["message"])
        far = self.r["far"]
        self.assertIn("#2 AXTextField 'Title = tick'", far["message"])
        self.assertIsNone(far["effect"])  # only a change far from the pressed control: not proof it landed
        self.assertIn("no capture is needed", delta["message"])
        gen, held = self.r["delta_gen"]
        self.assertEqual(self.r["delta_call"][0]["generation"], gen)
        self.assertEqual(held, gen + 2)  # the delta click and the click on element 4
        self.assertEqual(self.r["delta_gone"]["code"], "no_such_element")
        self.assertIn("disappeared", self.r["delta_gone"]["message"])
        self.assertEqual(self.r["delta_new_call"], [{"pid": 101, "action": "press", "ref": "c4", "generation": gen + 1}])

    def test_a_capture_after_a_delta_keeps_the_numbers_it_handed_out(self):
        cap = self.r["delta_capture"]
        self.assertEqual([e[:2] for e in cap["elements"]], [[1, "Save"], [2, "Title = bye"], [4, "Done"]])
        self.assertIn("4 more controls are scrolled out of view", cap["note"])

    def test_unchanged_and_whole_tree_replies(self):
        self.assertIn("did not change", self.r["unchanged"]["message"])
        self.assertIsNone(self.r["unchanged"]["effect"])
        whole = self.r["whole"]
        self.assertIn("#1 AXButton 'Saved'", whole["message"])
        self.assertNotIn("Done", whole["message"])  # c4 is the same, so it is not listed as changed
        self.assertIn("Gone: #2 AXTextField 'Title = tick'.", whole["message"])
        self.assertIn("unresponsive", self.r["no_tree"]["message"])
        self.assertIsNone(self.r["no_tree"]["effect"])

    def test_windows_refs_are_stable_so_a_delete_folds_in_without_shifting_numbers(self):
        r = self.r
        self.assertNotIn("fold_error", r)
        self.assertIn("Gone: #2 AXRow 'b.txt'.", r["fold_delete"]["message"])
        self.assertEqual(r["fold_delete"]["effect"], "confirmed")  # the pressed row itself went
        gen, held, names = r["fold_gen"]
        self.assertIsInstance(gen, int)
        self.assertEqual(held, gen + 2)
        self.assertEqual(names, ["a.txt", None, "c.txt", "d.txt"])
        self.assertEqual(r["fold_calls"], [{"pid": 101, "action": "press", "ref": "c2", "generation": gen},
                                           {"pid": 101, "action": "press", "ref": "c3", "generation": gen + 1}])
        self.assertTrue(r["fold_third"]["ok"], r["fold_third"])

    def test_positional_refs_keep_the_old_generation_so_a_shifted_number_is_refused(self):
        r = self.r
        self.assertNotIn("win_error", r)
        delete = r["win_delete"]
        self.assertTrue(delete["ok"], delete)
        self.assertIn("Gone: AXRow 'b.txt'.", delete["message"])
        self.assertIn("capture before acting by number", delete["message"])
        self.assertNotIn("#", delete["message"])
        self.assertIsNone(delete["effect"])
        gen, held, names = r["win_gen"]
        self.assertIsInstance(gen, int)
        self.assertEqual(held, gen)
        self.assertEqual(names, ["a.txt", "b.txt", "c.txt", "d.txt"])
        self.assertEqual(r["win_calls"], [{"pid": 101, "action": "press", "ref": "c2", "generation": gen},
                                          {"pid": 101, "action": "press", "ref": "c3", "generation": gen}])
        self.assertEqual((r["win_third"].get("ok"), r["win_third"].get("code")), (False, "stale_ref"), r["win_third"])

    def test_each_error_code_says_the_next_step(self):
        r = self.r
        expected = {"locked": ("locked", "unlock"), "permission": ("permission", "alans-way-localapp"),
                    "unresponsive": ("unresponsive", "do not repeat"), "timeout": ("timeout", "capture"),
                    "no_window": ("no_window", "another Space"), "stale": ("stale_ref", "capture again")}
        for key, (code, step) in expected.items():
            with self.subTest(key):
                self.assertEqual((r["err_" + key]["ok"], r["err_" + key]["code"]), (False, code))
                self.assertIn(step, r["err_" + key]["message"])
        self.assertTrue(r["err_capture"].startswith("locked: The screen is locked"), r["err_capture"])

    def test_ax_capture_skips_the_image_and_reuses_an_unchanged_tree(self):
        ax = self.r["ax"]
        self.assertIsNone(ax["png"])
        self.assertEqual(ax["n"], 3)
        self.assertEqual(ax["bounds"][0], [300, 250, 100, 40])
        names = [name for name, _ in ax["calls"]]
        self.assertNotIn("workspace_computer_screenshot", names)
        snapshot = next(args for name, args in ax["calls"] if name == "workspace_computer_snapshot")
        self.assertEqual(snapshot, {"pid": 101, "since": 7})

    def test_click_by_element_sends_the_capture_generation(self):
        self.assertEqual(self.r["click_el_call"], [{"pid": 101, "action": "press", "ref": "c1", "generation": 7}])
        self.assertTrue(self.r["click_el"]["ok"])

    def test_double_and_right_click_use_refs_with_generation(self):
        generation = self.r["double"][0]["generation"]
        self.assertEqual(self.r["double"], [{"pid": 101, "action": "double_click", "ref": "c2", "generation": generation}])
        self.assertEqual(self.r["right"][0]["action"], "right_click")
        self.assertEqual(self.r["right"][0]["ref"], "c2")

    def test_the_action_tree_is_held_and_a_stale_ref_is_mapped(self):
        self.assertTrue(self.r["after_click"]["ok"])
        self.assertEqual(self.r["after_click_call"][0]["generation"], 8)
        stale = self.r["stale"]
        self.assertFalse(stale["ok"])
        self.assertEqual(stale["code"], "stale_ref")
        self.assertIn("capture", stale["message"].lower())

    def test_element_without_geometry_still_presses_and_unknown_index_is_refused(self):
        self.assertEqual(self.r["no_geometry_call"][0]["ref"], "c3")
        bad = self.r["bad_index"]
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["code"], "no_such_element")

    def test_coordinates_convert_from_screenshot_pixels_to_screen_pixels(self):
        self.assertEqual(bare(self.r["click_xy"]), [{"pid": 101, "action": "click", "x": 300, "y": 250}])
        scroll = self.r["scroll_xy"][0]
        self.assertEqual((scroll["x"], scroll["y"], scroll["direction"]), (300, 250, "down"))
        self.assertEqual(bare(self.r["drag_xy"]), [{"pid": 101, "action": "drag", "x": 100, "y": 100, "x2": 300, "y2": 250}])

    def test_scroll_ticks_become_pages(self):
        self.assertEqual(self.r["scroll_xy"][0]["amount"], 0.75)
        self.assertEqual(bare(self.r["scroll_plain"]), [{"pid": 101, "action": "scroll", "direction": "up", "amount": 0.75}])

    def test_drag_between_elements_uses_their_centres(self):
        self.assertEqual(bare(self.r["drag_el"]), [{"pid": 101, "action": "drag", "x": 350, "y": 270, "x2": 200, "y2": 115}])

    def test_set_value_and_keys(self):
        generation = self.r["set_value"][0]["generation"]
        self.assertEqual(self.r["set_value"], [{"pid": 101, "action": "type", "ref": "c2", "text": "hello", "generation": generation}])
        self.assertEqual(bare(self.r["key_combo"]), [{"pid": 101, "action": "hotkey", "keys": "cmd+s"}])
        self.assertEqual(bare(self.r["key_plain"]), [{"pid": 101, "action": "key", "key": "return"}])
        # A VM desktop the agent owns types at the focus; a host that cannot refuses in the helper.
        self.assertEqual(bare(self.r["type_text"]), [{"pid": 101, "action": "type", "text": "hi"}])
        self.assertEqual(self.r["type_text_mac"]["code"], "bad_request")
        self.assertIn("set_value", self.r["type_text_mac"]["message"])
        self.assertTrue(self.r["type_text_desktop"]["ok"])

    def test_every_action_carries_the_held_generation_so_replies_can_be_deltas(self):
        for key in ("click_xy", "scroll_plain", "drag_xy", "key_combo", "type_text"):
            with self.subTest(key):
                self.assertIsInstance(self.r[key][0]["generation"], int)

    def test_unsupported_actions_are_refused_without_reaching_the_router(self):
        for name, result in self.r["unsupported"].items():
            with self.subTest(name):
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "unsupported_action")
        self.assertEqual(self.r["unsupported_calls"], [])

    def test_policy_refusals_surface_with_their_codes(self):
        self.assertIn("in front", self.r["in_front"])
        self.assertEqual(self.r["off_limits"]["code"], "off_limits")
        self.assertFalse(self.r["off_limits"]["ok"])

    def test_focus_app_only_retargets_and_never_calls_the_router(self):
        self.assertTrue(self.r["focus"]["ok"])
        self.assertIn("never", self.r["focus"]["message"])
        self.assertEqual(self.r["focus_calls"], ["workspace_computer_apps"])
        self.assertEqual(self.r["focus_target"], [{"pid": 102, "window_id": 0}, "Safari"])
        self.assertEqual(self.r["focus_unknown"]["code"], "not_found")

    def test_router_notice_is_passed_to_the_model(self):
        self.assertTrue(self.r["notice"]["ok"])
        self.assertIn("routed to VPS", self.r["notice"]["message"])

    def test_dead_router_is_restarted_for_reads_and_reported_for_actions(self):
        r = self.r
        self.assertEqual(r["apps_after_death"], ["Notes", "Safari", "Finder", "1Password"])
        self.assertEqual(r["procs_after_apps"], 1)
        self.assertEqual((r["action_death"]["ok"], r["action_death"]["code"]), (False, "host_changed"))
        self.assertEqual(r["after_death_click"]["code"], "no_target")
        self.assertIsNone(r["after_death_target"])
        self.assertEqual(r["recovered"], 3)

    def test_host_change_resets_state_and_actions_report_host_changed(self):
        r = self.r
        self.assertEqual((r["flip_action"]["ok"], r["flip_action"]["code"]), (False, "host_changed"))
        self.assertIn("vps", r["flip_action"]["message"])
        self.assertEqual(r["flip_state"], [None, None, None, None])
        self.assertTrue(r["flip_click_after"]["ok"])

    def test_reads_re_resolve_after_a_host_change(self):
        r = self.r
        self.assertEqual(r["flip_read_calls"], ["workspace_computer_apps", "workspace_computer_snapshot"])
        self.assertIn("list_apps", r["flip_cached_pid"])

    def test_an_action_lost_in_flight_maps_to_host_changed(self):
        self.assertEqual((self.r["lost"]["ok"], self.r["lost"]["code"]), (False, "host_changed"))
        self.assertIn("NOT retried", self.r["lost"]["message"])
        self.assertIsNone(self.r["lost_state"])

    def test_error_codes_come_from_text_or_a_passed_through_code(self):
        self.assertEqual(self.r["code_nowindow"]["code"], "no_window")
        self.assertEqual(self.r["code_nocontrol"]["code"], "not_found")
        self.assertEqual(self.r["code_coded"]["code"], "off_limits")

    def test_vision_fetches_only_the_screenshot(self):
        names, elements, png = self.r["vision"]
        self.assertEqual(names, ["workspace_computer_apps", "workspace_computer_screenshot"])
        self.assertEqual((elements, png), (0, True))

    def test_doctor_accepts_any_host_decision_and_flags_a_missing_one(self):
        r = self.r
        self.assertEqual(r["doctor_linux"][0], 0)
        self.assertIn("reachable", r["doctor_linux"][1])
        self.assertNotIn("unreachable", r["doctor_linux"][1])
        self.assertEqual(r["doctor_vps"][0], 0)
        self.assertIn("unreachable", r["doctor_vps"][1])
        self.assertEqual(r["doctor_junk"][0], 1)

    def test_command_resolution_matches_hermes_mcp_spawn(self):
        r = self.r
        self.assertFalse(r["alias_unpatched"])
        self.assertTrue(r["alias_patched"])
        self.assertEqual(r["alias_apps"], 4)

    def test_stop_ends_the_router_child(self):
        self.assertTrue(self.r["stopped"])

    def test_tool_handler_end_to_end(self):
        r = self.r
        self.assertIn("Save", r["e2e_capture"])
        self.assertEqual(r["e2e_click_calls"], [["workspace_computer_action", 101], ["workspace_computer_snapshot", 101], ["workspace_computer_screenshot", 101]])
        self.assertIn('"ok": true', r["e2e_click"].lower().replace('\\"', '"'))
        self.assertNotIn("unsupported_action", r["e2e_type"])


@NEEDS_HERMES
class RouterIntegrationTests(unittest.TestCase):
    """The real workspace router (ALANS_WAY_ROUTER overrides which one) between the provider and fake host and VM backends."""

    def test_a_host_app_dying_under_an_action_is_reported_and_the_session_recovers(self):
        router = os.environ.get("ALANS_WAY_ROUTER") or str(ROOT / "alans-way/scripts/workspace-router.cjs")
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            home = tmp / "home"
            shutil.copytree(PLUGIN, home / "plugins" / "alans-way-computer", ignore=shutil.ignore_patterns("__pycache__"))
            (tmp / "bin").mkdir()
            (tmp / "bin" / "ssh").write_text(FAKE_SSH)
            (tmp / "bin" / "ssh").chmod(0o755)
            (tmp / "stub.cjs").write_text(FAKE_ROUTER)
            (tmp / "conn.json").write_text(json.dumps({"url": "http://127.0.0.1:9", "token": "t"}))
            env = {"FAKE_PROBE": str(tmp / "probe"), "FAKE_LOG": str(tmp / "log.jsonl"), "FAKE_CTL": str(tmp / "ctl.json"),
                   "FAKE_STATE": str(tmp / "state.json"), "MAC_STUB": str(tmp / "stub.cjs")}
            (home / "config.yaml").write_text(json.dumps({
                "computer_use": {"backend": "alans-way-computer"},
                "mcp_servers": {"workspace_browser": {"command": NODE, "args": [
                    router, "--bot-id", "4242", "--mac-ssh", "fake@host", "--vps-script", str(tmp / "stub.cjs"),
                    "--vps-connection", str(tmp / "conn.json"), "--mac-state-file", str(tmp / "mac-state.json")],
                    "env": {**env, "PATH": f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}"}}}}))
            proc = subprocess.run([str(HERMES_PY), "-c", INTEGRATION], capture_output=True, text=True, timeout=120,
                                  env={**os.environ, **env, "PYTHONPATH": str(HERMES_MAIN), "T_HOME": str(home), "HERMES_HOME": str(home)})
            r = last_result(proc)
        self.assertEqual(r["first"], [3, "mac"])
        self.assertEqual((r["lost"]["ok"], r["lost"]["code"]), (False, "host_changed"))
        self.assertIsNone(r["lost_state"])
        self.assertEqual(r["again"][0], 3)
        self.assertTrue(r["click_after"]["ok"], r["click_after"])


VALIDATE = """
import sys, json
from pathlib import Path
from hermes_cli.plugin_validate import validate_plugin_dir
r = validate_plugin_dir(Path(sys.argv[1]), None)
print(json.dumps([[n, ok, d] for n, ok, d in r.checks]))
"""


@NEEDS_HERMES
class CatalogValidateTests(unittest.TestCase):
    def test_security_scan_is_not_dangerous(self):
        for plugin in (ROOT / "alans-way", PLUGIN):
            proc = subprocess.run([str(HERMES_PY), "-c", VALIDATE, str(plugin)], capture_output=True, text=True, timeout=120,
                                  env={**os.environ, "PYTHONPATH": str(HERMES_MAIN)})
            checks = json.loads(proc.stdout.strip().splitlines()[-1])
            scan = next(c for c in checks if c[0] == "security scan")
            self.assertFalse(scan[2].startswith("dangerous"), f"{plugin.name}: {scan[2]}")


if __name__ == "__main__":
    unittest.main()
