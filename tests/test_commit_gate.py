"""Commit gate: consequential browser actions wait for the user's Approve tap."""
from pathlib import Path
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the host tests' stubs, however this file is run
from test_workspace_host import FAKE_SSH, ROUTER, VM_STUB  # noqa: E402

NODE = shutil.which("node")
SH = shutil.which("sh")

# The user's computer: a checkout page (one commit button, a card field, two
# ordinary controls, an icon-only button) and, in a second tab, a search page with no commit control.
MAC_STUB = r"""
const fs = require('fs');
const mode = process.env.MAC_MODE || 'ok';
const pages = {
  'mac-tab-1': { url: 'https://shop.example/checkout?step=2', elements: [
    { ref: 'e1', role: 'button', name: 'Place order' },
    { ref: 'e2', role: 'button', name: 'Add to cart' },
    { ref: 'e3', role: 'link', name: 'Delete' },
    { ref: 'e4', role: 'input', name: 'Card number' },
    { ref: 'e5', role: 'button' },
    { ref: 'e6', role: 'button', name: 'Continue' },
    { ref: 'e8', role: 'button', name: 'Apply coupon' },
    { ref: 'e9', role: 'a', name: 'Item 3', href: 'https://shop.example/cart/delete?item=3' },
    { ref: 'e10', role: 'a', name: 'Help', href: 'https://shop.example/help' },
  ] },
  'mac-tab-2': { url: 'https://shop.example/search', elements: [
    { ref: 'e1', role: 'input', name: 'Search' },
  ], overlays: [{ name: 'Join our newsletter', close: 'e5', closeName: 'No thanks' }] },
  // A long page whose snapshot was cut at maxElements.
  'mac-tab-3': { url: 'https://shop.example/catalog', truncated: { text: false, elements: true }, elements: [
    { ref: 'e1', role: 'input', name: 'Filter' },
  ] },
  // A tab the bot handed to the human to solve a CAPTCHA.
  'mac-tab-4': { url: 'https://shop.example/handed', elements: [
    { ref: 'e1', role: 'button', name: 'Place order' },
  ] },
};
// Each tab's control epoch; a claim starts a new one.
const epochs = {};
const ep = (id) => epochs[id] || 1;
const navs = {};
const tabFor = (url) => (/search/.test(url) ? 'mac-tab-2' : /catalog/.test(url) ? 'mac-tab-3'
  : /handed/.test(url) ? 'mac-tab-4' : 'mac-tab-1');
const reply = (id, text) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id,
  result: { content: [{ type: 'text', text }] } }) + '\n');
require('readline').createInterface({ input: process.stdin }).on('line', (line) => {
  fs.appendFileSync(process.env.MAC_LOG, 'LINE ' + line + '\n');
  const m = JSON.parse(line);
  if (m.id === undefined) return;
  if (m.method === 'tools/list') {
    return process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result: { tools: [
      { name: 'cua_alans_way_action', inputSchema: { type: 'object', additionalProperties: false, properties: {
        tabId: { type: 'string' }, epoch: { type: 'integer' }, action: { type: 'string' },
        ref: { type: 'string' }, steps: { type: 'array' },
      }, required: ['tabId', 'epoch', 'action'] } },
      { name: 'cua_alans_way_open', inputSchema: { type: 'object', properties: { url: { type: 'string' } } } },
    ] } }) + '\n');
  }
  const a = (m.params && m.params.arguments) || {};
  if (m.method !== 'tools/call') return reply(m.id, 'mac');
  if (m.params.name === 'cua_alans_way_status' && mode === 'die-on-status') process.exit(1);
  if (m.params.name === 'cua_alans_way_open') {
    const id = tabFor(a.url || '');
    const handed = id === 'mac-tab-4'
      ? { controller: 'human', handback: { state: 'awaiting_human', reason: 'captcha', since: Date.now() } }
      : { controller: 'agent' };
    return reply(m.id, JSON.stringify({ id, url: pages[id].url, host: 'mac', epoch: ep(id), ...handed }));
  }
  // A snapshot always says whether it was cut and which frames the page holds.
  if (m.params.name === 'cua_alans_way_snapshot')
    return reply(m.id, JSON.stringify({ generation: 1, truncated: { text: false, elements: false }, iframes: [],
      ...(navs[a.tabId] || pages[a.tabId]), tab: { id: a.tabId, epoch: ep(a.tabId) },
      ...(a.maxChars === 200000 ? { text: 'x'.repeat(150000) } : {}) }));
  if (m.params.name === 'cua_alans_way_action') {
    if (mode === 'die-on-commit' && line.includes('"ref":"e1"')) process.exit(1);
    if (a.action === 'claim') {
      epochs[a.tabId] = ep(a.tabId) + 1;
      return reply(m.id, JSON.stringify({ tab: { id: a.tabId, epoch: ep(a.tabId), controller: 'agent' } }));
    }
    if (a.action === 'navigate') {
      // An action reply lists at most 40 controls; a long page fills all 40.
      const n = /long/.test(a.url) ? 40 : /bare/.test(a.url) ? 0 : 1;
      const elements = Array.from({ length: n }, (_, i) => ({ ref: 'e' + (21 + i), role: 'input', name: 'Field ' + (i + 1) }));
      // A booking page embeds a scheduler from another site.
      const iframes = /embed/.test(a.url) ? [{ title: 'Scheduler', src: 'https://calendly.example/alan' }]
        : /own-frame/.test(a.url) ? [{ title: 'Map', src: 'https://shop.example/map' }]
        : /many-frames/.test(a.url) ? Array.from({ length: 8 }, (_, i) => ({ title: '', src: 'https://shop.example/f' + i })) : [];
      // A checkout with a reCAPTCHA box in its form, and Google's whole-page check.
      const challenge = /captcha/.test(a.url) ? { kind: 'recaptcha', blocking: false }
        : /sorry/.test(a.url) ? { kind: 'google_sorry', blocking: true } : null;
      if (challenge) elements.splice(0, 1, { ref: 'e21', role: 'button', name: challenge.blocking ? 'Submit' : 'Place order' });
      navs[a.tabId] = { url: a.url, elements, iframes };
      return reply(m.id, JSON.stringify({ effect: { navigated: true, url: a.url }, generation: 3,
        ...(n ? { elements } : {}), ...(challenge ? { challenge } : {}), tab: { id: a.tabId, epoch: ep(a.tabId) } }));
    }
    // Continue becomes Place order on the same control; Apply coupon leaves
    // the list the reply carries.
    if (a.action === 'click' && (a.ref === 'e6' || a.ref === 'e8'))
      return reply(m.id, JSON.stringify({ elements: a.ref === 'e6' ? [{ ref: 'e6', role: 'button', name: 'Place order' }]
        : [{ ref: 'e1', role: 'button', name: 'Place order' }], generation: 2,
        effect: { url: pages['mac-tab-1'].url }, tab: { id: a.tabId, epoch: ep(a.tabId) } }));
    // With generation the app answers with what changed: here, a control
    // named after the typed text appears.
    if (a.generation !== undefined)
      return reply(m.id, JSON.stringify({ changed: [{ ref: 'e7', role: 'button', name: a.text || 'Clear' }], removed: [],
        generation: a.generation + 1, effect: { url: (pages[a.tabId] || {}).url }, tab: { id: a.tabId, epoch: ep(a.tabId) } }));
    return reply(m.id, JSON.stringify({ ok: true, tab: { id: a.tabId, epoch: ep(a.tabId) } }));
  }
  reply(m.id, 'mac');
});
"""

