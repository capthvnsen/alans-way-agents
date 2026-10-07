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
const reply = (id, text) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id,
  result: { content: [{ type: 'text', text }] } }) + '\n');
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
    ] } }) + '\n');
  }
  if (m.method === 'tools/call') {
    calls += 1;
    if (mode === 'die-on-call' && calls >= 2) process.exit(1);
    if (m.params.name === 'cua_alans_way_tabs')
      return reply(m.id, JSON.stringify({ tabs: [{ id: 'mac-tab-1', url: 'https://mac.example/', host: 'mac' }] }));
    if (m.params.name === 'cua_alans_way_open')
      return reply(m.id, JSON.stringify({ id: 'mac-tab-1', url: 'https://mac.example/', host: 'mac' }));
  }
  reply(m.id, 'mac');
});
"""

# A stand-in for the VM's own connector (the same script the failover backend runs).
VM_STUB = r"""
const fs = require('fs');
fs.appendFileSync(process.env.VPS_LOG, 'ARGV ' + JSON.stringify(process.argv.slice(2)) + '\n');
const reply = (id, text) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id,
  result: { content: [{ type: 'text', text }] } }) + '\n');
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
    if (m.params.name === 'cua_alans_way_tabs')
      return reply(m.id, JSON.stringify({ tabs: [{ id: 'vm-tab-1', url: 'https://vm.example/', host: 'vps' }] }));
    if (m.params.name === 'cua_alans_way_open')
      return reply(m.id, JSON.stringify({ id: 'vm-tab-1', url: (m.params.arguments || {}).url || 'https://vm.example/', host: 'vps' }));
    if (m.params.name === 'cua_alans_way_action') return reply(m.id, 'vm-action');
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

    def start(self, mac=True, mac_mode="ok"):
        argv = [NODE, str(ROUTER), "--bot-id", "bot1",
                "--vps-script", str(self.dir / "vm-stub.cjs"),
                "--vps-connection", str(self.dir / "conn.json"),
                "--mac-state-file", str(self.state)]
        if mac:
            argv += ["--mac-ssh", "fake@host"]
        env = dict(os.environ, PATH=str(self.dir / "bin") + os.pathsep + os.environ["PATH"],
                   MAC_STUB=str(self.dir / "mac-stub.cjs"), MAC_MODE=mac_mode,
                   MAC_LOG=str(self.dir / "mac.log"), VPS_LOG=str(self.dir / "vm.log"),
                   PROBE_DOWN=str(self.dir / "probe-down"))
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

    def recv(self, timeout=15):
        if not select.select([self.proc.stdout], [], [], timeout)[0]:
            self.fail("no response within %ss" % timeout)
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
        self.assertIn('"tabId": "vm-tab-1"', self.log("vm.log"))
        self.assertNotIn('"tabId": "vm-tab-1"', self.log("mac.log"))

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
