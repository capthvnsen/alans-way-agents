"""Remote client setup only touches the temporary HOME's SSH files."""
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/setup-remote-agent.sh"


@unittest.skipUnless(shutil.which("ssh-keygen") and shutil.which("sh"), "needs OpenSSH and sh")
class RemoteAgentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.env = dict(os.environ, HOME=str(self.home), HERMES_HOME=str(self.home / ".hermes"))
        self.authorized = self.home / ".ssh/authorized_keys"
        self.authorized.parent.mkdir()
        self.original = "# existing keys\nssh-ed25519 AAAA unrelated\n"
        self.authorized.write_text(self.original)
        self.router = self.home / ".hermes/plugins/alans-way/scripts/workspace-router.cjs"
        self.router.parent.mkdir(parents=True)
        self.router.touch()
        self.config = self.home / ".hermes/config.yaml"
        self.config.parent.mkdir(exist_ok=True)
        self.config_text = '''mcp_servers:
  other:
    env:
      HERMES_WORKSPACE_MAC_SSH: wrong@host
  workspace_browser:
    command: node
    env:
      HERMES_WORKSPACE_MAC_SSH: "user@mac.local"
      HERMES_WORKSPACE_HOST_OS: 'mac' # retained
      HERMES_MAC_STATE_FILE: "/var/lib/workspace/mac state.json"
  later:
    env:
      HERMES_WORKSPACE_MAC_SSH: also-wrong@host
'''
        self.config.write_text(self.config_text)

    def run_setup(self, *args, check=True):
        result = subprocess.run(["sh", str(SCRIPT), *args], env=self.env, text=True,
                                capture_output=True, timeout=15)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(self.config.read_text(), self.config_text)
        return result

    def command(self):
        line = self.authorized.read_text().splitlines()[-1]
        match = re.match(r'restrict,command="((?:[^"\\]|\\.)*)" ssh-ed25519 ', line)
        self.assertIsNotNone(match, line)
        return re.sub(r"\\(.)", r"\1", match[1])

    def test_install_copies_config_and_prints_stdio_client(self):
        result = self.run_setup("--bot-id", "remote.1", "--bot-name", "Remote Agent", "--user", "user",
                                "--mac-ssh", "ignored@host", "--host-os", "linux")
        client, _ = json.JSONDecoder().raw_decode(result.stdout)
        key = self.home / ".ssh/alans-way-remote-agent-remote.1"
        self.assertEqual(client, {"command": "ssh", "args": ["-T", "-i", str(key), "-o",
                         "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30", "user@HOST"]})
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.authorized.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.authorized.stat().st_mode & 0o777, 0o600)
        self.assertEqual(next(self.home.glob(".ssh/authorized_keys.bak-*")).read_text(), self.original)
        self.assertTrue(self.authorized.read_text().startswith(self.original))
        tokens = shlex.split(self.command())
        self.assertEqual(tokens[:4], ["HERMES_WORKSPACE_MAC_SSH=user@mac.local", "HERMES_WORKSPACE_HOST_OS=mac",
                         "HERMES_MAC_STATE_FILE=/var/lib/workspace/mac state.json", "HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS=1"])
        self.assertEqual(tokens[4:], ["exec", "node", str(self.router),
                         "--bot-id", "remote.1", "--bot-name", "Remote Agent"])
        self.assertIn("initialize + tools/list", result.stdout)

    def test_default_router_without_hermes_home_uses_home_plugin(self):
        env = dict(self.env)
        env.pop("HERMES_HOME")
        result = subprocess.run(["sh", str(SCRIPT), "--bot-id", "one", "--print"],
                                env=env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(shlex.quote(str(self.router)), result.stdout)
        self.assertEqual(list(self.authorized.parent.iterdir()), [self.authorized])

    def test_rerun_replaces_only_that_bot_and_keeps_its_key(self):
        self.run_setup("--bot-id", "one")
        key = self.home / ".ssh/alans-way-remote-agent-one"
        private = key.read_bytes()
        self.run_setup("--bot-id", "two")
        self.run_setup("--bot-id", "one", "--bot-name", "Updated")
        text = self.authorized.read_text()
        self.assertEqual(text.count("alans-way-remote-agent:one"), 1)
        self.assertEqual(text.count("alans-way-remote-agent:two"), 1)
        self.assertIn("--bot-name Updated", text)
        self.assertEqual(key.read_bytes(), private)
        before = self.authorized.read_bytes()
        self.run_setup("--bot-id", "one", "--bot-name", "Updated")
        self.assertEqual(self.authorized.read_bytes(), before)

    def test_remove_preserves_other_bots_and_key_and_backs_up(self):
        self.run_setup("--bot-id", "one")
        self.run_setup("--bot-id", "two")
        before = self.authorized.read_text()
        self.run_setup("--bot-id", "one", "--remove")
        self.assertNotIn("alans-way-remote-agent:one", self.authorized.read_text())
        self.assertIn("alans-way-remote-agent:two", self.authorized.read_text())
        self.assertTrue(self.authorized.read_text().startswith(self.original))
        self.assertIn(before, [p.read_text() for p in self.home.glob(".ssh/authorized_keys.bak-*")])
        self.assertTrue((self.home / ".ssh/alans-way-remote-agent-one").exists())
        self.run_setup("--bot-id", "one", "--remove")

    def test_concurrent_installs_preserve_all_twelve_bots(self):
        # Widen the stale-read window so an unlocked read/replace reliably loses entries.
        (self.home / "sitecustomize.py").write_text('''from pathlib import Path
import time
read_bytes = Path.read_bytes
def slow_read(path):
    data = read_bytes(path)
    if path.name == "authorized_keys":
        time.sleep(0.2)
    return data
Path.read_bytes = slow_read
''')
        env = dict(self.env, PYTHONPATH=str(self.home))
        processes = []
        try:
            for i in range(12):
                processes.append(subprocess.Popen(["sh", str(SCRIPT), "--bot-id", f"b{i}"],
                                 env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True))
            for proc in processes:
                stdout, stderr = proc.communicate(timeout=15)
                self.assertEqual(proc.returncode, 0, stderr + stdout)
        finally:
            for proc in processes:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.communicate()
        rows = self.authorized.read_text().splitlines()
        self.assertEqual({row.split()[-1] for row in rows[2:]},
                         {f"alans-way-remote-agent:b{i}" for i in range(12)})
        self.assertTrue(self.authorized.read_text().startswith(self.original))
        self.assertEqual(self.config.read_text(), self.config_text)

    def test_preview_and_remove_preview_do_not_write(self):
        self.run_setup("--bot-id", "one", "--print")
        self.run_setup("--bot-id", "one", "--remove", "--print")
        self.assertEqual(list(self.authorized.parent.iterdir()), [self.authorized])
        self.assertEqual(self.authorized.read_text(), self.original)

    def test_bad_ids_names_and_users_are_rejected_without_writes(self):
        modes = ("-agent", "--watch", "--probe", "--host-timezone-command")
        for bot_id in ("", "a" * 65, "a/b", "bad id", "a\nb", 'a"b', "$(id)", *modes):
            with self.subTest(bot_id=bot_id):
                self.assertEqual(self.run_setup("--bot-id=" + bot_id, check=False).returncode, 2)
        for name in ('bad"name', "bad'name", "bad\nname", "bad\rname", *modes):
            with self.subTest(name=name):
                self.assertEqual(self.run_setup("--bot-id", "one", "--bot-name=" + name, check=False).returncode, 2)
        self.assertEqual(self.run_setup("--bot-id", "one", "--user=-root", check=False).returncode, 2)
        self.assertEqual(list(self.authorized.parent.iterdir()), [self.authorized])

    def test_fallback_flags_and_shell_metacharacters_are_quoted(self):
        self.config_text = "mcp_servers:\n  other: {}\n"
        self.config.write_text(self.config_text)
        state = str(self.home / 'state "quoted"; $(touch nope).json')
        self.run_setup("--bot-id", "one", "--bot-name", "Agent; $(touch nope)",
                       "--mac-ssh", "user@mac.local", "--host-os", "linux", "--state-file", state)
        tokens = shlex.split(self.command())
        self.assertIn("HERMES_MAC_STATE_FILE=" + state, tokens)
        self.assertIn("HERMES_WORKSPACE_HOST_OS=linux", tokens)
        self.assertEqual(tokens[-1], "Agent; $(touch nope)")

    def test_remove_does_not_need_config_router_or_key(self):
        self.authorized.write_text(self.original + 'ssh-ed25519 BBBB alans-way-remote-agent:one\n')
        self.run_setup("--bot-id", "one", "--remove", "--router", "/missing/router", "--config", "/missing/config")
        self.assertEqual(self.authorized.read_text(), self.original)

    def test_install_creates_ssh_files_and_remove_preserves_unrelated_bytes(self):
        self.authorized.unlink()
        self.authorized.parent.rmdir()
        self.run_setup("--bot-id", "one")
        self.assertEqual(self.authorized.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(list(self.home.glob(".ssh/authorized_keys.bak-*")), [])
        original = b"# key owner \xff\r\nssh-ed25519 AAAA unrelated\r\n"
        self.authorized.write_bytes(original + self.authorized.read_bytes())
        self.run_setup("--bot-id", "one", "--remove")
        self.assertEqual(self.authorized.read_bytes(), original)

    def test_unsupported_yaml_and_multiline_env_fail_before_writing(self):
        for env in ('{HERMES_WORKSPACE_MAC_SSH: "user@mac.local"}', '*shared'):
            with self.subTest(env=env):
                self.config_text = "mcp_servers:\n  workspace_browser:\n    env: " + env + "\n"
                self.config.write_text(self.config_text)
                self.assertEqual(self.run_setup("--bot-id", "one", check=False).returncode, 2)
        self.config_text = 'mcp_servers:\n  workspace_browser:\n    env:\n      HERMES_MAC_STATE_FILE: "bad\\npath"\n'
        self.config.write_text(self.config_text)
        self.assertEqual(self.run_setup("--bot-id", "one", check=False).returncode, 2)
        self.assertEqual(list(self.authorized.parent.iterdir()), [self.authorized])

    @unittest.skipUnless(shutil.which("node"), "needs node")
    def test_probe_uses_the_forced_command_and_lists_tools(self):
        router = self.home / "fake router.cjs"
        router.write_text('''const readline = require('node:readline');
readline.createInterface({input: process.stdin}).on('line', line => {
  const msg = JSON.parse(line);
  if (!msg.id) return;
  const expected = process.env.HERMES_WORKSPACE_MAC_SSH === 'user@mac.local'
    && process.env.HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS === '1'
    && process.argv.includes('one');
  const result = msg.method === 'initialize' ? {protocolVersion: '2024-11-05'}
    : {tools: [{name: expected ? 'checked_tool' : 'wrong_env'}]};
  console.log(JSON.stringify({jsonrpc: '2.0', id: msg.id, result}));
});
''')
        result = self.run_setup("--bot-id", "one", "--router", str(router), "--print", "--probe")
        self.assertIn("Tools: checked_tool", result.stdout)
        self.assertEqual(list(self.authorized.parent.iterdir()), [self.authorized])
