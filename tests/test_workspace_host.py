"""Explicit host routing: the VM browser as a lazily started second backend."""
from pathlib import Path
import json
import os
import re
import select
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "alans-way" / "scripts" / "workspace-router.cjs"
NODE = shutil.which("node")
SH = shutil.which("sh")

FAKE_SSH = """#!/bin/sh
for last in "$@"; do :; done
case "$last" in
  *conn_script*) [ -f "$PROBE_DOWN" ] && exit 1; printf %s "/Users/user/Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs"; exit 0 ;;
  *) exec node "$MAC_STUB" ;;
esac
"""

# A stand-in for the connector running on the user's computer.
MAC_STUB = r"""
const fs = require('fs');
const mode = process.env.MAC_MODE || 'ok';
let calls = 0;
let epoch = 1;
const reply = (id, text, isError) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id,
  result: { ...(isError ? { isError: true } : {}), content: [{ type: 'text', text }] } }) + '\n');
require('readline').createInterface({ input: process.stdin }).on('line', (line) => {
  fs.appendFileSync(process.env.MAC_LOG, 'LINE ' + line + '\n');
  const m = JSON.parse(line);
  if (m.id === undefined) return;
  if (m.method === 'tools/list') {
    return process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result: { tools: [
      { name: 'cua_alans_way_open', inputSchema: { type: 'object', properties: {
        url: { type: 'string' },
        host: { type: 'string', enum: ['mac', 'windows', 'vps'],
                description: 'Ignored. The connector already chose the machine.' },
      }, required: ['url'] } },
      { name: 'cua_alans_way_tabs', inputSchema: { type: 'object', properties: {} } },
      { name: 'cua_alans_way_snapshot', inputSchema: { type: 'object', properties: {
        tabId: { type: 'string' }, maxChars: { type: 'integer' },
      }, required: ['tabId'] } },
      { name: 'cua_alans_way_action', inputSchema: { type: 'object', properties: {
        tabId: { type: 'string' }, epoch: { type: 'integer' }, action: { type: 'string' },
      }, required: ['tabId', 'epoch', 'action'] } },
      { name: 'workspace_computer_apps', inputSchema: { type: 'object', properties: {} } },
      { name: 'workspace_computer_snapshot', inputSchema: { type: 'object', properties: {
        pid: { type: 'integer' } } } },
      { name: 'workspace_computer_action', inputSchema: { type: 'object', properties: {
        pid: { type: 'integer' }, action: { type: 'string' } } } },
    ] } }) + '\n');
  }
  if (m.method === 'tools/call') {
    calls += 1;
    if (mode === 'die-on-call' && calls >= 2) process.exit(1);
    const a = (m.params && m.params.arguments) || {};
    if (m.params.name === 'cua_alans_way_tabs') {
      const tabs = [{ id: 'mac-tab-1', url: 'https://mac.example/', host: 'mac', epoch }];
      if (process.env.MAC_PROXY_VM) tabs.push({ id: 'vm-tab-1', url: 'https://vm.example/proxied', host: 'vps', epoch });
      return reply(m.id, JSON.stringify({ tabs }));
    }
    if (m.params.name === 'cua_alans_way_open')
      return reply(m.id, JSON.stringify({ id: 'mac-tab-1', url: 'https://mac.example/', host: 'mac', epoch }));
    if (m.params.name === 'cua_alans_way_snapshot') {
      if (!a.tabId) return reply(m.id, 'Tab not found.', true);
      return reply(m.id, JSON.stringify({ generation: 7, text: 'mac page', tab: { id: a.tabId, epoch } }));
    }
    if (m.params.name === 'cua_alans_way_action') {
      // A human takeover bumps the epoch outside the agent's calls: the error
      // reply teaches the router nothing, so the next injected epoch is stale.
      if (a.action === 'takeover') { epoch += 1; return reply(m.id, 'human_has_control: the human took the tab.', true); }
      if (!a.tabId) return reply(m.id, 'Tab not found.', true);
      if (a.epoch !== epoch) return reply(m.id, 'stale_control_epoch: read the tab state and retry after a fresh snapshot.', true);
      return reply(m.id, JSON.stringify({ ok: true, tab: { id: a.tabId, epoch } }));
    }
    if ((m.params.name || '').startsWith('workspace_computer_')) {
      return reply(m.id, 'computer-ok');
    }
  }
  reply(m.id, 'mac');
});
"""

