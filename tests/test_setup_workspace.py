"""setup-workspace.sh CLI: profile selection, safe YAML quoting, and config editing."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "setup-workspace.sh"
SH = shutil.which("sh")


def run(*args, env=None, check=True):
    cmd = [SH or "/bin/sh", str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise AssertionError(f"exit {result.returncode}: {result.stderr}\n{result.stdout}")
    return result


class PrintModeTests(unittest.TestCase):
    def test_prints_quoted_block_for_manual_paste(self):
        result = run("--bot-id", "bot_123", "--bot-name", 'Scout "The Bot"',
                     "--mac-ssh", "user@mac.local",
                     "--router", "/opt/alans way/router.cjs")
        out = result.stdout
        self.assertIn("workspace_browser:", out)
        # JSON-style double quotes contain spaces and embedded quotes safely.
        self.assertIn('- "/opt/alans way/router.cjs"', out)
        self.assertIn('- "bot_123"', out)
        self.assertIn('- "Scout \\"The Bot\\""', out)
        self.assertIn('HERMES_WORKSPACE_MAC_SSH: "user@mac.local"', out)

    def test_tool_timeout_outlasts_the_connector_action_budget(self):
        out = run("--bot-id", "bot_123").stdout
        # browser-mcp allows 90s for an action; Hermes must not cut it off first.
        self.assertIn("    timeout: 120\n", out)
        self.assertIn("    lazy: true\n", out)

    def test_omits_bot_name_args_when_not_given(self):
        result = run("--bot-id", "bot_123")
        self.assertNotIn("--bot-name", result.stdout)

    def test_the_block_carries_the_watcher_state_file_when_setup_chose_one(self):
        env = dict(os.environ)
        out = run("--bot-id", "bot_123", env=env).stdout
        self.assertNotIn("HERMES_MAC_STATE_FILE", out)
        env["ALANS_WAY_MAC_STATE_FILE"] = "/home/user/.local/share/hermes-alans-way/mac-state.json"
        out = run("--bot-id", "bot_123", env=env).stdout
        self.assertIn('HERMES_MAC_STATE_FILE: "/home/user/.local/share/hermes-alans-way/mac-state.json"', out)


class DesktopInputGateTests(unittest.TestCase):
    """The managed block excludes the ungated workspace_computer_action tool:
    desktop input must go through Hermes's approval-gated computer_use. Only
    the explicit --allow-desktop-actions opt-in writes the router's marker env."""

    def test_the_block_excludes_the_ungated_desktop_input_tool(self):
        out = run("--bot-id", "bot_123").stdout
        self.assertIn("    tools:\n      exclude:\n        - workspace_computer_action\n", out)
        self.assertNotIn("HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS", out)

    def test_the_written_config_carries_the_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("", encoding="utf-8")
            run("--bot-id", "bot123", "--config", str(config))
            text = config.read_text(encoding="utf-8")
            self.assertIn("tools:\n      exclude:\n        - workspace_computer_action", text)
            self.assertNotIn("HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS", text)

    def test_allow_desktop_actions_writes_the_router_marker_instead(self):
        out = run("--bot-id", "bot_123", "--allow-desktop-actions").stdout
        self.assertNotIn("exclude", out)
        self.assertIn('HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS: "1"', out)


