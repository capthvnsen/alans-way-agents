"""workspace-operations skill wording regression tests."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "alans-way" / "skills" / "workspace-operations" / "SKILL.md"


def _normalized(text: str) -> str:
    return " ".join(text.split())


class WorkspaceOperationsSkillPolicyTests(unittest.TestCase):
    def test_promised_follow_ups_are_saved_jobs_in_this_chat(self):
        section = re.search(r"## Promised follow-ups(.*?)(?:## |\Z)", self.text, re.S)
        self.assertIsNotNone(section)
        policy = _normalized(section.group(1))
        for rule in ("cronjob_manage", "`action` create", "`schedule`", "`prompt`",
                     "when to stop", "`attach_to_session` true", "no `deliver`",
                     "Confirm with the local time in one line",
                     "Never promise a later message without a saved job",
                     '"not yet"', "offer one more at a specific time",
                     "don't schedule repeats they didn't ask for",
                     "Remove the job when its reason goes away"):
            with self.subTest(rule=rule):
                self.assertIn(rule, policy)

    def test_move_is_described_truthfully(self):
        section = re.search(r"## Hand a task between computers(.*?)## ", self.text, re.S)
        self.assertIsNotNone(section)
        policy = _normalized(section.group(1))
        self.assertNotIn("handoff controls are not exposed in its UI", policy)
        for rule in ("Move button", "page address and scroll position",
                     "drafts when they choose", "only when the app reports a restore",
                     "passwords, uploads and in-memory state stay behind",
                     "You have no move tool", "check the destination page and login"):
            with self.subTest(rule=rule):
                self.assertIn(rule, policy)

    def test_browser_scrolling_uses_the_scroll_action(self):
        section = re.search(r"## Operate a browser tab(.*?)## ", self.text, re.S)
        self.assertIsNotNone(section)
        policy = _normalized(section.group(1))
        self.assertIn("use the scroll action", policy)
        self.assertIn("scripts and reloads are refused on pages that show payment or donate buttons", policy)

    def test_connector_recovery_separates_reads_from_uncertain_mutations(self):
        section = re.search(r"## The connector layer self-heals; never operate on it(.*?)## ", self.text, re.S)
        self.assertIsNotNone(section)
        policy = _normalized(section.group(1))
        self.assertNotIn("If a browser tool call errors or the tools seem missing", policy)
        for rule in ("Retry a read-only call once", "uncertain action or control change",
                     "do not repeat", "`cua_alans_way_tabs`", "controller and epoch",
                     "fresh snapshot", "confirmed pre-dispatch missing tab",
                     "approval-bearing calls", "fresh review"):
            with self.subTest(rule=rule):
                self.assertIn(rule, policy)

    def test_offline_continuation_keeps_uncertainty_and_approval_review(self):
        section = re.search(r"## When the Mac goes away mid-task(.*?)## ", self.text, re.S)
        self.assertIsNotNone(section)
        policy = _normalized(section.group(1))
        for rule in ("confirmed pre-dispatch missing tab", "approval-bearing call",
                     "fresh review", "uncertain", "do not repeat",
                     "controller and epoch", "fresh snapshot"):
            with self.subTest(rule=rule):
                self.assertIn(rule, policy)
        self.assertNotIn("A snapshot, screenshot, or action aimed at the Mac tab is carried onto that VPS tab", policy)
        self.assertNotIn("Open the same URL with `cua_alans_way_open` and keep acting", policy)

    def test_cross_host_handoff_preserves_required_human_review(self):
        section = re.search(r"## Hand a task between computers(.*?)## ", self.text, re.S)
        self.assertIsNotNone(section)
        policy = _normalized(section.group(1))
        self.assertNotIn("Do not wait for a human review of the page", policy)
        for rule in ("`review_required`", "wait for human review",
                     "approval-bearing call", "fresh review", "uncertain", "do not repeat"):
            with self.subTest(rule=rule):
                self.assertIn(rule, policy)

    def test_read_optimization_keeps_local_recovery_exceptions(self):
        for title in ("Operate a browser tab", "Spend tokens on structure, not screenshots"):
            with self.subTest(section=title):
                section = re.search(r"## " + re.escape(title) + r"(.*?)## ", self.text, re.S)
                self.assertIsNotNone(section)
                policy = _normalized(section.group(1))
                self.assertIn("successful", policy)
                self.assertIn("Recovery", policy)
                self.assertIn("uncertain", policy)
                self.assertIn("fresh", policy)
                self.assertNotIn("Every action reply carries", policy)
                self.assertNotIn("Do not snapshot or re-read the page after acting", policy)

    def test_finished_tabs_are_closed_only_with_live_ownership_and_control(self):
        section = re.search(r"## Tab hygiene(.*?)## ", self.text, re.S)
        self.assertIsNotNone(section, "finished tasks need a tab cleanup policy")
        policy = _normalized(section.group(1))
        for rule in (
            "When a task finishes, close the tabs you opened for it",
            "say which tabs you kept and why",
            "`requestingBotId`", "`botId` matches `requestingBotId`",
            "`allowedBots` is a grant, not ownership",
            "`controller` is `agent`", "fresh `epoch`",
            "Never close another bot's or the user's tabs",
            "At the tab limit, close your own confirmed finished tabs first",
            "retry opening once", "after `/new` or compaction",
            "do not infer that a tab is finished from its age or URL",
            "If ownership or task status is uncertain, leave the tab alone",
            "Do not claim a tab just to close it",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, policy)

    def test_real_decisions_use_native_clarify_with_text_and_no_approvals(self):
        self.assertIn("Hermes's `clarify` buttons for real decisions the user owns", self.normalized)
        self.assertIn("keep Other/free text possible and never use them for approvals", self.normalized)

    def test_toolbox_provenance_follows_the_running_routers_precedence(self):
        tools = self.normalized.split("- Alan's Tools:", 1)[1].split("- Alan's Workspace:", 1)[0]
        candidates = (
            "`--vps-script`", "`HERMES_WORKSPACE_VPS_MCP`", "sibling `browser-mcp.cjs`",
            "`/opt/hermes-alans-way/browser/desktop/scripts/browser-mcp.cjs`",
            "`~/.local/share/hermes-alans-way/app/desktop/scripts/browser-mcp.cjs`")
        for candidate in candidates:
            self.assertIn(candidate, tools)
        order = [tools.index(needle) for needle in candidates]
        self.assertEqual(order, sorted(order))
        for rule in ("workspace-router.cjs:104", "first existing candidate",
                     "explicit path wins even if it is missing",
                     "Resolve the selected script's symlinks",
                     "git -C <selected-script-directory> rev-parse --show-toplevel",
                     "unavailable", "metadata belongs to the selected script"):
            self.assertIn(rule, tools)

    def test_version_questions_can_discover_the_skill_without_a_browser_task(self):
        description = re.search(r"^description: (.*)$", self.text, re.M).group(1)
        self.assertIn("installed versions", description)

    def test_versions_include_all_components_and_observed_provenance(self):
        for requirement in ("When asked what versions", "hermes --version",
                            "plugin.yaml", ".install-metadata.json", "release SHA",
                            "git -C <toolbox-checkout> describe --tags --always --dirty",
                            "git -C <toolbox-checkout> rev-parse HEAD",
                            "HERMES_WORKSPACE_VPS_MCP", "/opt/hermes-alans-way/browser",
                            "cua_alans_way_status", "`version` and `build`",
                            "A response with `host: vps`", "unavailable",
                            "planned pin is not an observed running version"):
            self.assertIn(requirement, self.normalized)

    @classmethod
    def setUpClass(cls):
        cls.text = SKILL_PATH.read_text(encoding="utf-8")
        cls.normalized = _normalized(cls.text)

    def test_durable_memory_is_saved_during_work_without_transient_browser_state(self):
        for requirement in ("Save durable user facts, decisions and preferences to memory",
                            "as they come up during work", "only in chat history",
                            "Transient tab state, element refs and handback state",
                            "never go into durable memory"):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, self.normalized)

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

    def test_consequential_actions_carry_a_commit_object(self):
        self.assertNotIn("Native Hermes approval remains mandatory", self.normalized)
        self.assertIn(
            "Pass `commit` on the `cua_alans_way_action` call that does it: "
            "`{kind: purchase|booking|send|post|submit|delete|account_change, summary, "
            "amount?, currency?, counterparty?}`",
            self.normalized,
        )
        for phrase in ("the action runs only on Approve",
                       "Put a whole checkout batch under one `commit`.",
                       "`declined`, `approval_timeout` and `approval_unavailable` mean it did not run",
                       "do not retry it or reach the same result another way",
                       "any key other than Tab, an arrow, Escape or a plain character; any click, drag or select by position, on an unnamed control or by a selector that names no commit; and any `eval` or `cdp` call that can act",
                       "`eval` cannot commit: finish a purchase, booking, send, post, submit or delete with a click that carries `commit`",
                       "Typing and then pressing Enter in the same batch needs `commit` too",
                       "Never send `approval` yourself",
                       "It does not stop a deliberately hostile agent that also has terminal or file tools",
                       "Never work around the gate with any tool",
                       "refused with `snapshot_required`, so snapshot first",
                       "Ask the user before any other financial, destructive or production change."):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_automatic_takeover_preserves_holds_and_approval(self):
        for phrase in ("Ownership and control epoch gates remain.",
                       "after the grace period: act or claim",
                       "Awaiting-human, CAPTCHA and recording holds",
                       "Take-back cooldown still keep the bot out",
                       "A commit still needs fresh user approval",
                       "across the automatic takeover exactly once",
                       "Refused actions leave the human's focus, tab owner and control epoch untouched",
                       "With automatic takeover off, follow `human_has_control`"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.normalized)

    def test_supervisord_restart_uses_the_usr1_drain(self):
        """Issue #65: the post-update restart note must route a supervised
        gateway through `signal USR1`, never `supervisorctl restart`."""
        self.assertIn("signal USR1", self.normalized)
        self.assertIn("state.db", self.normalized)

    def test_every_model_uses_refs_before_screenshots(self):
        self.assertIn("same for every Hermes model", self.normalized)
        self.assertIn("workspace_computer_snapshot", self.normalized)
        self.assertIn("{unchanged:true}", self.normalized)
        self.assertIn("since=", self.normalized)
        self.assertIn("approval gate is the only desktop-input path", self.normalized)
        self.assertIn("a successful reply says unchanged, the controls you already have are still valid, so do not snapshot again.", self.normalized)
        self.assertIn("workspace_computer_screenshot", self.normalized)
        self.assertIn("capture` with `app` returns one app's numbered element list", self.normalized)
        self.assertIn("A stale element number comes back `stale_ref`", self.normalized)
        self.assertIn("A check box or radio name ends in on or off", self.normalized)
        self.assertIn("a disabled control's name ends in disabled", self.normalized)
        self.assertIn("a select name includes the chosen option", self.normalized)
        self.assertIn("a section name ends in open or closed", self.normalized)
        self.assertIn("a selected tab's name ends in selected", self.normalized)
        self.assertIn("the current link's name ends in current", self.normalized)
        self.assertIn("A menu item, option, tree item, slider, or clickable div is listed by its name, so do not screenshot it to find it.", self.normalized)
        self.assertIn("A control inside an open shadow root is listed the same way; a closed root is not readable.", self.normalized)
        self.assertIn("A control inside a same-origin frame is listed by its name. A cross-origin frame is not readable.", self.normalized)
        self.assertIn("A control whose text lives in aria-labelledby uses that text as its name, so do not screenshot it to read the label.", self.normalized)
        self.assertIn("A pressed toggle's name ends in on or off, so do not screenshot it to see the state.", self.normalized)
        self.assertIn("An action or batch result also includes elements for up to 40 controls; use those refs.", self.normalized)
        self.assertIn("When a successful reply says unchanged, the controls you already have are still valid, so do not snapshot again.", self.normalized)
        self.assertIn("`set_value` replaces a field's text", self.normalized)
        self.assertIn("Skip the focused window, Keychain, and password fields.", self.normalized)
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
        self.assertIn("computer_use", desktop)
        self.assertIn("does not move the pointer", desktop)
        self.assertNotIn("workspace_vps_browser", desktop)
        self.assertNotIn("Cua Driver", desktop)

    def test_vps_desktop_degraded_mode_is_reported_once(self):
        # Without an accessibility stack or screenshot tool on the VM the
        # desktop calls fail outright; the agent must say so once rather
        # than retry-loop or improvise with shell screenshot tools.
        desktop = (SKILL_PATH.parent / "references" / "vps-desktop.md").read_text(encoding="utf-8")
        self.assertIn("VM desktop accessibility unavailable", desktop)
        self.assertIn("once", desktop)

    def test_skill_gives_the_names_hermes_registers(self):
        # Hermes registers MCP tools as mcp__<server>__<tool>; a bare
        # cua_alans_way_snapshot does not exist, and calling it costs a turn.
        block = re.search(r"^  (\w+):\n    command: \"node\"", (ROOT / "setup-workspace.sh").read_text(encoding="utf-8"), re.M)
        self.assertIsNotNone(block, "setup-workspace.sh no longer writes the MCP server block this test reads")
        server = block.group(1)
        for tool in ["cua_alans_way_status", "cua_alans_way_tabs", "cua_alans_way_open", "cua_alans_way_snapshot",
                     "cua_alans_way_screenshot", "cua_alans_way_action", "cua_alans_way_close",
                     "workspace_computer_apps", "workspace_computer_snapshot", "workspace_computer_menu", "workspace_computer_screenshot"]:
            with self.subTest(tool=tool):
                self.assertIn(f"mcp__{server}__{tool}", self.text)
        self.assertNotIn("call the tools by these exact names: `cua_alans_way", self.normalized)
        self.assertIn("`workspace_computer_*` for short", self.normalized)
        self.assertIn("tool_call", self.normalized)

    def test_the_app_api_is_never_driven_directly(self):
        # Tabs opened by curl against connection.json belong to another bot id,
        # so the browser tools refuse them afterwards.
        self.assertIn("connection.json", self.normalized)
        self.assertRegex(self.normalized, r"[Nn]ever (call|drive) the app's HTTP API")

    def test_the_ungated_desktop_input_tool_is_never_named_as_callable(self):
        # Desktop input goes through Hermes' approval-gated computer_use tool.
        # The raw MCP action must not appear in any skill or reference as
        # something the agent can call.
        for path in [SKILL_PATH] + list((SKILL_PATH.parent / "references").glob("*.md")):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("workspace_computer_action", text, path)
        self.assertIn("computer_use", self.normalized)

    def test_in_app_browser_is_the_only_default_host(self):
        self.assertIn(
            "The in-app host browser is the only default host.",
            self.normalized,
        )

    def test_no_alternate_browser_paths_when_mac_reachable(self):
        for forbidden in [
            "browser_exec",
            "personal browser",
        ]:
            with self.subTest(forbidden=forbidden):
                self.assertIn(forbidden, self.normalized)
        self.assertIn("do not silently substitute another browser", self.normalized)
        self.assertIn("A snapshot defaults to 2000 characters of page text.", self.normalized)
        self.assertIn("Do not screenshot only because the text was cut.", self.normalized)
        self.assertIn("jpeg quality 50 at 960px is the default.", self.normalized)
        self.assertIn("A link href omits tracking parameters.", self.normalized)
        self.assertIn("A frame src omits tracking parameters too.", self.normalized)
        self.assertIn("When status shows the VPS, the Mac is unreachable", self.normalized)
        self.assertNotIn("must keep running after the Mac sleeps", self.normalized)
        self.assertIn("continue the task on the VPS", self.normalized)
        self.assertIn("use `cua_alans_way_open` to open a new page for inspection", self.normalized)
        self.assertIn("If the result reports a continued tab, use its returned id and take a fresh snapshot before acting.", self.normalized)
        self.assertIn("If the continued page is still loading, read it again before acting.", self.normalized)
        self.assertIn("confirmed pre-dispatch missing tab", self.normalized)
        self.assertIn("An approval-bearing call cannot continue under its old review on another tab.", self.normalized)
        self.assertIn("For an uncertain action or control change, do not repeat it", self.normalized)
        self.assertIn("read `cua_alans_way_tabs` for the controller and epoch", self.normalized)
        self.assertIn("follow the error's recovery instructions", self.normalized)
        self.assertIn("the first VPS result's `_meta.workspace.tabIdChanged` lists one", self.normalized)
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

    def test_one_turn_rules_replaced_the_extra_round_trips(self):
        # The action reply's effect is the observation, so a turn ends with
        # the action instead of a snapshot-and-check.
        self.assertIn("Use a successful action reply's `effect` as the current page state", self.normalized)
        self.assertIn("When that reply supplies the state you need, skip an extra confirmation read.", self.normalized)
        self.assertIn("Recovery is an exception", self.normalized)
        self.assertIn("Do ordinary multi-step work in short chunks", self.normalized)
        self.assertIn("End the chunk before any noticeable step", self.normalized)
        self.assertIn("read the returned errors and side effects before continuing", self.normalized)
        self.assertIn("Put a whole checkout batch under one `commit`.", self.normalized)
        self.assertNotIn("Do multi-step work as one batch", self.normalized)
        self.assertIn('{action:"wait", text:"Done", timeout:8000}', self.normalized)
        self.assertIn("`gone:true` waits for the text or selector to disappear", self.normalized)
        self.assertIn('{action:"read"}', self.normalized)
        self.assertIn("Continue into the next chunk until the task is done or blocked", self.normalized)
        self.assertNotIn("Before each multi-step chunk", self.normalized)
        self.assertNotIn("write no chat text between tool calls", self.normalized)
        self.assertIn("Skip status and tabs unless a call fails", self.normalized)

    def test_progress_is_bounded_and_mid_task_messages_are_folded_in(self):
        for rule in ("email sent, form submitted, or page the user must act on",
                     "side effects and mistakes right away",
                     "For multi-step work, send one short start line",
                     "then a one-line update only at a real milestone, a failed step you route around, or a noticeable wait",
                     "Keep routine reads, actions and step transitions quiet",
                     "one quick action", "no tool names, headings or step counters",
                     "acknowledge it in one line and fold it into the running task", "do not restart"):
            self.assertIn(rule, self.normalized)
        self.assertNotIn("Give progress updates only when the user asks for them", self.normalized)

    def test_tab_id_and_epoch_default_to_the_last_used_tab(self):
        # Every call used to repeat "tabId":"<uuid>","epoch":N — about 30
        # tokens of pure overhead per turn. The router injects both, so the
        # skill tells the agent to leave them out.
        self.assertIn("omit `tabId` and `epoch`", self.normalized)
        self.assertIn("they default to the tab you last used", self.normalized)
        self.assertIn(
            "you add `wait` or `read` steps only when you need something `effect` does not show",
            self.normalized,
        )

    def test_host_arg_routes_to_the_named_machine(self):
        self.assertIn('`host:"vm"` to use the VM\'s own browser even while the user\'s computer is online', self.normalized)
        self.assertIn('`host:"computer"` to force the user\'s computer', self.normalized)
        self.assertIn("Omit it for the default", self.normalized)

    def test_select_accepts_any_option_handle(self):
        self.assertIn("`select` (an option by value, label, option, text or choice)", self.normalized)

    def test_the_extra_turn_rules_are_gone(self):
        for removed in [
            "Begin with status and your owned tabs",
            "Confirm the reported host",
            "Read a fresh snapshot",
            "then inspect the result",
            "Completion requires observed page state",
            "Do not pass `host`",
            'host:"vps"',
        ]:
            with self.subTest(removed=removed):
                self.assertNotIn(removed, self.normalized)

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
        self.assertIn("macCommand ? 'mac' : 'vps'", self.source)

    def test_probe_joins_items_with_separator(self):
        # join(' ') produces `fi if` — a bash syntax error that makes every
        # Mac probe fail and silently pins all traffic to the VPS host.
        self.assertIn(".join('; ')", self.source)
        self.assertIn("+ '; exit 1'", self.source)

    def test_probe_verifies_app_liveness(self):
        # File existence alone routes to a closed app — a dead host. The
        # probe must also prove the workspace API answers on the Mac.
        self.assertIn("connection.json", self.source)
        self.assertIn("curl -sf -m 4 -o /dev/null", self.source)
        self.assertIn("/v1/status", self.source)
        self.assertIn("Authorization: Bearer", self.source)

    def test_candidate_failure_falls_through(self):
        # A candidate bundle that exists but is not live must skip to the
        # next candidate, not abort the whole probe — liveness is the
        # wsr_alive function inside the if condition, not an early exit.
        self.assertIn("&& wsr_alive; then", self.source)
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
        self.assertIn("if (activeHost === 'mac') {", self.source)
        self.assertIn("freshMacState(macStateFile)", self.source)
        self.assertIn("pendingRequests.size", self.source)
        self.assertIn("re-probes and routes to it", self.source)
        self.assertIn("continueRememberedPage", self.source)
        self.assertIn("markResumeOpened", self.source)
        self.assertIn("'--continued-tab'", self.source)
        self.assertIn("onlineStreak >= 2", self.source)
        self.assertIn("script replaced — exiting so the next connection loads it", self.source)

    def test_probe_mode_exists(self):
        self.assertIn("--probe", self.source)

    def test_both_ssh_calls_reuse_a_control_master(self):
        # The probe and the backend spawn each paid a full ssh handshake —
        # ~4.5s of warmup on every lazy respawn. A shared ControlMaster
        # socket makes the spawn's handshake nearly free.
        self.assertIn("ControlMaster=auto", self.source)
        self.assertIn("ControlPersist=600", self.source)
        self.assertIn("/tmp/wsr-", self.source)
        self.assertIn("ServerAliveInterval=5", self.source)
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

    def test_retry_read_once_then_report(self):
        self.assertIn("Retry a read-only call once", self.normalized)
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


class SearchRoutingAndCaptchaSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normalized = _normalized(SKILL_PATH.read_text(encoding="utf-8"))
        search = re.search(r"## Search the web(.*?)## ", SKILL_PATH.read_text(encoding="utf-8"), re.S)
        cls.search = _normalized(search.group(1)) if search else ""
        captcha = re.search(r"## When a site shows a CAPTCHA(.*?)## ", SKILL_PATH.read_text(encoding="utf-8"), re.S)
        cls.captcha = _normalized(captcha.group(1)) if captcha else ""

    def test_search_goes_hermes_tools_then_the_users_computer_then_the_vm(self):
        self.assertTrue(self.search, "the Search the web section is gone")
        hermes = self.search.index("use Hermes' own `web_search`, then `web_extract`")
        computer = self.search.index("open a tab on the user's computer: omit `host`")
        vm = self.search.index("search engine in the VM browser only while the user's computer is offline")
        self.assertLess(hermes, computer)
        self.assertLess(computer, vm)
        self.assertIn("Do not open a search engine page in a tab for this.", self.search)
        self.assertIn("maps, shopping, signed-in results", self.search)
        self.assertIn("expect a CAPTCHA there", self.search)
        self.assertIn('Never pass `host:"vm"` to a search engine while the computer is online.', self.search)
        self.assertIn("If `web_search` or `web_extract` is not in your tools, or it fails, go to 2.", self.search)
        # The browser is the default only for what a plain lookup cannot answer.
        self.assertIn("default surface for anything web-shaped that a plain lookup cannot answer", self.normalized)

    def test_the_bot_never_solves_a_captcha(self):
        self.assertTrue(self.captcha, "the CAPTCHA section is gone")
        self.assertIn("You never solve a CAPTCHA.", self.captcha)
        self.assertIn("Do not click, type into, drag, or screenshot a challenge widget to solve it", self.captcha)
        self.assertIn("do not reach it with `eval` or `cdp`", self.captcha)
        self.assertIn("never use a solver service", self.captcha)
        self.assertIn("do not ask the user to approve a click on one", self.captcha)

    def test_every_challenge_signal_uses_the_apps_field_names(self):
        # Field names as capthvnsen/alans-way#138 sends them.
        for signal in ["`challenge: {kind, blocking}`", "`challenge_present`", "`awaiting_human`",
                       '`state:"awaiting_human"`', '`reason:"captcha"`', '`controller:"human"`',
                       "the `viewerUrl` to solve it in", "`human_returned`",
                       "`backOff:true`", "its `advice` says the site has challenged twice in 10 minutes"]:
            with self.subTest(signal=signal):
                self.assertIn(signal, self.captcha)
        for kind in ["recaptcha", "hcaptcha", "turnstile", "cloudflare", "google_sorry", "arkose"]:
            with self.subTest(kind=kind):
                self.assertIn(f"`{kind}`", self.captcha)
        self.assertIn("`blocking:false` is a widget inside a page that stays yours", self.captcha)
        self.assertIn("is handed to the user by the app itself", self.captcha)
        self.assertIn('{action:"release", reason:"captcha", note:', self.captcha)
        for assumed in ["awaitingHuman", "handback.reason` is"]:
            with self.subTest(assumed=assumed):
                self.assertNotIn(assumed, self.captcha)

    def test_one_short_telegram_message_with_where_to_solve_it(self):
        self.assertIn("Tell the user once, as one short text before your next tool call", self.captcha)
        self.assertIn("Hermes delivers it to Telegram mid-turn", self.captcha)
        self.assertIn("say it is waiting in Alan's Workspace", self.captcha)
        self.assertIn("For a VM tab, include the handback's `viewerUrl`", self.captcha)
        self.assertIn("Google wants a CAPTCHA before I can search.", self.captcha)
        self.assertIn("I'll pick it back up.", self.captcha)
        self.assertIn("The CAPTCHA message below keeps its own handback rules.", self.normalized)

    def test_a_viewer_link_with_a_secret_is_never_pasted(self):
        self.assertIn("Never paste a viewer link that has a password, token or key in it", self.captcha)
        for part in ["`password=`", "`token=`", "`key=`", "`user:pass@`", "anything after `#`"]:
            with self.subTest(part=part):
                self.assertIn(part, self.captcha)
        self.assertIn("leave the link out and point them to the viewer in Alan's Workspace instead", self.captcha)

    def test_waiting_is_slow_and_bounded(self):
        self.assertIn("Check `cua_alans_way_tabs` at most once every 30 seconds", self.captcha)
        self.assertIn("for up to 30 minutes", self.captcha)
        self.assertIn("Do not snapshot, act on, or claim the tab meanwhile.", self.captcha)
        self.assertIn("The app hands the tab back on its own once the challenge clears.", self.captcha)
        # A handback that merely expired leaves the tab with the human.
        self.assertNotIn("handback is gone", self.captcha)
        self.assertIn("(`controller` is `agent` and its handback says `human_returned`)", self.captcha)
        self.assertIn("carry on without another message", self.captcha)
        self.assertIn("the tab list you just read gave you the fresh one", self.captcha)
        self.assertIn("After 30 minutes, or if you cannot keep waiting in this turn, stop.", self.captcha)
        # A bot's own release on the VM is not held or watched the same way:
        # the user's "done" ends the wait and is the claim agreement.
        self.assertIn("the user saying they're done also ends the wait", self.captcha)
        self.assertIn("their reply is the agreement to claim it", self.captcha)
        self.assertIn("ask them to say when they're through", self.captcha)

    def test_a_site_that_challenges_twice_is_dropped(self):
        self.assertIn("stop using that site for this task", self.captcha)
        self.assertIn("the same site challenges you twice within 10 minutes across tabs", self.captcha)
        self.assertIn("twice in this task counts", self.captcha)
        self.assertIn("Do not wait on that tab or retry the site in a fresh tab.", self.captcha)
        self.assertIn("Tell the user in one line that you moved on, so they can ignore that CAPTCHA.", self.captcha)
        self.assertIn("If no other source can answer, ask the user how to go on.", self.captcha)
        # Switching source must not read as the "do not silently substitute another browser" failure case.
        self.assertIn("This is a change of source, not a browser failure", self.captcha)


class DesktopAppsSkillTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.normalized = _normalized(SKILL_PATH.read_text(encoding="utf-8"))

    def test_desktop_apps_go_through_the_workspace_tools_only(self):
        self.assertIn("never run screencapture, osascript or ssh scripts to drive the user's desktop", self.normalized)
        self.assertIn("use the `computer_use` tool (and the read-only `workspace_computer_*` tools to look)", self.normalized)

    def test_where_to_act_names_each_surface_and_when_to_ask(self):
        self.assertIn("**Where to act.** A web page is `cua_alans_way_*` work", self.normalized)
        self.assertIn("A native app is `computer_use` work", self.normalized)
        self.assertIn("`vps` is the VM desktop", self.normalized)
        self.assertIn("ask the user instead of working around it", self.normalized)
        self.assertIn("use that observation instead of capturing it again", self.normalized)
        self.assertIn("Recovery from an uncertain action or missing current state needs a fresh capture", self.normalized)

    def test_a_permission_error_names_the_app_and_both_switches(self):
        self.assertIn("Accessibility and Screen Recording for the Alan's Workspace app (listed as alans-way-localapp)", self.normalized)
        self.assertIn("System Settings", self.normalized)


if __name__ == "__main__":
    unittest.main()
