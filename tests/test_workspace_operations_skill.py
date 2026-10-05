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

    def test_probe_verifies_app_liveness(self):
        # File existence alone routes to a closed app — a dead host. The
        # probe must also prove the workspace API answers on the Mac.
        self.assertIn("connection.json", self.source)
        self.assertIn("curl -s -m 4 -o /dev/null", self.source)
        self.assertIn("/status", self.source)

    def test_candidate_failure_falls_through(self):
        # A candidate bundle that exists but is not live must skip to the
        # next candidate, not abort the whole probe — liveness is a { … }
        # group inside the if condition, not an early exit.
        self.assertIn("{ conn=", self.source)
        self.assertNotIn("|| exit 1", self.source)

    def test_annotation_failure_degrades_to_passthrough(self):
        # A one-line ReferenceError in annotation setup dropped the whole
        # browser surface. Setup failures must degrade to passthrough.
        self.assertIn("annotator disabled", self.source)
        self.assertIn("(line) => line", self.source)

    def test_router_self_heals_host_drift(self):
        # A router that landed on the VPS during a transient probe miss must
        # exit once mac-watch reports the Mac online — Hermes lazy-respawns
        # the connector and the respawn re-probes, converging on the Mac
        # without any manual process surgery.
        self.assertIn("!macScript && macSsh", self.source)
        self.assertIn("readMacState(macStateFile)", self.source)
        self.assertIn("re-probes and routes to it", self.source)
        self.assertIn("onlineStreak >= 2", self.source)

    def test_probe_mode_exists(self):
        self.assertIn("--probe", self.source)


class ConnectorSelfHealSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normalized = _normalized(SKILL_PATH.read_text(encoding="utf-8"))

    def test_self_heal_section_present(self):
        self.assertIn("connector layer self-heals", self.normalized.lower())

    def test_retry_once_then_report(self):
        self.assertIn("retry once", self.normalized)
        self.assertIn("report the failure in one line and stop", self.normalized)

    def test_no_connector_surgery(self):
        self.assertIn("Never repair the connector layer yourself", self.normalized)
        for forbidden in [
            "kill connector/router processes",
            "hermes mcp test",
            "restart the gateway",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertIn(forbidden, self.normalized)


if __name__ == "__main__":
    unittest.main()
