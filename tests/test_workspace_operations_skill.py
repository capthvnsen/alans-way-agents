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

    def test_every_model_uses_refs_before_screenshots(self):
        self.assertIn("same for every Hermes model", self.normalized)
        self.assertIn("workspace_computer_snapshot", self.normalized)
        self.assertIn("{unchanged:true}", self.normalized)
        self.assertIn("since=", self.normalized)
        self.assertIn("desktop tree is the same", self.normalized)
        self.assertIn("When it says `unchanged`, do not snapshot again.", self.normalized)
        self.assertIn("workspace_computer_screenshot", self.normalized)
        self.assertIn("drag a slider or scroll bar to the end point", self.normalized)
        self.assertIn("A drag on a slider sets its value from the end point.", self.normalized)
        self.assertIn("A check box or radio name ends in on or off.", self.normalized)
        self.assertIn("A disabled control's name ends in disabled, so do not press it.", self.normalized)
        self.assertIn("a select name includes the chosen option", self.normalized)
        self.assertIn("a section name ends in open or closed", self.normalized)
        self.assertIn("a selected tab's name ends in selected", self.normalized)
        self.assertIn("the current link's name ends in current", self.normalized)
        self.assertIn("A menu item, option, tree item, slider, or clickable div is listed by its name, so do not screenshot it to find it.", self.normalized)
        self.assertIn("A control inside an open shadow root is listed the same way; a closed root is not readable.", self.normalized)
        self.assertIn("A control inside a same-origin frame is listed by its name. A cross-origin frame is not readable.", self.normalized)
        self.assertIn("A control whose text lives in aria-labelledby uses that text as its name, so do not screenshot it to read the label.", self.normalized)
        self.assertIn("A pressed toggle's name ends in on or off, so do not screenshot it to see the state.", self.normalized)
        self.assertIn("A click, type, press, scroll, navigate, or batch result includes elements for up to 40 controls and no page text.", self.normalized)
        self.assertIn("When it says unchanged, the controls you already have are still valid, so do not snapshot again.", self.normalized)
        self.assertIn("`type` replaces the text of a ref and does not send keystrokes.", self.normalized)
        self.assertIn("Do not screenshot a window you can already read as names and refs.", self.normalized)
        self.assertIn("Never screenshot a page you can already read as text.", self.normalized)
        self.assertIn("do not move the human's cursor", self.normalized)

    def test_skill_names_the_tools_the_connector_exposes(self):
        for name in [
            "cua_alans_way_status",
            "cua_alans_way_tabs",
            "cua_alans_way_open",
            "cua_alans_way_snapshot",
            "cua_alans_way_screenshot",
            "cua_alans_way_action",
            "cua_alans_way_close",
        ]:
            with self.subTest(name=name):
                self.assertIn(name, self.text)
        for stale in [
            "workspace_browser_open",
            "workspace_browser_snapshot",
            "workspace_browser_screenshot",
            "workspace_browser_action",
            "workspace_vps_browser",
        ]:
            with self.subTest(stale=stale):
                self.assertNotIn(stale, self.text)
        desktop = (SKILL_PATH.parent / "references" / "vps-desktop.md").read_text(encoding="utf-8")
        self.assertIn("cua_alans_way_snapshot", desktop)
        self.assertIn("workspace_computer_action", desktop)
        self.assertIn("does not move the pointer", desktop)
        self.assertNotIn("workspace_vps_browser", desktop)
        self.assertNotIn("Cua Driver", desktop)

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
        self.assertIn("Do not pass `host`.", self.normalized)
        self.assertIn("When status shows the VPS, the Mac is unreachable", self.normalized)
        self.assertNotIn("must keep running after the Mac sleeps", self.normalized)
        self.assertIn("continue the task on the VPS", self.normalized)
        self.assertIn("Open the same URL with `cua_alans_way_open`", self.normalized)
        self.assertIn("If the `[workspace]` line names a page, open that URL.", self.normalized)
        self.assertIn("API, MCP, and connector calls that do not run on the Mac keep going.", self.normalized)
        self.assertIn("A closed laptop does not stop them.", self.normalized)
        self.assertIn("A closed laptop is not this handoff.", self.normalized)
        self.assertNotIn("do not improvise on the VPS", self.normalized)
        self.assertNotIn("explicit `host: vps` open", self.normalized)

    def test_human_has_control_asks_before_claim(self):
        self.assertIn('action:"claim"', self.normalized)
        self.assertIn("ask the user before", self.normalized)
        # A human-controlled tab is never claimed silently — not for reach
        # and not to reuse a login that only exists there.
        self.assertNotIn("do not wait, ask, or describe a handoff", self.normalized)
        self.assertNotIn("only exists there", self.normalized)

    def test_bounded_snapshot_and_screenshot_params_documented(self):
        # Snapshots must stay cheap: bound the payload, re-check by
        # generation, and reach for pixels only when the DOM cannot answer.
        for param in [
            "maxChars",
            "maxElements",
            "since=",
            "{unchanged:true}",
            "format",
            "quality",
            "maxWidth",
        ]:
            with self.subTest(param=param):
                self.assertIn(param, self.normalized)


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
        self.assertIn("freshMacState(macStateFile)", self.source)
        self.assertIn("pendingRequests.size", self.source)
        self.assertIn("re-probes and routes to it", self.source)
        self.assertIn("onlineStreak >= 2", self.source)
        self.assertIn("script replaced — exiting so the next connection loads it", self.source)

    def test_probe_mode_exists(self):
        self.assertIn("--probe", self.source)

    def test_both_ssh_calls_reuse_a_control_master(self):
        # The probe and the backend spawn each paid a full ssh handshake —
        # ~4.5s of warmup on every lazy respawn. A shared ControlMaster
        # socket makes the spawn's handshake nearly free.
        self.assertIn("ControlMaster=auto", self.source)
        self.assertIn("ControlPersist=120", self.source)
        self.assertIn("wsr-%C", self.source)
        self.assertGreaterEqual(self.source.count("...sshControlArgs"), 2)

    def test_fresh_offline_state_skips_the_probe(self):
        # A fresh mac-watch "offline" verdict must short-circuit to the VPS
        # leg — the watcher already paid the ssh timeout, so probing again
        # just adds seconds per respawn while the Mac is down.
        self.assertIn("freshMacState(macStateFile)", self.source)
        self.assertIn("macSeen.state === 'offline'", self.source)


class ConnectorSelfHealSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normalized = _normalized(SKILL_PATH.read_text(encoding="utf-8"))

    def test_self_heal_section_present(self):
        self.assertIn("connector layer self-heals", self.normalized.lower())

    def test_retry_once_then_report(self):
        self.assertIn("retry once", self.normalized)
        self.assertIn("report the failure in one line and stop", self.normalized)
        self.assertIn("exits after the current call", self.normalized)

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
