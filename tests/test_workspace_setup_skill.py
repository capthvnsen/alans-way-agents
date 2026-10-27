"""workspace-setup skill regression tests: agents must drive setup.sh, not improvise."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "alans-way" / "skills" / "workspace-setup" / "SKILL.md"


def _normalized(text: str) -> str:
    return " ".join(text.split())


class WorkspaceSetupSkillTests(unittest.TestCase):
    def test_keep_browser_only_skips_disabling_and_needs_explicit_reenable(self):
        self.assertIn("built-in browser toolset for Telegram and cron", self.normalized)
        self.assertIn("`--keep-browser` only skips disabling it; it does not re-enable an already-disabled toolset", self.normalized)
        self.assertIn("hermes -p <profile> tools enable browser --platform <platform>", self.normalized)
        self.assertNotIn("`--keep-browser` undoes that", self.normalized)

    def telegram_step(self):
        return _normalized(self.text.split("**Make Telegram feel right.**", 1)[1]
                           .split("```sh", 1)[0])

    def test_telegram_preset_uses_global_memory_notice_key(self):
        step = self.telegram_step()
        expected = {
            "platforms.telegram.typing_indicator": "true",
            "display.platforms.telegram.interim_assistant_messages": "true",
            "display.platforms.telegram.tool_progress": "off",
            "display.platforms.telegram.notifications": "important",
            "display.platforms.telegram.long_running_notifications": "generic",
            "display.platforms.telegram.busy_steer_ack_enabled": "false",
            "display.memory_notifications": "off",
            "cron.wrap_response": "false",
            "platforms.telegram.reactions": "true",
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertIn(f"| `{key}` | `{value}` |", step)
        self.assertIn("hermes -p <profile> config set <key> <answered-value>", step)
        self.assertIn("6e7b83a2f1c093e992a8d838ed77ea320fbd8e51", step)
        for forbidden in ("config set display.busy_steer_ack_enabled",
                          "config set display.interim_assistant_messages",
                          "display.message_reactions"):
            self.assertNotIn(forbidden, self.normalized)

    def test_telegram_choice_reuses_answer_and_readback_gate(self):
        step = self.telegram_step()
        for rule in ("An absent marker means ask once", "one grouped question",
                     "Apply only the answered choice with the supported CLI",
                     "Never treat silence or non-interactive runs as consent",
                     "with no answer, leave the settings and marker untouched",
                     "General setup, proactivity or busy-mode consent does not answer this question",
                     "Read back each changed key", "report the mismatch",
                     "leave the marker untouched", "only after that answer and successful readbacks"):
            self.assertIn(rule, step)
        self.assertLess(step.index("config set <key> <answered-value>"),
                        step.index("Read back each changed key"))
        self.assertLess(step.index("Read back each changed key"),
                        step.index("config set skills.config.workspace-setup.telegram_feel_choice chosen"))
        self.assertLess(self.text.index("**Make Telegram feel right.**"),
                        self.text.index("```sh\n# Prepare"))

    def test_telegram_choice_preserves_existing_values_and_remembers_decline(self):
        step = self.telegram_step()
        for rule in ("config get <key>", "config get skills.config.workspace-setup.telegram_feel_choice",
                     "platform override → global value → Telegram default → global default",
                     "show current values that differ", "Preserve existing user values",
                     "unless the answer explicitly includes changing them",
                     "A recorded `keep-current` or `chosen`", "continue without asking or rewriting",
                     "never restore settings from it or override later user changes",
                     "confirmed “Config key not set”", "report the unknown state",
                     "An explicit no records `keep-current`",
                     "config unset skills.config.workspace-setup.telegram_feel_choice",
                     "config.yaml", "remember the answer",
                     "HERMES_GATEWAY_BUSY_STEER_ACK_ENABLED", "HERMES_TELEGRAM_NOTIFICATIONS",
                     "TELEGRAM_REACTIONS", "Environment overrides"):
            self.assertIn(rule, step)

    def test_telegram_offer_explains_defaults_scope_and_lifecycle_limits(self):
        step = self.telegram_step()
        for rule in ("typing", "short updates", "mechanical tool progress",
                     "sound", "visual notifications", "plain words", "my own acknowledgment",
                     "profile-wide", "all delivery targets", "job IDs",
                     "👀", "👍", "👎", "cancellation clears",
                     "does not verify the user's goal", "cannot reply immediately while a tool is blocked"):
            self.assertIn(rule, step)

    def test_upgrade_honors_legacy_steer_ack_answers_until_explicit_revisit(self):
        step = self.telegram_step()
        self.assertIn("config get skills.config.workspace-setup.busy_steer_ack_choice", step)
        for answer in ("keep-ack", "own-ack"):
            with self.subTest(answer=answer):
                self.assertIn(f"`{answer}`", step)
        for rule in ("legacy answer", "continue without asking or rewriting",
                     "unless the user explicitly revisits", "Preserve unknown legacy markers",
                     "never migrate the legacy marker automatically"):
            self.assertIn(rule, step)

    def test_timezone_is_city_based_explicit_and_read_back(self):
        step = self.telegram_step()
        for rule in ("config get timezone", "empty", "MST", "EST", "PST", "CST",
                     "UTC offsets", "daylight-saving", "ask the user's city; don't guess",
                     "offer the matching IANA zone", "Preserve an existing IANA zone",
                     "config set timezone <answered-IANA-zone>", "read back `timezone`",
                     "Never change it silently", "no city or explicit zone answer",
                     "leave timezone untouched", "--timezone"):
            self.assertIn(rule, step)

    def test_presentation_consent_is_remembered_independently_of_timezone(self):
        step = self.telegram_step()
        self.assertNotIn("leave timezone and the marker untouched", step)
        for rule in ("Remember the completed presentation answer independently of timezone",
                     "unresolved timezone or a failed timezone write/readback",
                     "does not block the presentation marker",
                     "perform the timezone check below even when a saved answer skips",
                     "ask only the separate timezone question",
                     "defer the setup invocation that requires it"):
            self.assertIn(rule, step)

    def test_legacy_tool_progress_all_wins_over_global_off_until_platform_off(self):
        step = self.telegram_step()
        for rule in ("config get display.tool_progress_overrides.telegram",
                     "platform override → legacy Telegram override → global value",
                     "global `off` plus legacy `all` still enables progress",
                     "write `display.platforms.telegram.tool_progress off`",
                     "Preserve the legacy key", "null legacy values inherit"):
            self.assertIn(rule, step)

    def test_memory_skill_notice_offer_is_global_consented_and_read_back(self):
        step = self.telegram_step()
        for rule in ("hide memory/skill bookkeeping notices",
                     "| `display.memory_notifications` | `off` |",
                     "Hiding “💾 Memory updated / Self-improvement review” notices affects every platform this profile uses, not only Telegram",
                     "off|on|verbose", "background review still runs",
                     "run_turn_runner.py#L1289", "use the global `display.memory_notifications` directly",
                     "boolean `false` means `off`",
                     "A Telegram-only memory/skill notice switch isn't supported by Hermes yet",
                     "`display.memory_notifications` must read back `off` (or `false`)",
                     "report only that stored value", "not verified banner suppression",
                     "Read back each changed key", "already-planned gateway restart"):
            self.assertIn(rule, step)
        for obsolete in ("display.platforms.telegram.memory_notifications",
                         "skip this leaf", "where supported",
                         "memory/skill notice support check"):
            self.assertNotIn(obsolete, step)

    def test_binding_explains_native_telegram_home_and_manual_fallback(self):
        for rule in ("same primary DM becomes Hermes' Telegram home channel",
                     "config set TELEGRAM_HOME_CHANNEL", "send `/sethome` in that DM",
                     "loads on gateway restart", "config_env.py:515"):
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

    def test_desktop_api_prerequisite_has_a_known_build_and_diagnostic(self):
        for path in (SKILL_PATH, ROOT / "README.md"):
            text = _normalized(path.read_text())
            for rule in ("0.21.5", "63f5e0ea45726c5d8d7d207d140613997730aab3",
                         "ComputerUseProvider", "HERMES_PYTHON", "probe failed"):
                self.assertIn(rule, text)

    def test_noninteractive_scan_confirmation_requires_review_and_consent(self):
        for rule in ("--enable does not confirm", "--force", "dangerous",
                     "Never disable scanning", "explicit consent", "dependency consent"):
            self.assertIn(rule, self.normalized)

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

    def autonomy_step(self):
        self.assertIn("**Working on its own", self.text)
        return _normalized(self.text.split("**Working on its own", 1)[1]
                           .split("**Make Telegram feel right.**", 1)[0])

    def test_autonomy_question_and_goal_hint_are_exact_and_before_restart(self):
        question = ("Want me to work on my own? I'll keep going until a job is done instead of stopping to check in, "
                    "and fold in anything you send while I'm working. "
                    "(Recommended. Say no to keep things as they are.)")
        hint = "For a big job, start your message with /goal and I'll keep at it until it's verified done."
        step = self.autonomy_step()
        self.assertEqual(step.count(question), 1)
        self.assertEqual(step.count(hint), 1)
        for rule in ("ask once", "every platform in that profile", "takes effect after the bot restarts",
                     "the restart at the end of setup does that", "it applies at the next restart",
                     "a message sent mid-task waits for the current step to finish",
                     "After setup, say once"):
            self.assertIn(rule, step)
        self.assertLess(self.text.index("**Working on its own"), self.text.index("```sh\n# Prepare"))
        self.assertLess(self.text.index("**Working on its own"),
                        self.text.index("6. **The gateway restart"))

    def test_autonomy_reads_each_key_and_only_changes_stock_defaults(self):
        step = self.autonomy_step()
        for key, stock, recommended in (("display.busy_input_mode", "interrupt", "steer"),
                                        ("agent.intent_ack_continuation", "auto", "true")):
            with self.subTest(key=key):
                self.assertIn(f"| `{key}` | `{stock}` | `{recommended}` |", step)
                self.assertIn(f"config get {key}", step)
                self.assertIn(f"config set {key} {recommended}", step)
        for rule in ("effective value", "including Hermes's defaults", "only when its effective value is the stock default",
                     "Read back both keys", "including unchanged keys", "report the actual values",
                     "Preserve and show every other existing value", "`steer` or `queue`",
                     "`agent.intent_ack_continuation: false`", "including `interrupt`",
                     "deliberately chose a stock value, preserve it", "merged value", "cannot distinguish",
                     "Show current values and proposed changes.",
                     "Preserve unknown values and unreadable config"):
            self.assertIn(rule, step)
        self.assertNotIn("stock-looking", self.text)

    def test_code_verification_is_separate_and_only_when_requested(self):
        step = self.autonomy_step()
        opt_in = ("Leave `agent.verify_on_stop` as it is. If the user codes with this bot and asks for stricter checks, "
                  "`hermes -p <profile> config set agent.verify_on_stop true` makes it double-check code changes "
                  "before finishing; don't offer it otherwise.")
        self.assertIn(opt_in, step)
        self.assertEqual(step.count("config set agent.verify_on_stop true"), 1)
        self.assertNotIn("agent.verify_on_stop", step.replace(opt_in, ""))
        yes_path = step.split("After yes, recheck each", 1)[1].split("An explicit no", 1)[0]
        self.assertEqual(re.findall(r"config set ([\w.]+) (\w+)", yes_path),
                         [("display.busy_input_mode", "steer"), ("agent.intent_ack_continuation", "true")])

    def test_idempotent_and_verify_documented(self):
        self.assertIn("idempotent", self.normalized)
        self.assertIn("--verify", self.normalized)

    def test_autonomy_reruns_preserve_saved_and_legacy_choices(self):
        step = self.autonomy_step()
        for rule in ("config get skills.config.workspace-setup.autonomy_choice",
                     "A recorded `keep-current` or `chosen`", "continue without asking or rewriting",
                     "config get skills.config.workspace-setup.busy_input_choice",
                     "A recorded `keep-interrupt` skips only `display.busy_input_mode`",
                     "still offer the other key", "confirmed “Config key not set”",
                     "report the unknown state", "never restore settings from it or override later user changes",
                     "config unset skills.config.workspace-setup.autonomy_choice"):
            self.assertIn(rule, step)

    def test_silence_cannot_be_overridden_by_setup(self):
        for rule in ("with no answer, leave the settings and marker untouched",
                     "Never treat silence or non-interactive runs as consent",
                     "General setup or proactivity consent does not answer this question"):
            self.assertIn(rule, self.autonomy_step())
        self.assertIn("Neither `setup.sh` nor `setup-workspace.sh` writes these Telegram choices", self.normalized)

    def test_autonomy_marker_is_last_and_requires_successful_readbacks(self):
        step = self.autonomy_step()
        for rule in ("Apply only the answered choice with the supported CLI",
                     "An explicit no preserves both settings", "config.yaml",
                     "only after that answer and successful readbacks",
                     "report the mismatch and leave the marker untouched",
                     "Read back the marker too", "failed writes/readbacks"):
            self.assertIn(rule, step)
        for answer in ("chosen", "keep-current"):
            marker_write = f"config set skills.config.workspace-setup.autonomy_choice {answer}"
            self.assertIn(marker_write, step)
            self.assertLess(step.index("Read back both keys"), step.index(marker_write))
            for key in ("display.busy_input_mode", "agent.intent_ack_continuation"):
                self.assertLess(step.index(f"config set {key}"), step.index(marker_write))

    def test_global_interim_preference_is_preserved_by_telegram_offer(self):
        self.assertNotIn("config set display.interim_assistant_messages", self.normalized)
        self.assertIn("Leave other global display settings and other platforms untouched",
                      self.telegram_step())

    def test_display_stack_is_guided_not_auto(self):
        self.assertIn("never auto-installed", self.normalized)

    def test_vm_preview_wiring_is_in_the_order_of_work(self):
        # A VM that already serves noVNC over websockify only needs the app's
        # Settings filled in; the skill must surface the URL shape and where
        # the VNC password lives instead of telling the user to install one.
        self.assertIn("websockify", self.normalized)
        self.assertIn("/vnc.html", self.text)
        self.assertIn("Remote desktop connection", self.text)

    def test_loopback_viewer_requires_consented_bounded_computer_forward_and_probe(self):
        for rule in ("127.0.0.1 only", "explicit consent", "StrictHostKeyChecking=yes",
                     "ExitOnForwardFailure=yes", "ServerAliveCountMax=2", "sleep 1800",
                     "127.0.0.1:16080:127.0.0.1:<viewer-port>", "--max-time 10",
                     "from the user's computer", "Ctrl-C", "never change the listener"):
            self.assertIn(rule, self.normalized)

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

    def test_setup_hands_a_pinned_plan_to_the_app_outside_the_gateway(self):
        for instruction in ("Never bypass the lifecycle guard", "Finish setup and restart my bot",
                            "repoRef", "desktopRef", "JSON setup plan", "outside the gateway",
                            "Hermes 0.21.x", "Check setup"):
            self.assertIn(instruction, self.normalized)
        self.assertNotIn("most likely running inside this gateway. `setup.sh --restart`", self.normalized)

    def test_restart_checks_use_output_pasted_by_the_user(self):
        self.assertIn("Ask the user to paste the app's output, then report failed checks and warnings from it.",
                      self.normalized)
        self.assertNotIn("Read the app's output", self.text)

    def test_windows_setup_is_a_human_handoff_outside_the_gateway(self):
        step = self.normalized.split("4. **A Windows guest", 1)[1].split("5. **", 1)[0]
        for rule in ("ask the human", "external Git Bash shell", "outside the gateway",
                     "Never run setup through Hermes's terminal", "pinned setup command",
                     "WSL2 counts as Linux"):
            self.assertIn(rule, step)
        self.assertNotIn("so run the same command there", step)

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


class SetupPinProcedureTests(unittest.TestCase):
    SHA = "1234567890abcdef1234567890abcdef12345678"

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / "profile"
        (self.home / "plugins").mkdir(parents=True)
        self.source = self.root / "source with spaces"
        self.env = dict(os.environ, HERMES_HOME=str(self.home), GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_CONFIG_SYSTEM=os.devnull)
        subprocess.run(["git", "init", "-q", str(self.source)], check=True, env=self.env)
        # A detached auto-maintenance repack would race the temp dir cleanup.
        self.git("config", "maintenance.auto", "false")
        self.git("remote", "add", "origin", "https://github.com/capthvnsen/alans-way-agents")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.source), *args], check=True, env=self.env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def resolve(self, row):
        (self.home / "plugins" / ".install-metadata.json").write_text(json.dumps({"alans-way": row}))
        code = re.search(r"PIN=\$\(python3 -c '(.*?)'\)", SKILL_PATH.read_text(), re.DOTALL).group(1)
        return subprocess.run([sys.executable, "-c", code], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_file_source_uses_installer_revision_after_validating_origin(self):
        result = self.resolve({"source": self.source.as_uri() + "#alans-way", "revision": self.SHA})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), self.SHA)

    def test_unrecorded_install_fetches_and_checks_out_the_release_tag(self):
        self.prepare_checkout()
        (self.home / "plugins" / ".install-metadata.json").unlink()
        result = self.procedure()
        self.assertEqual(result.returncode, 0, result.stderr)
        checkout = subprocess.run(["git", "-C", str(self.root / "alans-way-agents"),
                                   "describe", "--tags", "--exact-match"],
                                  capture_output=True, text=True, env=self.env)
        self.assertEqual(checkout.stdout.strip(), "v0.21.13")

    def prepare_checkout(self, existing=False):
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-qm", "first")
        self.git("tag", "-f", "v0.21.13")
        self.destination = self.root / "alans-way-agents"
        if existing:
            subprocess.run(["git", "clone", "-q", str(self.source), str(self.destination)],
                           check=True, env=self.env)
            subprocess.run(["git", "-C", str(self.destination), "remote", "set-url", "origin",
                            "https://github.com/capthvnsen/alans-way-agents"], check=True, env=self.env)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-qm", "installed")
        self.revision = subprocess.check_output(["git", "-C", str(self.source), "rev-parse", "HEAD"],
                                                 env=self.env, text=True).strip()
        (self.home / "plugins" / ".install-metadata.json").write_text(json.dumps({"alans-way": {
            "source": "https://github.com/capthvnsen/alans-way-agents#alans-way",
            "revision": self.revision}}))
        # Only the transport is mocked: origin/config/status validation uses real Git.
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.fetch_log = self.root / "fetches"
        real_git = shutil.which("git")
        wrapper = self.bin / "git"
        wrapper.write_text(f"#!{sys.executable}\n" +
            "import os, pathlib, subprocess, sys\nargs = sys.argv[1:]\n" +
            f"if len(args) > 2 and args[2] == 'fetch':\n    pathlib.Path({str(self.fetch_log)!r}).touch()\n" +
            f"    args[4] = {str(self.source)!r}\n" +
            f"sys.exit(subprocess.call([{real_git!r}, *args]))\n")
        wrapper.chmod(0o755)

    def procedure(self):
        block = re.search(r"```sh\n((?:mkdir |# Prepare).*?)\n# End checkout preparation",
                          SKILL_PATH.read_text(), re.S).group(1)
        return subprocess.run(["sh", "-c", block], env=dict(self.env, HOME=str(self.root),
                              PATH=str(self.bin) + os.pathsep + os.environ["PATH"]),
                              capture_output=True, text=True, timeout=15)

    def test_new_checkout_rejects_effective_origin_rewrite_before_fetch(self):
        self.prepare_checkout()
        config = self.root / "gitconfig"
        config.write_text('[url "' + self.source.as_uri() + '"]\n'
                          '    insteadOf = https://github.com/capthvnsen/alans-way-agents\n')
        self.env["GIT_CONFIG_GLOBAL"] = str(config)
        result = self.procedure()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.fetch_log.exists())
        self.assertIn("Setup checkout unavailable", result.stderr)

    def test_clean_existing_clone_fetches_and_checks_out_installed_revision(self):
        self.prepare_checkout(existing=True)
        result = self.procedure()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.fetch_log.exists())
        head = subprocess.check_output(["git", "-C", str(self.destination), "rev-parse", "HEAD"], text=True)
        self.assertEqual(head.strip(), self.revision)

    def test_invalid_existing_clone_stops_with_reason_before_fetch(self):
        for invalid in ("foreign", "multiple", "rewrite", "dirty", "plain-directory"):
            with self.subTest(invalid=invalid):
                # Each case has independent Git config and destination contents.
                if hasattr(self, "destination"):
                    shutil.rmtree(self.destination)
                    shutil.rmtree(self.bin)
                self.prepare_checkout(existing=True)
                git = ["git", "-C", str(self.destination)]
                if invalid == "foreign":
                    subprocess.run([*git, "remote", "set-url", "origin", "https://example.invalid/foreign"], check=True)
                elif invalid == "multiple":
                    subprocess.run([*git, "config", "--add", "remote.origin.url", "https://github.com/capthvnsen/alans-way-agents.git"], check=True)
                elif invalid == "rewrite":
                    subprocess.run([*git, "config", "url.https://example.invalid/foreign.insteadOf",
                                    "https://github.com/capthvnsen/alans-way-agents"], check=True)
                elif invalid == "dirty":
                    (self.destination / "untracked").write_text("preserve me")
                else:
                    shutil.rmtree(self.destination / ".git")
                result = self.procedure()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.fetch_log.exists())
                self.assertIn("Setup checkout unavailable", result.stderr)
                if invalid == "dirty":
                    self.assertEqual((self.destination / "untracked").read_text(), "preserve me")

    def test_catalog_pin_outranks_a_revision_and_missing_record_allows_tag_fallback(self):
        result = self.resolve({"source": "catalog", "catalog": {"sha": self.SHA}, "revision": "a" * 40})
        self.assertEqual(result.stdout.strip(), self.SHA)
        self.assertEqual(self.resolve({}).stdout.strip(), "")

    def test_all_six_origin_forms_and_foreign_push_urls_are_allowed(self):
        for prefix in ("https://github.com/", "git@github.com:", "ssh://git@github.com/"):
            for suffix in ("", ".git"):
                url = prefix + "capthvnsen/alans-way-agents" + suffix
                self.git("config", "remote.origin.url", url)
                self.git("config", "remote.origin.pushurl", "https://example.invalid/push-only")
                result = self.resolve({"source": self.source.as_uri() + "#alans-way", "revision": self.SHA})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), self.SHA)

    def test_foreign_ambiguous_and_rewritten_file_origins_stop_without_fallback(self):
        row = {"source": self.source.as_uri() + "#alans-way", "revision": self.SHA}
        valid = "https://github.com/capthvnsen/alans-way-agents"
        for extra in ("https://example.invalid/foreign", ""):
            self.git("config", "--add", "remote.origin.url", extra)
            result = self.resolve(row)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.git("config", "--unset-all", "remote.origin.url")
            self.git("config", "remote.origin.url", valid)
        self.git("config", "remote.origin.url", "https://example.invalid/foreign")
        self.assertNotEqual(self.resolve(row).returncode, 0)
        self.git("config", "remote.origin.url", valid)
        self.git("config", "url.https://example.invalid/foreign.insteadOf", valid)
        result = self.resolve(row)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("example.invalid", result.stderr)

    def test_untrusted_sources_or_malformed_revisions_never_use_tag_fallback(self):
        for source in ("https://github.com/other/repo", "file://remote/path#alans-way", "file:///missing#alans-way"):
            result = self.resolve({"source": source, "revision": self.SHA})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
        for revision in ("v0.21.5", "a" * 39, ""):
            result = self.resolve({"source": self.source.as_uri(), "revision": revision})
            self.assertNotEqual(result.returncode, 0)
        result = self.resolve({"source": "https://github.com/capthvnsen/alans-way-agents#alans-way", "revision": self.SHA})
        self.assertEqual(result.stdout.strip(), self.SHA)

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