# A stand-in for the VM's own connector (the same script the failover backend runs).
VM_STUB = r"""
const fs = require('fs');
fs.appendFileSync(process.env.VPS_LOG, 'ARGV ' + JSON.stringify(process.argv.slice(2)) + '\n');
const mode = process.env.VM_MODE || 'ok';
const reply = (id, text) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id,
  result: { content: [{ type: 'text', text }] } }) + '\n');
let opened = 0;
let prevId = null;
const closedTabs = () => (mode === 'reap' && prevId ? { closedTabs: [{ tabId: prevId, url: 'https://vm.example/reaped' }] } : {});
require('readline').createInterface({ input: process.stdin }).on('line', (line) => {
  fs.appendFileSync(process.env.VPS_LOG, 'LINE ' + line + '\n');
  const m = JSON.parse(line);
  if (m.id === undefined) return;
  if (m.method === 'tools/list') {
    return process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result: { tools: [
      { name: 'cua_alans_way_open', inputSchema: { type: 'object', properties: {
        url: { type: 'string' },
        host: { type: 'string', enum: ['mac', 'windows', 'vps'],
                description: 'Ignored. The connector already chose the machine.' },
      }, required: ['url'] } },
    ] } }) + '\n');
  }
  if (m.method === 'tools/call') {
    if (mode === 'die') process.exit(1);
    if (m.params.name === 'cua_alans_way_tabs') {
      if (mode === 'hang-tabs') return;
      const n = Number(process.env.VM_TABCOUNT || 1);
      const tabs = [];
      for (let i = 1; i <= n; i++)
        tabs.push({ id: 'vm-tab-' + i, url: 'https://vm.example/' + 'x'.repeat(80) + i, host: 'vps' });
      return reply(m.id, JSON.stringify({ tabs, ...closedTabs() }));
    }
    if (m.params.name === 'cua_alans_way_open') {
      opened += 1;
      const id = mode === 'reap' ? 'vm-tab-' + opened : 'vm-tab-1';
      const out = { id, url: (m.params.arguments || {}).url || 'https://vm.example/', host: 'vps', epoch: 1, ...closedTabs() };
      prevId = id;
      return reply(m.id, JSON.stringify(out));
    }
    if (m.params.name === 'cua_alans_way_action') {
      if (mode === 'hang') return;
      if (mode === 'slow')
        return setTimeout(() => reply(m.id, 'vm-action'), Number(process.env.VM_DELAY_MS || 2000));
      return reply(m.id, 'vm-action');
    }
  }
  reply(m.id, 'vps');
});
"""


