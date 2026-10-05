"""workspace-operations skill wording regression tests."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "alans-way" / "skills" / "workspace-operations" / "SKILL.md"


def _normalized(text: str) -> str:
    return " ".join(text.split())


class WorkspaceOperationsSkillPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.normalized = _normalized(cls.text)

    def test_ordinary_actions_are_preauthorized(self):
        self.assertIn(
            "Ordinary actions in a bot-owned in-app browser tab are preauthorized and "
            "require no extra browser permission prompt: navigation, typing, forms, "
            "upload/download, research, and normal account work.",
            self.normalized,
        )

    def test_no_separate_browser_permission_prompt(self):
        self.assertIn(
            "require no extra browser permission prompt",
            self.normalized,
        )

    def test_ordinary_actions_listed(self):
        for action in [
            "navigation",
            "typing",
            "forms",
            "upload/download",
            "research",
            "normal account work",
        ]:
            with self.subTest(action=action):
                self.assertIn(action, self.normalized)

    def test_never_ask_merely_to_use_browser(self):
        self.assertIn("Never ask merely to use the browser.", self.normalized)

    def test_native_approval_mandatory_actions_listed(self):
        self.assertIn(
            "Native Hermes approval remains mandatory for sending external messages/posts, "
            "purchases, bookings, deletions, financial actions, credential/permission "
            "changes, destructive actions, and production changes.",
            self.normalized,
        )

    def test_ownership_control_epoch_and_human_takeover_gates_remain(self):
        self.assertIn(
            "Ownership, control epoch, and human takeover gates remain.",
            self.normalized,
        )

    def test_in_app_browser_is_the_only_default_host(self):
        self.assertIn(
            "The in-app Mac browser is the only default host.",
            self.normalized,
        )

    def test_no_alternate_browser_paths_when_mac_reachable(self):
        for forbidden in [
            'host:"vps"',
            "browser_exec",
            "personal browser",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertIn(forbidden, self.normalized)
        self.assertIn("do not silently substitute another browser", self.normalized)

    def test_human_has_control_claim_not_wait(self):
        self.assertIn('action:"claim"', self.normalized)
        self.assertIn("do not wait, ask, or describe a handoff", self.normalized)


ROUTER_PATH = ROOT / "alans-way" / "scripts" / "workspace-router.cjs"


class WorkspaceRouterRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ROUTER_PATH.read_text(encoding="utf-8")

    def test_no_dangling_macup_reference(self):
        # The probe returns the resolved script path (macScript); a leftover
        # macUp reference crashes the router after spawn and kills the session.
        self.assertNotIn("macUp", self.source)
        self.assertIn("macScript ? 'mac' : 'vps'", self.source)

    def test_probe_joins_items_with_separator(self):
        # join(' ') produces `fi if` — a bash syntax error that makes every
        # Mac probe fail and silently pins all traffic to the VPS host.
        self.assertIn(".join('; ')", self.source)
        self.assertIn("+ '; exit 1'", self.source)


if __name__ == "__main__":
    unittest.main()
