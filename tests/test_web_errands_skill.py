"""web-errands skill regression tests: gated commits, reasoned handback, cron checks."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import json
import os
import shutil
import subprocess
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "alans-way"
SKILL_DIR = PLUGIN / "skills" / "web-errands"
SKILL_PATH = SKILL_DIR / "SKILL.md"
RECIPES_PATH = SKILL_DIR / "references" / "recipes.md"

# The only tools the skill may name: the workspace browser set, Hermes'
# approval-gated desktop tool, the Hermes scheduler and its deferred-tool
# dispatcher. Anything else — a deleted proactivity tool, a raw MCP action,
# another browser driver — is a regression.
EXISTING_TOOLS = {
    "cua_alans_way_status",
    "cua_alans_way_tabs",
    "cua_alans_way_open",
    "cua_alans_way_snapshot",
    "cua_alans_way_screenshot",
    "cua_alans_way_action",
    "cua_alans_way_close",
    "computer_use",
    "cronjob_manage",
    "tool_call",
}


def _normalized(text: str) -> str:
    return " ".join(text.split())


def _tool_mentions(text: str) -> set:
    """Backticked identifiers that read as callable tool names."""
    names = set()
    for token in re.findall(r"`([A-Za-z][A-Za-z0-9_]*(?:__[A-Za-z0-9_]+)*)`", text):
        token = re.sub(r"^[A-Za-z][A-Za-z0-9_]*__", "", token)
        if (token.startswith(("cua_alans_way_", "workspace_computer_", "browser_"))
                or token.endswith(("_manage", "_use", "_control", "_driver",
                                   "_exec", "_call"))):
            names.add(token)
    return names


def _register_calls():
    """Run the plugin's register() against a fake ctx and capture skill regs."""
    name = "alans_way_errands_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    calls = []
    state = {}
    ctx = SimpleNamespace(
        profile_name="default",
        state=SimpleNamespace(get=state.get, set=lambda k, v: state.__setitem__(k, v)),
        register_tool=lambda **kw: calls.append(("tool", kw["name"])),
        register_hook=lambda hook, fn: calls.append(("hook", hook)),
        register_skill=lambda skill, path: calls.append(("skill", skill, path)),
        register_command=lambda cmd, fn, **kw: calls.append(("command", cmd)),
        on_unload=lambda fn: calls.append(("unload",)),
    )
    with tempfile.TemporaryDirectory() as d:
        module.register(ctx, legacy_home=d, background=False)
    return calls


class WebErrandsSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.normalized = _normalized(cls.text)
        cls.recipes = RECIPES_PATH.read_text(encoding="utf-8")
        cls.recipes_normalized = _normalized(cls.recipes)
        cls.all_text = cls.text + "\n" + cls.recipes

    def test_has_valid_frontmatter(self):
        match = re.match(r"^---\n(.*?)\n---\n", self.text, re.DOTALL)
        self.assertIsNotNone(match, "SKILL.md must start with frontmatter")
        self.assertIn("name: web-errands", match.group(1))
        self.assertIn("description:", match.group(1))

    def test_the_skill_is_registered_and_loads(self):
        skills = {call[1]: call[2] for call in _register_calls()
                  if call[0] == "skill"}
        self.assertIn("web-errands", skills)
        self.assertEqual(Path(skills["web-errands"]), SKILL_PATH)
        self.assertTrue(SKILL_PATH.is_file())
        self.assertTrue(RECIPES_PATH.is_file())

    def test_names_only_tools_that_exist(self):
        mentioned = _tool_mentions(self.all_text)
        self.assertEqual(mentioned - EXISTING_TOOLS, set())
        for required in ("cua_alans_way_action", "cua_alans_way_screenshot",
                         "cronjob_manage"):
            self.assertIn(required, mentioned)

    @unittest.skipUnless(os.environ.get("ALANS_WAY_APP"),
                         "set ALANS_WAY_APP to an app checkout for cross-repo schema drift")
    def test_tools_and_release_reasons_match_app_schema(self):
        # Release enums belong to the app connector, not the plugin router.
        # Run this against a detached origin/main checkout when refreshing N4.
        connector = (Path(os.environ["ALANS_WAY_APP"]) / "desktop" / "scripts"
                     / "browser-mcp.cjs").read_text()
        actual_tools = set(re.findall(r"name: '(cua_alans_way_[a-z_]+)'", connector))
        mentioned = {name for name in _tool_mentions(self.all_text)
                     if name.startswith("cua_alans_way_")}
        self.assertEqual(mentioned - actual_tools, set())
        match = re.search(r"reason: \{ type: 'string', enum: \[(.*?)\]", connector)
        self.assertIsNotNone(match)
        reasons = set(re.findall(r"'([a-z_]+)'", match.group(1)))
        documented = set(re.findall(r'reason:\s*"([a-z_]+)"', self.all_text))
        # Plain backticked alternatives in the handback paragraph count too.
        section = self.text.split("## The walls you hand back")[1].split("## Verify")[0]
        documented.update(re.findall(r"`([a-z_]+)`", section))
        documented -= {"note", "awaiting_human", "human_returned", "challenge_present"}
        self.assertTrue(documented)
        self.assertEqual(documented - reasons, set())

    def test_deleted_proactivity_tools_are_never_mentioned(self):
        for deleted in ("proactive_control", "watch_manage", "record_task",
                        "`watch`", "/watch", "proactive-primary"):
            with self.subTest(deleted=deleted):
                self.assertNotIn(deleted, self.all_text)
        for path in (SKILL_PATH, RECIPES_PATH):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"\bsweep\b")
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"\bwatch_")

    def test_commit_step_uses_the_gate(self):
        self.assertIn(
            "`{kind: purchase|booking|send|post|submit|delete|account_change, "
            "summary, amount?, currency?, counterparty?}`",
            self.normalized,
        )
        for phrase in ("`declined`, `approval_timeout` and `approval_unavailable`",
                       "do not retry it",
                       "never work around the gate",
                       "leaves the last click to the user"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_shared_operations_are_linked(self):
        links = re.findall(r"\]\(([^)]+workspace-operations[^)]*)\)", self.text)
        self.assertTrue(links, "link to the shared operations skill")
        for link in links:
            self.assertTrue((SKILL_DIR / link.split("#")[0]).resolve().is_file())

    def test_documented_refusals_exist_in_the_router(self):
        router = (PLUGIN / "scripts" / "workspace-router.cjs").read_text()
        # Read literal refusal prefixes, including template-string refusals;
        # do not maintain a second allowlist that could drift with the docs.
        actual = set(re.findall(r"['`\"]([a-z_]+): ", router))
        mentioned = {token for token in re.findall(r"`([a-z_]+)`", self.all_text)
                     if token.endswith(("_required", "_invalid", "_changed", "_present"))
                     or token.startswith("approval_")
                     or token in {"declined", "awaiting_human", "human_returned"}}
        self.assertTrue(mentioned)
        self.assertEqual(mentioned - actual, set())
        for code in ("commit_required", "commit_invalid", "snapshot_required",
                     "host_changed", "page_changed", "challenge_present"):
            self.assertIn(code, mentioned)

    def test_commit_fields_and_kinds_match_router_schema(self):
        router = (PLUGIN / "scripts" / "workspace-router.cjs").read_text()
        verbs = re.search(r"const COMMIT_VERBS = \{(.*?)\n\};", router, re.S).group(1)
        actual_kinds = re.findall(r"^  ([a-z_]+):", verbs, re.M)
        schema = re.search(r"props.commit = \{(.*?)\n    \};", router, re.S).group(1)
        fields = re.findall(r"^        ([a-z_]+):", schema, re.M)
        required = re.search(r"required: \[(.*?)\]", schema).group(1)
        required = re.findall(r"'([a-z_]+)'", required)
        documented = re.search(r"`\{kind: ([^}]+)\}`", self.normalized).group(1)
        kinds, *optional = documented.split(", ")
        self.assertEqual(kinds.split("|"), actual_kinds)
        self.assertEqual(["kind"] + [f.rstrip("?") for f in optional], fields)
        self.assertEqual(["kind"] + [f for f in optional if not f.endswith("?")], required)
        max_length = re.search(r"summary:.*?maxLength: (\d+)", schema).group(1)
        self.assertIn(f"1–{max_length} characters", self.normalized)
        self.assertIn("strings", self.normalized)
        self.assertIn("Never supply `approval`", self.normalized)

    @unittest.skipUnless(shutil.which("node"), "node is required to check Unicode commit patterns")
    def test_documented_commit_controls_match_shared_patterns(self):
        match = re.search(r"Commit-name examples: (.*?)\.", self.normalized)
        self.assertIsNotNone(match, "document the commit controls used by the recipes")
        examples = match.group(1)
        names = re.findall(r'"([^"\n]+)"', examples)
        # Include the application recipe's claim as well as the skill examples.
        names += re.findall(r'"(Easy Apply|Submit application)"', self.recipes)
        self.assertGreaterEqual(len(names), 3)
        router = PLUGIN / "scripts" / "workspace-router.cjs"
        script = """
const fs = require('node:fs'), path = require('node:path');
const file = process.argv[1], names = JSON.parse(process.argv[2]);
const source = fs.readFileSync(file, 'utf8');
const start = source.indexOf('const COMMIT_PATTERNS =');
const end = source.indexOf('// A selector read as words:', start);
const check = new Function('require', 'path', '__dirname', 'names',
  source.slice(start, end) + '; return names.map(isCommitName);');
process.stdout.write(JSON.stringify(check(require, path, path.dirname(file), names)));
"""
        result = subprocess.run([shutil.which("node"), "-e", script, str(router),
                                 json.dumps(names)], capture_output=True, text=True,
                                timeout=10, check=True)
        self.assertEqual(json.loads(result.stdout), [True] * len(names))

    def test_echo_before_commit_covers_the_decision(self):
        for detail in ("the dates", "the party size",
                       "the total with fees and shipping", "recipient"):
            with self.subTest(detail=detail):
                self.assertIn(detail, self.normalized)
        self.assertIn("read off the page", self.normalized)

    def test_walls_release_with_a_reason(self):
        self.assertIn('{action:"release", reason:"captcha"}', self.normalized)
        for reason in ("login", "two_factor", "payment_details"):
            with self.subTest(reason=reason):
                self.assertIn(reason, self.normalized)
        self.assertIn("`note`", self.normalized)
        self.assertIn("awaiting_human", self.normalized)
        self.assertIn("On the user's computer", self.normalized)
        self.assertIn("On the VPS", self.normalized)
        self.assertIn("does not hold the tab", self.normalized)
        self.assertIn("140 characters", self.normalized)
        self.assertIn("[CAPTCHA handback]", self.text)
        self.assertIn("human_returned", self.normalized)

    def test_never_solves_a_captcha(self):
        self.assertIn("Never solve a CAPTCHA.", self.normalized)
        # Sentence boundaries apply to prose, not dots in Markdown link URLs.
        prose = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", self.all_text)
        for line in re.findall(r"[^.]*[Cc][Aa][Pp][Tt][Cc][Hh][Aa][^.]*\.", prose):
            self.assertTrue(
                re.search(r"[Nn]ever|[Rr]elease|hand", line),
                f"CAPTCHA mention without a handback or refusal: {line!r}")

    def test_never_stores_card_numbers(self):
        self.assertIn("never store a card number", self.normalized)
        self.assertIn("reason:\"payment_details\"", self.recipes)

    def test_compares_at_least_two_sources(self):
        self.assertIn("at least two sources", self.normalized)
        self.assertIn("shipping, tax, fees", self.normalized)
        comparison = self.normalized.split("## Compare before you commit")[1].split(
            "## Stage, then commit")[0]
        for detail in ("comparison in chat before requesting approval",
                       "`commit.summary`", "chosen source",
                       "total with fees and shipping", "runner-up if it matters",
                       "at most 200 characters", "appear on the approval card"):
            with self.subTest(detail=detail):
                self.assertIn(detail, comparison)
        for text in (self.normalized, self.recipes_normalized):
            self.assertNotIn("so the approval shows the comparison", text)

    def test_confirmation_and_telegram_receipt(self):
        self.assertIn("capture the order, booking or reference number", self.normalized)
        self.assertIn("`cua_alans_way_screenshot` of the confirmation", self.normalized)
        self.assertIn("Telegram receipt", self.normalized)
        self.assertIn("never claim success the page did not show", self.normalized)

    def test_watches_are_cron_with_polling_limits(self):
        self.assertIn("a Hermes cron job", self.normalized)
        self.assertIn("no more often than every 10 minutes", self.normalized)
        self.assertIn("back off", self.normalized)
        self.assertIn("stop on success", self.normalized)
        self.assertIn("A cron run has no one to answer an approval", self.normalized)
        self.assertIn("self-contained prompt", self.normalized)
        self.assertIn("three consecutive failures", self.normalized)
        self.assertIn("`cron.allow_agent_scheduling: true`", self.normalized)

    def test_host_choice_follows_the_users_session(self):
        self.assertIn("`host:\"vm\"`", self.normalized)
        self.assertIn("when their own session matters", self.normalized)
        self.assertIn("computer is asleep", self.normalized)

    def test_watches_use_continuity_and_conditional_change_detection(self):
        watch = self.normalized.split("## A watch is a cron job")[1]
        for rule in ('"continuity": true', "previous completed output",
                     "reply exactly `[SILENT]`", "only when the user asks",
                     "or accepts your offer", "`attach_to_session` true",
                     "omit `deliver`", '"monitor": "https://example.com/status.json"',
                     "safe, read-only deterministic probe",
                     "matches the condition the user asked to watch",
                     "omit `monitor`", "no timestamps",
                     "first tick runs the agent", "first check report a compact baseline",
                     "continuity skips silent outputs", "unchanged output skips",
                     "changed output gives the agent a diff", "a check failed",
                     "source failure is an error"):
            with self.subTest(rule=rule):
                self.assertIn(rule, watch)

    def test_application_records_use_the_users_chosen_place(self):
        applications = self.recipes_normalized.split("## Job applications")[1].split("## Forms")[0]
        self.assertIn("in the user's chosen project or task record", applications)
        self.assertNotIn("in memory", applications)

    def test_recipes_cover_the_errand_kinds(self):
        for heading in ("## Shopping and cart comparison",
                        "## Booking and travel",
                        "## Job applications",
                        "## Forms, permits and civic portals",
                        "## Cancellations and refunds",
                        "## Claims pipeline"):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.recipes)
        # Vision inspection, cancellation policy, draft-review-submit and
        # document-driven follow-up are the load-bearing details.
        for detail in ("inspect them for condition", "cancellation policy",
                       "Show the user the draft", "reference or case number",
                       "retention offer", "extract", "stopping on resolution"):
            with self.subTest(detail=detail):
                self.assertIn(detail, self.recipes_normalized)


if __name__ == "__main__":
    unittest.main()
