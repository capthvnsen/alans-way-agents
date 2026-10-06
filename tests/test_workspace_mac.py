"""Mac availability state: watcher file parsing, observer signatures, router notices."""
from pathlib import Path
import importlib.util
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "alans-way" / "scripts" / "workspace-router.cjs"
WATCH = ROOT / "alans-way" / "scripts" / "mac-watch.sh"
SETUP = ROOT / "setup.sh"
NODE = shutil.which("node")
SH = shutil.which("sh")


def plugin():
    name = "companion_workspace_mac_test"
    path = ROOT / "alans-way"
    spec = importlib.util.spec_from_file_location(name, path / "__init__.py", submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MacStateEnvTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("HERMES_MAC_STATE_FILE")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("HERMES_MAC_STATE_FILE", None)
        else:
            os.environ["HERMES_MAC_STATE_FILE"] = self._saved


class MacStateReaderTests(MacStateEnvTest):
    def test_missing_malformed_and_wrong_shape_are_tolerated(self):
        module = plugin()
        observe = __import__(module.__name__ + ".proactive_observe", fromlist=["mac_state"])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mac-state.json"
            os.environ["HERMES_MAC_STATE_FILE"] = str(path)
            self.assertIsNone(observe.mac_state())
            path.write_text("not json{", encoding="utf-8")
            self.assertIsNone(observe.mac_state())
            path.write_text(json.dumps({"state": "sideways"}), encoding="utf-8")
            self.assertIsNone(observe.mac_state())
            path.write_text(json.dumps(["offline"]), encoding="utf-8")
            self.assertIsNone(observe.mac_state())
            path.write_text(" " * 5000, encoding="utf-8")
            self.assertIsNone(observe.mac_state())
            path.write_text(json.dumps({"state": "offline", "since": "2026-02-01T10:00:00Z",
                                        "lastSeenOnline": "2026-02-01T09:59:00Z", "extra": [1]}),
                            encoding="utf-8")
            self.assertEqual(observe.mac_state(), {"state": "offline",
                                                   "since": "2026-02-01T10:00:00Z",
                                                   "lastSeenOnline": "2026-02-01T09:59:00Z"})
            real = Path(directory) / "real.json"
            real.write_text(json.dumps({"state": "online"}), encoding="utf-8")
            path.unlink()
            path.symlink_to(real)
            self.assertIsNone(observe.mac_state())

    def test_offline_online_flip_records_one_context_change(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home / "mac-state.json"
            os.environ["HERMES_MAC_STATE_FILE"] = str(path)
            runtime = module.Runtime(None, home)
            runtime.store.update_policy({"session_key": "agent:main:telegram:dm:123456789"})
            self.assertIsNone(runtime.review_context()["preferences"]["workspace_mac"])
            self.assertEqual(runtime.observe(), 0)
            path.write_text(json.dumps({"state": "offline", "since": "2026-02-01T10:00:00Z"}),
                            encoding="utf-8")
            self.assertEqual(runtime.observe(), 0)
            self.assertEqual(runtime.review_context()["preferences"]["workspace_mac"]["state"], "offline")
            path.write_text(json.dumps({"state": "online", "since": "2026-02-01T10:30:00Z"}),
                            encoding="utf-8")
            self.assertEqual(runtime.observe(), 1)
            self.assertEqual(runtime.observe(), 0)
            path.write_text(json.dumps({"state": "offline", "since": "2026-02-01T11:00:00Z"}),
                            encoding="utf-8")
            self.assertEqual(runtime.observe(), 1)
            self.assertEqual(runtime.store.status()["counts"], {"pending": 2})
            restarted = module.Runtime(None, home)
            self.assertEqual(restarted.observe(), 0)
            path.write_text(json.dumps({"state": "online", "since": "2026-02-01T12:00:00Z"}),
                            encoding="utf-8")
            self.assertEqual(restarted.observe(), 1)
            runtime.close()
            restarted.close()


TOOL_RESULT = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "result": {"content": [{"type": "text", "text": "tabs listed"}]}})