@unittest.skipUnless(NODE and SH, "node and sh are required for host routing tests")
class ExplicitHostRoutingTests(unittest.TestCase):
    """Drive the real router over a fake ssh, a fake computer backend and a
    fake VM backend, like HostFailoverTests in test_workspace_mac.py."""

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
        self.state = self.dir / "mac-state.json"
        self.proc = None
        self.next_id = 1

    def tearDown(self):
        if self.proc:
            self.proc.kill()
            self.proc.communicate()
        self.tmp.cleanup()

    def start(self, mac=True, mac_mode="ok", vm_mode="ok", vm_tabs=1,
              mac_proxy_vm=False, **extra_env):
        argv = [NODE, str(ROUTER), "--bot-id", "bot1",
                "--vps-script", str(self.dir / "vm-stub.cjs"),
                "--vps-connection", str(self.dir / "conn.json"),
                "--mac-state-file", str(self.state)]
        if mac:
            argv += ["--mac-ssh", "fake@host"]
        env = dict(os.environ, PATH=str(self.dir / "bin") + os.pathsep + os.environ["PATH"],
                   MAC_STUB=str(self.dir / "mac-stub.cjs"), MAC_MODE=mac_mode,
                   MAC_LOG=str(self.dir / "mac.log"), VPS_LOG=str(self.dir / "vm.log"),
                   PROBE_DOWN=str(self.dir / "probe-down"),
                   VM_MODE=vm_mode, VM_TABCOUNT=str(vm_tabs),
                   MAC_PROXY_VM="1" if mac_proxy_vm else "")
        env.pop("HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS", None)
        env.update(extra_env)
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env)

    def send(self, method, **params):
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        if method != "notifications/initialized":
            msg["id"] = self.next_id
            self.next_id += 1
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        return msg.get("id")

    def recv(self, timeout=15, required=True):
        if not select.select([self.proc.stdout], [], [], timeout)[0]:
            if required:
                self.fail("no response within %ss" % timeout)
            return None
        return json.loads(self.proc.stdout.readline())

    def text(self, msg):
        return " ".join(part["text"] for part in msg["result"]["content"] if part["type"] == "text")

    def handshake(self, host="mac"):
        self.send("initialize")
        msg = self.recv()
        self.assertEqual(msg["id"], 1)
        self.assertEqual(self.text(msg).split()[0], host)
        self.send("notifications/initialized")
        return msg

    def call(self, name, arguments=None):
        params = {"name": name}
        if arguments is not None:
            params["arguments"] = arguments
        return self.send("tools/call", **params)

    def log(self, name):
        path = self.dir / name
        return path.read_text() if path.exists() else ""

    def backend_calls(self, log_name, tool):
        """The arguments a backend log captured for calls of one tool."""
        out = []
        for line in self.log(log_name).splitlines():
            if not line.startswith("LINE "):
                continue
            msg = json.loads(line[5:])
            params = msg.get("params") or {}
            if msg.get("method") == "tools/call" and params.get("name") == tool:
                out.append(params.get("arguments") or {})
        return out

    def vm_spawns(self):
        return [line[5:] for line in self.log("vm.log").splitlines() if line.startswith("ARGV ")]

    def test_host_vm_opens_on_the_vm_backend_while_the_computer_stays_up(self):
        self.start()
        self.handshake()
        opened = self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        msg = self.recv()
        self.assertEqual(msg["id"], opened)
        self.assertEqual(msg["result"]["_meta"]["workspace"]["host"], "vm")
        self.assertIn("vm-tab-1", self.text(msg))
        other = self.call("cua_alans_way_status", {})
        answered = self.recv()
        self.assertEqual((answered["id"], self.served(answered)), (other, "mac"))
        self.assertEqual(len(self.vm_spawns()), 1)
        self.assertIn('"host": "vm"', self.log("vm.log"))
        self.assertNotIn('"host": "vm"', self.log("mac.log"))

    def served(self, msg):
        return self.text(msg).split()[0]

    def test_a_known_vm_tab_id_routes_to_the_vm_backend(self):
        self.start()
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vps"})
        self.recv()
        action = self.call("cua_alans_way_action", {"tabId": "vm-tab-1", "action": "click", "ref": "r1"})
        answered = self.recv()
        self.assertEqual((answered["id"], self.served(answered)), (action, "vm-action"))
        self.assertEqual(answered["result"]["_meta"]["workspace"]["host"], "vm")
        self.assertIn('"tabId":"vm-tab-1"', self.log("vm.log"))
        self.assertNotIn('"tabId":"vm-tab-1"', self.log("mac.log"))

    def test_tabs_are_merged_from_both_backends_once_the_vm_runs(self):
        self.start()
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        self.recv()
        listing = self.call("cua_alans_way_tabs")
        merged = json.loads(self.text(self.recv()))
        self.assertEqual(
            [(t["id"], t["host"]) for t in merged["tabs"]],
            [("mac-tab-1", "computer"), ("vm-tab-1", "vm")])
        self.assertIn('"wsr-tabs-%d"' % listing, self.log("vm.log"))
        solo = self.call("cua_alans_way_tabs", {"host": "computer"})
        only = json.loads(self.text(self.recv()))
        self.assertEqual([t["id"] for t in only["tabs"]], ["mac-tab-1"])

    def test_a_large_vm_tab_list_is_merged_not_leaked(self):
        # 60 padded tabs put the VM connector's reply over the old 4000-byte
        # gate: the internal wsr-tabs answer reached the client and the real
        # request stalled until the call hard deadline failed the session over.
        self.start(vm_tabs=60)
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        self.recv()
        listing = self.call("cua_alans_way_tabs")
        first = self.recv()
        self.assertEqual(first["id"], listing)
        self.assertNotIn("wsr-tabs-", str(first["id"]))
        merged = json.loads(self.text(first))["tabs"]
        hosts = {}
        for tab in merged:
            hosts.setdefault(tab["host"], []).append(tab["id"])
        self.assertEqual(hosts.get("computer"), ["mac-tab-1"])
        self.assertEqual(len(hosts.get("vm", [])), 60)
        self.assertIsNone(self.recv(timeout=2, required=False))
        self.assertIn('"wsr-tabs-%d"' % listing, self.log("vm.log"))

    def test_tabs_merge_dedupes_vm_tabs_the_computer_app_proxies(self):
        # The app lists its proxied VM tabs in /v1/tabs marked host:"vps"; the
        # merged list must show such a tab once, under the VM backend's record.
        self.start(mac_proxy_vm=True)
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        self.recv()
        self.call("cua_alans_way_tabs")
        merged = json.loads(self.text(self.recv()))["tabs"]
        self.assertEqual(sorted(t["id"] for t in merged), ["mac-tab-1", "vm-tab-1"])
        vm_tab = next(t for t in merged if t["id"] == "vm-tab-1")
        self.assertEqual(vm_tab["host"], "vm")
        self.assertNotIn("proxied", vm_tab["url"])

    def test_a_wedged_vm_call_errors_at_the_hard_deadline(self):
        self.start(vm_mode="hang", HERMES_ROUTER_CALL_HARD_MS="1500")
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        self.recv()
        call = self.call("cua_alans_way_action", {"tabId": "vm-tab-1", "action": "click", "ref": "r1"})
        msg = self.recv(timeout=10)
        self.assertEqual(msg["id"], call)
        self.assertTrue(msg["result"]["isError"])
        self.assertIn("VM browser", self.text(msg))
        self.assertEqual(msg["result"]["_meta"]["workspace"]["host"], "vm")
        status = self.call("cua_alans_way_status", {})
        answered = self.recv()
        self.assertEqual((answered["id"], self.served(answered)), (status, "mac"))

    def test_a_merged_tabs_call_completes_when_the_vm_half_hangs(self):
        self.start(vm_mode="hang-tabs", HERMES_ROUTER_CALL_HARD_MS="1500")
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        self.recv()
        listing = self.call("cua_alans_way_tabs")
        merged = self.recv(timeout=10)
        self.assertEqual(merged["id"], listing)
        tabs = json.loads(self.text(merged))["tabs"]
        self.assertEqual([(t["id"], t["host"]) for t in tabs], [("mac-tab-1", "computer")])
        status = self.call("cua_alans_way_status", {})
        answered = self.recv()
        self.assertEqual((answered["id"], self.served(answered)), (status, "mac"))

    def test_host_computer_while_offline_is_a_clear_error(self):
        self.start(mac=False)
        self.handshake(host="vps")
        opened = self.call("cua_alans_way_open", {"url": "https://mac.example/", "host": "computer"})
        msg = self.recv()
        self.assertEqual(msg["id"], opened)
        self.assertTrue(msg["result"]["isError"])
        self.assertIn('Your computer is offline. Omit host to use the VM browser, or pass host: "vm".',
                      self.text(msg))
        self.assertNotIn("cua_alans_way_open", self.log("vm.log"))
        # host:"vm" while the session runs on the VM uses the active backend.
        again = self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        answered = self.recv()
        self.assertEqual(answered["id"], again)
        self.assertIn("vm-tab-1", self.text(answered))
        self.assertEqual(len(self.vm_spawns()), 1)

    def test_tools_list_rewrites_open_host_to_a_plain_string(self):
        self.start()
        self.handshake()
        self.send("tools/list")
        msg = self.recv()
        tool = next(t for t in msg["result"]["tools"] if t["name"] == "cua_alans_way_open")
        host = tool["inputSchema"]["properties"]["host"]
        self.assertEqual(host["type"], "string")
        self.assertNotIn("enum", host)
        self.assertNotIn("Ignored", host.get("description", ""))
        self.assertIn('"computer" or "vm"', host["description"])

    def test_no_duplicate_vm_backend_after_failover(self):
        self.start(mac_mode="die-on-call")
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        self.recv()
        self.assertEqual(len(self.vm_spawns()), 1)
        self.call("cua_alans_way_status", {})
        self.assertEqual(self.served(self.recv()), "mac")
        lost = self.call("cua_alans_way_action", {"tabId": "mac-tab-1", "action": "click", "ref": "r1"})
        failed = self.recv()
        self.assertEqual((failed["id"], failed["result"]["isError"]), (lost, True))
        self.assertIn("NOT retried", self.text(failed))
        again = self.call("cua_alans_way_open", {"url": "https://vm.example/2", "host": "vm"})
        answered = self.recv()
        self.assertEqual(answered["id"], again)
        self.assertFalse(answered["result"].get("isError"))
        # one lazy connector + one failover backend; the second spawn logs once booted
        deadline = time.time() + 10
        while len(self.vm_spawns()) < 2 and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(len(self.vm_spawns()), 2)

    def test_host_vm_after_failover_uses_the_active_backend(self):
        self.start(mac=False)
        self.handshake(host="vps")
        opened = self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        msg = self.recv()
        self.assertEqual(msg["id"], opened)
        self.assertIn("vm-tab-1", self.text(msg))
        self.assertEqual(len(self.vm_spawns()), 1)

    def test_a_vm_page_is_not_recorded_as_the_computers_resume_page(self):
        self.start()
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        self.recv()
        time.sleep(1.3)  # resume writes are debounced 1s
        resume = self.dir / "resume-url-bot1.json"
        self.assertFalse(resume.exists() and "vm.example" in resume.read_text())

    def test_action_and_snapshot_default_to_the_last_used_tab(self):
        self.start()
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://mac.example/"})
        self.recv()
        action = self.call("cua_alans_way_action", {"action": "click", "ref": "r1"})
        answered = self.recv()
        self.assertEqual(answered["id"], action)
        self.assertFalse(answered["result"].get("isError"))
        snap = self.call("cua_alans_way_snapshot", {"maxChars": 200})
        got = self.recv()
        self.assertEqual(got["id"], snap)
        self.assertFalse(got["result"].get("isError"))
        actions = self.backend_calls("mac.log", "cua_alans_way_action")
        self.assertEqual((actions[-1].get("tabId"), actions[-1].get("epoch")), ("mac-tab-1", 1))
        snaps = self.backend_calls("mac.log", "cua_alans_way_snapshot")
        self.assertEqual(snaps[-1].get("tabId"), "mac-tab-1")

    def test_supplied_tab_id_and_epoch_are_never_overwritten(self):
        self.start()
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://mac.example/"})
        self.recv()
        self.call("cua_alans_way_action", {"tabId": "other-tab", "epoch": 9, "action": "click"})
        self.recv()
        args = self.backend_calls("mac.log", "cua_alans_way_action")[-1]
        self.assertEqual((args["tabId"], args["epoch"]), ("other-tab", 9))
        # A supplied tabId with no epoch still gets that tab's known epoch.
        self.call("cua_alans_way_action", {"tabId": "mac-tab-1", "action": "click"})
        self.recv()
        args = self.backend_calls("mac.log", "cua_alans_way_action")[-1]
        self.assertEqual((args["tabId"], args["epoch"]), ("mac-tab-1", 1))

    def test_an_unrecognized_host_is_a_tool_error_not_a_silent_default(self):
        self.start()
        self.handshake()
        opened = self.call("cua_alans_way_open", {"url": "https://x.example/", "host": "remotevm"})
        msg = self.recv()
        self.assertEqual(msg["id"], opened)
        self.assertTrue(msg["result"]["isError"])
        self.assertIn('Use host "computer" or "vm", or omit it.', self.text(msg))
        self.assertNotIn("cua_alans_way_open", self.log("mac.log"))
        self.assertNotIn("cua_alans_way_open", self.log("vm.log"))
        ok = self.call("cua_alans_way_open", {"url": "https://mac.example/"})
        answered = self.recv()
        self.assertEqual(answered["id"], ok)
        self.assertIn("mac-tab-1", self.text(answered))

    def test_a_late_vm_reply_after_the_deadline_is_dropped(self):
        self.start(vm_mode="slow", VM_DELAY_MS="3000", HERMES_ROUTER_CALL_HARD_MS="1000")
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        self.recv()
        call = self.call("cua_alans_way_action", {"tabId": "vm-tab-1", "action": "click", "ref": "r1"})
        msg = self.recv(timeout=10)
        self.assertEqual(msg["id"], call)
        self.assertTrue(msg["result"]["isError"])
        self.assertIn("VM browser", self.text(msg))
        # The stub answers ~3s after the call, past the error the client got.
        time.sleep(3)
        status = self.call("cua_alans_way_status", {})
        answered = self.recv()
        self.assertEqual((answered["id"], self.served(answered)), (status, "mac"))
        self.assertIsNone(self.recv(timeout=2, required=False))

    def test_a_reaped_tab_is_pruned_from_the_routers_tab_maps(self):
        self.start(vm_mode="reap")
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/1", "host": "vm"})
        first = json.loads(self.text(self.recv()))
        self.assertEqual(first["id"], "vm-tab-1")
        self.call("cua_alans_way_action", {"action": "click", "ref": "r1"})
        self.recv()
        self.assertEqual(
            self.backend_calls("vm.log", "cua_alans_way_action")[-1].get("tabId"), "vm-tab-1")
        self.call("cua_alans_way_open", {"url": "https://vm.example/2", "host": "vm"})
        second = json.loads(self.text(self.recv()))
        self.assertEqual(second["id"], "vm-tab-2")
        self.assertEqual([t["tabId"] for t in second["closedTabs"]], ["vm-tab-1"])
        # The reaped id no longer routes calls to the VM backend.
        self.call("cua_alans_way_action", {"tabId": "vm-tab-1", "action": "click", "ref": "r2"})
        self.recv()
        self.assertEqual(
            self.backend_calls("mac.log", "cua_alans_way_action")[-1].get("tabId"), "vm-tab-1")
        # A reply that reports the current tab reaped clears it: a defaulted
        # call goes out with no tabId instead of the dead one.
        self.call("cua_alans_way_tabs")
        self.recv()
        self.call("cua_alans_way_action", {"action": "click", "ref": "r3"})
        self.recv()
        args = self.backend_calls("mac.log", "cua_alans_way_action")[-1]
        self.assertNotIn("tabId", args)

    def test_an_injected_vm_tab_routes_to_the_vm_backend(self):
        self.start()
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://vm.example/", "host": "vm"})
        self.recv()
        action = self.call("cua_alans_way_action", {"action": "click", "ref": "r1"})
        answered = self.recv()
        self.assertEqual((answered["id"], self.served(answered)), (action, "vm-action"))
        args = self.backend_calls("vm.log", "cua_alans_way_action")[-1]
        self.assertEqual((args["tabId"], args["epoch"]), ("vm-tab-1", 1))
        self.assertFalse(self.backend_calls("mac.log", "cua_alans_way_action"))

    def test_a_stale_injected_epoch_is_rejected_not_retried(self):
        self.start()
        self.handshake()
        self.call("cua_alans_way_open", {"url": "https://mac.example/"})
        self.recv()
        self.call("cua_alans_way_action", {"action": "click"})
        self.assertFalse(self.recv()["result"].get("isError"))
        # The human takes the tab between calls: the backend bumps its epoch
        # and the error reply teaches the router nothing new.
        self.call("cua_alans_way_action", {"tabId": "mac-tab-1", "epoch": 1, "action": "takeover"})
        self.assertTrue(self.recv()["result"]["isError"])
        stale = self.call("cua_alans_way_action", {"action": "click", "ref": "r2"})
        rejected = self.recv()
        self.assertEqual(rejected["id"], stale)
        self.assertTrue(rejected["result"]["isError"])
        self.assertIn("stale_control_epoch", self.text(rejected))
        # The re-read learns the fresh epoch, so the next action succeeds.
        self.call("cua_alans_way_snapshot", {})
        self.recv()
        retry = self.call("cua_alans_way_action", {"action": "click", "ref": "r2"})
        self.assertFalse(self.recv()["result"].get("isError"))
        epochs = [a.get("epoch") for a in self.backend_calls("mac.log", "cua_alans_way_action")]
        self.assertEqual(epochs, [1, 1, 1, 2])

    def test_tools_list_makes_tab_id_and_epoch_optional(self):
        self.start()
        self.handshake()
        self.send("tools/list")
        msg = self.recv()
        tools = {t["name"]: t for t in msg["result"]["tools"]}
        action = tools["cua_alans_way_action"]["inputSchema"]
        self.assertEqual(action["required"], ["action"])
        for key in ("tabId", "epoch"):
            self.assertIn("Optional: defaults to the tab you last used.",
                          action["properties"][key]["description"])
        snap = tools["cua_alans_way_snapshot"]["inputSchema"]
        self.assertNotIn("tabId", snap.get("required", []))
        self.assertIn("Optional: defaults to the tab you last used.",
                      snap["properties"]["tabId"]["description"])
        # The rest of each schema is untouched.
        self.assertNotIn("epoch", snap["properties"])
        self.assertEqual(snap["properties"]["maxChars"], {"type": "integer"})

    def test_a_call_without_a_known_tab_passes_through(self):
        self.start()
        self.handshake()
        call = self.call("cua_alans_way_action", {"action": "click", "ref": "r1"})
        msg = self.recv()
        self.assertEqual(msg["id"], call)
        self.assertTrue(msg["result"]["isError"])
        self.assertIn("Tab not found", self.text(msg))
        args = self.backend_calls("mac.log", "cua_alans_way_action")[-1]
        self.assertNotIn("tabId", args)
        self.assertNotIn("epoch", args)


