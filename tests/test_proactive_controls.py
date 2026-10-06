"""Real companion state backs chat controls; no native profile is touched."""
from pathlib import Path
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def plugin():
    name = "companion_proactive_controls_test"
    path = ROOT / "alans-way"
    spec = importlib.util.spec_from_file_location(name, path / "__init__.py", submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ControlTests(unittest.TestCase):
    def test_chat_controls_read_back_effective_preferences_without_private_audit(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            route = "agent:main:telegram:dm:123456789"
            runtime.store.update_policy({"session_key": route})
            with patch.dict(os.environ, {"HERMES_SESSION_KEY": route}):
                self.assertIn("Proactivity: enabled", runtime.command("resume"))
                configured = runtime.command('configure {"quiet_start":23}')
                self.assertIn("23:00–08:00", configured)
                self.assertNotIn(route, configured)
                self.assertNotIn('"audit"', configured)
                self.assertIn("Proactivity: paused", runtime.command("pause"))
                self.assertIn("no useful opportunity", runtime.command("review"))
            runtime.close()

    def test_mutations_and_watch_disclosure_stay_on_the_bound_route(self):
        """Plugin slash commands bypass the gateway's slash access check, so
        any session that can message the bot could otherwise pause, retune or
        read private watch scopes. Read-only status stays open; an unbound
        install stays fully open so setup can bind it."""
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            route = "agent:main:telegram:dm:123456789"
            runtime.ledger.record_task({"id": "rent", "title": "Rent watch",
                "scope": "Check rent postings", "next_action": "Check",
                "owner": "primary", "status": "active", "approved": True})
            # Unbound: everything works — setup needs to reach these controls.
            self.assertIn("Standing watches", runtime.watch_command("list"))
            self.assertIn("Proactivity: paused", runtime.command("pause"))
            runtime.store.update_policy({"session_key": route})
            with patch.dict(os.environ, {"HERMES_SESSION_KEY": "agent:main:telegram:dm:999"}):
                denied = runtime.command("pause")
                self.assertIn("bound", denied)
                self.assertNotIn("Proactivity: paused", denied)
                self.assertNotIn("rent", runtime.watch_command("list"))
                self.assertNotIn("Rent watch", runtime.watch_command("show rent"))
                # Read-only status remains usable from any session.
                self.assertIn("Proactivity:", runtime.command("status"))
            with patch.dict(os.environ, {"HERMES_SESSION_KEY": route}):
                self.assertIn("Proactivity: paused", runtime.command("pause"))
                self.assertIn("rent", runtime.watch_command("list"))
            runtime.close()

    def test_status_text_surfaces_observer_storage_and_gateway_health(self):
        """A dead observer, a saturated event table or a failing appraiser
        must be visible in /proactivity status, not only in the JSON."""
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            text = runtime.command("status")
            self.assertIn("Gateway: not armed", text)
            self.assertIn("Observer: stopped", text)
            self.assertNotIn("Attention", text)
            runtime.observer_error = "observer_failed; inspect locally before resuming"
            runtime.appraisal_error = "appraisal_failed; inspect locally before resuming"
            runtime.store._MAX_EVENTS = 0
            text = runtime.command("status")
            self.assertIn("observer_failed", text)
            self.assertIn("appraisal_failed", text)
            self.assertIn("storage full", text)
            runtime.start(interval=3600)
            self.assertIn("Observer: running", runtime.command("status"))
            runtime.close()

    def test_swallowed_appraisal_errors_are_recorded_for_status(self):
        """review() returns not-useful on any failure, including plugin LLM
        trust/provider errors — that must surface in status instead of being
        indistinguishable from a clean 'nothing useful' verdict."""
        from types import SimpleNamespace
        class LLM:
            def complete_structured(self, **kwargs):
                raise RuntimeError("plugin llm trust denied")
        module = plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            runtime = module.Runtime(SimpleNamespace(llm=LLM()), home)
            runtime.store.update_policy({"enabled": True,
                "session_key": "agent:main:telegram:dm:123456789",
                "debounce_seconds": 0, "min_interval_seconds": 0,
                "quiet_start": 0, "quiet_end": 0})
            guard.mark_gateway_ready(home)
            runtime.ledger.record_task({"id": "watch", "title": "T",
                "scope": "Review the approved draft", "next_action": "Review",
                "owner": "primary", "status": "active", "approved": True})
            runtime.store.record_event("manual_review", "opaque-review", purpose=True)
            self.assertEqual(runtime.tick()["status"], "no_op")
            self.assertIsNotNone(runtime.appraisal_error)
            status = json.loads(runtime.control({"action": "status"}))
            self.assertEqual(status["appraisal_error"], runtime.appraisal_error)
            self.assertNotIn("trust denied", json.dumps(status))
            runtime.close()

    def test_interactive_review_returns_now_while_paused_without_queue_or_injection(self):
        from types import SimpleNamespace
        class LLM:
            calls = 0
            def complete_structured(self, **kwargs):
                self.calls += 1
                return SimpleNamespace(content_type="json", parsed={"useful": False, "action": "ask", "task_id": None})
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            llm = LLM()
            runtime = module.Runtime(SimpleNamespace(llm=llm), Path(directory))
            runtime.store.update_policy({"enabled": False})
            runtime.ledger.record_task({"id": "watch", "title": "Draft", "scope": "Draft approved test cases",
                "next_action": "Draft", "owner": "primary", "status": "active", "approved": True})
            result = json.loads(runtime.control({"action": "review"}))
            self.assertTrue(result["ok"])
            self.assertFalse(result["injected"])
            self.assertEqual(llm.calls, 1)
            self.assertFalse(runtime.store.load_policy().enabled)
            self.assertEqual(runtime.store.status()["counts"], {})
            runtime.close()

    def test_task_scope_and_focus_survive_restart_without_self_generated_wakes(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            runtime = module.Runtime(None, home)
            runtime.store.update_policy({"session_key": "agent:main:telegram:dm:123456789"})
            task = {"id": "companion-build", "title": "Companion", "scope": "Review approved handoff research",
                    "next_action": "Draft the next acceptance tests", "owner": "primary", "status": "active", "approved": True}
            self.assertTrue(json.loads(runtime.control({"action": "record_task", "task": task}))["ok"])
            self.assertTrue(json.loads(runtime.control({"action": "configure", "changes": {"preferences": {"focus": ["approved projects"]}}}))["ok"])
            self.assertEqual(runtime.store.status()["counts"], {})
            runtime.close()
            restarted = module.Runtime(None, home)
            status = json.loads(restarted.control({"action": "status"}))
            self.assertEqual(status["tasks"][0]["id"], "companion-build")
            self.assertEqual(status["preferences"]["focus"], ["approved projects"])
            self.assertTrue(json.loads(restarted.control({"action": "finish_task", "task_id": "companion-build", "status": "cancelled"}))["ok"])
            self.assertFalse(json.loads(restarted.control({"action": "record_task", "task": task}))["ok"])
            self.assertFalse(json.loads(restarted.control({"action": "configure", "changes": {"preferences": {"autonomy": "unrestricted"}}}))["ok"])
            restarted.close()

    def test_registered_tool_schema_can_express_the_live_task_controls(self):
        module = plugin()
        class Facade:
            def register_tool(self, **kwargs): self.schema = kwargs["schema"]
            def register_command(self, *args, **kwargs): pass
            def register_skill(self, *args, **kwargs): pass
            def on_unload(self, *args): pass
        with tempfile.TemporaryDirectory() as directory:
            facade = Facade()
            runtime = module.register(facade, home=Path(directory), background=False)
            parameters = facade.schema["parameters"]
            self.assertIn("record_task", parameters["properties"]["action"]["enum"])
            self.assertIn("task", parameters["properties"])
            self.assertIn("event_id", parameters["properties"])
            self.assertIn("preferences", parameters["properties"]["settings"]["properties"])
            runtime.close()

    def test_mac_execution_binding_cannot_silently_move_to_cloud(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            task = {"id": "mac-work", "title": "Local work", "scope": "Read an approved Mac file",
                    "next_action": "Read it", "owner": "primary", "status": "active", "approved": True,
                    "execution_host": "mac"}
            runtime.ledger.record_task(task)
            with self.assertRaises(ValueError):
                runtime.ledger.record_task({**task, "execution_host": "cloud"})
            self.assertEqual(runtime.ledger.snapshot()["tasks"][0]["execution_host"], "mac")
            runtime.close()

    def test_omitting_host_in_a_watch_update_preserves_the_mac_binding(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            task = {"id": "mac-work", "title": "Local work", "scope": "Read an approved Mac file",
                    "next_action": "Read it", "owner": "primary", "status": "active", "approved": True,
                    "execution_host": "mac"}
            runtime.ledger.record_task(task)
            update = {key: value for key, value in task.items() if key != "execution_host"}
            update["next_action"] = "Wait for the Mac to reconnect"
            runtime.ledger.record_task(update)
            self.assertEqual(runtime.ledger.snapshot()["tasks"][0]["execution_host"], "mac")
            runtime.close()

    def test_model_tool_never_resumes_or_loosens_the_operator_envelope(self):
        """The model surface tightens only: resume and every raise of a cap,
        drop of an interval, shrink of the quiet window, or raise of
        max_work_minutes is refused with an operator pointer. The operator's
        own control() path keeps all of them."""
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            route = "agent:main:telegram:dm:123456789"
            runtime.store.update_policy({"session_key": route})
            with patch.dict(os.environ, {"HERMES_SESSION_KEY": route}):
                # resume is refused on the tool even from the bound route.
                refused = json.loads(runtime.tool_control({"action": "resume"}))
                self.assertFalse(refused["ok"])
                self.assertIn("operator", refused["error"])
                self.assertTrue(runtime.store.load_policy().enabled)
                # Set a strict baseline through the operator path so every
                # loosening direction below is a real loosening.
                self.assertTrue(json.loads(runtime.control({"action": "configure", "changes": {
                    "max_daily_wakes": 1, "max_daily_watch_wakes": 4,
                    "max_low_purpose_wakes": 0, "min_interval_seconds": 3600,
                    "debounce_seconds": 60, "event_ttl_seconds": 86400,
                    "max_pending": 16}}))["ok"])
                self.assertTrue(json.loads(runtime.control({"action": "configure",
                    "changes": {"preferences": {"max_work_minutes": 10}}}))["ok"])
                for changes in ({"max_daily_wakes": 2},
                                {"max_daily_watch_wakes": 5},
                                {"max_low_purpose_wakes": 1},
                                {"min_interval_seconds": 1800},
                                {"debounce_seconds": 30},
                                {"quiet_start": 23},  # 23–8 shrinks 22–8
                                {"event_ttl_seconds": 172800},
                                {"max_pending": 32},
                                {"preferences": {"max_work_minutes": 15}}):
                    result = json.loads(runtime.tool_control({"action": "configure", "changes": changes}))
                    self.assertFalse(result["ok"], changes)
                    self.assertIn("operator", result["error"], changes)
                # The baseline is untouched by any refused call.
                self.assertEqual(runtime.store.load_policy().max_daily_wakes, 1)
                # Tightening directions still work through the tool.
                for changes in ({"max_daily_wakes": 0},
                                {"min_interval_seconds": 7200},
                                {"quiet_start": 20},  # 20–8 grows 22–8
                                {"event_ttl_seconds": 3600},
                                {"max_pending": 8},
                                {"preferences": {"max_work_minutes": 5}}):
                    self.assertTrue(json.loads(runtime.tool_control({"action": "configure", "changes": changes}))["ok"], changes)
                self.assertEqual(runtime.store.load_policy().max_daily_wakes, 0)
                self.assertEqual(runtime.store.load_policy().quiet_start, 20)
                # pause stays on the tool.
                self.assertTrue(json.loads(runtime.tool_control({"action": "pause"}))["ok"])
                # The operator path is ungated: resume and loosening work.
                self.assertTrue(json.loads(runtime.control({"action": "resume"}))["ok"])
                self.assertTrue(json.loads(runtime.control({"action": "configure",
                    "changes": {"max_daily_wakes": 3, "quiet_start": 22}}))["ok"])
                self.assertTrue(runtime.store.load_policy().enabled)
                self.assertEqual(runtime.store.load_policy().quiet_start, 22)
            runtime.close()

    PROPOSAL = {"id": "rent", "title": "Rent", "scope": "Check rent posts",
                "next_action": "Check the bank feed", "owner": "primary",
                "status": "active", "cadence_seconds": 3600}

    def propose(self, runtime, **changes):
        return json.loads(runtime.tool_control({"action": "record_task",
                                                "task": {**self.PROPOSAL, **changes}}))

    def test_model_can_only_propose_and_the_reply_names_the_approve_command(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            result = self.propose(runtime, approved=True, consent_reference="user said yes",
                                  next_review_at="2020-01-01T00:00:00+00:00")
            self.assertTrue(result["ok"])
            self.assertIn("/watch approve rent", result["tell_user"])
            task = runtime.ledger.snapshot()["tasks"][0]
            self.assertEqual((task["status"], task["approved"]), ("proposed", False))
            self.assertNotIn("approved_at", task)
            self.assertEqual(runtime.review_context()["tasks"], [])
            self.assertIn("/watch approve rent", runtime.watch_command("list"))
            runtime.close()

    def test_only_the_operator_approves_and_it_activates_the_watch(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            self.propose(runtime)
            self.assertIn("only proposed", runtime.watch_command("resume rent"))
            self.assertFalse(json.loads(runtime.tool_control({"action": "approve_task", "task_id": "rent"}))["ok"])
            self.assertEqual(runtime.ledger.snapshot()["tasks"][0]["status"], "proposed")
            self.assertIn("approved", runtime.watch_command("approve rent"))
            task = runtime.ledger.snapshot()["tasks"][0]
            self.assertEqual((task["status"], task["approved"]), ("active", True))
            self.assertTrue(task["approved_at"])
            self.assertEqual(len(runtime.review_context()["tasks"]), 1)
            self.assertIn("failed", runtime.watch_command("approve rent"))
            runtime.close()

    def test_cli_approve_activates_a_proposed_watch(self):
        from types import SimpleNamespace
        module = plugin()
        operator = sys.modules[module.__name__ + ".proactive_operator"]
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            self.propose(runtime)
            with patch("builtins.print"):
                self.assertEqual(operator.execute(runtime, SimpleNamespace(action="approve", watch_id="rent")), 0)
                self.assertEqual(operator.execute(runtime, SimpleNamespace(action="approve", watch_id="rent")), 1)
            self.assertEqual(runtime.ledger.snapshot()["tasks"][0]["status"], "active")
            runtime.close()

    def test_approved_watch_may_only_be_tightened_by_the_model(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            self.propose(runtime)
            runtime.watch_command("approve rent")
            def state():
                return runtime.ledger.snapshot()["tasks"][0]["status"]
            for change in ({"cadence_seconds": 7200}, {"cadence_seconds": 7200, "title": "Rent check"},
                           {"cadence_seconds": 7200, "status": "waiting"}):
                self.assertTrue(self.propose(runtime, **change)["ok"])
                self.assertNotEqual(state(), "proposed", change)
                self.assertTrue(runtime.ledger.snapshot()["tasks"][0]["approved"])
            self.assertTrue(json.loads(runtime.tool_control(
                {"action": "finish_task", "task_id": "rent", "status": "waiting"}))["ok"])
            # Reactivating a paused watch, a new action or a faster cadence
            # all need the user again.
            for change in ({"status": "active"}, {"next_action": "Email the landlord"},
                           {"status": "active", "cadence_seconds": 600}):
                runtime.watch_command("resume rent")
                self.assertNotEqual(state(), "proposed")
                self.assertTrue(self.propose(runtime, **change)["ok"])
                self.assertEqual(state(), "proposed", change)
                self.assertFalse(runtime.ledger.snapshot()["tasks"][0]["approved"])
                runtime.watch_command("approve rent")
                runtime.watch_command("pause rent")
            self.assertFalse(self.propose(runtime, scope="Something else")["ok"])
            runtime.close()

    def test_proposals_are_bounded_and_do_not_squat_the_watch_cap(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            for index in range(8):
                self.assertTrue(self.propose(runtime, id=f"w{index}")["ok"])
            self.assertFalse(self.propose(runtime, id="w8")["ok"])
            self.assertTrue(self.propose(runtime, id="w0", title="Edited")["ok"])
            runtime.close()

    def test_terminal_watches_are_pruned_after_two_weeks_and_never_count_toward_the_cap(self):
        from datetime import datetime, timedelta, timezone
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            base = {**self.PROPOSAL, "approved": True}
            for index in range(64):
                runtime.ledger.record_task({**base, "id": f"w{index}"})
            with self.assertRaises(ValueError):
                runtime.ledger.record_task({**base, "id": "extra"})
            runtime.ledger.finish_task("w0", "done")
            runtime.ledger.record_task({**base, "id": "extra"})
            self.assertEqual(len(runtime.ledger.snapshot()["tasks"]), 65)
            with runtime.ledger.transaction() as data:
                data["tasks"]["w0"]["closed_at"] = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
            runtime.ledger.finish_task("w1", "cancelled")
            ids = {task["id"] for task in runtime.ledger.snapshot()["tasks"]}
            self.assertNotIn("w0", ids)
            self.assertIn("w1", ids)
            runtime.close()

    def test_model_cannot_shift_quiet_hours_with_a_timezone_change(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            result = json.loads(runtime.tool_control({"action": "configure",
                                                      "changes": {"timezone": "Pacific/Auckland"}}))
            self.assertFalse(result["ok"])
            self.assertIn("operator", result["error"])
            self.assertEqual(runtime.store.load_policy().timezone, "America/Denver")
            self.assertTrue(json.loads(runtime.tool_control({"action": "configure",
                "changes": {"timezone": "America/Denver", "quiet_start": 21}}))["ok"])
            self.assertTrue(json.loads(runtime.control({"action": "configure",
                "changes": {"timezone": "Pacific/Auckland"}}))["ok"])
            runtime.close()


    def test_effective_chat_preferences_persist_across_runtime_restart(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            runtime = module.Runtime(None, home)
            result = json.loads(runtime.control({"action": "status"}))
            self.assertTrue(result["ok"])
            self.assertTrue(result["enabled"])
            self.assertTrue(json.loads(runtime.control({"action": "configure", "changes": {"quiet_start": 23}}))["ok"])
            runtime.close()
            restarted = module.Runtime(None, home)
            status = json.loads(restarted.control({"action": "status"}))
            self.assertEqual(status["policy"]["quiet_start"], 23)
            self.assertTrue(status["enabled"])
            self.assertFalse(json.loads(restarted.control({"action": "configure", "changes": {"session_key": "foreign"}}))["ok"])
            restarted.close()


if __name__ == "__main__":
    unittest.main()