ROUTER_DRIVER = (
    "const fs = require('fs');"
    "const path = require('path');"
    "const router = require(process.argv[1]);"
    "const annotate = router.makeAnnotator(process.argv[2], process.argv[3] === '1', process.argv[4]);"
    "for (const op of JSON.parse(fs.readFileSync(0, 'utf8'))) {"
    "  if ('rm' in op) fs.rmSync(process.argv[4], { force: true });"
    "  if ('raw' in op) fs.writeFileSync(process.argv[4], op.raw);"
    "  if ('state' in op) fs.writeFileSync(process.argv[4], JSON.stringify(op.state));"
    "  if ('resume' in op) fs.writeFileSync(path.join(path.dirname(process.argv[4]), 'resume-url.json'), JSON.stringify(op.resume));"
    "  if ('line' in op) {"
    "    const out = annotate(op.line);"
    "    if (out !== null) process.stdout.write(out + '\\n');"
    "  }"
    "}"
)


@unittest.skipUnless(NODE, "node is required for router tests")
class RouterNoticeTests(MacStateEnvTest):
    def annotate(self, directory, ops, host="vps", mac_configured=True):
        proc = subprocess.run(
            [NODE, "-e", ROUTER_DRIVER, str(ROUTER), host,
             "1" if mac_configured else "0", str(Path(directory) / "mac-state.json")],
            input=json.dumps(ops), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.splitlines(), proc.stderr.splitlines()

    def test_offline_result_carries_state_and_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            [line], _ = self.annotate(directory, [
                {"state": {"state": "offline", "since": "2026-02-01T10:00:00Z",
                           "lastSeenOnline": "2026-02-01T09:59:00Z"},
                 "line": TOOL_RESULT}])
            msg = json.loads(line)
            self.assertEqual(msg["id"], 1)
            self.assertEqual(msg["result"]["content"][0], {"type": "text", "text": "tabs listed"})
            self.assertEqual(msg["result"]["_meta"]["workspace"],
                             {"host": "vps",
                              "mac": {"state": "offline", "since": "2026-02-01T10:00:00Z",
                                      "lastSeenOnline": "2026-02-01T09:59:00Z"}})
            notice = msg["result"]["content"][1]["text"]
            self.assertIn("[workspace] Mac unreachable since 2026-02-01T10:00:00Z", notice)
            self.assertIn("VPS browser", notice)
            self.assertIn("Reopen the same URL and continue.", notice)
            self.assertIn("API, MCP, and connector calls that do not run on the Mac keep going.", notice)

    def test_last_mac_page_is_named_after_the_mac_drops(self):
        with tempfile.TemporaryDirectory() as directory:
            page = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [
                {"type": "text", "text": json.dumps({"url": "https://docs.example/d/abc", "title": "Notes"})},
            ]}})
            self.annotate(directory, [
                {"state": {"state": "online", "since": "2026-02-01T10:00:00Z"}, "line": page},
            ], host="mac")
            [line], _ = self.annotate(directory, [
                {"state": {"state": "offline", "since": "2026-02-01T10:05:00Z"}, "line": TOOL_RESULT},
            ])
            notice = json.loads(line)["result"]["content"][1]["text"]
            self.assertIn("Reopen https://docs.example/d/abc and continue.", notice)

    def test_a_tab_list_does_not_replace_the_page_being_worked(self):
        with tempfile.TemporaryDirectory() as directory:
            page = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [
                {"type": "text", "text": json.dumps({"url": "https://docs.example/d/abc", "title": "Notes"})},
            ]}})
            listed = json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": [
                {"type": "text", "text": json.dumps({"tabs": [
                    {"url": "https://other.example/inbox"},
                    {"url": "https://docs.example/d/abc"},
                ]})},
            ]}})
            secret = json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"content": [
                {"type": "text", "text": json.dumps({"url": "https://user:password@docs.example/private"})},
            ]}})
            self.annotate(directory, [
                {"state": {"state": "online", "since": "2026-02-01T10:00:00Z"}, "line": page},
                {"line": listed},
                {"line": secret},
            ], host="mac")
            [line], _ = self.annotate(directory, [
                {"state": {"state": "offline", "since": "2026-02-01T10:05:00Z"}, "line": TOOL_RESULT},
            ])
            notice = json.loads(line)["result"]["content"][1]["text"]
            self.assertIn("Reopen https://docs.example/d/abc and continue.", notice)
            self.assertNotIn("other.example", notice)
            self.assertNotIn("password", notice)

    def test_an_opened_page_tells_the_model_to_keep_that_tab(self):
        with tempfile.TemporaryDirectory() as directory:
            now = int(time.time() * 1000)
            [line], _ = self.annotate(directory, [
                {"resume": {"url": "https://docs.example/d/abc", "at": now, "openedAt": now + 1, "tabId": "tab-9"},
                 "state": {"state": "offline", "since": "2026-02-01T10:05:00Z"},
                 "line": TOOL_RESULT},
            ])
            notice = json.loads(line)["result"]["content"][1]["text"]
            self.assertIn("Continued https://docs.example/d/abc in the VPS browser as tab tab-9.", notice)
            self.assertIn("Keep working in that tab.", notice)
            self.assertIn("A login does not copy", notice)
            self.assertNotIn("Reopen", notice)

    def test_continue_opens_the_page_once_and_reuses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = Path(directory) / "connection.json"
            connection.write_text(json.dumps({"url": "http://127.0.0.1:9", "token": "AAFakeTokenForTests"}))
            script = r"""
const router = require(process.argv[1]);
const fs = require('fs');
(async () => {
  const calls = [];
  const fetchImpl = async (url, opts = {}) => {
    calls.push({ url: String(url), method: opts.method || 'GET', body: opts.body || '' });
    if ((opts.method || 'GET') === 'GET') {
      const tabs = calls.filter((call) => call.method === 'POST').length
        ? [{ id: 'tab-9', url: 'https://docs.example/d/abc' }] : [];
      return { ok: true, json: async () => ({ tabs }) };
    }
    return { ok: true, json: async () => ({ id: 'tab-9', url: 'https://docs.example/d/abc' }) };
  };
  const now = Date.now();
  const record = { url: 'https://docs.example/d/abc', at: now, openedAt: 0, tabId: '' };
  const first = await router.continueRememberedPage({
    connectionFile: process.argv[2], record, botId: 'bot', botName: 'Alan', fetchImpl,
  });
  router.markResumeOpened(process.argv[3], record, first.tabId, now + 1);
  const saved = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
  const second = await router.continueRememberedPage({
    connectionFile: process.argv[2],
    record: router.readResumeRecord(process.argv[3], now + 2),
    botId: 'bot', fetchImpl,
  });
  const reused = await router.continueRememberedPage({
    connectionFile: process.argv[2],
    record: { url: 'https://docs.example/d/abc', at: now, openedAt: 0, tabId: '' },
    botId: 'bot', fetchImpl,
  });
  const refused = await router.continueRememberedPage({
    connectionFile: process.argv[2],
    record: { url: 'https://user:secret@docs.example/private', at: now, openedAt: 0, tabId: '' },
    botId: 'bot', fetchImpl,
  });
  const remote = await router.continueRememberedPage({
    connectionFile: process.argv[4],
    record, botId: 'bot', fetchImpl,
  });
  const posted = calls.find((call) => call.method === 'POST');
  process.stdout.write(JSON.stringify({ first, saved, second, reused, refused, remote, posts: calls.filter((call) => call.method === 'POST').length, postBody: posted && posted.body }));
})().catch((error) => { process.stderr.write(String(error)); process.exit(1); });
"""
            remote = Path(directory) / "remote.json"
            remote.write_text(json.dumps({"url": "http://example.com", "token": "AAFakeTokenForTests"}))
            resume = Path(directory) / "resume-url.json"
            proc = subprocess.run(
                [NODE, "-e", script, str(ROUTER), str(connection), str(resume), str(remote)],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = json.loads(proc.stdout)
            self.assertEqual(out["first"], {"url": "https://docs.example/d/abc", "tabId": "tab-9", "already": False})
            self.assertEqual(out["saved"]["tabId"], "tab-9")
            self.assertGreaterEqual(out["saved"]["openedAt"], out["saved"]["at"])
            self.assertEqual(out["second"]["already"], True)
            self.assertEqual(out["reused"], {"url": "https://docs.example/d/abc", "tabId": "tab-9", "already": True})
            self.assertIsNone(out["refused"])
            self.assertIsNone(out["remote"])
            self.assertEqual(out["posts"], 1)
            self.assertIn('"settle":false', out["postBody"])

    def test_continued_tab_is_passed_to_the_vps_browser(self):
        script = r"""
const router = require(process.argv[1]);
const good = router.continuedArgs({ url: 'https://docs.example/d/abc', tabId: 'tab-9' });
const secret = router.continuedArgs({ url: 'https://user:secret@docs.example/d/abc', tabId: 'tab-9' });
const bad = router.continuedArgs({ url: 'https://docs.example/d/abc', tabId: 'tab 9' });
process.stdout.write(JSON.stringify({ good, secret, bad }));
"""
        proc = subprocess.run([NODE, "-e", script, str(ROUTER)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["good"], ["--continued-tab", "tab-9", "--continued-url", "https://docs.example/d/abc"])
        self.assertEqual(out["secret"], [])
        self.assertEqual(out["bad"], [])

    def test_back_online_notice_fires_once_per_flip(self):
        with tempfile.TemporaryDirectory() as directory:
            lines, _ = self.annotate(directory, [
                {"state": {"state": "online", "since": "2026-02-01T10:05:00Z"}, "line": TOOL_RESULT},
                {"line": TOOL_RESULT},
                {"state": {"state": "offline", "since": "2026-02-01T10:20:00Z"}, "line": TOOL_RESULT},
                {"state": {"state": "online", "since": "2026-02-01T10:40:00Z"}, "line": TOOL_RESULT},
            ])
            contents = [json.loads(line)["result"]["content"] for line in lines]
            self.assertIn("Mac is back online as of 2026-02-01T10:05:00Z", contents[0][1]["text"])
            self.assertIn("can resume", contents[0][1]["text"])
            self.assertEqual(len(contents[1]), 1)
            self.assertIn("Mac unreachable since 2026-02-01T10:20:00Z", contents[2][1]["text"])
            self.assertIn("Mac is back online as of 2026-02-01T10:40:00Z", contents[3][1]["text"])

    def test_missing_and_malformed_state_files_report_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            lines, _ = self.annotate(directory, [
                {"line": TOOL_RESULT},
                {"raw": "not json{"},
                {"line": TOOL_RESULT},
                {"raw": json.dumps({"state": "sideways"})},
                {"line": TOOL_RESULT},
            ])
            for line in lines:
                msg = json.loads(line)
                self.assertIsNone(msg["result"]["_meta"]["workspace"]["mac"])
                self.assertEqual(len(msg["result"]["content"]), 1)

    def test_non_json_stdout_is_not_forwarded_to_mcp_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            lines, err_lines = self.annotate(directory, [
                {"state": {"state": "offline", "since": "2026-02-01T10:00:00Z"}},
                {"line": "browser log noise"},
                {"line": json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}})},
                {"line": json.dumps({"jsonrpc": "2.0", "id": 2, "error": {"code": -1, "message": "x"}})},
                {"line": json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"value": 42}})},
            ])
            self.assertEqual(lines[0], json.dumps({"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}))
            self.assertEqual(json.loads(lines[1]), {"jsonrpc": "2.0", "id": 2, "error": {"code": -1, "message": "x"}})
            meta = json.loads(lines[2])["result"]["_meta"]["workspace"]
            self.assertEqual(meta["host"], "vps")
            self.assertEqual(meta["mac"]["state"], "offline")
            self.assertIn("browser log noise", err_lines)

    def test_mac_host_and_unconfigured_mac_emit_no_notice(self):
        with tempfile.TemporaryDirectory() as directory:
            [line], _ = self.annotate(directory, [
                {"state": {"state": "offline", "since": "2026-02-01T10:00:00Z"}, "line": TOOL_RESULT}],
                host="mac")
            msg = json.loads(line)
            self.assertEqual(msg["result"]["_meta"]["workspace"]["host"], "mac")
            self.assertEqual(len(msg["result"]["content"]), 1)
            [line], _ = self.annotate(directory, [
                {"state": {"state": "offline", "since": "2026-02-01T10:00:00Z"}, "line": TOOL_RESULT}],
                mac_configured=False)
            msg = json.loads(line)
            self.assertIsNone(msg["result"]["_meta"]["workspace"]["mac"])
            self.assertEqual(len(msg["result"]["content"]), 1)


@unittest.skipUnless(NODE and SH, "node and sh are required for backend command tests")
class MacBackendCommandTests(unittest.TestCase):
    """Non-interactive ssh never loads Homebrew's PATH, so a bare `node` misses."""

    def run_remote(self, home, node="", with_bundle=True):
        bundle = Path(home) / "Apps" / "Open Alan.app"
        script = bundle / "Contents" / "Resources" / "app" / "scripts" / "browser-mcp.cjs"
        script.parent.mkdir(parents=True)
        script.write_text("")
        if with_bundle:
            exe = bundle / "Contents" / "MacOS" / "Open Alan"
            exe.parent.mkdir(parents=True)
            exe.write_text('#!/bin/sh\necho "app-binary run-as-node=$ELECTRON_RUN_AS_NODE $*"\n')
            exe.chmod(0o755)
        bin_dir = Path(home) / "bin"
        bin_dir.mkdir()
        fake_node = bin_dir / "node"
        fake_node.write_text('#!/bin/sh\necho "path-node $*"\n')
        fake_node.chmod(0o755)
        command = subprocess.run(
            [NODE, "-e", "process.stdout.write(require(process.argv[1]).macBackendCommand("
                         "process.argv[2], process.argv[3], 'bot-1', \"Alan's bot\"))",
             str(ROUTER), str(script), node],
            capture_output=True, text=True, check=True).stdout
        env = {"PATH": str(bin_dir) + os.pathsep + "/usr/bin:/bin"}
        return subprocess.run([SH, "-c", command], env=env, capture_output=True, text=True), script

    def test_default_runs_the_app_bundle_binary_as_node(self):
        with tempfile.TemporaryDirectory() as home:
            result, script = self.run_remote(home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(),
                             f"app-binary run-as-node=1 {script} --bot-id bot-1 --bot-name Alan's bot")

    def test_falls_back_to_path_node_without_a_bundle_binary(self):
        with tempfile.TemporaryDirectory() as home:
            result, script = self.run_remote(home, with_bundle=False)
            self.assertEqual(result.stdout.strip(), f"path-node {script} --bot-id bot-1 --bot-name Alan's bot")

    def test_an_explicit_mac_node_wins(self):
        with tempfile.TemporaryDirectory() as home:
            result, script = self.run_remote(home, node="node")
            self.assertEqual(result.stdout.strip(), f"path-node {script} --bot-id bot-1 --bot-name Alan's bot")

    def test_home_connector_runs_with_the_installed_app_node(self):
        script = "/Users/user/Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs"
        command = subprocess.run(
            [NODE, "-e", "process.stdout.write(require(process.argv[1]).macBackendCommand("
                         "process.argv[2], '', 'bot-1', ''))",
             str(ROUTER), script],
            capture_output=True, text=True, check=True).stdout
        self.assertIn("NODE_PATH=", command)
        self.assertIn("ELECTRON_RUN_AS_NODE=1", command)
        self.assertIn("alans-way-localapp.app", command)
        self.assertIn(script, command)

    def test_home_connector_command_parses(self):
        # The app checks chain `if ...; fi` blocks — a missing separator once
        # produced "fi if", which zsh rejects and which killed every Mac spawn.
        # `sh -n` syntax-checks without executing, so the result does not
        # depend on which /Applications bundles exist on the test host.
        script = "/Users/user/Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs"
        command = subprocess.run(
            [NODE, "-e", "process.stdout.write(require(process.argv[1]).macBackendCommand("
                         "process.argv[2], '', 'bot-1', ''))",
             str(ROUTER), script],
            capture_output=True, text=True, check=True).stdout
        result = subprocess.run([SH, "-n", "-c", command],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_mac_node_path_with_spaces_is_quoted(self):
        with tempfile.TemporaryDirectory() as home:
            bundle = Path(home) / "Apps" / "Open Alan.app"
            script = bundle / "Contents" / "Resources" / "app" / "scripts" / "browser-mcp.cjs"
            script.parent.mkdir(parents=True)
            script.write_text("")
            node = "/Applications/My Tools/node"
            command = subprocess.run(
                [NODE, "-e", "process.stdout.write(require(process.argv[1]).macBackendCommand("
                             "process.argv[2], process.argv[3], 'bot-1', ''))",
                 str(ROUTER), str(script), node],
                capture_output=True, text=True, check=True).stdout
            self.assertIn("'{}'".format(node.replace("'", "'\\''")), command)


@unittest.skipUnless(NODE, "node is required for router rpc tests")
class RouterRpcTrackingTests(unittest.TestCase):
    def run_helper(self, script):
        proc = subprocess.run([NODE, "-e", script, str(ROUTER)],
                              capture_output=True, text=True, check=True)
        return json.loads(proc.stdout)

    def test_pending_requests_block_reconvergence(self):
        data = self.run_helper(
            "const r = require(process.argv[1]);"
            "const pending = new Set();"
            "r.noteClientRpc(JSON.stringify({jsonrpc:'2.0',id:9,method:'tools/call',params:{}}), pending);"
            "const mac = {state:'online'};"
            "const idle = r.RECONVERGE_IDLE_MS + 1;"
            "const inFlight = r.mayReconverge({mac, onlineStreak:2, lastActivity:Date.now()-idle,"
            " pendingSize:pending.size, idleMs:r.RECONVERGE_IDLE_MS, now:Date.now()});"
            "r.noteServerRpc(JSON.stringify({jsonrpc:'2.0',id:9,result:{}}), pending);"
            "const idleReady = r.mayReconverge({mac, onlineStreak:2, lastActivity:Date.now()-idle,"
            " pendingSize:pending.size, idleMs:r.RECONVERGE_IDLE_MS, now:Date.now()});"
            "process.stdout.write(JSON.stringify({inFlight, idleReady, pending:pending.size}));"
        )
        self.assertFalse(data["inFlight"])
        self.assertTrue(data["idleReady"])
        self.assertEqual(data["pending"], 0)

    def test_client_and_server_lines_refresh_activity_tracking(self):
        data = self.run_helper(
            "const r = require(process.argv[1]);"
            "const pending = new Set();"
            "const req = JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/call',params:{}});"
            "r.noteClientRpc(req, pending);"
            "process.stdout.write(JSON.stringify({client:pending.size}));"
        )
        self.assertEqual(data["client"], 1)


@unittest.skipUnless(NODE, "node is required for router freshness tests")
class RouterFreshnessTests(unittest.TestCase):
    def test_stale_mac_state_does_not_count_for_reconvergence(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "mac-state.json"
            state.write_text(json.dumps({"state": "online", "since": "2026-02-01T10:00:00Z"}),
                             encoding="utf-8")
            old = time.time() - 120
            os.utime(state, (old, old))
            proc = subprocess.run(
                [NODE, "-e",
                 "const fs=require('fs');"
                 "const r=require(process.argv[1]);"
                 "const mac=r.freshMacState(process.argv[2]);"
                 "process.stdout.write(JSON.stringify(mac));",
                 str(ROUTER), str(state)],
                capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(proc.stdout), None)


@unittest.skipUnless(NODE, "node is required for router self-probe tests")
class RouterSelfProbeTests(unittest.TestCase):
    def test_router_self_probes_despite_fresh_offline_after_interval(self):
        source = ROUTER.read_text(encoding="utf-8")
        self.assertIn("SELF_PROBE_INTERVAL_MS", source)
        self.assertIn("staleSelfProbe", source)
        self.assertIn("self-probe despite fresh offline", source)


@unittest.skipUnless(NODE, "node is required for probe stderr tests")
class RouterProbeStderrTests(unittest.TestCase):
    def test_stderr_tail_surfaces_ssh_failure_detail(self):
        proc = subprocess.run(
            [NODE, "-e",
             "const r=require(process.argv[1]);"
             "process.stdout.write(r.stderrTail('Warning: Permanently added host.\\n"
             "Permission denied (publickey).\\n'));",
             str(ROUTER)],
            capture_output=True, text=True, check=True)
        self.assertIn("Permission denied", proc.stdout)


@unittest.skipUnless(SH, "sh is required for setup unit tests")
class MacWatchUnitGenerationTests(unittest.TestCase):
    def test_setup_generates_mac_watch_user_from_hermes_home_owner(self):
        source = SETUP.read_text(encoding="utf-8")
        self.assertNotIn("User=root", source.split("mac-watch.service")[1].split("EOF")[0])
        self.assertIn("MAC_WATCH_USER=", source)
        self.assertIn("User=$MAC_WATCH_USER", source)

    def test_deploy_template_does_not_hardcode_root(self):
        unit = (ROOT / "deploy" / "mac-watch.service").read_text(encoding="utf-8")
        self.assertIsNotNone(re.search(r"^User=", unit, re.MULTILINE))
        self.assertNotIn("User=root", unit)


@unittest.skipUnless(SH, "sh is required for watcher tests")
class MacWatchScriptTests(MacStateEnvTest):
    def run_once(self, home, online, *args):
        bin_dir = Path(home) / "bin"
        bin_dir.mkdir(exist_ok=True)
        stub = bin_dir / "ssh"
        stub.write_text("#!/bin/sh\nexit %d\n" % (0 if online else 1))
        stub.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
        env["HERMES_WORKSPACE_MAC_SSH"] = "test@mac"
        env["HERMES_MAC_STATE_FILE"] = str(Path(home) / "state" / "mac-state.json")
        return subprocess.run([SH, str(WATCH), "--once", *args],
                              env=env, capture_output=True, text=True)

    def test_once_writes_state_and_logs_transitions(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state" / "mac-state.json"
            events = Path(directory) / "state" / "mac-events.log"
            result = self.run_once(directory, online=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            first = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(first["state"], "online")
            self.assertEqual(first["since"], first["lastTransition"])
            self.assertEqual(first["lastSeenOnline"], first["since"])
            self.assertEqual(events.read_text().count("unknown -> online"), 1)
            result = self.run_once(directory, online=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            second = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(second["state"], "offline")
            self.assertEqual(second["lastSeenOnline"], first["lastSeenOnline"])
            self.assertEqual(events.read_text().count("online -> offline"), 1)
            result = self.run_once(directory, online=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(events.read_text().splitlines()), 2)

    def test_once_tolerates_a_corrupt_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            (state_dir / "mac-state.json").write_text("garbage{{{", encoding="utf-8")
            result = self.run_once(directory, online=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((state_dir / "mac-state.json").read_text())["state"], "online")


class DeadBackendFallbackTests(unittest.TestCase):
    def test_a_mac_child_that_dies_before_answering_falls_back_to_vps(self):
        """A dead-on-arrival Mac spawn must not strand the MCP client until its
        connect timeout: the router replays buffered requests onto the VPS
        backend and keeps serving."""
        if not NODE:
            self.skipTest("node required")
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            bin_dir = home / "bin"
            bin_dir.mkdir()
            fake_ssh = bin_dir / "ssh"
            fake_ssh.write_text(
                "#!/bin/sh\n"
                "for last in \"$@\"; do :; done\n"
                "case \"$last\" in\n"
                "  *conn_script*) printf %s \"/Users/user/Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs\"; exit 0 ;;\n"
                "  *) exit 1 ;;\n"  # the remote backend dies instantly
                "esac\n",
                encoding="utf-8")
            fake_ssh.chmod(0o755)
            stub = home / "vps-stub.cjs"
            stub.write_text(
                "require('readline').createInterface({input:process.stdin}).on('line',l=>{"
                "const m=JSON.parse(l);"
                "process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result:{ok:true,stub:'vps'}})+'\\n');});\n",
                encoding="utf-8")
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            proc = subprocess.Popen(
                [NODE, str(ROUTER), "--mac-ssh", "fake@host", "--bot-id", "1",
                 "--vps-script", str(stub),
                 "--vps-connection", str(home / "conn.json"),
                 "--mac-state-file", str(home / "mac-state.json")],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, env=env)
            try:
                proc.stdin.write('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n')
                proc.stdin.flush()
                if not select.select([proc.stdout], [], [], 15)[0]:
                    self.fail("no response within 15s — the fallback did not replay the request")
                line = proc.stdout.readline()
            finally:
                proc.kill()
                _, err = proc.communicate()
            self.assertIn('"id":1', line, err)
            self.assertIn('"stub":"vps"', line)
            self.assertIn("died before its first response", err)


if __name__ == "__main__":
    unittest.main()
