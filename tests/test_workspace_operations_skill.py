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


if __name__ == "__main__":
    unittest.main()
