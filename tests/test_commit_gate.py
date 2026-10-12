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

# The user's computer on a checkout page: one commit button, two ordinary ones.
MAC_STUB = r"""
const fs = require('fs');
const mode = process.env.MAC_MODE || 'ok';
const page = { url: 'https://shop.example/checkout?step=2', elements: [
  { ref: 's1-1', role: 'button', name: 'Place order' },
  { ref: 's1-2', role: 'button', name: 'Add to cart' },
  { ref: 's1-3', role: 'link', name: 'Delete' },
] };
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
    ] } }) + '\n');
  }
  const a = (m.params && m.params.arguments) || {};
  if (m.method !== 'tools/call') return reply(m.id, 'mac');
  if (m.params.name === 'cua_alans_way_status' && mode === 'die-on-status') process.exit(1);
  if (m.params.name === 'cua_alans_way_open')
    return reply(m.id, JSON.stringify({ id: 'mac-tab-1', url: page.url, host: 'mac', epoch: 1 }));
  if (m.params.name === 'cua_alans_way_snapshot')
    return reply(m.id, JSON.stringify({ generation: 1, ...page, tab: { id: a.tabId, epoch: 1 } }));
  if (m.params.name === 'cua_alans_way_action') {
    if (mode === 'die-on-commit' && line.includes('s1-1')) process.exit(1);
    return reply(m.id, JSON.stringify({ ok: true, tab: { id: a.tabId, epoch: 1 } }));
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
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
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
        self.assertEqual((sent[0]["ref"], sent[0]["tabId"], sent[0]["epoch"]), ("s1-1", "mac-tab-1", 1))
        [entry] = self.decisions()
        self.assertEqual({k: entry[k] for k in ("bot", "origin", "kind", "summary", "amount", "decision")},
                         {"bot": "bot1", "origin": "https://shop.example", "kind": "purchase",
                          "summary": "One brass desk lamp", "amount": "40.00", "decision": "approved"})
        self.assertIn("ts", entry)

    def test_a_declined_commit_never_reaches_the_backend(self):
        self.open_checkout()
        for action in ("decline", "cancel"):
            with self.subTest(action=action):
                call = self.act(action="click", ref="s1-1", commit=PURCHASE)
                self.answer(self.recv(), action)
                self.refused(call, "declined")
        self.answer_with_unchecked_box()
        self.assertEqual(self.actions(), [])
        self.assertEqual([d["decision"] for d in self.decisions()], ["declined"] * 3)

    def answer_with_unchecked_box(self):
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
        self.answer(self.recv(), "accept", {"approve": False})
        self.refused(call, "declined")

    def test_without_elicitation_support_nothing_runs(self):
        self.open_checkout(elicitation=False)
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
        msg = self.refused(call, "approval_unavailable")
        self.assertNotIn("method", msg)
        self.assertEqual(self.actions(), [])
        self.assertEqual(self.decisions()[-1]["decision"], "approval_unavailable")

    def test_an_elicitation_error_fails_closed(self):
        self.open_checkout()
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
        ask = self.recv()
        self.write({"jsonrpc": "2.0", "id": ask["id"], "error": {"code": -32601, "message": "no"}})
        self.refused(call, "approval_unavailable")
        self.assertEqual(self.actions(), [])

    def test_a_commit_button_without_commit_is_refused(self):
        self.open_checkout()
        call = self.act(action="click", ref="s1-1")
        self.refused(call, "commit_required")
        self.assertEqual(self.actions(), [])
        ok = self.act(action="click", ref="s1-2")
        done = self.recv()
        self.assertEqual(done["id"], ok)
        self.assertFalse(done["result"].get("isError"))
        self.assertEqual([a["ref"] for a in self.actions()], ["s1-2"])
        self.assertEqual(self.decisions()[-1]["decision"], "commit_required")

    def test_a_ref_this_router_never_saw_is_refused_until_a_snapshot(self):
        self.start()
        self.handshake()
        self.send("tools/call", name="cua_alans_way_open", arguments={"url": "https://shop.example/"})
        self.recv()
        # A respawned router has no names for refs the agent still holds.
        call = self.act(action="click", ref="s1-1")
        self.refused(call, "snapshot_required")
        self.assertEqual(self.actions(), [])
        self.send("tools/call", name="cua_alans_way_snapshot", arguments={})
        self.recv()
        self.refused(self.act(action="click", ref="s1-1"), "commit_required")

    def test_a_duplicate_accept_runs_the_action_once(self):
        self.open_checkout()
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
        ask = self.recv()
        self.answer(ask, "accept", {})
        self.answer(ask, "accept", {})
        self.assertEqual(self.recv()["id"], call)
        self.assertIsNone(self.recv(timeout=1, required=False))
        self.assertEqual(len(self.actions()), 1)

    def test_a_batch_with_a_commit_step_is_refused_without_commit(self):
        self.open_checkout()
        call = self.act(action="batch", steps=[{"action": "click", "ref": "s1-2"},
                                               {"action": "press", "ref": "s1-3", "key": "Enter"}])
        self.refused(call, "commit_required")
        self.assertEqual(self.actions(), [])

    def test_a_batch_is_gated_once_before_it_runs(self):
        self.open_checkout()
        steps = [{"action": "click", "ref": "s1-2"}, {"action": "click", "ref": "s1-1"},
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
                self.refused(self.act(action="click", ref="s1-1", commit=commit), "commit_invalid")
        self.assertEqual(self.actions(), [])

    def test_an_unanswered_approval_times_out_and_a_late_tap_does_nothing(self):
        self.env = {"HERMES_ROUTER_APPROVAL_MS": "500"}
        self.open_checkout()
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
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
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
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
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
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
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
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
        call = self.act(tabId="vm-tab-1", action="click", ref="buy", commit=PURCHASE)
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
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
        self.send("notifications/cancelled", requestId=call, reason="user stopped the turn")
        self.assertEqual(self.recv()["id"], status)
        self.assertIsNone(self.recv(timeout=2, required=False))
        self.assertEqual(self.actions("vm.log"), [])

    def test_a_failover_while_awaiting_approval_never_runs_the_commit(self):
        self.env = {"MAC_MODE": "die-on-status"}
        self.open_checkout()
        call = self.act(action="click", ref="s1-1", commit=PURCHASE)
        ask = self.recv()
        status = self.send("tools/call", name="cua_alans_way_status", arguments={})
        replayed = self.recv()
        self.assertEqual(replayed["id"], status)
        self.answer(ask, "accept", {})
        self.refused(call, "host_changed")
        self.assertEqual(self.actions(), [])
        self.assertEqual(self.actions("vm.log"), [])


if __name__ == "__main__":
    unittest.main()
