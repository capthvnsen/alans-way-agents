"""workspace-setup skill regression tests: agents must drive setup.sh, not improvise."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "alans-way" / "skills" / "workspace-setup" / "SKILL.md"


def _normalized(text: str) -> str:
    return " ".join(text.split())


class WorkspaceSetupSkillTests(unittest.TestCase):
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

    def test_idempotent_and_verify_documented(self):
        self.assertIn("idempotent", self.normalized)
        self.assertIn("--verify", self.normalized)

    def test_display_stack_is_guided_not_auto(self):
        self.assertIn("never auto-installed", self.normalized)

    def test_primary_binding_not_silent(self):
        self.assertIn("do not bind a different bot's route silently", self.normalized)

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


if __name__ == "__main__":
    unittest.main()