class DesktopInputGateTests(ExplicitHostRoutingTests):
    """The ungated desktop-input tool is dropped from tools/list and refused
    unless the opt-in marker env is set. setup-workspace.sh writes it only
    with --allow-desktop-actions; the alans-way-computer provider sets it on
    its own private router child."""

    def tool_names(self):
        self.send("tools/list")
        return [tool["name"] for tool in self.recv()["result"]["tools"]]

    def test_the_desktop_input_tool_is_dropped_from_tools_list(self):
        self.start()
        self.handshake()
        names = self.tool_names()
        self.assertNotIn("workspace_computer_action", names)
        # Read-only computer tools stay exposed.
        self.assertIn("workspace_computer_apps", names)
        self.assertIn("workspace_computer_snapshot", names)

    def test_the_desktop_input_call_is_refused_without_the_marker(self):
        self.start()
        self.handshake()
        call = self.call("workspace_computer_action", {"pid": 5, "action": "key", "key": "a"})
        msg = self.recv()
        self.assertEqual(msg["id"], call)
        self.assertTrue(msg["result"]["isError"])
        self.assertIn("computer_use", self.text(msg))
        self.assertNotIn("workspace_computer_action", self.log("mac.log"))

    def test_the_opt_in_marker_restores_listing_and_calls(self):
        self.start(HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS="1")
        self.handshake()
        self.assertIn("workspace_computer_action", self.tool_names())
        call = self.call("workspace_computer_action", {"pid": 5, "action": "key", "key": "a"})
        answered = self.recv()
        self.assertEqual(answered["id"], call)
        self.assertFalse(answered["result"].get("isError"))
        self.assertIn("workspace_computer_action", self.log("mac.log"))


@unittest.skipUnless(NODE, "node is required for normalizeHost tests")
class NormalizeHostTests(unittest.TestCase):
    def test_the_alias_table_matches_the_shared_contract(self):
        proc = subprocess.run(
            [NODE, "-e",
             "const n = require(process.argv[1]).normalizeHost;"
             "process.stdout.write(JSON.stringify(['computer','mac','windows','linux','local','pc','MAC',"
             "'vm','vps','remote','server',' VM ','',null,'box'].map(n)));",
             str(ROUTER)],
            capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(proc.stdout),
                         ["computer"] * 7 + ["vm"] * 5 + [None, None, None])
