"""Mac availability state: watcher file parsing, observer signatures, router notices."""
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
WATCH = ROOT / "alans-way" / "scripts" / "mac-watch.sh"
SETUP = ROOT / "setup.sh"
NODE = shutil.which("node")
SH = shutil.which("sh")


class MacStateEnvTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("HERMES_MAC_STATE_FILE")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("HERMES_MAC_STATE_FILE", None)
        else:
            os.environ["HERMES_MAC_STATE_FILE"] = self._saved


TOOL_RESULT = json.dumps({"jsonrpc": "2.0", "id": 1,
                          "result": {"content": [{"type": "text", "text": "tabs listed"}]}})

ROUTER_DRIVER = (
    "const fs = require('fs');"
    "const path = require('path');"
    "const router = require(process.argv[1]);"
    "const annotate = router.makeAnnotator(process.argv[2], process.argv[3] === '1', process.argv[4], 'Mac', { botId: process.argv[5] || '' });"
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
    def annotate(self, directory, ops, host="vps", mac_configured=True, bot=""):
        proc = subprocess.run(
            [NODE, "-e", ROUTER_DRIVER, str(ROUTER), host,
             "1" if mac_configured else "0", str(Path(directory) / "mac-state.json"), bot],
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


@unittest.skipUnless(SH and NODE, "sh and node are required for watcher tests")
class MacWatchScriptTests(MacStateEnvTest):
    def run_once(self, home, online, *args):
        bin_dir = Path(home) / "bin"
        bin_dir.mkdir(exist_ok=True)
        stub = bin_dir / "ssh"
        reply = ('printf %s "$HOME/Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs"\n'
                 if online else "")
        stub.write_text("#!/bin/sh\n%sexit %d\n" % (reply, 0 if online else 1))
        stub.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
        env["HERMES_WORKSPACE_MAC_SSH"] = "test@mac"
        env["HERMES_MAC_STATE_FILE"] = str(Path(home) / "state" / "mac-state.json")
        env.pop("HERMES_WORKSPACE_HOST_OS", None)
        return subprocess.run([SH, str(WATCH), "--once", *args],
                              env=env, capture_output=True, text=True)

    def test_once_writes_state_and_logs_transitions(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state" / "mac-state.json"
            events = Path(directory) / "state" / "mac-events.log"
            result = self.run_once(directory, True, "--hysteresis", "1")
            self.assertEqual(result.returncode, 0, result.stderr)
            first = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(first["state"], "online")
            self.assertEqual(first["since"], first["lastTransition"])
            self.assertEqual(first["lastSeenOnline"], first["since"])
            self.assertEqual(events.read_text().count("unknown -> online"), 1)
            result = self.run_once(directory, False, "--hysteresis", "1")
            self.assertEqual(result.returncode, 0, result.stderr)
            second = json.loads(state.read_text(encoding="utf-8"))
            self.assertEqual(second["state"], "offline")
            self.assertEqual(second["lastSeenOnline"], first["lastSeenOnline"])
            self.assertEqual(events.read_text().count("online -> offline"), 1)
            result = self.run_once(directory, False, "--hysteresis", "1")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(events.read_text().splitlines()), 2)

    def test_a_flip_needs_two_consecutive_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state" / "mac-state.json"
            read = lambda: json.loads(state.read_text(encoding="utf-8"))
            self.run_once(directory, online=True)
            self.assertEqual(read()["state"], "online")
            self.run_once(directory, online=False)
            self.assertEqual((read()["state"], read()["pending"], read()["pendingCount"]), ("online", "offline", 1))
            self.run_once(directory, online=True)
            self.assertNotIn("pending", read())
            self.run_once(directory, online=False)
            self.run_once(directory, online=False)
            self.assertEqual(read()["state"], "offline")
            self.assertNotIn("pending", read())
            self.run_once(directory, online=True)
            self.assertEqual(read()["state"], "offline")
            self.run_once(directory, online=True)
            self.assertEqual(read()["state"], "online")

    def test_online_means_the_app_answered_not_just_sshd(self):
        # sshd answers (exit 0) but no connector path comes back: the app is
        # down, so the host is offline.
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            (bin_dir / "ssh").write_text("#!/bin/sh\nexit 0\n")
            (bin_dir / "ssh").chmod(0o755)
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                       HERMES_WORKSPACE_MAC_SSH="test@mac",
                       HERMES_MAC_STATE_FILE=str(Path(directory) / "s" / "mac-state.json"))
            probe = subprocess.run([SH, str(WATCH), "--once"], env=env, capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(json.loads((Path(directory) / "s" / "mac-state.json").read_text())["state"], "offline")

    def test_missing_ssh_target_is_a_clear_config_error(self):
        env = {k: v for k, v in os.environ.items() if k != "HERMES_WORKSPACE_MAC_SSH"}
        result = subprocess.run([SH, str(WATCH), "--once"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("HERMES_WORKSPACE_MAC_SSH is not set", result.stderr)
        unit = (ROOT / "deploy" / "mac-watch.service").read_text(encoding="utf-8")
        self.assertIn("RestartPreventExitStatus=2", unit)

    def test_once_tolerates_a_corrupt_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            state_dir = Path(directory) / "state"
            state_dir.mkdir()
            (state_dir / "mac-state.json").write_text("garbage{{{", encoding="utf-8")
            result = self.run_once(directory, online=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((state_dir / "mac-state.json").read_text())["state"], "online")

    def test_without_node_the_wrapper_stops_with_a_clear_config_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = "/usr/bin" + os.pathsep + "/bin"
            if shutil.which("node", path=path):
                self.skipTest("node is on the minimal PATH")
            env = dict(os.environ, PATH=path, HERMES_WORKSPACE_MAC_SSH="test@mac",
                       HERMES_MAC_STATE_FILE=str(Path(directory) / "s" / "mac-state.json"))
            result = subprocess.run(["/bin/sh", str(WATCH), "--once"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("node", result.stderr)

    def test_the_loop_runs_inside_the_router_so_every_os_shares_it(self):
        self.assertNotIn("sleep", WATCH.read_text(encoding="utf-8"))
        self.assertLess(len(WATCH.read_text(encoding="utf-8").splitlines()), 20)

    def test_a_non_numeric_interval_is_a_config_error(self):
        env = dict(os.environ, HERMES_WORKSPACE_MAC_SSH="test@mac")
        result = subprocess.run([SH, str(WATCH), "--once", "--interval", "soon"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("positive integers", result.stderr)

    def test_the_loop_ticks_until_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            (bin_dir / "ssh").write_text("#!/bin/sh\necho x >> \"%s/ticks\"\nexit 1\n" % directory)
            (bin_dir / "ssh").chmod(0o755)
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                       HERMES_WORKSPACE_MAC_SSH="test@mac",
                       HERMES_MAC_STATE_FILE=str(Path(directory) / "s" / "mac-state.json"))
            proc = subprocess.Popen([SH, str(WATCH), "--interval", "1"], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 15
                ticks = Path(directory) / "ticks"
                while time.time() < deadline and (not ticks.exists() or len(ticks.read_text().split()) < 2):
                    time.sleep(0.2)
            finally:
                proc.kill()
                proc.wait()
            self.assertGreaterEqual(len(ticks.read_text().split()), 2)


@unittest.skipUnless(SH and NODE, "sh and node are required for the Windows guest simulation")
class WindowsGuestRouterTests(unittest.TestCase):
    """A native-Windows guest, simulated by presenting process.platform as win32 to the router."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.preload = self.root / "win32.cjs"
        self.preload.write_text("Object.defineProperty(process, 'platform', {value: 'win32'});\n", encoding="utf-8")
        self.system_root = self.root / "Windows"
        self.native_ssh = self.system_root / "System32" / "OpenSSH" / "ssh.exe"

    def js(self, script, **env):
        proc = subprocess.run([NODE, "-r", str(self.preload), "-e", script, str(ROUTER)],
                              capture_output=True, text=True,
                              env=dict(os.environ, HOME=str(self.root), USERPROFILE=str(self.root),
                                       SystemRoot=str(self.system_root), **env))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_no_control_master_because_win32_openssh_cannot_mux(self):
        args = json.loads(self.js("process.stdout.write(JSON.stringify(require(process.argv[1]).sshControlArgs))"))
        self.assertEqual(args, ["-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2"])

    def test_the_native_openssh_is_chosen_over_whatever_ssh_is_on_path(self):
        self.native_ssh.parent.mkdir(parents=True)
        self.native_ssh.write_text("", encoding="utf-8")
        self.assertEqual(self.js("process.stdout.write(require(process.argv[1]).sshBinary)"), str(self.native_ssh))

    def test_without_the_native_openssh_it_falls_back_to_path_ssh(self):
        self.assertEqual(self.js("process.stdout.write(require(process.argv[1]).sshBinary)"), "ssh")

    def test_other_guests_keep_plain_ssh(self):
        out = subprocess.run([NODE, "-e", "process.stdout.write(require(process.argv[1]).sshBinary)", str(ROUTER)],
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out, "ssh")

    def test_state_lives_under_the_profile_not_var_lib(self):
        out = self.js("process.stdout.write(require(process.argv[1]).macStateFile)")
        self.assertEqual(out, str(self.root / ".local" / "share" / "hermes-alans-way" / "mac-state.json"))

    def test_children_never_pop_a_console_window(self):
        source = ROUTER.read_text(encoding="utf-8")
        self.assertEqual(source.count("windowsHide: true"), 4)

    def test_the_watcher_probes_with_the_native_ssh_and_writes_state_under_the_profile(self):
        self.native_ssh.parent.mkdir(parents=True)
        log = self.root / "ssh-args"
        self.native_ssh.write_text("#!/bin/sh\necho \"$@\" >> \"%s\"\nexit 1\n" % log, encoding="utf-8")
        self.native_ssh.chmod(0o755)
        proc = subprocess.run([NODE, "-r", str(self.preload), str(ROUTER), "--watch", "--once",
                               "--mac-ssh", "me@pc.tail1.ts.net", "--host-os", "windows"],
                              capture_output=True, text=True,
                              env=dict(os.environ, HOME=str(self.root), USERPROFILE=str(self.root),
                                       SystemRoot=str(self.system_root)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state = json.loads((self.root / ".local" / "share" / "hermes-alans-way" / "mac-state.json").read_text())
        self.assertEqual(state["state"], "offline")
        args = log.read_text()
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertNotIn("ControlMaster", args)
        self.assertIn("$conn = ", args)


@unittest.skipUnless(NODE, "node is required for router tests")
class WindowsRouterTests(unittest.TestCase):
    """Windows host: PowerShell probe + backend quoting mirror the Mac path."""

    def run_js(self, script, *args):
        proc = subprocess.run([NODE, "-e", script, str(ROUTER), *args],
                              capture_output=True, text=True, check=True)
        return proc.stdout

    def test_probe_reads_connection_and_verifies_app_api(self):
        command = self.run_js(
            "process.stdout.write(require(process.argv[1]).windowsProbeCommand());")
        self.assertIn(r"$env:APPDATA\Hermes Workspace\connection.json", command)
        self.assertIn("/v1/status", command)
        # Parity with the posix wsr_alive check: the app must accept this
        # machine's connection token, so a stale connection.json (a 401)
        # means the host is not usable, not "alive".
        self.assertIn("$doc.token", command)
        self.assertIn("Bearer", command)
        self.assertIn("browser-mcp.cjs", command)

    def test_probe_rejects_a_missing_token_and_an_error_status(self):
        command = self.run_js(
            "process.stdout.write(require(process.argv[1]).windowsProbeCommand());")
        # No token in connection.json, or any HTTP error answer (a 401 from a
        # stale token included), exits 1: it must not count as "app is up".
        self.assertIn("IsNullOrWhiteSpace($token)", command)
        self.assertNotIn("$_.Exception.Response", command)

    def test_backend_prefers_the_installed_app_runtime(self):
        command = self.run_js(
            "process.stdout.write(require(process.argv[1]).windowsBackendCommand("
            "process.argv[2], 'bot-1', 'A bot'));",
            r"C:\Users\u\AppData\Roaming\Hermes Workspace\connector\scripts\browser-mcp.cjs")
        self.assertIn("alans-way-localapp.exe", command)
        self.assertIn("ELECTRON_RUN_AS_NODE", command)
        self.assertIn("NODE_PATH", command)
        self.assertIn("--bot-id 'bot-1'", command)
        self.assertIn("--bot-name 'A bot'", command)
        # Private Node and PATH Node fallbacks both appear.
        self.assertIn(r"$env:USERPROFILE\.alans-way\node\node.exe", command)
        self.assertIn("& node", command)

    def test_powershell_single_quotes_are_doubled(self):
        command = self.run_js(
            "process.stdout.write(require(process.argv[1]).windowsBackendCommand("
            "process.argv[2], 'bot-1', \"o'hara\"));",
            r"C:\s\browser-mcp.cjs")
        self.assertIn("--bot-name 'o''hara'", command)

    def test_windows_label_flows_into_notices(self):
        out = self.run_js(
            "const r = require(process.argv[1]);"
            "const notice = r.workspaceNotice('vps',"
            " {state:'offline', since:'2026-02-01T10:00:00Z'}, null, null, 'Windows host');"
            "process.stdout.write(notice);")
        self.assertIn("[workspace] Windows host unreachable since 2026-02-01T10:00:00Z", out)
        self.assertIn("do not run on the Windows host keep going", out)
        self.assertIn("Windows host-local files are unavailable", out)

    def test_mac_label_is_unchanged(self):
        out = self.run_js(
            "const r = require(process.argv[1]);"
            "const notice = r.workspaceNotice('vps',"
            " {state:'online', since:'t'}, null, null, 'Mac');"
            "process.stdout.write(notice);")
        self.assertIn("Mac is back online as of t", out)


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

    def test_a_mac_child_that_hangs_silently_falls_back_to_vps(self):
        """A wedged remote that never exits is the stall this prevents: once
        the client is talking, a silent Mac backend is routed around after the
        watchdog window instead of burning the whole MCP connect_timeout."""
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
                "  *) sleep 30 ;;\n"  # the remote backend wedges: no exit, no output
                "esac\n",
                encoding="utf-8")
            fake_ssh.chmod(0o755)
            stub = home / "vps-stub.cjs"
            stub.write_text(
                "require('readline').createInterface({input:process.stdin}).on('line',l=>{"
                "const m=JSON.parse(l);"
                "process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result:{ok:true,stub:'vps'}})+'\\n');});\n",
                encoding="utf-8")
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                       HERMES_ROUTER_MAC_WATCHDOG_MS="400")
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
                    self.fail("no response within 15s — the watchdog fallback did not fire")
                line = proc.stdout.readline()
            finally:
                proc.kill()
                _, err = proc.communicate()
            self.assertIn('"id":1', line)
            self.assertIn('"stub":"vps"', line)
            self.assertIn("silent 400ms after initialize", err)


@unittest.skipUnless(NODE, "node is required for router tests")
class RouterHelperTests(unittest.TestCase):
    def js(self, script, *args):
        proc = subprocess.run([NODE, "-e", script, str(ROUTER), *args],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_control_path_stays_under_the_unix_socket_limit_with_a_long_tmpdir(self):
        env = dict(os.environ, TMPDIR="/var/folders/zz/" + "x" * 40 + "/T/")
        proc = subprocess.run(
            [NODE, "-e", "process.stdout.write(JSON.stringify(require(process.argv[1]).sshControlArgs))", str(ROUTER)],
            capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        args = json.loads(proc.stdout)
        control = next(a for a in args if a.startswith("ControlPath="))[len("ControlPath="):]
        # %C expands to a 40-char hash; ssh appends a 17-char temp suffix.
        self.assertLess(len(control.replace("%C", "x" * 40)) + 17, 104)
        self.assertTrue(control.startswith("/tmp/wsr-"))
        self.assertIn("ControlPersist=600", args)
        self.assertIn("ServerAliveInterval=5", args)
        self.assertIn("ServerAliveCountMax=2", args)
        self.assertEqual(os.stat(os.path.dirname(control)).st_mode & 0o077, 0)

    def control_path(self, *bot):
        args = json.loads(self.js(
            "process.stdout.write(JSON.stringify(require(process.argv[1]).sshControlArgs))", *bot))
        return next(a for a in args if a.startswith("ControlPath="))[len("ControlPath="):]

    def test_each_bot_gets_its_own_control_master(self):
        a1, a2, b = (self.control_path("--bot-id", "111222333"), self.control_path("--bot-id", "111222333"),
                     self.control_path("--bot-id", "444555666"))
        self.assertEqual(a1, a2)
        self.assertNotEqual(a1, b)
        self.assertRegex(a1, r"^/tmp/wsr-\d+/[0-9a-f]{8}-%C$")
        self.assertNotIn("111222333", a1)

    def test_no_bot_id_keeps_the_shared_control_master(self):
        self.assertRegex(self.control_path(), r"^/tmp/wsr-\d+/%C$")

    def test_a_per_bot_control_path_stays_under_the_unix_socket_limit(self):
        control = self.control_path("--bot-id", "9" * 200)
        self.assertLess(len(control.replace("%C", "x" * 40)) + 17, 104)
        self.assertEqual(os.stat(os.path.dirname(control)).st_mode & 0o077, 0)

    def test_a_refused_mux_session_is_named_in_one_clear_line(self):
        out = self.js(
            "const t = require(process.argv[1]).muxTrouble;"
            "process.stdout.write(JSON.stringify([t('mux_client_request_session: session request failed: Session open refused by peer\\nControlSocket /tmp/x already exists, disabling multiplexing\\n'), t('Connection refused'), t('')]))")
        line, other, empty = json.loads(out)
        self.assertRegex(line, r"^workspace-router: ssh multiplexing .*MaxSessions")
        self.assertNotIn("\n", line)
        self.assertEqual((other, empty), (None, None))

    def test_resume_files_are_scoped_by_bot(self):
        with tempfile.TemporaryDirectory() as directory:
            page = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"content": [
                {"type": "text", "text": json.dumps({"url": "https://docs.example/d/abc"})}]}})
            self.annotator = RouterNoticeTests("annotate")
            RouterNoticeTests.annotate(self.annotator, directory, [{"line": page}], host="mac", bot="bot-a")
            self.assertTrue((Path(directory) / "resume-url-bot-a.json").exists())
            self.assertFalse((Path(directory) / "resume-url.json").exists())
            self.assertEqual([p.name for p in Path(directory).glob("*.tmp")], [])
            [line], _ = RouterNoticeTests.annotate(
                self.annotator, directory,
                [{"state": {"state": "offline", "since": "2026-02-01T10:05:00Z"}, "line": TOOL_RESULT}], bot="bot-b")
            self.assertIn("Reopen the same URL and continue.", json.loads(line)["result"]["content"][1]["text"])
            [line], _ = RouterNoticeTests.annotate(
                self.annotator, directory,
                [{"state": {"state": "offline", "since": "2026-02-01T10:05:00Z"}, "line": TOOL_RESULT}], bot="bot-a")
            self.assertIn("Reopen https://docs.example/d/abc and continue.", json.loads(line)["result"]["content"][1]["text"])

    def test_a_large_result_is_annotated_without_parsing_it(self):
        # Both key orders: {"jsonrpc","id","result"} and what the MCP SDK
        # really writes, {"result":...,"jsonrpc":"2.0","id":N}.
        out = self.js(r"""
const router = require(process.argv[1]);
const fs = require('fs'), os = require('os'), path = require('path');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wsr-'));
const state = path.join(dir, 'mac-state.json');
fs.writeFileSync(state, JSON.stringify({ state: 'offline', since: 'T0' }));
const content = [{ type: 'image', data: 'A'.repeat(3000000), mimeType: 'image/png' }];
const lines = {
  idFirst: JSON.stringify({ jsonrpc: '2.0', id: 7, result: { content } }),
  sdk: JSON.stringify({ result: { content }, jsonrpc: '2.0', id: 7 }),
  sdkStringId: JSON.stringify({ result: { content }, jsonrpc: '2.0', id: 'abc' }),
};
const realParse = JSON.parse;
const out = {};
for (const [name, line] of Object.entries(lines)) {
  const id = name === 'sdkStringId' ? 'abc' : 7;
  const pending = new Map([[id, { method: 'tools/call' }]]);
  JSON.parse = (text, ...rest) => { if (String(text).length > 100000 && text !== undefined && !/^"/.test(text)) throw new Error('parsed a screenshot'); return realParse(text, ...rest); };
  router.noteServerRpc(line, pending);
  const annotated = router.makeAnnotator('vps', true, state)(line);
  JSON.parse = realParse;
  const msg = JSON.parse(annotated);
  out[name] = { pending: pending.size, parts: msg.result.content.map((p) => p.type), meta: msg.result._meta.workspace.mac.state, id: msg.id, size: msg.result.content[0].data.length };
}
// An unrecognised big shape (isError after content) is parsed, not skipped.
const odd = JSON.stringify({ result: { content, isError: true }, jsonrpc: '2.0', id: 9 });
const pendingOdd = new Map([[9, {}]]);
router.noteServerRpc(odd, pendingOdd);
const oddMsg = JSON.parse(router.makeAnnotator('vps', true, state)(odd));
out.odd = { pending: pendingOdd.size, parts: oddMsg.result.content.map((p) => p.type), host: oddMsg.result._meta.workspace.host };
process.stdout.write(JSON.stringify(out));
""")
        data = json.loads(out)
        for name, expected_id in (("idFirst", 7), ("sdk", 7), ("sdkStringId", "abc")):
            with self.subTest(shape=name):
                self.assertEqual(data[name], {"pending": 0, "parts": ["image", "text"], "meta": "offline",
                                              "id": expected_id, "size": 3000000})
        self.assertEqual(data["odd"], {"pending": 0, "parts": ["image", "text"], "host": "vps"})

    def test_each_tool_call_reports_its_round_trip_even_for_a_screenshot(self):
        out = self.js(r"""
const router = require(process.argv[1]);
const fs = require('fs'), os = require('os'), path = require('path');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wsr-'));
const state = path.join(dir, 'mac-state.json');
fs.writeFileSync(state, JSON.stringify({ state: 'offline', since: 'T0' }));
const small = JSON.stringify({ jsonrpc: '2.0', id: 1, result: { content: [{ type: 'text', text: 'ok' }] } });
const big = JSON.stringify({ result: { content: [{ type: 'image', data: 'A'.repeat(3000000), mimeType: 'image/png' }] }, jsonrpc: '2.0', id: 2 });
const realParse = JSON.parse;
const out = {};
for (const [name, line, id, method] of [['small', small, 1, 'tools/call'], ['big', big, 2, 'tools/call'], ['list', small, 1, 'tools/list']]) {
  const pending = new Map([[id, { method, at: Date.now() - 412 }]]);
  JSON.parse = (text, ...rest) => { if (name === 'big' && String(text).length > 100000 && !/^"/.test(text)) throw new Error('parsed a screenshot'); return realParse(text, ...rest); };
  const ms = router.noteServerRpc(line, pending);
  const msg = realParse((router.makeAnnotator('vps', true, state)(line, ms)));
  JSON.parse = realParse;
  out[name] = { ms: msg.result._meta.workspace.ms, text: msg.result.content[msg.result.content.length - 1].text };
}
process.stdout.write(JSON.stringify(out));
""")
        data = json.loads(out)
        for name in ("small", "big"):
            with self.subTest(shape=name):
                self.assertGreaterEqual(data[name]["ms"], 412)
                self.assertLess(data[name]["ms"], 2000)
                self.assertIn("took %dms" % data[name]["ms"], data[name]["text"])
        self.assertNotIn("ms", data["list"])

    def test_restore_mirror_reports_what_the_host_did(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = Path(directory) / "connection.json"
            connection.write_text(json.dumps({"url": "http://127.0.0.1:9", "token": "tok"}))
            out = self.js(r"""
const router = require(process.argv[1]);
(async () => {
  const calls = [];
  const ok = (body, status = 200) => async (url, opts) => { calls.push({ url: String(url), method: opts.method, body: opts.body, headers: opts.headers }); return { ok: status < 300, status, json: async () => body }; };
  const timeout = () => { const e = new Error('timed out'); e.name = 'TimeoutError'; throw e; };
  const args = (fetchImpl) => ({ connectionFile: process.argv[2], botId: 'bot-1', botName: 'Al', timeoutMs: 50, retryMs: 50, fetchImpl });
  const restored = await router.restoreMirror(args(ok({
    map: { 'tab-1': 'vps-1', 'tab-3': 'vps-3', 'bad id': 'x', 'tab-2': '../etc' },
    verification: { 'tab-1': 'verified', 'tab-3': 'review_required' } })));
  const first = calls[0];
  const none404 = await router.restoreMirror(args(ok({}, 404)));
  const none = await router.restoreMirror(args(ok({ map: {} })));
  const down500 = await router.restoreMirror(args(ok({}, 500)));
  const downRefused = await router.restoreMirror(args(async () => { throw new TypeError('fetch failed'); }));
  const downNoFile = await router.restoreMirror({ ...args(ok({})), connectionFile: '/nonexistent' });
  let n = 0;
  const slowThenFast = await router.restoreMirror(args(async (url, opts) => {
    n += 1;
    if (n === 1) timeout();
    return { ok: true, status: 200, json: async () => ({ map: { a: 'b' } }) };
  }));
  let m = 0;
  const pending = await router.restoreMirror(args(async () => { m += 1; timeout(); }));
  process.stdout.write(JSON.stringify({ restored, none404, none, down500, downRefused, downNoFile, slowThenFast, retries: n, pending, attempts: m, first }));
})();
""", str(connection))
            data = json.loads(out)
            self.assertEqual(data["restored"], {"status": "restored", "map": {"tab-1": "vps-1", "tab-3": "vps-3"},
                                                "review": ["vps-3"]})
            for key in ("none404", "none"):
                self.assertEqual(data[key], {"status": "none"})
            for key in ("down500", "downRefused", "downNoFile"):
                self.assertEqual(data[key], {"status": "down"})
            self.assertEqual(data["slowThenFast"]["map"], {"a": "b"})
            self.assertEqual(data["retries"], 2)
            self.assertEqual(data["pending"], {"status": "pending"})
            self.assertEqual(data["attempts"], 2)
            self.assertEqual(data["first"]["url"], "http://127.0.0.1:9/v1/restore")
            self.assertEqual(data["first"]["method"], "POST")
            self.assertEqual(json.loads(data["first"]["body"]), {"bot": "bot-1"})
            self.assertEqual(data["first"]["headers"]["Authorization"], "Bearer tok")
            self.assertEqual(data["first"]["headers"]["X-Hermes-Bot"], "bot-1")

    def test_failover_notice_names_restored_tabs_without_overclaiming_logins(self):
        out = self.js(r"""
const r = require(process.argv[1]);
process.stdout.write(JSON.stringify([
  r.continuationNotice({ map: { 'h-1': 'v-1', 'h-2': 'v-2' }, review: ['v-2'] }),
  r.continuationNotice({ continued: { url: 'https://docs.example/d/abc', tabId: 'v-9' } }),
  r.continuationNotice({}, 'Windows host'),
  r.continuationNotice({ status: 'pending' }),
  r.continuationNotice({ status: 'down' }),
]));
""")
        mirrored, continued, bare, pending, down = json.loads(out)
        self.assertIn("Restored 2 tabs", mirrored)
        self.assertIn("h-1 -> v-1, h-2 -> v-2", mirrored)
        self.assertIn("Cookies were restored for tabs that had them", mirrored)
        self.assertNotIn("logins carried over", mirrored)
        self.assertIn("Look at these before acting", mirrored)
        self.assertIn("v-2", mirrored.split("Look at these")[1])
        self.assertIn("Continued https://docs.example/d/abc as VPS tab v-9", continued)
        self.assertIn("Logins did not carry over", continued)
        self.assertIn("Windows host connection lost", bare)
        self.assertIn("No tabs were mirrored", bare)
        self.assertIn("still restoring", pending)
        self.assertNotIn("No tabs were mirrored", pending)
        self.assertIn("VPS browser is not responding", down)
        self.assertNotIn("No tabs were mirrored", down)
        for text in (mirrored, continued, bare, pending, down):
            self.assertNotIn("—", text)

    def test_only_the_connection_file_error_counts_toward_failover(self):
        out = self.js(r"""
const r = require(process.argv[1]);
const err = (text) => JSON.stringify({ result: { content: [{ type: 'text', text }], isError: true }, jsonrpc: '2.0', id: 1 });
process.stdout.write(JSON.stringify([
  r.hostUnavailableLine(err('Configured browser unavailable: start its app or browser host first.')),
  r.hostUnavailableLine(err('Configured browser unavailable or timed out. Inspect existing task state before retrying an action.')),
  r.hostUnavailableLine(err('Timed out waiting for selector #x')),
  r.hostUnavailableLine(JSON.stringify({ jsonrpc: '2.0', id: 1, result: { content: [{ type: 'text', text: 'Configured browser unavailable: start its app' }] } })),
]));
""")
        self.assertEqual(json.loads(out), [True, False, False, False])


def _posix_env(home, bin_dir, **extra):
    env = {k: v for k, v in os.environ.items() if k not in ("XDG_CONFIG_HOME", "HERMES_WORKSPACE_HOST_OS")}
    env.update(HOME=str(home), PATH=str(bin_dir) + os.pathsep + env["PATH"], **extra)
    return env


@unittest.skipUnless(NODE and SH, "node and sh are required for host command tests")
class HostCommandShellTests(unittest.TestCase):
    """Run the generated probe and probe-and-exec commands under sh with a stub curl."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        curl = self.bin / "curl"
        curl.write_text("#!/bin/sh\ngrep -q 'Bearer good' || exit 22\nexit 0\n")
        curl.chmod(0o755)
        node = self.home / "fake-node"
        node.write_text("#!/bin/sh\necho \"$@\"\n")
        node.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, conn_dir, token="good"):
        conn_dir.mkdir(parents=True)
        (conn_dir / "connection.json").write_text(
            json.dumps({"url": "http://127.0.0.1:9464", "token": token, "protocol": 1}, indent=2))
        script = conn_dir / "connector" / "scripts" / "browser-mcp.cjs"
        script.parent.mkdir(parents=True)
        script.write_text("")
        return script

    def command(self, fn, host_os, *args):
        proc = subprocess.run(
            [NODE, "-e", "process.stdout.write(require(process.argv[1])." + fn + "(" + ", ".join(args) + "))",
             str(ROUTER), "--host-os", host_os, "--mac-node", str(self.home / "fake-node")],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def run_sh(self, command, **extra):
        return subprocess.run([SH, "-c", command], capture_output=True, text=True,
                              env=_posix_env(self.home, self.bin, **extra))

    def test_mac_probe_needs_the_token_to_be_accepted(self):
        conn = self.home / "Library" / "Application Support" / "Hermes Workspace"
        script = self.install(conn)
        found = self.run_sh(self.command("posixProbeCommand", "mac"))
        self.assertEqual((found.returncode, found.stdout), (0, str(script)), found.stderr)
        (conn / "connection.json").write_text(json.dumps({"url": "http://127.0.0.1:9464", "token": "stale"}))
        dead = self.run_sh(self.command("posixProbeCommand", "mac"))
        self.assertEqual((dead.returncode, dead.stdout), (1, ""))

    def test_linux_probe_follows_xdg_config_home(self):
        script = self.install(self.home / ".config" / "Hermes Workspace")
        found = self.run_sh(self.command("posixProbeCommand", "linux"))
        self.assertEqual((found.returncode, found.stdout), (0, str(script)), found.stderr)
        moved = self.install(Path(self.tmp.name) / "xdg" / "Hermes Workspace")
        found = self.run_sh(self.command("posixProbeCommand", "linux"), XDG_CONFIG_HOME=str(Path(self.tmp.name) / "xdg"))
        self.assertEqual((found.returncode, found.stdout), (0, str(moved)), found.stderr)

    def test_probe_and_exec_runs_the_backend_or_exits_97(self):
        for host_os, conn in (("mac", "Library/Application Support/Hermes Workspace"), ("linux", ".config/Hermes Workspace")):
            with self.subTest(host_os=host_os):
                conn_dir = self.home / conn
                script = self.install(conn_dir)
                ran = self.run_sh(self.command("posixAutoBackendCommand", host_os, "process.argv[5]", "'bot-1'", "''"))
                self.assertEqual(ran.returncode, 0, ran.stderr)
                self.assertIn(str(script), ran.stdout)
                self.assertIn("--bot-id bot-1", ran.stdout)
                (conn_dir / "connection.json").write_text(json.dumps({"url": "http://127.0.0.1:9464", "token": "stale"}))
                dead = self.run_sh(self.command("posixAutoBackendCommand", host_os, "process.argv[5]", "'bot-1'", "''"))
                self.assertEqual((dead.returncode, dead.stdout), (97, ""))

    def test_linux_backend_runs_electron_as_node_with_the_linux_connection_file(self):
        out = subprocess.run(
            [NODE, "-e",
             "process.stdout.write(require(process.argv[1]).linuxBackendCommand('/x/browser-mcp.cjs', '', 'bot-1', \"o'hara\"))",
             str(ROUTER)], capture_output=True, text=True, check=True).stdout
        self.assertIn("ELECTRON_RUN_AS_NODE=1", out)
        self.assertIn("'/opt/alans-way-localapp-linux-x64'/alans-way-localapp", out)
        self.assertIn("'/opt/alans-way-localapp'/alans-way-localapp", out)
        self.assertIn('"$HOME/.local/share/alans-way-localapp-linux-x64"/alans-way-localapp', out)
        self.assertIn("XDG_CONFIG_HOME:-$HOME/.config}/Hermes Workspace/connection.json", out)
        self.assertIn("--bot-name 'o'\\''hara'", out)
        self.assertEqual(subprocess.run([SH, "-n", "-c", out]).returncode, 0)


@unittest.skipUnless(NODE and SH, "node and sh are required for router process tests")
class HostOsTests(unittest.TestCase):
    def probe(self, host_os, ssh_reply):
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            ssh = bin_dir / "ssh"
            ssh.write_text("#!/bin/sh\nprintf %%s '%s'\n" % ssh_reply)
            ssh.chmod(0o755)
            proc = subprocess.run(
                [NODE, str(ROUTER), "--probe", "--mac-ssh", "u@h", "--host-os", host_os],
                capture_output=True, text=True, env=_posix_env(directory, bin_dir))
            return proc.stdout.strip()

    def test_linux_is_a_host_os(self):
        self.assertEqual(self.probe("linux", "/home/user/.config/Hermes Workspace/connector/scripts/browser-mcp.cjs"),
                         "linux: /home/user/.config/Hermes Workspace/connector/scripts/browser-mcp.cjs")
        self.assertTrue(self.probe("linux", "").startswith("vps (linux unreachable"))

    def test_an_unknown_host_os_still_means_mac(self):
        path = "/Users/user/Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs"
        self.assertEqual(self.probe("freebsd", path), "mac: " + path)


class FakeVmHost:
    """The VPS browser host's loopback API: only POST /v1/restore is served."""

    def __init__(self, mapping=None, delay=0.0, first_delay=None, verification=None):
        import http.server
        import threading
        self.requests = []
        self.mapping = mapping
        self.delay = delay
        self.first_delay = delay if first_delay is None else first_delay
        self.verification = verification or {}
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
                outer.requests.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                       "bot": self.headers.get("X-Hermes-Bot"), "body": body})
                time.sleep(outer.first_delay if len(outer.requests) == 1 else outer.delay)
                if self.path == "/v1/restore" and outer.mapping is not None:
                    payload = json.dumps({"map": outer.mapping, "verification": outer.verification}).encode()
                    self.send_response(200)
                else:
                    payload = b"{}"
                    self.send_response(404)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                outer.requests.append({"path": self.path, "method": "GET"})
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


MAC_STUB = r"""
const mode = process.env.MAC_MODE || 'ok';
let calls = 0;
const reply = (id, text, isError) => process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id,
  result: { content: [{ type: 'text', text }], ...(isError ? { isError: true } : {}) } }) + '\n');
require('readline').createInterface({ input: process.stdin }).on('line', (line) => {
  const m = JSON.parse(line);
  if (m.id === undefined) return;
  if (m.method === 'tools/call') {
    calls += 1;
    if (mode === 'hang' && calls >= 2) return;
    if (calls >= 2 && mode === 'die-on-call') process.exit(1);
    if (calls >= 2 && mode === 'unavailable') return reply(m.id, 'Configured browser unavailable: start its app or browser host first.', true);
    if (mode === 'die-on-snapshot' && m.params.name === 'cua_alans_way_snapshot') process.exit(1);
    if (mode === 'bigshot' && m.params.name === 'shot') {
      // Exactly what the MCP SDK writes: result first, jsonrpc and id last.
      return process.stdout.write(JSON.stringify({ result: { content: [{ type: 'image', data: 'A'.repeat(150000), mimeType: 'image/jpeg' }] }, jsonrpc: '2.0', id: m.id }) + '\n');
    }
  }
  if (m.method === 'tools/list' && mode === 'die-on-list') process.exit(1);
  reply(m.id, 'mac');
});
"""

VPS_STUB = r"""
const fs = require('fs');
fs.appendFileSync(process.env.VPS_LOG, 'ARGV ' + JSON.stringify(process.argv.slice(2)) + '\n');
require('readline').createInterface({ input: process.stdin }).on('line', (line) => {
  fs.appendFileSync(process.env.VPS_LOG, 'LINE ' + line + '\n');
  const m = JSON.parse(line);
  if (m.id === undefined) return;
  process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: m.id, result: { content: [{ type: 'text', text: 'vps' }] } }) + '\n');
});
"""

FAKE_SSH = """#!/bin/sh
echo call >> "$SSH_LOG"
for last in "$@"; do :; done
case "$last" in
  *"exit 97"*) [ -n "$MAC_DEAD" ] && exit 97; exec node "$MAC_STUB" ;;
  *conn_script*) [ -f "$PROBE_DOWN" ] && exit 1; printf %s "/Users/user/Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs"; exit 0 ;;
  *) exec node "$MAC_STUB" ;;
esac
"""


@unittest.skipUnless(NODE and SH, "node and sh are required for router process tests")
class HostFailoverTests(unittest.TestCase):
    """Drive the real router against a fake ssh, a fake host backend and a fake VPS backend."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "bin").mkdir()
        ssh = self.dir / "bin" / "ssh"
        ssh.write_text(FAKE_SSH)
        ssh.chmod(0o755)
        (self.dir / "mac-stub.cjs").write_text(MAC_STUB)
        (self.dir / "vps-stub.cjs").write_text(VPS_STUB)
        self.state = self.dir / "mac-state.json"
        self.vm = None
        self.proc = None
        self.next_id = 1

    def tearDown(self):
        if self.proc:
            self.proc.kill()
            self.proc.communicate()
        if self.vm:
            self.vm.close()
        self.tmp.cleanup()

    def start(self, mode="ok", vm=None, **env):
        self.vm = vm
        connection = self.dir / "conn.json"
        if vm:
            connection.write_text(json.dumps({"url": vm.url, "token": "tok"}))
        environment = dict(os.environ, PATH=str(self.dir / "bin") + os.pathsep + os.environ["PATH"],
                           MAC_STUB=str(self.dir / "mac-stub.cjs"), VPS_LOG=str(self.dir / "vps.log"),
                           SSH_LOG=str(self.dir / "ssh.log"), MAC_MODE=mode,
                           PROBE_DOWN=str(self.dir / "probe-down"),
                           HERMES_ROUTER_CALL_DEADLINE_MS="700", HERMES_ROUTER_CALL_HARD_MS="1500")
        environment.update(env)
        self.proc = subprocess.Popen(
            [NODE, str(ROUTER), "--mac-ssh", "fake@host", "--bot-id", "bot1",
             "--vps-script", str(self.dir / "vps-stub.cjs"), "--vps-connection", str(connection),
             "--mac-state-file", str(self.state)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)

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
        return " ".join(part["text"] for part in msg["result"]["content"])

    def served_by(self, msg):
        return msg["result"]["content"][0]["text"]

    def handshake(self):
        self.send("initialize")
        self.assertEqual(self.served_by(self.recv()), "mac")
        self.send("notifications/initialized")

    def call(self):
        return self.send("tools/call", name="cua_alans_way_action", arguments={"action": "click"})

    def vps_log(self):
        path = self.dir / "vps.log"
        return path.read_text() if path.exists() else ""

    def vps_spawns(self):
        return [json.loads(line[5:]) for line in self.vps_log().splitlines() if line.startswith("ARGV ")]

    def test_a_hung_call_fails_over_and_the_action_is_not_replayed(self):
        vm = FakeVmHost({"h1": "v1"})
        self.start("hang", vm)
        self.handshake()
        self.call()
        self.assertEqual(self.served_by(self.recv()), "mac")
        stuck = self.call()
        started = time.time()
        lost = self.recv()
        self.assertLess(time.time() - started, 10)
        self.assertEqual(lost["id"], stuck)
        self.assertTrue(lost["result"]["isError"])
        text = self.text(lost)
        self.assertIn("NOT retried", text)
        self.assertIn("Restored 1 tab", text)
        self.assertIn("h1 -> v1", text)
        self.assertEqual(lost["result"]["_meta"]["workspace"]["host"], "vps")
        after = self.call()
        answered = self.recv()
        self.assertEqual((answered["id"], self.served_by(answered)), (after, "vps"))
        self.assertEqual(json.dumps(vm.requests[0]["body"]), json.dumps('{"bot":"bot1"}'))
        self.assertEqual((vm.requests[0]["path"], vm.requests[0]["auth"], vm.requests[0]["bot"]),
                         ("/v1/restore", "Bearer tok", "bot1"))
        spawns = self.vps_spawns()
        self.assertEqual(spawns[-1][spawns[-1].index("--tab-map") + 1], '{"h1":"v1"}')
        log = self.vps_log()
        self.assertIsNone(re.search(r'"id": ?%d[,}]' % stuck, log))
        self.assertIsNotNone(re.search(r'"id": ?%d[,}]' % after, log))
        self.assertIn("wsr-init-", log)

    def test_the_host_process_dying_replays_reads_but_not_actions(self):
        self.start("die-on-list")
        self.handshake()
        self.call()
        self.assertEqual(self.served_by(self.recv()), "mac")
        listing = self.send("tools/list")
        answered = self.recv()
        self.assertEqual((answered["id"], self.served_by(answered)), (listing, "vps"))

    def test_an_action_in_flight_when_the_host_dies_gets_a_clear_error(self):
        self.start("die-on-call")
        self.handshake()
        self.call()
        self.assertEqual(self.served_by(self.recv()), "mac")
        lost_id = self.call()
        lost = self.recv()
        self.assertEqual(lost["id"], lost_id)
        self.assertTrue(lost["result"]["isError"])
        self.assertIn("NOT retried", self.text(lost))
        self.assertIn("VPS browser is not responding", self.text(lost))
        self.assertNotIn("No tabs were mirrored", self.text(lost))
        self.assertNotIn('"tools/call"', self.vps_log())

    def test_both_hosts_down_is_not_reported_as_an_empty_mirror(self):
        # The VPS host answers 404: it is up and has nothing to restore.
        self.start("die-on-call", FakeVmHost(None))
        self.handshake()
        self.call()
        self.assertEqual(self.served_by(self.recv()), "mac")
        self.call()
        self.assertIn("No tabs were mirrored", self.text(self.recv()))

    def test_two_unavailable_errors_in_a_row_fail_over(self):
        self.start("unavailable")
        self.handshake()
        self.call()
        self.assertEqual(self.served_by(self.recv()), "mac")
        first = self.recv_after_call()
        self.assertIn("Configured browser unavailable", self.text(first))
        self.assertNotIn("NOT retried", self.text(first))
        second = self.recv_after_call()
        self.assertIn("NOT retried", self.text(second))
        third = self.recv_after_call()
        self.assertEqual(third["result"]["content"][0]["text"], "vps")

    def recv_after_call(self):
        self.call()
        return self.recv()

    def test_a_fresh_offline_verdict_newer_than_the_backend_fails_over(self):
        self.start("ok")
        self.handshake()
        self.state.write_text(json.dumps({"state": "offline",
                                          "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
        time.sleep(2.5)
        self.call()
        self.assertEqual(self.served_by(self.recv()), "vps")

    def test_a_stale_offline_verdict_does_not_move_a_backend_that_just_answered(self):
        self.state.write_text(json.dumps({"state": "offline", "since": "2020-01-01T00:00:00Z"}))
        self.start("ok")
        self.handshake()
        time.sleep(2.5)
        self.call()
        self.assertEqual(self.served_by(self.recv()), "mac")

    def test_a_fresh_online_verdict_starts_the_backend_without_a_separate_probe(self):
        self.state.write_text(json.dumps({"state": "online", "since": "2026-02-01T10:00:00Z"}))
        self.start("ok")
        self.handshake()
        self.assertEqual(len((self.dir / "ssh.log").read_text().splitlines()), 1)

    def test_a_fresh_online_verdict_that_is_wrong_still_reaches_the_vps(self):
        self.state.write_text(json.dumps({"state": "online", "since": "2026-02-01T10:00:00Z"}))
        self.start("ok", MAC_DEAD="1")
        self.send("initialize")
        self.assertEqual(self.served_by(self.recv()), "vps")

    def test_initialize_does_not_wait_for_a_slow_restore(self):
        self.state.write_text(json.dumps({"state": "offline", "since": "2026-02-01T10:00:00Z",
                                          "lastSeenOnline": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
        (self.dir / "router-last-self-probe").write_text(str(int(time.time() * 1000)))
        vm = FakeVmHost({"h1": "v1"}, delay=2.0)
        self.start("ok", vm)
        started = time.time()
        self.send("initialize")
        self.assertEqual(self.served_by(self.recv()), "vps")
        self.assertLess(time.time() - started, 1.5)
        self.send("notifications/initialized")
        call_id = self.call()
        answered = self.recv()
        self.assertEqual(answered["id"], call_id)
        self.assertGreaterEqual(time.time() - started, 1.9)
        self.assertIn("Mac unreachable since", self.text(answered))
        self.assertIn("Restored 1 tab", self.text(answered))
        self.assertNotIn("Reopen the same URL", self.text(answered))
        spawns = self.vps_spawns()
        self.assertEqual(len(spawns), 2)
        self.assertIn("--tab-map", spawns[1])

    def test_a_fresh_session_does_not_restore_a_mirror_the_host_has_not_touched_lately(self):
        self.state.write_text(json.dumps({"state": "offline", "since": "2026-02-01T10:00:00Z",
                                          "lastSeenOnline": "2026-02-01T09:00:00Z"}))
        (self.dir / "router-last-self-probe").write_text(str(int(time.time() * 1000)))
        vm = FakeVmHost({"h1": "v1"})
        self.start("ok", vm)
        self.send("initialize")
        self.recv()
        self.send("notifications/initialized")
        self.call()
        self.assertEqual(self.served_by(self.recv()), "vps")
        self.assertEqual(vm.requests, [])

    def test_a_restore_still_running_on_the_host_is_retried_once_and_never_duplicated(self):
        vm = FakeVmHost({"h1": "v1"}, delay=0.0, first_delay=1.2)
        self.start("hang", vm, HERMES_ROUTER_RESTORE_MS="600")
        self.handshake()
        self.call()
        self.recv()
        self.call()
        lost = self.recv()
        self.assertIn("Restored 1 tab", self.text(lost))
        self.assertEqual([r["path"] for r in vm.requests], ["/v1/restore", "/v1/restore"])

    def test_a_restore_that_never_finishes_does_not_fall_back_to_a_cookieless_duplicate(self):
        vm = FakeVmHost({"h1": "v1"}, delay=3.0)
        self.start("hang", vm, HERMES_ROUTER_RESTORE_MS="400")
        self.handshake()
        self.call()
        self.recv()
        self.call()
        lost = self.recv()
        self.assertIn("still restoring", self.text(lost))
        self.assertIn("NOT retried", self.text(lost))
        time.sleep(0.5)
        self.assertEqual([r["path"] for r in vm.requests if r["path"] != "/v1/restore"], [])
        self.assertEqual(len([r for r in vm.requests if r["path"] == "/v1/restore"]), 2)

    def test_restored_tabs_needing_a_look_are_named(self):
        vm = FakeVmHost({"h1": "v1", "h2": "v2"}, verification={"h1": "verified", "h2": "review_required"})
        self.start("hang", vm)
        self.handshake()
        self.call()
        self.recv()
        self.call()
        text = self.text(self.recv())
        self.assertIn("h1 -> v1, h2 -> v2", text)
        self.assertIn("Look at these before acting", text)
        self.assertIn("v2", text.split("Look at these")[1])

    def test_reads_in_flight_when_the_host_dies_are_replayed_on_the_vps(self):
        vm = FakeVmHost({"h1": "v1"})
        self.start("die-on-snapshot", vm)
        self.handshake()
        snapshot = self.send("tools/call", name="cua_alans_way_snapshot", arguments={"tabId": "h1"})
        answered = self.recv()
        self.assertEqual((answered["id"], self.served_by(answered)), (snapshot, "vps"))
        self.assertFalse(answered["result"].get("isError"))
        self.assertIn("Restored 1 tab", self.text(answered))
        log = self.vps_log()
        self.assertEqual(len(re.findall(r'cua_alans_way_snapshot', log)), 1)
        spawns = self.vps_spawns()
        self.assertIn("--tab-map", spawns[-1])

    def test_a_slow_call_on_a_live_host_is_waited_for_until_the_hard_limit(self):
        self.start("hang", HERMES_ROUTER_CALL_DEADLINE_MS="400", HERMES_ROUTER_CALL_HARD_MS="4500",
                   HERMES_ROUTER_RECHECK_MS="500")
        self.handshake()
        self.call()
        self.assertEqual(self.served_by(self.recv()), "mac")
        stuck = self.call()
        # The probe answers (fake ssh finds the app), so no failover yet.
        self.assertFalse(select.select([self.proc.stdout], [], [], 2.5)[0])
        lost = self.recv(10)
        self.assertEqual(lost["id"], stuck)
        self.assertIn("NOT retried", self.text(lost))

    def test_a_slow_call_fails_over_at_once_when_the_liveness_probe_fails(self):
        self.start("hang", HERMES_ROUTER_CALL_DEADLINE_MS="400", HERMES_ROUTER_CALL_HARD_MS="60000")
        self.handshake()
        self.call()
        self.assertEqual(self.served_by(self.recv()), "mac")
        (self.dir / "probe-down").write_text("")
        stuck = self.call()
        started = time.time()
        lost = self.recv(10)
        self.assertEqual(lost["id"], stuck)
        self.assertLess(time.time() - started, 5)
        self.assertIn("NOT retried", self.text(lost))

    def test_a_large_sdk_ordered_screenshot_clears_its_pending_call(self):
        # The MCP SDK writes {"result":...,"jsonrpc":"2.0","id":N}. If the id
        # is not found, the call stays pending, the deadline fires and a
        # healthy session is moved to the VPS.
        self.start("bigshot", HERMES_ROUTER_CALL_DEADLINE_MS="300", HERMES_ROUTER_CALL_HARD_MS="800")
        self.handshake()
        shot = self.send("tools/call", name="shot", arguments={})
        answered = self.recv()
        self.assertEqual(answered["id"], shot)
        self.assertEqual([p["type"] for p in answered["result"]["content"]], ["image"])
        time.sleep(2.5)
        self.call()
        self.assertEqual(self.served_by(self.recv()), "mac")


class HostTimezoneCommandTests(unittest.TestCase):
    def command(self, host_os):
        return subprocess.run([NODE, str(ROUTER), "--host-timezone-command", "--host-os", host_os],
                              capture_output=True, text=True, check=True).stdout

    def test_posix_hosts_run_node_for_the_zone(self):
        for host_os in ("mac", "linux"):
            command = self.command(host_os)
            self.assertIn("ELECTRON_RUN_AS_NODE=1", command)
            self.assertNotIn("--bot-id", command)
            zone = subprocess.run([SH, "-c", command], capture_output=True, text=True,
                                  env={"PATH": str(Path(NODE).parent) + os.pathsep + "/usr/bin:/bin"}).stdout.strip()
            self.assertRegex(zone, r"^[A-Za-z_+\-]+(/[A-Za-z0-9_+\-]+)*$", host_os)

    def test_windows_runs_the_app_runtime_in_powershell(self):
        command = self.command("windows")
        self.assertIn("ELECTRON_RUN_AS_NODE", command)
        self.assertIn("-p 'Intl.DateTimeFormat().resolvedOptions().timeZone'", command)
        self.assertNotIn("--bot-id", command)


if __name__ == "__main__":
    unittest.main()
