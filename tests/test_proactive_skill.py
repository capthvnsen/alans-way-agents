"""Offline content contracts, not runtime/model/delivery certification."""
from pathlib import Path
import ast
import json
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "alans-way" / "skills" / "proactive-primary" / "SKILL.md"
REFERENCES = SKILL.parent / "references"
DOCS = ROOT / "docs" / "proactivity.md"


def reference(name):
    return (REFERENCES / name).read_text(encoding="utf-8")


def flat(text):
    return " ".join(text.split())


class ProactiveSkillTests(unittest.TestCase):
    def skill(self):
        self.assertTrue(SKILL.is_file(), "The plugin-bundled task skill must exist")
        return SKILL.read_text(encoding="utf-8")

    def test_chat_adjustments_use_durable_explicit_controls_with_readback(self):
        content = reference("controls.md")
        calls = re.findall(r'proactive_control\(action="([a-z_]+)"', content)
        self.assertTrue({"status", "pause", "configure", "review"}.issubset(calls))
        for requirement in (
            "quiet_start", "quiet_end", "max_daily_wakes", "min_interval_seconds",
            "$HERMES_HOME/companion/proactivity", "ordinary chat", "priorities",
            "schema", "read back", "survives restart", "general memory",
            "Never automatically resume", "unsupported", "/proactivity", "operator-only",
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(requirement in flat(content), f"Missing contract: {requirement}")
        self.assertIn("alans-way:proactive-primary", self.skill())

    def test_review_is_ordered_evidence_backed_and_owner_routed(self):
        content = self.skill()
        self.assertIn("## Procedure", content)
        headings = re.findall(r"(?m)^\d+\. \*\*([^*]+)\*\*", content)
        self.assertEqual(headings, [
            "Load live policy.", "Inspect relevant evidence.", "Resolve ownership.",
            "Choose one useful outcome.", "Execute one bounded chunk.",
            "Record, verify, and route.",
        ])
        for requirement in (
            "native memory", "schedule", "goals", "approved tasks", "bound session",
            "bound conversation", "existing delegation", "another owner", "no-op",
            "20 minutes", "cronjob", "session_search", "Kanban",
            "record_task", "finish_task", "artifact", "verification", "next action",
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(requirement in " ".join(content.split()), f"Missing contract: {requirement}")
        self.assertNotIn("## Routing Table", content)

    def test_specialist_followup_is_finite_and_does_not_start_a_ping_loop(self):
        content = reference("signals.md")
        self.assertIn("## Specialist follow-up", content)
        for requirement in (
            "delegate_task", "finite independent", "existing owner", "task id",
            "result summary", "verify the artifact", "awaiting-approval",
            "No recursive delegation", "polling loop", "re-delegation",
            "unchanged checkpoint", "replace the primary",
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(requirement in flat(content), f"Missing contract: {requirement}")
        self.assertIn("signals.md", self.skill())

    def test_silence_is_the_default_and_limits_are_ceilings(self):
        content = self.skill()
        self.assertIn("## Silence", content)
        for requirement in (
            "reply with exactly `[SILENT]`", "ceilings, not quotas", "No catch-up",
            "own ledger writes", "Never retry an uncertain queued wake",
            "acceptance is not turn completion or platform delivery",
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(requirement in flat(content), f"Missing contract: {requirement}")
        for number in ("America/Denver", "22:00", "at most 3"):
            self.assertNotIn(number, content, "Defaults belong in docs/proactivity.md")

    def test_approval_and_privacy_boundaries_are_explicit_not_a_sandbox_claim(self):
        content = self.skill()
        self.assertIn("## Approvals and Safety", content)
        for requirement in (
            "Ask before", "external messages or posts", "purchases", "credential or permission",
            "production changes", "destructive actions", "new scopes", "Third-party",
            "secrets", "other profiles", "raw specialist chats", "not a sandbox",
            "native broad tools", "native core", "## Verification",
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(requirement in flat(content), f"Missing contract: {requirement}")

    def test_reviewer_required_rules_stay_in_the_core_skill(self):
        content = flat(self.skill())
        for requirement in (
            "`resume`, raising the level or a limit, shortening quiet hours and changing the timezone are operator-only",
            "ask the user before `claim`", "`human_has_control`",
            "You may only propose a watch", "/watch approve <id>",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, content)
        self.assertIn("/watch approve <id>", flat(reference("watches.md")))
        self.assertNotIn('"approved"', reference("watches.md"))

    def test_core_skill_stays_small_and_loads_detail_on_demand(self):
        content = self.skill()
        self.assertLessEqual(len(content.splitlines()), 130)
        self.assertLessEqual(len(content.split()), 1300)
        linked = set(re.findall(r"`([a-z]+\.md)`", content))
        self.assertEqual(linked, {path.name for path in REFERENCES.glob("*.md")})
        self.assertIn("skill_view(", content)
        for forbidden in ("gateway-owner.json", "HOOK.yaml", "PID"):
            self.assertNotIn(forbidden, content)
        prompts = (ROOT / "alans-way" / "__init__.py").read_text(encoding="utf-8")
        for name in set(re.findall(r"references/([a-z]+\.md)", prompts)):
            self.assertTrue((REFERENCES / name).is_file(), name)

    def test_public_docs_explain_reviewable_install_binding_and_limits(self):
        self.assertTrue(DOCS.is_file(), "A concise public proactivity guide must exist")
        content = DOCS.read_text(encoding="utf-8")
        for requirement in (
            "$HERMES_HOME/plugins/alans-way", "hermes plugins enable alans-way",
            "plugins:", "enabled:", "entries:", "allow_gateway_injection: true",
            "fragment", "Do not replace", "existing", "session_key", "default",
            "alans-way:proactive-primary", "/proactivity", "proactive_control",
            "$HERMES_HOME/companion/proactivity", "22:00–08:00", "America/Denver",
            "upper limits, not quotas", "zero model turns", "not a sandbox",
            "acceptance is not turn completion or platform delivery", "Do not retry",
            "Mac/phone", "Content tests", "test_proactive_skill.py",
        ):
            with self.subTest(requirement=requirement):
                self.assertTrue(requirement in " ".join(content.split()), f"Missing contract: {requirement}")
        self.assertLessEqual(len(content), 16_000, "Keep the public guide concise")

    def test_docs_lead_with_the_two_knobs_and_do_not_oversell_approval(self):
        content = flat(DOCS.read_text(encoding="utf-8"))
        self.assertLess(content.index("## The two knobs"), content.index("## Review and enable"))
        for requirement in ("/proactivity level quiet|normal|eager", "/proactivity quiet 22-8",
                            "/proactivity snooze 3d", "/proactivity log", "Approve", "Snooze 1d", "Dismiss",
                            "policy boundary, not a sandbox", "operator-only through Hermes's command surfaces"):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, content)
        self.assertNotIn("Approval is yours alone", content)

    def test_native_startup_hook_is_separate_trusted_optin_not_cli_dispatch(self):
        self.assertTrue(DOCS.is_file())
        for path in (DOCS,):
            content = " ".join(path.read_text(encoding="utf-8").split())
            for requirement in (
                "gateway:startup", "HOOK.yaml", "handler.py", "trusted by placement",
                "plugins.enabled", "gateway-owner.json", "CLI/doctor", "pre_gateway_dispatch",
                "before authentication", "no automatic retarget",
            ):
                with self.subTest(path=path.name, requirement=requirement):
                    self.assertTrue(requirement in content, f"Missing contract: {requirement}")

    def test_documented_frontend_commands_and_tool_examples_are_actionable(self):
        for path in (REFERENCES / "controls.md", REFERENCES / "watches.md", DOCS):
            content = path.read_text(encoding="utf-8")
            if path.name != "watches.md":
                for action in ("status", "pause", "resume", "review"):
                    with self.subTest(path=path.name, action=action):
                        self.assertTrue(f"/proactivity {action}" in content,
                                        f"Missing frontend command: {action}")
                configure = re.findall(r'/proactivity configure (\{[^`\n]+\})', content)
                self.assertTrue(configure, "Show an actual configure JSON command")
                for payload in configure:
                    self.assertIsInstance(json.loads(payload), dict)
            examples = re.findall(r"```python\n(.*?)\n```", content, re.DOTALL)
            self.assertTrue(examples, "Show literal Hermes tool invocations")
            for example in examples:
                tree = ast.parse(example)
                for statement in tree.body:
                    self.assertIsInstance(statement, ast.Expr)
                    call = statement.value
                    self.assertIsInstance(call, ast.Call)
                    self.assertIsInstance(call.func, ast.Name)
                    self.assertEqual(call.func.id, "proactive_control")
                    self.assertFalse(call.args, "Use explicit tool keyword arguments")
                    arguments = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords}
                    self.assertIn(arguments["action"], {
                        "status", "pause", "resume", "configure", "review",
                        "record_task", "finish_task", "report_signal", "level",
                    })
                    if arguments["action"] == "configure":
                        self.assertIsInstance(arguments["settings"], dict)
                        self.assertTrue(arguments["settings"], "An empty change is not an example")
                    if arguments["action"] == "record_task":
                        self.assertNotIn("approved", arguments["task"], "The bot only proposes")

    def test_consent_is_rechecked_at_action_and_reporting_boundaries(self):
        content = flat(self.skill())
        self.assertIn("Recheck policy and task consent before working and before reporting", content)
        self.assertIn("stop if paused, cancelled or awaiting approval", content)
        self.assertIn("a no-purpose review ends silently", content)

    def test_offline_mac_keeps_web_and_api_work_moving(self):
        content = flat(reference("signals.md"))
        self.assertIn("Web work in progress continues on the VPS browser", content)
        self.assertIn("the connector opens the last page there when the Mac drops", content)
        self.assertIn("API, MCP and connector calls that do not run on the Mac keep going", content)

    def test_frontmatter_is_a_portable_human_credited_skill_contract(self):
        content = self.skill()
        self.assertTrue(content.startswith("---\n"))
        frontmatter, separator, body = content[4:].partition("\n---\n")
        self.assertTrue(separator, "Frontmatter must close before the body")
        self.assertTrue(body.strip(), "The skill must have an actionable body")
        fields = dict(re.findall(r"^([a-z_]+): (.+)$", frontmatter, re.MULTILINE))
        self.assertEqual(fields["name"], "proactive-primary")
        self.assertRegex(fields["name"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        self.assertLessEqual(len(fields["name"]), 64)
        description = json.loads(fields["description"])
        self.assertIsInstance(description, str)
        self.assertTrue(description.strip())
        self.assertLessEqual(len(description), 60)
        self.assertTrue(description.endswith("."))
        self.assertEqual(description.count("."), 1)
        self.assertNotIn(fields["name"], description.casefold())
        self.assertRegex(fields["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(fields["author"], "capthvnsen, Hermes Agent")
        self.assertEqual(fields["license"], "MIT")
        self.assertEqual(fields["platforms"], "[linux, macos]")
        self.assertRegex(frontmatter, r"(?m)^metadata:\n  hermes:\n")
        self.assertRegex(frontmatter, r"(?m)^    tags: \[[^\n]+\]$")
        self.assertRegex(frontmatter, r"(?m)^    related_skills: \[\]$")
        self.assertLessEqual(len(content), 100_000)


if __name__ == "__main__":
    unittest.main()
