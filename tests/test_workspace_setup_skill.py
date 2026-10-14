"""workspace-setup skill regression tests: agents must drive setup.sh, not improvise."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "alans-way" / "skills" / "workspace-setup" / "SKILL.md"


def _normalized(text: str) -> str:
    return " ".join(text.split())


class WorkspaceSetupSkillTests(unittest.TestCase):
    def test_telegram_ack_override_is_checked_before_global_off_or_saved_choice(self):
        ack = _normalized(self.text.split("**Acknowledgment while folding messages in.**", 1)[1]
                          .split("**Interim messages.**", 1)[0])
        # The reported bug: global=false + own-ack cannot hide Telegram=true.
        for rule in ("config get display.platforms.telegram.busy_steer_ack_enabled",
                     "skip the offer and leave both the global setting and marker untouched"):
            self.assertIn(rule, ack)
        override = ack.index("config get display.platforms.telegram.busy_steer_ack_enabled")
        guard = ack.index("skip the offer and leave both the global setting and marker untouched")
        skip = ack.index("is already off, or the marker")
        self.assertLess(override, guard)
        self.assertLess(guard, skip)
        for rule in ("even when the global value is false or the marker is `own-ack`",
                     "Telegram's extra bubble remains on", "Telegram's extra bubble is already off",
                     "confirmed “Config key not set” or `null`", "report the unknown state",
                     "platform override → global value → Telegram default → global default",
                     "gateway/display_config.py:117"):
            self.assertIn(rule, ack)

    def test_ack_marker_requires_effective_telegram_readback_after_consent(self):
        ack = _normalized(self.text.split("**Acknowledgment while folding messages in.**", 1)[1]
                          .split("**Interim messages.**", 1)[0])
        write = ack.index("config set display.busy_steer_ack_enabled false")
        self.assertIn("Re-read the Telegram override first", ack)
        readback = ack.index("Re-read the Telegram override first", write)
        marker = ack.index("config set skills.config.workspace-setup.busy_steer_ack_choice own-ack")
        self.assertLess(write, readback)
        self.assertLess(readback, marker)
        for rule in ("effective Telegram value is confirmed false",
                     "leave the marker untouched", "platforms that inherit the global setting",
                     "Explicit overrides on other platforms remain unchanged"):
            self.assertIn(rule, ack)
        self.assertNotIn("config set display.platforms.", ack)

    def test_binding_explains_native_telegram_home_and_manual_fallback(self):
        for rule in ("same primary DM becomes Hermes' Telegram home channel",
                     "config set TELEGRAM_HOME_CHANNEL", "send `/sethome` in that DM",
                     "loads on gateway restart", "config_env.py:515"):
            self.assertIn(rule, self.normalized)

    def test_steer_ack_choice_is_explicit_and_remembered(self):
        for rule in ("config get display.busy_steer_ack_enabled",
                     "skills.config.workspace-setup.busy_steer_ack_choice",
                     "Want just my own acknowledgment when you add something while I'm working?",
                     "config set display.busy_steer_ack_enabled false",
                     "An explicit no records `keep-ack`",
                     "with no answer, leave the acknowledgment setting and marker untouched",
                     "read back the acknowledgment setting before recording `own-ack`",
                     "gateway/run_busy.py:893"):
            self.assertIn(rule, self.normalized)

    @classmethod
    def setUpClass(cls):
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.normalized = _normalized(cls.text)

    def test_has_valid_frontmatter(self):
        match = re.match(r"^---\n(.*?)\n---\n", self.text, re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md must start with frontmatter")
        self.assertIn("name: workspace-setup", match.group(1))
        self.assertIn("description:", match.group(1))

    def test_directs_to_setup_script(self):
        self.assertIn("setup.sh", self.normalized)
        self.assertIn("--bot-id", self.normalized)
        self.assertIn("--mac-ssh", self.normalized)
        self.assertIn("--skip-plugin", self.normalized)
        self.assertIn("https://github.com/capthvnsen/alans-way", self.text)
        self.assertIn("docs/setup-prompt.md", self.text)
        self.assertIn("do not replace this plugin", self.normalized)

    def test_remotes_are_pinned_to_reviewed_commits(self):
        self.assertRegex(
            self.text,
            r"raw\.githubusercontent\.com/capthvnsen/alans-way/[0-9a-f]{40}/docs/setup-prompt\.md",
            "setup-prompt.md must be fetched at a pinned commit, not main",
        )
        # A catalog install's reviewed sha lives in the install record, so the
        # skill reads it from there and hands it to setup.sh as --repo-ref.
        self.assertIn(".install-metadata.json", self.text)
        self.assertRegex(
            self.text,
            r"git -C ~/alans-way-agents checkout \"\$PIN\"",
            "the agents repo clone must be checked out to the resolved pin",
        )
        self.assertRegex(
            self.text,
            r"--repo-ref \"\$PIN\"",
            "setup.sh must be passed the resolved pin so a stale clone hard-stops",
        )
        # Without a catalog record the fallback is the release tag matching
        # plugin.yaml's version field, and the skill must say it has to exist.
        version = re.search(
            r"^version:\s*['\"]?([0-9.]+)",
            (ROOT / "alans-way" / "plugin.yaml").read_text(encoding="utf-8"),
            re.MULTILINE,
        ).group(1)
        tag = "v" + version
        self.assertIn("PIN=" + tag, self.text)
        self.assertIn("tag must exist", self.normalized)
        self.assertRegex(
            self.text,
            r"--desktop-ref [0-9a-f]{40}",
            "setup.sh must be passed the pinned desktop ref",
        )

    def test_busy_mode_choice_requires_an_answer_before_restart(self):
        for phrase in ("When you message me while I'm working, should I fold it into the current task (recommended) or stop and start over?",
                       "every platform in that profile", "after the current step finishes",
                       "Never treat silence or non-interactive runs as consent",
                       "already `steer`", "skills.config.workspace-setup.busy_input_choice",
                       "config set display.busy_input_mode steer",
                       "config set display.busy_input_mode interrupt"):
            self.assertIn(phrase, self.normalized)
        self.assertLess(self.text.index("**Messages while working"), self.text.index("```sh\ngit clone"))

    def test_idempotent_and_verify_documented(self):
        self.assertIn("idempotent", self.normalized)
        self.assertIn("--verify", self.normalized)

    def test_busy_mode_uses_effective_value_and_skips_steer_queue_or_remembered_interrupt(self):
        for rule in ("effective value", "config get display.busy_input_mode",
                     "already `steer` or `queue`", "A recorded `keep-interrupt`",
                     "An absent marker means ask once", "report the unknown state"):
            self.assertIn(rule, self.normalized)

    def test_silence_cannot_be_overridden_by_setup(self):
        for rule in ("with no answer, leave the mode and marker untouched",
                     "General setup or proactivity consent does not answer this question",
                     "Neither `setup.sh` nor `setup-workspace.sh` writes these two display keys"):
            self.assertIn(rule, self.normalized)

    def test_answer_and_readback_gate_marker_write(self):
        for rule in ("Apply only the answered choice with the supported CLI",
                     "Read back that key and report a failure before continuing",
                     "only after that answer and a successful mode readback",
                     "never restore a mode from it or override later user changes",
                     "config unset skills.config.workspace-setup.busy_input_choice"):
            self.assertIn(rule, self.normalized)

    def test_interim_default_true_requires_no_write_and_false_is_only_reported(self):
        for rule in ("config get display.interim_assistant_messages",
                     "hermes_cli/config_defaults.py:919", "defaults to `true`",
                     "Only when the effective value is `false`",
                     "report that the user's choice disables interim messages",
                     "Write nothing for this key"):
            self.assertIn(rule, self.normalized)
        self.assertNotIn("config set display.interim_assistant_messages", self.normalized)

    def test_display_stack_is_guided_not_auto(self):
        self.assertIn("never auto-installed", self.normalized)

    def test_vm_preview_wiring_is_in_the_order_of_work(self):
        # A VM that already serves noVNC over websockify only needs the app's
        # Settings filled in; the skill must surface the URL shape and where
        # the VNC password lives instead of telling the user to install one.
        self.assertIn("websockify", self.normalized)
        self.assertIn("/vnc.html", self.text)
        self.assertIn("Remote desktop connection", self.text)

    def test_vm_moved_checklist_lists_every_saved_address(self):
        # A VM move leaves several independently stored addresses stale and
        # they mostly do not update each other; the skill must walk every
        # copy, not just the app's Settings.
        self.assertIn("Moved your agent", self.text)
        for needle in ("vpsBrowser.sshHost", "remoteUrl", "connections.json",
                       "phone", "API_SERVER_HOST", "tailscale serve status"):
            self.assertIn(needle, self.text)
        # A deliberate other-host preview is a valid setting: the checklist
        # must qualify the repoint, not prescribe it unconditionally.
        self.assertIn("meant to follow", self.text)

    def test_primary_binding_not_silent(self):
        self.assertIn("do not bind a different bot's route silently", self.normalized)
        self.assertIn("proactivity bind --session-key", self.normalized)
        self.assertIn("proactivity status", self.normalized)

    def test_restart_comes_last_and_the_agent_answers_first(self):
        self.assertIn("comes last", self.normalized)
        self.assertIn("send your final message", self.normalized)
        self.assertIn("detached", self.normalized)

    def test_linux_hosts_and_validated_key_flags_are_covered(self):
        self.assertIn("--host-os <mac|windows|linux>", self.normalized)
        self.assertIn("--mac-key", self.normalized)
        self.assertIn("--mac-host-key", self.normalized)

    def test_gateway_restart_through_owner(self):
        self.assertIn("never kill -9 a gateway", self.normalized)

    def test_supervisord_restart_uses_the_usr1_drain(self):
        """Issue #65: the skill must steer a hand restart on a supervisord
        host to `signal USR1`, since `supervisorctl restart` escalates to
        SIGKILL after stopwaitsecs and corrupts state.db mid-checkpoint."""
        self.assertIn("signal USR1", self.normalized)
        self.assertIn("stopwaitsecs", self.normalized)
        self.assertIn("state.db", self.normalized)

    def test_long_chats_step_precedes_restart_and_requires_consent(self):
        self.assertLess(self.text.index("**Long chats"), self.text.index("## Order of work"))
        for requirement in ("explicit user consent", "each Alan's Way profile",
                            "customized values", "micro_compact", "effective compression threshold",
                            "auxiliary.compression", "never switch it automatically"):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.normalized)
        self.assertIn("references/long-chats.md", self.text)


class LongChatsSetupProcedureTests(unittest.TestCase):
    """Execute the documented opt-in block with an isolated Hermes CLI double."""

    def setUp(self):
        reference = SKILL_PATH.parent / "references" / "long-chats.md"
        self.text = reference.read_text(encoding="utf-8")
        self.block = re.search(r"<!-- pruning-commands -->\s*```sh\n(.*?)```", self.text, re.S).group(1)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = self.directory / "config.json"
        self.calls = self.directory / "calls.jsonl"
        self.config.write_text(json.dumps({
            "proactive_prune_tokens": 0,
            "proactive_prune_min_result_chars": 8000,
            "proactive_prune_min_reclaim_tokens": 4096,
        }))
        cli = self.directory / "hermes"
        cli.write_text(f"#!{sys.executable}\n" + '''import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["TEST_CALLS"], "a") as stream:
    stream.write(json.dumps(args) + "\\n")
assert args[:3] == ["-p", "test-profile", "config"], args
path = pathlib.Path(os.environ["TEST_CONFIG"])
config = json.loads(path.read_text())
key = args[4].removeprefix("compression.")
if args[3] == "get":
    if key == os.environ.get("TEST_FAIL_KEY"):
        sys.exit(1)
    print(json.dumps(config[key]))
elif args[3] == "set":
    config[key] = int(args[5])
    path.write_text(json.dumps(config))
else:
    sys.exit(2)
''')
        cli.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.directory) + os.pathsep + os.environ["PATH"],
                        profile="test-profile", TEST_CONFIG=str(self.config), TEST_CALLS=str(self.calls))
        self.env.pop("PRUNING_CONSENT", None)

    def run_procedure(self, consent=None):
        if consent is not None:
            self.env["PRUNING_CONSENT"] = consent
        result = subprocess.run(["sh", "-c", self.block], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        return json.loads(self.config.read_text()), [call for call in calls if call[3] == "set"]

    def test_no_consent_makes_no_writes(self):
        for consent in (None, "no"):
            with self.subTest(consent=consent):
                config, writes = self.run_procedure(consent)
                self.assertEqual(writes, [])
                self.assertEqual(config, {"proactive_prune_tokens": 0,
                                          "proactive_prune_min_result_chars": 8000,
                                          "proactive_prune_min_reclaim_tokens": 4096})

    def test_consent_sets_stock_values_and_is_idempotent(self):
        config, writes = self.run_procedure("yes")
        self.assertEqual(config, {"proactive_prune_tokens": 48000,
                                  "proactive_prune_min_result_chars": 8000,
                                  "proactive_prune_min_reclaim_tokens": 4096})
        self.assertEqual(len(writes), 1)
        _, repeated_writes = self.run_procedure("yes")
        self.assertEqual(repeated_writes, writes)

    def test_every_custom_threshold_is_preserved(self):
        custom = {"proactive_prune_tokens": 64000, "proactive_prune_min_result_chars": 12000,
                  "proactive_prune_min_reclaim_tokens": 2048}
        self.config.write_text(json.dumps(custom))
        config, writes = self.run_procedure("yes")
        self.assertEqual(config, custom)
        self.assertEqual(writes, [])

    def test_custom_eligibility_does_not_prevent_approved_trigger_opt_in(self):
        config = json.loads(self.config.read_text())
        config["proactive_prune_min_result_chars"] = 12000
        self.config.write_text(json.dumps(config))
        config, writes = self.run_procedure("yes")
        self.assertEqual(config["proactive_prune_tokens"], 48000)
        self.assertEqual(config["proactive_prune_min_result_chars"], 12000)
        self.assertEqual(len(writes), 1)

    def test_unreadable_trigger_is_not_treated_as_a_default(self):
        self.env["TEST_FAIL_KEY"] = "proactive_prune_tokens"
        config, writes = self.run_procedure("yes")
        self.assertEqual(config["proactive_prune_tokens"], 0)
        self.assertEqual(writes, [])

    def test_sanity_check_and_undo_are_documented(self):
        for key in ("compression", "model", "auxiliary.compression.provider",
                    "auxiliary.compression.model", "auxiliary.compression.base_url"):
            self.assertIn(key, self.text)
        for requirement in ("model_thresholds", "threshold_tokens", "75%", "512,000",
                            "output reservation", "runtime", "unknown", "config unset",
                            "config set compression.proactive_prune_tokens 0"):
            self.assertIn(requirement, self.text)


if __name__ == "__main__":
    unittest.main()
