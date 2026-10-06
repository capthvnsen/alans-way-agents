"""alans-way-computer provider: driven through Hermes main's own provider loader against a fake MCP router.

Hermes runs in a subprocess (HERMES_MAIN=<hermes checkout with .venv>), so the rest of the suite stays free of
Hermes internals. Without HERMES_MAIN the Hermes-backed tests skip; the static checks always run."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "alans-way-computer"
NODE = shutil.which("node")
HERMES_MAIN = Path(os.environ["HERMES_MAIN"]) if os.environ.get("HERMES_MAIN") else None
HERMES_PY = HERMES_MAIN and next((p for p in (HERMES_MAIN / ".venv/bin/python", HERMES_MAIN / ".venv/Scripts/python.exe") if p.exists()), None)
NEEDS_HERMES = unittest.skipUnless(HERMES_PY and NODE, "set HERMES_MAIN to a Hermes checkout with a .venv, and have node on PATH")

FAKE_ROUTER = r"""
const fs = require('fs');
const readline = require('readline');
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
  fs.appendFileSync(log, JSON.stringify({ proc: process.pid, name, args, argv: process.argv.slice(2) }) + '\n');
  const c = ctl();
  if (c.die_on === name) process.exit(1);
  const s = state();
  let result;
  if (name === 'workspace_computer_apps') result = text({ apps: APPS });
  else if (args.pid === 103) result = fail('That app is the one in front. Leave it there; the pointer stays where it is.');
  else if (name === 'workspace_computer_snapshot') result = args.since === s.generation ? text({ unchanged: true, generation: s.generation }) : text(tree(s.generation));
  else if (name === 'workspace_computer_screenshot') result = { content: [{ type: 'image', data: Buffer.from('jpegbytes').toString('base64'), mimeType: 'image/jpeg' },
    { type: 'text', text: JSON.stringify({ imageWidth: 480, imageHeight: 300, window: { x: 100, y: 100, width: 960, height: 600 } }) }] };
  else if (name === 'workspace_computer_action') {
    if (args.pid === 104) result = fail('off_limits: That app is off limits.');
    else if (args.ref !== undefined && args.generation !== s.generation) result = fail('stale_ref: The app changed since your snapshot. Take a fresh snapshot.');
    else if (args.action === 'drag' && args.x2 === undefined) result = fail('bad_request: drag needs x2 and y2.');
    else { s.generation += 1; save(s); result = text({ ok: true, generation: s.generation, elements: tree(s.generation).elements }); }
  } else result = fail('Unknown browser tool.');
  if (c.notice) { result.content.push({ type: 'text', text: c.notice }); result._meta = { workspace: { host: 'vps' } }; }
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
R["stale"] = plain(be.click(element=2))  # the click above changed the tree; the old generation must be refused

be.capture(mode="som", app="Notes")
m = mark(); be.click(element=2, click_count=2); R["double"] = action_calls(m)
be.capture(mode="som", app="Notes")
m = mark(); be.click(element=2, button="right"); R["right"] = action_calls(m)
be.capture(mode="som", app="Notes")
m = mark(); R["no_geometry"] = plain(be.click(element=3)); R["no_geometry_call"] = action_calls(m)
R["bad_index"] = plain(be.click(element=99))

# --- coordinates: screenshot pixels in, screen pixels out
be.capture(mode="som", app="Notes")
m = mark(); be.click(x=100, y=75); R["click_xy"] = action_calls(m)
m = mark(); be.scroll(direction="down", amount=3, x=100, y=75); R["scroll_xy"] = action_calls(m)
m = mark(); be.scroll(direction="up"); R["scroll_plain"] = action_calls(m)
m = mark(); be.drag(from_xy=(0, 0), to_xy=(100, 75)); R["drag_xy"] = action_calls(m)
m = mark(); be.drag(from_element=1, to_element=2); R["drag_el"] = action_calls(m)
be.capture(mode="som", app="Notes")
m = mark(); be.set_value("hello", element=2); R["set_value"] = action_calls(m)
m = mark(); be.key("cmd+s"); R["key_combo"] = action_calls(m)
m = mark(); be.key("return"); R["key_plain"] = action_calls(m)

