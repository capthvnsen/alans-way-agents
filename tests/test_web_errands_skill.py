"""web-errands skill regression tests: gated commits, reasoned handback, cron checks."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
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
            "summary, amount, currency, counterparty}`",
            self.normalized,
        )
        for phrase in ("`declined`, `approval_timeout` and `approval_unavailable`",
                       "do not retry it",
                       "never work around the gate",
                       "leaves the last click to the user"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

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
        self.assertIn("a plain `release` still hands the tab over", self.normalized)

    def test_never_solves_a_captcha(self):
        self.assertIn("Never solve a CAPTCHA.", self.normalized)
        for line in re.findall(r"[^.]*[Cc][Aa][Pp][Tt][Cc][Hh][Aa][^.]*\.", self.all_text):
            self.assertTrue(
                re.search(r"[Nn]ever|[Rr]elease|hand", line),
                f"CAPTCHA mention without a handback or refusal: {line!r}")

    def test_never_stores_card_numbers(self):
        self.assertIn("never store a card number", self.normalized)
        self.assertIn("reason:\"payment_details\"", self.recipes)

    def test_compares_at_least_two_sources(self):
        self.assertIn("at least two sources", self.normalized)
        self.assertIn("shipping, tax, fees", self.normalized)

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

    def test_host_choice_follows_the_users_session(self):
        self.assertIn("`host:\"vm\"`", self.normalized)
        self.assertIn("when their own session matters", self.normalized)
        self.assertIn("computer is asleep", self.normalized)

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