PURCHASE = {"kind": "purchase", "summary": "One brass desk lamp", "amount": "40.00",
            "currency": "EUR", "counterparty": "Lamp Shop"}


@unittest.skipUnless(NODE and SH, "node and sh are required for commit gate tests")
class CommitGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "bin").mkdir()
        ssh = self.dir / "bin" / "ssh"
        ssh.write_text(FAKE_SSH)
        ssh.chmod(0o755)
        (self.dir / "mac-stub.cjs").write_text(MAC_STUB)
        (self.dir / "vm-stub.cjs").write_text(VM_STUB)
        (self.dir / "conn.json").write_text(json.dumps({"url": "http://127.0.0.1:9", "token": "tok"}))
        self.proc = None
        self.next_id = 1

    def tearDown(self):
        if self.proc:
            self.proc.kill()
            self.proc.communicate()
        self.tmp.cleanup()

    def start(self, mac_mode="ok", **extra_env):
        argv = [NODE, str(ROUTER), "--bot-id", "bot1", "--bot-name", "Alan",
                "--mac-ssh", "fake@host",
                "--vps-script", str(self.dir / "vm-stub.cjs"),
                "--vps-connection", str(self.dir / "conn.json"),
                "--mac-state-file", str(self.dir / "mac-state.json")]
        env = dict(os.environ, PATH=str(self.dir / "bin") + os.pathsep + os.environ["PATH"],
                   MAC_STUB=str(self.dir / "mac-stub.cjs"), MAC_MODE=mac_mode,
                   MAC_LOG=str(self.dir / "mac.log"), VPS_LOG=str(self.dir / "vm.log"),
                   PROBE_DOWN=str(self.dir / "probe-down"), HERMES_ROUTER_RESTORE_MS="500")
        env.update(extra_env)
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env)

    def write(self, msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def send(self, method, **params):
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        if not method.startswith("notifications/"):
            msg["id"] = self.next_id
            self.next_id += 1
        self.write(msg)
        return msg.get("id")

    def recv(self, timeout=15, required=True):
        if not select.select([self.proc.stdout], [], [], timeout)[0]:
            if required:
                self.fail("no message within %ss" % timeout)
            return None
        return json.loads(self.proc.stdout.readline())

    def text(self, msg):
        return " ".join(part["text"] for part in msg["result"]["content"] if part["type"] == "text")

    def handshake(self, elicitation=True):
        self.send("initialize", protocolVersion="2025-06-18",
                  capabilities={"elicitation": {}} if elicitation else {},
                  clientInfo={"name": "test", "version": "0"})
        self.recv()
        self.send("notifications/initialized")

    def open_checkout(self, elicitation=True):
        self.start(**getattr(self, "env", {}))
        self.handshake(elicitation)
        self.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://shop.example/"})
        self.recv()
        self.send("tools/call", name="cua_alans_way_snapshot", arguments={})
        self.recv()

    def act(self, **arguments):
        return self.send("tools/call", name="cua_alans_way_action", arguments=arguments)

    def answer(self, request, action, content=None):
        result = {"action": action}
        if content is not None:
            result["content"] = content
        self.write({"jsonrpc": "2.0", "id": request["id"], "result": result})

    def actions(self, log="mac.log"):
        path = self.dir / log
        out = []
        for line in (path.read_text() if path.exists() else "").splitlines():
            msg = json.loads(line[5:]) if line.startswith("LINE ") else {}
            params = msg.get("params") or {}
            if msg.get("method") == "tools/call" and params.get("name") == "cua_alans_way_action":
                out.append(params.get("arguments") or {})
        return out

    def decisions(self):
        path = self.dir / "commit-decisions.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def refused(self, call, code):
        msg = self.recv()
        self.assertEqual(msg["id"], call)
        self.assertTrue(msg["result"]["isError"])
        self.assertIn(code, self.text(msg))
        return msg

    def test_tools_list_offers_a_commit_object(self):
        self.start()
        self.handshake()
        self.send("tools/list")
        tool = self.recv()["result"]["tools"][0]
        commit = tool["inputSchema"]["properties"]["commit"]
        self.assertEqual(commit["properties"]["kind"]["enum"],
                         ["purchase", "booking", "send", "post", "submit", "delete", "account_change"])
        self.assertEqual(commit["properties"]["summary"]["maxLength"], 200)
        self.assertEqual(commit["required"], ["kind", "summary"])
        self.assertNotIn("commit", tool["inputSchema"]["required"])

    def test_an_approved_commit_runs_once_without_the_commit_object(self):
        self.open_checkout()
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        ask = self.recv()
        self.assertEqual(ask["method"], "elicitation/create")
        self.assertEqual(ask["params"]["message"],
                         "Alan wants to buy: One brass desk lamp · 40.00 EUR · Lamp Shop on https://shop.example"
                         ' (clicks "Place order")')
        schema = ask["params"]["requestedSchema"]
        self.assertEqual(schema["properties"]["approve"]["type"], "boolean")
        self.assertIn("Place order", schema["properties"]["approve"]["description"])
        self.assertEqual(self.actions(), [])
        self.answer(ask, "accept", {})  # Hermes accepts with empty content
        done = self.recv()
        self.assertEqual(done["id"], call)
        self.assertFalse(done["result"].get("isError"))
        sent = self.actions()
        self.assertEqual(len(sent), 1)
        self.assertNotIn("commit", sent[0])
        self.assertEqual((sent[0]["ref"], sent[0]["tabId"], sent[0]["epoch"]), ("e1", "mac-tab-1", 1))
        [entry] = self.decisions()
        self.assertEqual({k: entry[k] for k in ("bot", "origin", "kind", "summary", "amount", "decision")},
                         {"bot": "bot1", "origin": "https://shop.example", "kind": "purchase",
                          "summary": "One brass desk lamp", "amount": "40.00", "decision": "approved"})
        self.assertIn("ts", entry)

    def test_a_declined_commit_never_reaches_the_backend(self):
        self.open_checkout()
        for action in ("decline", "cancel"):
            with self.subTest(action=action):
                call = self.act(action="click", ref="e1", commit=PURCHASE)
                self.answer(self.recv(), action)
                self.refused(call, "declined")
        self.answer_with_unchecked_box()
        self.assertEqual(self.actions(), [])
        self.assertEqual([d["decision"] for d in self.decisions()], ["declined"] * 3)

    def answer_with_unchecked_box(self):
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        self.answer(self.recv(), "accept", {"approve": False})
        self.refused(call, "declined")

    def test_a_scheduled_job_is_declined_and_told_to_leave_it_staged(self):
        # Hermes advertises elicitation to every MCP server and, with no user
        # to ask (cron, -q), declines on its own.
        self.open_checkout()
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        self.answer(self.recv(), "decline")
        msg = self.refused(call, "declined")
        self.assertIn("Leave everything staged", self.text(msg))
        self.assertIn("tell the user", self.text(msg))
        self.assertEqual(self.actions(), [])

    def test_without_elicitation_support_nothing_runs(self):
        self.open_checkout(elicitation=False)
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        msg = self.refused(call, "approval_unavailable")
        self.assertNotIn("method", msg)
        self.assertEqual(self.actions(), [])
        self.assertEqual(self.decisions()[-1]["decision"], "approval_unavailable")

    def test_an_elicitation_error_fails_closed(self):
        self.open_checkout()
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        ask = self.recv()
        self.write({"jsonrpc": "2.0", "id": ask["id"], "error": {"code": -32601, "message": "no"}})
        self.refused(call, "approval_unavailable")
        self.assertEqual(self.actions(), [])

    def test_a_commit_button_without_commit_is_refused(self):
        self.open_checkout()
        call = self.act(action="click", ref="e1")
        self.refused(call, "commit_required")
        self.assertEqual(self.actions(), [])
        ok = self.act(action="click", ref="e2")
        done = self.recv()
        self.assertEqual(done["id"], ok)
        self.assertFalse(done["result"].get("isError"))
        self.assertEqual([a["ref"] for a in self.actions()], ["e2"])
        self.assertEqual(self.decisions()[-1]["decision"], "commit_required")

    def open_search(self):
        self.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://shop.example/search"})
        self.recv()
        self.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": "mac-tab-2"})
        self.recv()

    def ran(self, call):
        done = self.recv()
        self.assertEqual(done["id"], call)
        self.assertFalse(done["result"].get("isError"), done)

    def test_enter_or_space_on_a_page_with_a_commit_control_needs_commit(self):
        self.open_checkout()
        for args in ({"action": "press", "ref": "e4", "key": "Enter"},
                     {"action": "press", "key": "Return"},
                     {"action": "press", "key": " "},
                     {"action": "batch", "steps": [{"action": "type", "ref": "e4", "text": "4242"},
                                                   {"action": "press", "key": "Enter"}]}):
            with self.subTest(args=args):
                self.refused(self.act(**args), "commit_required")
        self.assertEqual(self.actions(), [])
        self.ran(self.act(action="press", ref="e4", key="Tab"))
        call = self.act(action="press", ref="e4", key="Enter", commit=PURCHASE)
        ask = self.recv()
        self.assertIn('presses Enter; presses a key on "Card number"', ask["params"]["message"])
        self.answer(ask, "accept", {})
        self.ran(call)
        self.assertEqual([a["key"] for a in self.actions()], ["Tab", "Enter"])

    def test_enter_on_a_page_without_a_commit_control_runs(self):
        self.open_checkout()
        # The same tab, once it leaves the checkout page, no longer counts it.
        self.ran(self.act(action="navigate", url="https://shop.example/thanks"))
        self.ran(self.act(action="press", ref="e21", key="Enter"))
        # A navigation reply names no frames, so a key aimed at no control
        # waits for a snapshot that does.
        self.refused(self.act(action="press", key="Enter"), "snapshot_required")
        self.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": "mac-tab-1"})
        self.recv()
        self.ran(self.act(action="press", key="Enter"))
        self.ran(self.act(action="press", ref="e21", key="Enter", modifiers=["control"]))
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="press", ref="e1", key="Enter"))
        self.ran(self.act(tabId="mac-tab-2", action="click", x=10, y=20))

    def test_any_key_that_can_act_needs_commit_on_a_commit_page(self):
        self.open_checkout()
        for key, modifiers in (("\r", None), ("\n", None), ("Delete", None), ("Backspace", None),
                               ("F5", None), ("a", ["meta"])):
            with self.subTest(key=key, modifiers=modifiers):
                args = {"action": "press", "ref": "e4", "key": key}
                if modifiers:
                    args["modifiers"] = modifiers
                self.refused(self.act(**args), "commit_required")
        self.assertEqual(self.actions(), [])
        for key in ("Tab", "ArrowDown", "Escape", "a", "7", "A"):
            with self.subTest(key=key):
                self.ran(self.act(action="press", ref="e4", key=key))

    def test_batch_steps_are_judged_on_the_batch_tab(self):
        self.open_checkout()
        self.open_search()
        # The app runs every step on the batch's tab; a step's own tabId is ignored.
        msg = self.refused(self.act(tabId="mac-tab-1", action="batch", steps=[
            {"action": "press", "tabId": "mac-tab-2", "key": "Enter"}]), "commit_required")
        self.assertIn("Place order", self.text(msg))
        self.ran(self.act(tabId="mac-tab-2", action="batch", steps=[
            {"action": "press", "tabId": "mac-tab-1", "key": "Enter"}]))

    def test_a_page_not_seen_in_full_gates_keys_and_position_clicks(self):
        self.open_checkout()
        cases = [
            # Opened, so its URL is known, but no element list yet.
            ("open", {"url": "https://shop.example/search"}, "mac-tab-2"),
            # Navigated: the reply's 40 controls may be the first 40 of more.
            ("navigate", {"url": "https://shop.example/long"}, "mac-tab-1"),
            # Navigated from a page seen in full, and the reply named no controls.
            ("bare", {"url": "https://shop.example/bare"}, "mac-tab-2"),
            # A snapshot cut at maxElements.
            ("snapshot", {"tabId": "mac-tab-3"}, "mac-tab-3"),
            # A snapshot too big for the router to read.
            ("big", {"tabId": "mac-tab-2", "maxChars": 200000}, "mac-tab-2"),
        ]
        for kind, args, tab in cases:
            with self.subTest(kind=kind, url=args.get("url")):
                if kind == "open":
                    self.send("tools/call", name="cua_alans_way_open", arguments=args)
                elif kind == "navigate":
                    self.act(tabId=tab, action="navigate", **args)
                elif kind == "bare":
                    self.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": tab})
                    self.recv()
                    self.ran(self.act(tabId=tab, action="press", key="Enter"))  # seen in full
                    self.act(tabId=tab, action="navigate", **args)
                elif kind == "snapshot":
                    self.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://shop.example/catalog"})
                    self.recv()
                    self.send("tools/call", name="cua_alans_way_snapshot", arguments=args)
                else:
                    self.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": tab})
                    self.recv()
                    self.send("tools/call", name="cua_alans_way_snapshot", arguments=args)
                self.recv()
                self.refused(self.act(tabId=tab, action="press", key="Enter"), "snapshot_required")
                self.refused(self.act(tabId=tab, action="click", x=5, y=5), "snapshot_required")
        self.assertEqual([a for a in self.actions() if a.get("action") != "navigate"],
                         [{"tabId": "mac-tab-2", "action": "press", "key": "Enter", "epoch": 1}])
        # With commit the user decides instead.
        call = self.act(tabId="mac-tab-3", action="press", key="Enter", commit=PURCHASE)
        self.answer(self.recv(), "accept", {})
        self.ran(call)

    def test_clicks_by_selector_or_position_are_checked(self):
        self.open_checkout()
        for args in ({"action": "click", "selector": "#placeOrderBtn"},
                     {"action": "click", "selector": "[data-test=buy-now]"},
                     {"action": "click", "selector": "button[type=submit]"},
                     {"action": "click", "x": 640, "y": 410},
                     {"action": "batch", "steps": [{"action": "click", "selector": "form .submit-order"}]},
                     # A selector that names no commit can still point at one.
                     {"action": "click", "selector": "form > button:last-child"},
                     {"action": "click", "selector": ".btn-primary"},
                     {"action": "batch", "steps": [{"action": "click", "selector": ".add-to-cart"}]}):
            with self.subTest(args=args):
                self.refused(self.act(**args), "commit_required")
        self.assertEqual(self.actions(), [])
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="click", selector=".btn-primary"))
        self.refused(self.act(tabId="mac-tab-3", action="click", selector=".btn-primary"), "snapshot_required")

    def test_an_icon_only_button_counts_as_a_blind_click(self):
        self.open_checkout()
        msg = self.refused(self.act(action="click", ref="e5"), "commit_required")
        self.assertIn("unnamed control", self.text(msg))
        self.refused(self.act(action="batch", steps=[{"action": "double_click", "ref": "e5"}]), "commit_required")
        self.assertEqual(self.actions(), [])
        call = self.act(action="click", ref="e5", commit=PURCHASE)
        ask = self.recv()
        self.assertIn("clicks an unnamed control", ask["params"]["message"])
        self.answer(ask, "accept", {})
        self.ran(call)

    def test_page_script_and_devtools_input_need_commit_on_a_commit_page(self):
        self.open_checkout()
        for args in ({"action": "eval", "code": "document.querySelector('button').click()"},
                     {"action": "cdp", "method": "Input.dispatchKeyEvent",
                      "params": {"type": "keyDown", "key": "Enter"}},
                     {"action": "cdp", "method": "Runtime.evaluate",
                      "params": {"expression": "document.forms[0].submit()"}},
                     {"action": "cdp", "method": "DOM.setOuterHTML", "params": {"nodeId": 1, "outerHTML": "x"}},
                     {"action": "batch", "steps": [{"action": "eval", "code": "document.forms[0].requestSubmit()"}]},
                     {"action": "batch", "steps": [{"action": "cdp", "method": "Input.dispatchMouseEvent"}]}):
            with self.subTest(args=args):
                msg = self.refused(self.act(**args), "commit_required")
                self.assertIn("Place order", self.text(msg))
        self.assertEqual(self.actions(), [])
        for method in ("Accessibility.getFullAXTree", "DOM.getDocument", "Page.captureScreenshot",
                       "Network.enable", "Emulation.setDeviceMetricsOverride"):
            with self.subTest(method=method):
                self.ran(self.act(action="cdp", method=method))
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="eval", code="document.title"))
        self.refused(self.act(tabId="mac-tab-3", action="eval", code="document.title"), "snapshot_required")
        call = self.act(action="eval", code="document.forms[0].requestSubmit()", commit=PURCHASE)
        ask = self.recv()
        self.assertIn("runs a page script", ask["params"]["message"])
        self.answer(ask, "accept", {})
        self.ran(call)

    def test_drags_and_selects_are_judged_like_clicks(self):
        self.open_checkout()
        for args in ({"action": "drag", "ref": "e2", "toRef": "e1"},
                     {"action": "drag", "x": 640, "y": 410, "toX": 640, "toY": 410},
                     {"action": "drag", "ref": "e2", "toSelector": ".cart"},
                     {"action": "select", "selector": "#shipping", "value": "express"}):
            with self.subTest(args=args):
                self.refused(self.act(**args), "commit_required")
        self.assertEqual(self.actions(), [])
        self.ran(self.act(action="drag", ref="e2", toRef="e4"))
        self.ran(self.act(action="select", ref="e4", value="visa"))

    def test_a_control_targeted_by_name_is_judged_by_that_name(self):
        self.open_checkout()
        for args in ({"action": "click", "name": "Place order"},
                     {"action": "double_click", "name": "Place order", "role": "button"},
                     {"action": "select", "name": "Delete"},
                     {"action": "batch", "steps": [{"action": "click", "name": "Place order"}]}):
            with self.subTest(args=args):
                self.refused(self.act(**args), "commit_required")
        self.assertEqual(self.actions(), [])
        call = self.act(action="click", name="Place order", commit=PURCHASE)
        ask = self.recv()
        self.assertIn('(clicks "Place order")', ask["params"]["message"])
        self.answer(ask, "accept", {})
        self.ran(call)
        # The app acts only on that exact name, so a harmless one passes even here.
        self.ran(self.act(action="click", name="Add to cart"))
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="click", name="Search"))
        self.refused(self.act(tabId="mac-tab-2", action="click", name="Send"), "commit_required")

    def test_a_ref_not_seen_on_the_current_page_is_refused(self):
        self.open_checkout()
        for args in ({"action": "click", "ref": "e99"},
                     {"action": "drag", "ref": "e2", "toRef": "e98"},
                     {"action": "press", "ref": "e97", "key": "Tab"},
                     {"action": "click", "ref": "e96", "commit": PURCHASE}):
            with self.subTest(args=args):
                self.refused(self.act(**args), "snapshot_required")
        # A ref from the page before a navigation names nothing on the new one.
        self.ran(self.act(action="navigate", url="https://shop.example/thanks"))
        self.refused(self.act(action="click", ref="e2"), "snapshot_required")
        self.ran(self.act(action="click", ref="e21"))
        self.assertEqual([a["action"] for a in self.actions()], ["navigate", "click"])

    def test_controls_that_appear_in_a_delta_reply_are_learned(self):
        self.open_checkout()
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="press", key="Enter"))
        # A Send button appears after typing; the reply says only what changed.
        self.ran(self.act(tabId="mac-tab-2", action="type", ref="e1", text="Send", generation=1))
        for args in ({"action": "click", "ref": "e7"}, {"action": "press", "key": "Enter"},
                     {"action": "eval", "code": "document.forms[0].submit()"}):
            with self.subTest(args=args):
                msg = self.refused(self.act(tabId="mac-tab-2", **args), "commit_required")
                self.assertIn("Send", self.text(msg))

    def test_a_delta_reply_leaves_the_page_partly_seen(self):
        self.open_checkout()
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="type", ref="e1", text="Clear", generation=1))
        self.ran(self.act(tabId="mac-tab-2", action="click", ref="e7"))
        self.refused(self.act(tabId="mac-tab-2", action="press", key="Enter"), "snapshot_required")
        self.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": "mac-tab-2"})
        self.recv()
        self.ran(self.act(tabId="mac-tab-2", action="press", key="Enter"))

    def test_an_overlay_close_ref_is_learned(self):
        self.open_checkout()
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="click", ref="e5"))

    def test_a_reload_on_a_commit_page_needs_commit(self):
        self.open_checkout()
        self.refused(self.act(action="reload"), "commit_required")
        self.refused(self.act(action="cdp", method="Page.reload"), "commit_required")
        self.assertEqual(self.actions(), [])
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="reload"))

    def test_an_address_that_reads_like_an_action_needs_commit(self):
        self.open_checkout()
        for args in ({"action": "navigate", "url": "https://shop.example/checkout/complete"},
                     {"action": "navigate", "url": "shop.example/orders/7/delete"},
                     {"action": "navigate", "url": "https://shop.example/cart?step=confirm"},
                     {"action": "navigate", "url": "https://shop.example/api/placeOrder"},
                     {"action": "cdp", "method": "Page.navigate", "params": {"url": "https://shop.example/pay"}},
                     {"action": "batch", "steps": [{"action": "navigate", "url": "https://shop.example/submit"}]},
                     # Another site's action address counts too.
                     {"action": "navigate", "url": "https://other.example/delete"}):
            with self.subTest(args=args):
                msg = self.refused(self.act(**args), "commit_required")
                self.assertIn("looks like an address", self.text(msg))
        self.assertEqual(self.actions(), [])
        for url in ("https://shop.example/maps/place/x", "https://shop.example/payments-help",
                    "https://other.example/help"):
            with self.subTest(url=url):
                self.ran(self.act(action="navigate", url=url))

    def test_accepting_a_page_dialog_counts_as_blind_input(self):
        self.open_checkout()
        self.refused(self.act(action="click", ref="e2", dialog={"accept": True}), "commit_required")
        self.refused(self.act(action="batch", dialog={"accept": True}, steps=[{"action": "click", "ref": "e2"}]),
                     "commit_required")
        self.assertEqual(self.actions(), [])
        self.ran(self.act(action="click", ref="e2", dialog={"accept": False}))
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="click", ref="e1", dialog={"accept": True}))

    def test_blind_steps_after_one_that_may_change_the_page_need_their_own_call(self):
        self.open_checkout()
        self.open_search()
        for steps in ([{"action": "click", "ref": "e1"}, {"action": "press", "key": "Enter"}],
                      [{"action": "navigate", "url": "https://shop.example/cart"}, {"action": "click", "x": 5, "y": 5}],
                      [{"action": "back"}, {"action": "eval", "code": "1"}]):
            with self.subTest(steps=steps):
                msg = self.refused(self.act(tabId="mac-tab-2", action="batch", steps=steps), "snapshot_required")
                self.assertIn("earlier step in this batch", self.text(msg))
        self.ran(self.act(tabId="mac-tab-2", action="batch", steps=[
            {"action": "type", "ref": "e1", "text": "lamp"}, {"action": "press", "key": "Tab"}]))

    def test_a_frame_from_another_site_leaves_the_page_unjudgeable(self):
        self.open_checkout()
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="navigate", url="https://shop.example/embed"))
        for attempt in range(2):  # a snapshot cannot read into the frame
            self.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": "mac-tab-2"})
            self.recv()
            for args in ({"action": "press", "key": "Enter"}, {"action": "click", "x": 300, "y": 400},
                         {"action": "cdp", "method": "Input.dispatchMouseEvent"}):
                with self.subTest(attempt=attempt, args=args):
                    msg = self.refused(self.act(tabId="mac-tab-2", **args), "snapshot_required")
                    self.assertIn("https://calendly.example", self.text(msg))
        # Input aimed at the page's own controls cannot land in the frame.
        self.ran(self.act(tabId="mac-tab-2", action="click", ref="e21"))
        self.ran(self.act(tabId="mac-tab-2", action="press", ref="e21", key="Enter"))
        self.ran(self.act(tabId="mac-tab-2", action="eval", code="1"))
        call = self.act(tabId="mac-tab-2", action="click", x=300, y=400,
                        commit={"kind": "booking", "summary": "30 minute call"})
        self.answer(self.recv(), "accept", {})
        self.ran(call)
        # A frame from the page's own site is readable.
        self.ran(self.act(tabId="mac-tab-2", action="navigate", url="https://shop.example/own-frame"))
        self.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": "mac-tab-2"})
        self.recv()
        self.ran(self.act(tabId="mac-tab-2", action="press", key="Enter"))
        # The app lists at most 8 frames, so a ninth may be from anywhere.
        self.ran(self.act(tabId="mac-tab-2", action="navigate", url="https://shop.example/many-frames"))
        self.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": "mac-tab-2"})
        self.recv()
        msg = self.refused(self.act(tabId="mac-tab-2", action="press", key="Enter"), "snapshot_required")
        self.assertIn("more frames than it lists", self.text(msg))

    def test_a_script_for_every_later_page_is_never_allowed(self):
        self.open_checkout()
        self.open_search()
        for args in ({"action": "cdp", "method": "Page.addScriptToEvaluateOnNewDocument", "params": {"source": "x"}},
                     {"action": "cdp", "method": "Page.addScriptToEvaluateOnNewDocument", "commit": PURCHASE},
                     {"action": "batch", "steps": [{"action": "cdp", "method": "Page.addScriptToEvaluateOnLoad"}]}):
            with self.subTest(args=args):
                self.refused(self.act(tabId="mac-tab-2", **args), "not_allowed")
        self.assertEqual(self.actions(), [])

    def test_a_right_click_is_judged_like_a_click(self):
        self.open_checkout()
        self.refused(self.act(action="right_click", ref="e1"), "commit_required")
        self.refused(self.act(action="right_click", x=5, y=5), "commit_required")
        self.assertEqual(self.actions(), [])

    def test_back_or_forward_after_an_action_address_needs_commit(self):
        self.open_checkout()
        self.open_search()
        self.ran(self.act(tabId="mac-tab-2", action="back"))
        call = self.act(tabId="mac-tab-2", action="navigate", url="https://shop.example/order/complete", commit=PURCHASE)
        self.answer(self.recv(), "accept", {})
        self.ran(call)
        self.ran(self.act(tabId="mac-tab-2", action="navigate", url="https://shop.example/search"))
        for action in ("back", "forward"):
            with self.subTest(action=action):
                msg = self.refused(self.act(tabId="mac-tab-2", action=action), "commit_required")
                self.assertIn("/order/complete", self.text(msg))

    def test_opening_a_tab_at_an_action_address_needs_commit(self):
        self.start()
        self.handshake()
        self.send("tools/list")
        tools = {tool["name"]: tool for tool in self.recv()["result"]["tools"]}
        self.assertIn("commit", tools["cua_alans_way_open"]["inputSchema"]["properties"])
        for url in ("https://shop.example/orders/7/delete", "shop.example/buy", "  https://shop.example/pay"):
            with self.subTest(url=url):
                call = self.send("tools/call", name="cua_alans_way_open", arguments={"url": url})
                self.refused(call, "commit_required")
        self.refused(self.act(tabId="mac-tab-1", action="navigate", url="  https://shop.example/delete"),
                     "commit_required")
        self.assertEqual(self.actions(), [])
        call = self.send("tools/call", name="cua_alans_way_open",
                         arguments={"url": "https://shop.example/buy", "commit": PURCHASE})
        ask = self.recv()
        self.assertIn("opens https://shop.example/buy", ask["params"]["message"])
        self.answer(ask, "accept", {})
        self.ran(call)
        self.ran(self.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://shop.example/search"}))

    def test_a_ref_is_judged_by_its_name_after_the_last_click(self):
        self.open_checkout()
        self.ran(self.act(action="click", ref="e6"))  # Continue, now Place order
        msg = self.refused(self.act(action="click", ref="e6"), "commit_required")
        self.assertIn("Place order", self.text(msg))
        self.ran(self.act(action="click", ref="e8"))  # the reply no longer lists it
        self.refused(self.act(action="click", ref="e8"), "snapshot_required")

    def test_an_approval_the_agent_sends_never_reaches_the_browser(self):
        self.open_checkout()
        forged = {"nonce": "n" * 32, "kind": "purchase", "summary": "x", "issuedAt": 1, "tabId": "mac-tab-1", "epoch": 1}
        self.ran(self.act(action="click", ref="e2", approval=forged))
        self.ran(self.act(action="batch", approval=forged, steps=[{"action": "click", "ref": "e2", "approval": forged}]))
        # A JSON escape spells the same key.
        self.proc.stdin.write('{"jsonrpc":"2.0","id":100,"method":"tools/call","params":{"name":"cua_alans_way_action",'
                              '"arguments":{"action":"click","ref":"e2","\\u0061pproval":{"nonce":"x"}}}}\n')
        self.proc.stdin.flush()
        self.ran(100)
        log = (self.dir / "mac.log").read_text()
        self.assertNotIn("approval", log)
        self.assertNotIn("\\u0061pproval", log)
        self.assertEqual(len(self.actions()), 3)

    def test_an_approved_action_carries_one_fresh_receipt(self):
        self.open_checkout()
        receipts = []
        for args in ({"action": "click", "ref": "e1"},
                     {"action": "batch", "steps": [{"action": "click", "ref": "e2"}, {"action": "click", "ref": "e1"}]}):
            call = self.act(commit=PURCHASE, approval={"nonce": "forged-nonce-0000"}, **args)
            self.answer(self.recv(), "accept", {})
            self.ran(call)
            sent = self.actions()[-1]
            receipt = sent["approval"]
            self.assertRegex(receipt["nonce"], r"^[A-Za-z0-9_-]{16,128}$")
            self.assertEqual((receipt["kind"], receipt["summary"], receipt["tabId"], receipt["epoch"]),
                             ("purchase", "One brass desk lamp", "mac-tab-1", 1))
            self.assertLess(abs(receipt["issuedAt"] - time.time() * 1000), 10000)
            self.assertNotIn("commit", sent)
            for step in sent.get("steps", []):
                self.assertNotIn("approval", step)
            receipts.append(receipt["nonce"])
        self.assertNotEqual(receipts[0], receipts[1])
        # An unapproved call never carries one.
        self.ran(self.act(action="click", ref="e2"))
        self.assertNotIn("approval", self.actions()[-1])

    def test_an_approved_open_carries_no_receipt(self):
        self.start()
        self.handshake()
        call = self.send("tools/call", name="cua_alans_way_open",
                         arguments={"url": "https://shop.example/buy", "commit": PURCHASE})
        self.answer(self.recv(), "accept", {})
        self.ran(call)
        opened = [json.loads(line[5:]) for line in (self.dir / "mac.log").read_text().splitlines()
                  if '"cua_alans_way_open"' in line and '"tools/call"' in line]
        self.assertNotIn("approval", opened[-1]["params"]["arguments"])

    def test_typing_then_a_key_in_one_batch_needs_commit(self):
        self.open_checkout()
        self.open_search()
        for key in ("Enter", "\r"):
            with self.subTest(key=key):
                msg = self.refused(self.act(tabId="mac-tab-2", action="batch", steps=[
                    {"action": "type", "ref": "e1", "text": "hi"}, {"action": "press", "key": key}]), "commit_required")
                self.assertIn("right after typing", self.text(msg))
        self.assertEqual(self.actions(), [])
        # On its own, the key is judged against the page.
        self.ran(self.act(tabId="mac-tab-2", action="type", ref="e1", text="hi"))
        self.ran(self.act(tabId="mac-tab-2", action="press", key="Enter"))
        self.ran(self.act(tabId="mac-tab-2", action="batch", steps=[
            {"action": "type", "ref": "e1", "text": "hi"}, {"action": "press", "key": " "}]))

    def test_a_link_to_an_action_address_needs_commit(self):
        self.open_checkout()
        for args in ({"action": "click", "ref": "e9"}, {"action": "click", "name": "Item 3"}):
            with self.subTest(args=args):
                msg = self.refused(self.act(**args), "commit_required")
                self.assertIn("/cart/delete", self.text(msg))
        self.assertEqual(self.actions(), [])
        self.ran(self.act(action="press", ref="e9", key="Tab"))
        self.ran(self.act(action="click", ref="e10"))

    def test_input_that_may_land_on_a_captcha_is_refused_before_anyone_is_asked(self):
        self.open_checkout()
        self.ran(self.act(action="navigate", url="https://shop.example/captcha-form"))
        for args in ({"action": "click", "x": 120, "y": 300},
                     {"action": "click", "x": 120, "y": 300, "commit": PURCHASE},
                     {"action": "press", "key": "Enter"},
                     {"action": "eval", "code": "document.querySelector('iframe').click()"}):
            with self.subTest(args=args):
                msg = self.refused(self.act(**args), "challenge_present")
                self.assertIn('recaptcha challenge', self.text(msg))
                self.assertIn('reason "captcha"', self.text(msg))
                self.assertNotIn("commit_required", self.text(msg))
        self.assertEqual(self.decisions(), [])
        # The rest of the page is still the bot's: a named commit asks as before.
        self.refused(self.act(action="click", ref="e21"), "commit_required")
        call = self.act(action="click", ref="e21", commit=PURCHASE)
        self.answer(self.recv(), "decline")
        self.refused(call, "declined")
        self.assertEqual(self.actions()[-1]["action"], "navigate")
        # A reply without the challenge means it has cleared.
        self.ran(self.act(action="scroll", y=0))
        self.refused(self.act(action="click", x=120, y=300), "commit_required")

    def test_a_whole_page_check_refuses_its_commit_words(self):
        self.open_checkout()
        self.ran(self.act(action="navigate", url="https://www.google.com/sorry/index?continue=x"))
        for args in ({"action": "click", "ref": "e21"}, {"action": "click", "name": "Submit", "commit": PURCHASE}):
            with self.subTest(args=args):
                msg = self.refused(self.act(**args), "challenge_present")
                self.assertIn("google_sorry challenge", self.text(msg))
        self.assertEqual(self.actions()[-1]["action"], "navigate")
        self.assertEqual(self.decisions(), [])

    def test_a_tab_the_human_holds_is_refused_in_its_own_words(self):
        self.open_checkout()
        self.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://shop.example/handed"})
        self.recv()
        msg = self.refused(self.act(tabId="mac-tab-4", action="click", name="Place order", commit=PURCHASE),
                           "awaiting_human")
        self.assertIn("captcha", self.text(msg))
        self.refused(self.act(tabId="mac-tab-4", action="press", key="Enter"), "awaiting_human")
        # A stale epoch is refused before anyone is asked to approve.
        msg = self.refused(self.act(tabId="mac-tab-1", epoch=0, action="click", ref="e1", commit=PURCHASE),
                           "stale_control_epoch")
        self.assertEqual(self.actions(), [])
        self.assertEqual(self.decisions(), [])

    def test_a_new_control_epoch_drops_what_the_gate_knew_of_the_page(self):
        self.open_checkout()
        self.ran(self.act(action="claim"))
        self.refused(self.act(action="click", ref="e2"), "snapshot_required")
        self.send("tools/call", name="cua_alans_way_snapshot", arguments={})
        self.recv()
        self.ran(self.act(action="click", ref="e2"))
        self.assertEqual(self.actions()[-1]["epoch"], 2)

    def test_an_approval_is_void_once_the_page_or_epoch_changes(self):
        for change in ({"action": "claim"}, {"action": "navigate", "url": "https://other.example/"}):
            with self.subTest(change=change):
                self.tearDown()
                self.setUp()
                self.open_checkout()
                call = self.act(action="click", ref="e1", commit=PURCHASE)
                ask = self.recv()
                self.ran(self.act(**change))
                self.answer(ask, "accept", {})
                self.refused(call, "page_changed")
                self.assertEqual([a["action"] for a in self.actions()], [change["action"]])
                self.assertEqual(self.decisions()[-1]["decision"], "page_changed")

    def test_a_blind_press_on_a_tab_never_read_needs_a_snapshot(self):
        self.start()
        self.handshake()
        self.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://shop.example/"})
        self.recv()
        self.refused(self.act(tabId="mac-tab-9", action="press", key="Enter"), "snapshot_required")
        self.assertEqual(self.actions(), [])

    def test_a_ref_this_router_never_saw_is_refused_until_a_snapshot(self):
        self.start()
        self.handshake()
        self.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://shop.example/"})
        self.recv()
        # A respawned router has no names for refs the agent still holds.
        call = self.act(action="click", ref="e1")
        self.refused(call, "snapshot_required")
        self.assertEqual(self.actions(), [])
        self.send("tools/call", name="cua_alans_way_snapshot", arguments={})
        self.recv()
        self.refused(self.act(action="click", ref="e1"), "commit_required")

    def test_a_duplicate_accept_runs_the_action_once(self):
        self.open_checkout()
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        ask = self.recv()
        self.answer(ask, "accept", {})
        self.answer(ask, "accept", {})
        self.assertEqual(self.recv()["id"], call)
        self.assertIsNone(self.recv(timeout=1, required=False))
        self.assertEqual(len(self.actions()), 1)

    def test_a_batch_with_a_commit_step_is_refused_without_commit(self):
        self.open_checkout()
        call = self.act(action="batch", steps=[{"action": "click", "ref": "e2"},
                                               {"action": "press", "ref": "e3", "key": "Enter"}])
        self.refused(call, "commit_required")
        self.assertEqual(self.actions(), [])

    def test_a_batch_is_gated_once_before_it_runs(self):
        self.open_checkout()
        steps = [{"action": "click", "ref": "e2"}, {"action": "click", "ref": "e1"},
                 {"action": "wait", "text": "Thanks"}]
        call = self.act(action="batch", steps=steps, commit=PURCHASE)
        self.answer(self.recv(), "accept", {"approve": True})
        done = self.recv()
        self.assertEqual(done["id"], call)
        self.assertFalse(done["result"].get("isError"))
        self.assertEqual([a["steps"] for a in self.actions()], [steps])
        self.assertEqual(len(self.decisions()), 1)

    def test_an_invalid_commit_is_refused(self):
        self.open_checkout()
        for commit in ({"kind": "gift", "summary": "x"}, {"kind": "purchase"},
                       {"kind": "purchase", "summary": "x" * 201}):
            with self.subTest(commit=commit):
                self.refused(self.act(action="click", ref="e1", commit=commit), "commit_invalid")
        self.assertEqual(self.actions(), [])

    def test_an_unanswered_approval_times_out_and_a_late_tap_does_nothing(self):
        self.env = {"HERMES_ROUTER_APPROVAL_MS": "500"}
        self.open_checkout()
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        ask = self.recv()
        withdrawn = self.recv()
        self.assertEqual((withdrawn["method"], withdrawn["params"]["requestId"]),
                         ("notifications/cancelled", ask["id"]))
        self.refused(call, "approval_timeout")
        self.answer(ask, "accept", {})
        self.assertIsNone(self.recv(timeout=1, required=False))
        self.assertEqual(self.actions(), [])
        self.assertEqual(self.decisions()[-1]["decision"], "approval_timeout")

    def test_a_slow_approval_does_not_trip_the_call_deadlines(self):
        self.env = {"HERMES_ROUTER_CALL_DEADLINE_MS": "300", "HERMES_ROUTER_CALL_HARD_MS": "600"}
        self.open_checkout()
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        ask = self.recv()
        time.sleep(2)  # the user reads the card; the host is fine
        self.answer(ask, "accept", {})
        done = self.recv()
        self.assertEqual(done["id"], call)
        self.assertFalse(done["result"].get("isError"))
        self.assertEqual(done["result"]["_meta"]["workspace"]["host"], "mac")
        self.assertEqual(len(self.actions()), 1)

    def test_a_cancelled_call_never_runs_on_a_late_approval(self):
        self.open_checkout()
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        ask = self.recv()
        self.send("notifications/cancelled", requestId=call, reason="user stopped the turn")
        withdrawn = self.recv()
        self.assertEqual(withdrawn["params"]["requestId"], ask["id"])
        self.answer(ask, "accept", {})
        self.assertIsNone(self.recv(timeout=1, required=False))
        self.assertEqual(self.actions(), [])

    def test_an_approved_commit_lost_in_failover_is_not_replayed(self):
        self.env = {"MAC_MODE": "die-on-commit"}
        self.open_checkout()
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        self.answer(self.recv(), "accept", {})
        msg = self.refused(call, "NOT retried")
        self.assertEqual(len(self.actions()), 1)
        self.assertEqual(self.actions("vm.log"), [])
        self.assertIsNone(self.recv(timeout=1, required=False), msg)

    def test_an_approved_vm_commit_that_times_out_is_not_called_retryable(self):
        self.env = {"VM_MODE": "slow", "VM_DELAY_MS": "3000", "HERMES_ROUTER_CALL_HARD_MS": "1000"}
        self.open_checkout()
        self.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://vm.example/", "host": "vm"})
        self.recv()
        call = self.act(tabId="vm-tab-1", action="click", name="Buy now", commit=PURCHASE)
        self.answer(self.recv(), "accept", {})
        msg = self.refused(call, "NOT retried")
        self.assertNotIn("Retry", self.text(msg))

    def test_a_cancelled_call_held_during_a_failover_never_prompts_or_runs(self):
        self.env = {"MAC_MODE": "die-on-status", "HERMES_ROUTER_RESTORE_MS": "3000"}
        # A VPS browser host that accepts and never answers keeps the restore,
        # and so the hold on new calls, open for its full timeout.
        silent = socket.socket()
        self.addCleanup(silent.close)
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        (self.dir / "conn.json").write_text(json.dumps(
            {"url": "http://127.0.0.1:%d" % silent.getsockname()[1], "token": "tok"}))
        self.open_checkout()
        status = self.send("tools/call", name="cua_alans_way_status", arguments={})
        time.sleep(0.5)  # the host is gone; calls now wait for the VPS restore
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        self.send("notifications/cancelled", requestId=call, reason="user stopped the turn")
        self.assertEqual(self.recv()["id"], status)
        self.assertIsNone(self.recv(timeout=2, required=False))
        self.assertEqual(self.actions("vm.log"), [])

    def test_a_failover_while_awaiting_approval_never_runs_the_commit(self):
        self.env = {"MAC_MODE": "die-on-status"}
        self.open_checkout()
        call = self.act(action="click", ref="e1", commit=PURCHASE)
        ask = self.recv()
        status = self.send("tools/call", name="cua_alans_way_status", arguments={})
        replayed = self.recv()
        self.assertEqual(replayed["id"], status)
        self.answer(ask, "accept", {})
        self.refused(call, "host_changed")
        self.assertEqual(self.actions(), [])
        self.assertEqual(self.actions("vm.log"), [])



@unittest.skipUnless(NODE, "node is required for the commit name tests")
class CommitNameTests(unittest.TestCase):
    COMMITS = [
        "Place order", "Place your order", "Pay $40.00", "Buy now", "Buy-now", "Purchase",
        "Confirm and pay", "Complete booking", "Book now", "Book", "Reserve", "Request to book",
        "Confirm order", "Confirm booking", "Complete order", "Submit order", "Order now",
        "Send", "Send message", "Post", "Publish", "Submit application", "Easy Apply",
        "Delete", "Delete account", "Subscribe", "Donate", "Transfer",
        "Zahlungspflichtig bestellen", "Bestellen", "Kostenpflichtig bestellen",
        "Jetzt kostenpflichtig bestellen", "Kauf abschließen", "Kauf abschliessen",
        "Pay with Google Pay now", "Confirm and pay with PayPal",
        "Complete reservation", "Confirm reservation", "Confirm", "Confirm payment", "Make payment",
        "Reply", "Comment", "Remove", "Schedule Event", "Place bid", "Close account", "Remove filter, delete account",
        "Reservar", "Jetzt buchen", "Buchen", "Reservieren", "Bestellung abschicken", "Passer la commande",
        "Acheter", "Valider votre commande", "Confirmer", "réservation", "Finalizar compra", "Confirmar reserva",
        "今すぐ買う", "注文する", "Senden", "Envoyer", "Enviar", "送信", "Löschen", "Supprimer", "Eliminar", "削除",
        "Pay with credit card and place order", "Pay with Visa ending 4242 now", "Remove from cart and delete account", "Remove filter, delete account", "Delete account filter", "Jetzt kaufen", "Commander", "Comprar", "Pagar",
        "注文を確定する", "ご注文を確定する", "Réserver", "RÉSERVER UNE TABLE",
        "Buy", "Submit", "Payer", "Valider la commande", "Confirmer la commande",
        "Realizar pedido", "Confirmar pedido", "Kaufen", "Bezahlen", "Jetzt bezahlen",
        "購入する", "支払う", "予約する", "Pay with card and place order", "Pay with PayPal and submit",
    ]
    NOT_COMMITS = [
        "Add to cart", "Send code", "Send verification code", "Send me a code",
        "Pay with PayPal", "Pay with Apple Pay", "Purchase history", "Delete filter: Red",
        "Size M filter, delete", "Address book", "Books", "Facebook", "Postal code",
        "Resend", "PayPal", "Booking details", "Reserved seats", "Transferable",
        "Buying guide", "Submitted", "Einkaufswagen", "Pay with Google Pay",
        "Meine Bestellungen", "Pay with Amazon Pay",
        "Confirm email", "Confirm password", "Confirm your e-mail address", "Remove filter: Red",
        "Comments", "Bids", "Reservations",
        "Continue to payment", "Proceed to payment", "Pay with credit card", "Pay with Visa ending 4242",
        "Confirm new password", "Post code", "Remove from cart", "Use this payment method",
    ]

    def judge(self, names, selectors=False):
        script = ("const r = require(process.argv[1]); const sel = process.argv[3] === '1';"
                  "process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map("
                  "(n) => r.isCommitName(sel ? r.selectorWords(n) : n))));")
        out = subprocess.run([NODE, "-e", script, str(ROUTER), json.dumps(names), "1" if selectors else "0"],
                             capture_output=True, text=True, check=True).stdout
        return dict(zip(names, json.loads(out)))

    def test_commit_names_match(self):
        self.assertEqual([n for n, hit in self.judge(self.COMMITS).items() if not hit], [])

    def test_look_alikes_do_not_match(self):
        self.assertEqual([n for n, hit in self.judge(self.NOT_COMMITS).items() if hit], [])

    def test_selectors_are_read_as_words(self):
        self.assertEqual(self.judge(["#placeOrderBtn", "[data-test=place-order]", "#buy_now",
                                     "button[type=submit]", ".add-to-cart", "#search"], selectors=True),
                         {"#placeOrderBtn": True, "[data-test=place-order]": True, "#buy_now": True,
                          "button[type=submit]": True, ".add-to-cart": False, "#search": False})


if __name__ == "__main__":
    unittest.main()