class ConfigEditTests(unittest.TestCase):
    def test_creates_managed_block_when_config_file_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "nested" / "config.yaml"
            run("--bot-id", "bot123", "--config", str(config))
            text = config.read_text(encoding="utf-8")
            self.assertTrue(config.exists())
            self.assertEqual(oct(config.stat().st_mode & 0o777), oct(0o600))
            self.assertIn("workspace_browser:", text)

    def test_creates_managed_block_from_empty_config_file(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("", encoding="utf-8")
            run("--bot-id", "bot123", "--config", str(config))
            text = config.read_text(encoding="utf-8")
            self.assertIn("mcp_servers:\n", text)
            self.assertIn("workspace_browser:", text)

    def test_creates_mcp_servers_block_when_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("model:\n  default: gpt-4\n", encoding="utf-8")
            run("--bot-id", "bot123", "--config", str(config))
            text = config.read_text(encoding="utf-8")
            self.assertIn("mcp_servers:\n", text)
            self.assertIn("workspace_browser:", text)
            [backup] = config.parent.glob("config.yaml.bak-*")
            self.assertEqual(backup.read_text(encoding="utf-8"), "model:\n  default: gpt-4\n")

    def test_inserts_under_existing_top_level_mcp_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(
                "model:\n  default: gpt-4\nmcp_servers:\n  other:\n    command: echo\n",
                encoding="utf-8")
            run("--bot-id", "bot123", "--config", str(config))
            text = config.read_text(encoding="utf-8")
            self.assertEqual(text.count("mcp_servers:"), 1)
            self.assertIn("workspace_browser:", text)
            self.assertIn("  other:\n    command: echo", text)

    def test_replaces_managed_block_in_place(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(
                "mcp_servers:\n"
                "# >>> alans-way workspace_browser managed block >>>\n"
                "  workspace_browser:\n"
                "    command: node\n"
                "# <<< alans-way workspace_browser managed block <<<\n"
                "  other:\n    command: echo\n",
                encoding="utf-8")
            run("--bot-id", "newbot", "--config", str(config))
            text = config.read_text(encoding="utf-8")
            self.assertEqual(text.count("workspace_browser:"), 1)
            self.assertIn('- "newbot"', text)
            self.assertIn("  other:\n    command: echo", text)

    def test_adopts_a_hand_written_entry_instead_of_duplicating_it(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(
                "mcp_servers:\n"
                "  workspace_browser:\n"
                "    command: node\n"
                "    args:\n"
                "      - /old/router.cjs\n"
                "    timeout: 30\n"
                "  other:\n    command: echo\n"
                "model:\n  default: gpt-4\n",
                encoding="utf-8")
            run("--bot-id", "newbot", "--config", str(config))
            text = config.read_text(encoding="utf-8")
            self.assertEqual(text.count("workspace_browser:"), 1)
            self.assertNotIn("/old/router.cjs", text)
            self.assertIn('- "newbot"', text)
            self.assertIn("  other:\n    command: echo", text)
            self.assertIn("model:\n  default: gpt-4", text)

    def test_special_chars_are_quoted_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("model:\n  default: gpt-4\n", encoding="utf-8")
            run("--bot-id", "bot123", "--bot-name", 'Scout: "Helper"',
                "--mac-ssh", "user@mac.local",
                "--router", "/path/with\\backslash/router.cjs",
                "--config", str(config))
            text = config.read_text(encoding="utf-8")
            # Values are double-quoted so colons, hashes and backslashes are safe.
            self.assertIn('- "/path/with\\\\backslash/router.cjs"', text)
            self.assertIn('- "bot123"', text)
            self.assertIn('- "Scout: \\"Helper\\""', text)
            self.assertIn('HERMES_WORKSPACE_MAC_SSH: "user@mac.local"', text)

    def test_ignores_commented_or_indented_mcp_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(
                "# mcp_servers:\n"
                "profiles:\n"
                "  demo:\n"
                "    mcp_servers:\n"
                "      other:\n"
                "        command: echo\n",
                encoding="utf-8")
            run("--bot-id", "bot123", "--config", str(config))
            text = config.read_text(encoding="utf-8")
            # Commented/indented mcp_servers are left alone; a new top-level key is created.
            self.assertEqual(text.count("mcp_servers:"), 3)
            self.assertIn("\nmcp_servers:\n", text)


HAND_WRITTEN = (
    "model:\n  default: gpt-4  # keep\r\n"
    "mcp_servers:\n"
    "  # mine\n"
    "  other:\n    command: echo\n"
    "  cua_alans_way:\n"
    "    command: node\n"
    "    args:\n"
    "      - /opt/x/workspace-router.cjs\n"
    "      - --bot-id\n"
    "      - '123'\n"
    "    # note\n"
    "  cua_alans_way_vps:\n"
    "    command: node\n"
    "    args: [\"/opt/x/browser-mcp.cjs\", \"--bot-id\", \"123\"]\n"
    "\n"
    "  keepme:\n    command: node\n    args: [server.js]\n"
    "# tail\nagent:\n  x: 1\n"
)
LEGACY_BLOCK = (
    "# >>> alans-way cua_alans_way managed block >>>\n"
    "  cua_alans_way:\n    command: node\n    args:\n      - /opt/workspace-router.cjs\n"
    "# <<< alans-way cua_alans_way managed block <<<\n"
)


class LegacyCleanupTests(unittest.TestCase):
    def setup_config(self, text):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Path(directory.name) / "config.yaml"
        config.write_bytes(text.encode("utf-8"))
        return config

    def test_hand_written_router_entries_are_replaced_by_one_managed_block(self):
        config = self.setup_config(HAND_WRITTEN)
        out = run("--bot-id", "bot123", "--config", str(config)).stdout
        text = config.read_bytes().decode("utf-8")
        self.assertEqual(text.count("workspace_browser:"), 1)
        self.assertNotIn("cua_alans_way", text)
        self.assertNotIn("workspace-router.cjs\n      - --bot", text)
        self.assertNotIn("browser-mcp.cjs", text)
        self.assertIn("removed unmanaged mcp_servers entry cua_alans_way\n", out)
        self.assertIn("removed unmanaged mcp_servers entry cua_alans_way_vps\n", out)
        for kept in ("model:\n  default: gpt-4  # keep\r\n", "  # mine\n  other:\n    command: echo\n",
                     "\n  keepme:\n    command: node\n    args: [server.js]\n# tail\nagent:\n  x: 1\n"):
            self.assertIn(kept, text)
        [backup] = config.parent.glob("config.yaml.bak-*")
        self.assertEqual(backup.read_bytes().decode("utf-8"), HAND_WRITTEN)

    def test_the_legacy_managed_block_is_removed_beside_the_current_one(self):
        before = "mcp_servers:\n" + LEGACY_BLOCK + "  other:\n    command: echo\nmodel:\n  default: x\n"
        config = self.setup_config(before)
        out = run("--bot-id", "bot123", "--config", str(config)).stdout
        text = config.read_text(encoding="utf-8")
        self.assertNotIn("cua_alans_way", text)
        self.assertEqual(text.count("workspace_browser:"), 1)
        self.assertIn("removed legacy managed block cua_alans_way\n", out)
        self.assertIn("  other:\n    command: echo\nmodel:\n  default: x\n", text)
        run("--bot-id", "bot123", "--config", str(config))
        self.assertEqual(config.read_text(encoding="utf-8"), text)
        self.assertEqual(len(list(config.parent.glob("config.yaml.bak-*"))), 1)

    def test_a_clean_config_gets_no_removal_report(self):
        config = self.setup_config("mcp_servers:\n  other:\n    command: echo\n")
        out = run("--bot-id", "bot123", "--config", str(config)).stdout
        self.assertNotIn("removed", out)


def servers(text):
    """Names of the mcp_servers children, read by indentation (no YAML library here)."""
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if re.match(r"mcp_servers:\s*(#.*)?$", l))
    names, indent = [], None
    for line in lines[start + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            break
        depth = len(line) - len(line.lstrip())
        indent = depth if indent is None else indent
        if depth == indent and not line.lstrip().startswith("-"):
            names.append(line.strip().split(":")[0])
    return names, indent


class MappingShapeTests(unittest.TestCase):
    def apply(self, text, check=True):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Path(directory.name) / "config.yaml"
        config.write_bytes(text.encode("utf-8"))
        result = run("--bot-id", "42", "--config", str(config), check=check)
        return config, config.read_bytes().decode("utf-8"), result

    def test_children_keep_the_indent_the_file_already_uses(self):
        before = ("mcp_servers:\n    keepme:\n        command: node\n    cua_alans_way:\n        command: node\n"
                  "        args:\n            - /x/workspace-router.cjs\nagent:\n  x: 1\n")
        _, text, _ = self.apply(before)
        self.assertEqual(servers(text), (["workspace_browser", "keepme"], 4))
        self.assertIn("    workspace_browser:\n      command: \"node\"\n      args:\n        - ", text)
        self.assertIn("      env:\n        HERMES_WORKSPACE_MAC_SSH", text)
        self.assertIn("    keepme:\n        command: node\nagent:\n  x: 1\n", text)

    def test_a_crlf_file_stays_crlf_throughout(self):
        _, text, _ = self.apply("mcp_servers:\r\n  keepme:\r\n    command: node\r\nmodel:\r\n  x: 1\r\n")
        self.assertNotIn("\r\r", text)
        self.assertEqual(text.count("\n"), text.count("\r\n"))
        self.assertEqual(servers(text.replace("\r", "")), (["workspace_browser", "keepme"], 2))

    def test_an_undeterminable_indent_refuses_and_leaves_the_file_alone(self):
        before = "mcp_servers:\n- keepme\nmodel:\n  default: x\n"
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Path(directory.name) / "config.yaml"
        config.write_text(before, encoding="utf-8")
        result = run("--bot-id", "42", "--config", str(config), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot tell how mcp_servers is indented", result.stderr)
        self.assertEqual(config.read_text(encoding="utf-8"), before)
        self.assertEqual(list(config.parent.glob("config.yaml.bak-*")), [])

    def test_a_trailing_comment_on_mcp_servers_does_not_create_a_second_key(self):
        before = ("mcp_servers:   # my servers\n  keepme:\n    command: node\n  cua_alans_way:\n"
                  "    command: node\n    args: [/x/workspace-router.cjs]\n")
        _, text, _ = self.apply(before)
        self.assertEqual(text.count("mcp_servers:"), 1)
        self.assertTrue(text.startswith("mcp_servers:   # my servers\n"))
        self.assertEqual(servers(text), (["workspace_browser", "keepme"], 2))

    def test_an_empty_mcp_servers_value_is_replaced_not_duplicated(self):
        for empty in ("{}", "[]", "null", "~", "{}  # none yet"):
            with self.subTest(empty=empty):
                _, text, _ = self.apply("mcp_servers: %s\nmodel:\n  default: x\n" % empty)
                self.assertEqual(text.count("mcp_servers:"), 1)
                self.assertEqual(servers(text), (["workspace_browser"], 2))
                self.assertTrue(text.endswith("model:\n  default: x\n"))

    def test_a_non_empty_inline_mcp_servers_is_refused_untouched(self):
        before = "mcp_servers: {a: {command: x}}\n"
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        config = Path(directory.name) / "config.yaml"
        config.write_text(before, encoding="utf-8")
        result = run("--bot-id", "42", "--config", str(config), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot tell how mcp_servers is indented", result.stderr)
        self.assertEqual(config.read_text(encoding="utf-8"), before)

    def test_the_inline_mapping_form_is_removed_too(self):
        before = ("mcp_servers:\n  keepme:\n    command: node\n"
                  "  cua_alans_way: {command: node, args: [/x/workspace-router.cjs, --bot-id, '1']}\n"
                  "  other: {command: \"node\", args: [\"C:\\\\app\\\\browser-mcp.cjs\"]}\n")
        _, text, out = self.apply(before)
        self.assertEqual(servers(text), (["workspace_browser", "keepme"], 2))
        self.assertIn("removed unmanaged mcp_servers entry other", out.stdout)

    def test_only_node_entries_that_run_our_script_are_removed(self):
        before = ("mcp_servers:\n"
                  "  npx_one:\n    command: npx\n    args: [-y, /x/workspace-router.cjs]\n"
                  "  mentions:\n    command: node\n    args: [server.js]\n    env:\n      NOTE: browser-mcp.cjs\n"
                  "  commented:\n    command: node\n    # old: workspace-router.cjs\n    args: [a]\n"
                  "  other_script:\n    command: node\n    args: [/x/not-browser-mcp.cjs.sh]\n"
                  "  ours:\n    command: node\n    args:\n    - /x/browser-mcp.cjs\n    - --vps\n")
        _, text, _ = self.apply(before)
        self.assertEqual(servers(text)[0], ["workspace_browser", "npx_one", "mentions", "commented", "other_script"])
        self.assertIn("# old: workspace-router.cjs", text)


class ProfileOptionTests(unittest.TestCase):
    def test_profile_resolves_to_hermes_home_profile_config(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            profile_dir = home / "profiles" / "alan-local"
            profile_dir.mkdir(parents=True)
            config = profile_dir / "config.yaml"
            config.write_text("model:\n  default: gpt-4\n", encoding="utf-8")
            env = dict(os.environ)
            env["HERMES_HOME"] = str(home)
            run("--bot-id", "bot123", "--profile", "alan-local", env=env)
            text = config.read_text(encoding="utf-8")
            self.assertIn("workspace_browser:", text)
            self.assertIn("alan-local", str(config))

    def test_profile_and_config_are_mutually_exclusive(self):
        result = run("--bot-id", "bot123", "--profile", "p", "--config", "/x.yaml", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mutually exclusive", result.stderr)

    def test_profile_rejects_bad_characters(self):
        result = run("--bot-id", "bot123", "--profile", "bad/profile", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bad --profile", result.stderr)


class VerifyTests(unittest.TestCase):
    def test_verify_reports_managed_block_for_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "hermes_home"
            profile_dir = home / "profiles" / "alan-local"
            profile_dir.mkdir(parents=True)
            config = profile_dir / "config.yaml"
            config.write_text(
                "mcp_servers:\n"
                "# >>> alans-way workspace_browser managed block >>>\n"
                "  workspace_browser:\n"
                "    command: node\n"
                "# <<< alans-way workspace_browser managed block <<<\n",
                encoding="utf-8")
            env = dict(os.environ)
            env["HERMES_HOME"] = str(home)
            result = run("--verify", "--profile", "alan-local", env=env)
            self.assertIn("managed workspace_browser block present", result.stdout)
            self.assertIn("all checks passed", result.stdout)

    def test_verify_warns_instead_of_crashing_when_the_mac_app_is_closed(self):
        if not shutil.which("node"):
            self.skipTest("node is required for the router probe")
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            ssh = bin_dir / "ssh"
            ssh.write_text("#!/bin/sh\nexit 0\n")
            ssh.chmod(0o755)
            env = dict(os.environ, HOME=directory, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            result = run("--verify", "--mac-ssh", "me@mac", env=env)
            self.assertIn("warn router probe → vps (mac unreachable)", result.stdout)
            self.assertIn("all checks passed", result.stdout)

    def test_verify_fails_a_tool_timeout_shorter_than_the_action_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(
                "mcp_servers:\n"
                "  workspace_browser:\n"
                "    command: node\n"
                "    lazy: true\n"
                "    timeout: 30\n"
                "  other:\n"
                "    timeout: 5\n",
                encoding="utf-8")
            result = run("--verify", "--config", str(config), check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("workspace_browser timeout 30s is below 120s", result.stdout)
            config.write_text(config.read_text().replace("timeout: 30", "timeout: 120"), encoding="utf-8")
            result = run("--verify", "--config", str(config))
            self.assertIn("workspace_browser timeout 120s", result.stdout)

    def test_verify_reports_the_desktop_input_exclusion_and_the_opt_in(self):
        for block, want in (
            ("    timeout: 120\n    tools:\n      exclude:\n        - workspace_computer_action\n",
             "ungated desktop input excluded from workspace_browser"),
            ('    timeout: 120\n    env:\n      HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS: "1"\n',
             "workspace_computer_action exposed by explicit opt-in"),
        ):
            with self.subTest(want=want), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "config.yaml"
                config.write_text(
                    "mcp_servers:\n  workspace_browser:\n    command: node\n" + block,
                    encoding="utf-8")
                result = run("--verify", "--config", str(config), check=False)
                self.assertIn(want, result.stdout)

    def test_verify_warns_when_desktop_input_is_not_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(
                "mcp_servers:\n  workspace_browser:\n    command: node\n    timeout: 120\n",
                encoding="utf-8")
            result = run("--verify", "--config", str(config), check=False)
            self.assertIn("does not exclude workspace_computer_action", result.stdout)

    def test_verify_counts_only_the_exclusion_under_the_blocks_own_tools_exclude(self):
        # The tool name appearing anywhere else in the file is not an
        # exclusion: a comment, or another server's tools.exclude.
        for extra in (
            "    # workspace_computer_action is not excluded here\n",
            "  other_server:\n    command: x\n    tools:\n      exclude:\n        - workspace_computer_action\n",
        ):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / "config.yaml"
                config.write_text(
                    "# >>> alans-way workspace_browser managed block >>>\n"
                    "  workspace_browser:\n    command: node\n    timeout: 120\n" + extra +
                    "# <<< alans-way workspace_browser managed block <<<\n",
                    encoding="utf-8")
                result = run("--verify", "--config", str(config), check=False)
                self.assertIn("does not exclude workspace_computer_action", result.stdout)
                self.assertNotIn("ungated desktop input excluded", result.stdout)

    def test_verify_reads_the_exclusion_inside_the_managed_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text(
                "# >>> alans-way workspace_browser managed block >>>\n"
                "  workspace_browser:\n    command: node\n    timeout: 120\n"
                "    tools:\n      exclude:\n        - workspace_computer_action\n"
                "# <<< alans-way workspace_browser managed block <<<\n"
                "  other_server:\n    command: x\n",
                encoding="utf-8")
            result = run("--verify", "--config", str(config), check=False)
            self.assertIn("ungated desktop input excluded from workspace_browser", result.stdout)


class HostOsFlagTests(unittest.TestCase):
    def test_host_os_is_emitted_in_the_env_block(self):
        out = run("--bot-id", "bot_123", "--host-os", "windows").stdout
        self.assertIn('HERMES_WORKSPACE_HOST_OS: "windows"', out)

    def test_host_os_defaults_to_mac(self):
        out = run("--bot-id", "bot_123").stdout
        self.assertIn('HERMES_WORKSPACE_HOST_OS: "mac"', out)

    def test_host_os_accepts_linux(self):
        out = run("--bot-id", "bot_123", "--host-os", "linux").stdout
        self.assertIn('HERMES_WORKSPACE_HOST_OS: "linux"', out)

    def test_host_os_rejects_other_values(self):
        result = run("--bot-id", "bot_123", "--host-os", "freebsd", check=False)
        self.assertNotEqual(result.returncode, 0)


class HostAddressTests(unittest.TestCase):
    def test_malformed_mac_ssh_is_rejected(self):
        for address in ("-oProxyCommand=x", "me@mac host", "me@mac;ls", "@mac", "me@", "me@@mac", "me@-mac"):
            result = run("--bot-id", "bot_123", "--mac-ssh", address, check=False)
            self.assertEqual(result.returncode, 2, address)
            self.assertIn("invalid --mac-ssh", result.stderr)

    def test_verify_ends_ssh_options_before_the_host(self):
        with tempfile.TemporaryDirectory() as directory:
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            log = Path(directory) / "ssh.log"
            ssh = bin_dir / "ssh"
            ssh.write_text('#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s"\nexit 1\n' % log)
            ssh.chmod(0o755)
            env = dict(os.environ, HOME=directory, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])
            run("--verify", "--mac-ssh", "me@mac", env=env, check=False)
            self.assertIn(" -- me@mac", log.read_text())


class WindowsGuestTests(unittest.TestCase):
    """Git Bash on native Windows: uname says MINGW and cygpath maps to C:/ paths."""

    def guest(self, prefix="C:"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "uname").write_text("#!/bin/sh\necho MINGW64_NT-10.0-26100\n")
        (bin_dir / "cygpath").write_text('#!/bin/sh\ncase "$1" in -m) printf "%s%%s" "$2";; *) printf "%%s" "$2";; esac\n' % prefix)
        for name in ("uname", "cygpath"):
            (bin_dir / name).chmod(0o755)
        return dict(os.environ, HOME=str(self.root), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"])

    def test_the_router_path_reaches_the_config_as_a_windows_path(self):
        env = self.guest()
        out = run("--bot-id", "bot_123", env=env).stdout
        self.assertRegex(out, r'- "C:/\S*/alans-way/scripts/workspace-router\.cjs"')
        out = run("--bot-id", "bot_123", "--router", "/opt/r/router.cjs", env=env).stdout
        self.assertIn('- "C:/opt/r/router.cjs"', out)

    def test_other_guests_keep_the_posix_router_path(self):
        out = run("--bot-id", "bot_123").stdout
        self.assertNotIn('"C:', out)

    def test_a_profile_lives_under_the_native_default_home(self):
        env = self.guest(prefix="")
        env.pop("HERMES_HOME", None)
        env["LOCALAPPDATA"] = str(self.root / "Local")
        run("--bot-id", "bot_123", "--profile", "p1", env=env)
        self.assertTrue((self.root / "Local" / "hermes" / "profiles" / "p1" / "config.yaml").exists())

    def test_verify_reaches_the_host_with_the_native_openssh(self):
        env = self.guest(prefix="")
        native = self.root / "Windows" / "System32" / "OpenSSH" / "ssh.exe"
        native.parent.mkdir(parents=True)
        native.write_text('#!/bin/sh\necho native >> "%s"\nexit 1\n' % (self.root / "ssh.log"))
        native.chmod(0o755)
        env["SYSTEMROOT"] = str(self.root / "Windows")
        run("--verify", "--mac-ssh", "me@mac", env=env, check=False)
        self.assertIn("native", (self.root / "ssh.log").read_text())


if __name__ == "__main__":
    unittest.main()