# --- unsupported actions never reach the router
m = mark()
R["unsupported"] = {
    "type_text": plain(be.type_text("x")),
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
        env = {"FAKE_LOG": str(tmp / "log.jsonl"), "FAKE_CTL": str(tmp / "ctl.json"), "FAKE_STATE": str(tmp / "state.json")}
        (home / "config.yaml").write_text(textwrap.dedent(f"""\
            computer_use:
              backend: alans-way-computer
            mcp_servers:
              workspace_browser:
                command: node
                args:
                  - {tmp / 'router.cjs'}
                  - --bot-id
                  - "4242"
                env:
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

    def test_list_apps(self):
        self.assertEqual(self.r["apps"][0], {"name": "Notes", "bundle_id": "com.apple.Notes", "pid": 101, "frontmost": False})

    def test_som_capture_maps_elements_and_converts_bounds_to_screenshot_pixels(self):
        som = self.r["som"]
        self.assertEqual((som["mode"], som["w"], som["h"], som["mime"], som["png"], som["app"]), ("som", 480, 300, "image/jpeg", True, "Notes"))
        # screen (300,250,100,40) in a window at (100,100) 960x600 shown at 480x300 is (100,75,50,20)
        self.assertEqual(som["elements"][0], [1, "AXButton", "Save", [100, 75, 50, 20]])
        self.assertEqual(som["elements"][1][3], [0, 0, 100, 15])
        self.assertEqual(som["elements"][2][3], [0, 0, 0, 0])
        self.assertEqual([name for name, _ in som["calls"]], ["workspace_computer_apps", "workspace_computer_snapshot", "workspace_computer_screenshot"])
        self.assertEqual(self.r["target"], [{"pid": 101, "window_id": 0}, "Notes"])

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

    def test_stale_ref_is_mapped_and_the_action_tree_is_not_adopted(self):
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
        self.assertEqual(self.r["click_xy"], [{"pid": 101, "action": "click", "x": 300, "y": 250}])
        scroll = self.r["scroll_xy"][0]
        self.assertEqual((scroll["x"], scroll["y"], scroll["direction"]), (300, 250, "down"))
        self.assertEqual(self.r["drag_xy"], [{"pid": 101, "action": "drag", "x": 100, "y": 100, "x2": 300, "y2": 250}])

    def test_scroll_ticks_become_pages(self):
        self.assertEqual(self.r["scroll_xy"][0]["amount"], 0.75)
        self.assertEqual(self.r["scroll_plain"], [{"pid": 101, "action": "scroll", "direction": "up", "amount": 0.75}])

    def test_drag_between_elements_uses_their_centres(self):
        self.assertEqual(self.r["drag_el"], [{"pid": 101, "action": "drag", "x": 350, "y": 270, "x2": 200, "y2": 115}])

    def test_set_value_and_keys(self):
        generation = self.r["set_value"][0]["generation"]
        self.assertEqual(self.r["set_value"], [{"pid": 101, "action": "type", "ref": "c2", "text": "hello", "generation": generation}])
        self.assertEqual(self.r["key_combo"], [{"pid": 101, "action": "hotkey", "keys": "cmd+s"}])
        self.assertEqual(self.r["key_plain"], [{"pid": 101, "action": "key", "key": "return"}])

    def test_unsupported_actions_are_refused_without_reaching_the_router(self):
        for name, result in self.r["unsupported"].items():
            with self.subTest(name):
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "unsupported_action")
        self.assertEqual(self.r["unsupported_calls"], [])
        self.assertIn("set_value", self.r["unsupported"]["type_text"]["message"])

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

    def test_stop_ends_the_router_child(self):
        self.assertTrue(self.r["stopped"])

    def test_tool_handler_end_to_end(self):
        r = self.r
        self.assertIn("Save", r["e2e_capture"])
        self.assertEqual(r["e2e_click_calls"], [["workspace_computer_action", 101], ["workspace_computer_snapshot", 101], ["workspace_computer_screenshot", 101]])
        self.assertIn('"ok": true', r["e2e_click"].lower().replace('\\"', '"'))
        self.assertIn("unsupported_action", r["e2e_type"])


if __name__ == "__main__":
    unittest.main()
