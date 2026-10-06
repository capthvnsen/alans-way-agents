"""Public plugin facade contracts; no Hermes internals in unit tests."""
from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "alans-way"


def load_plugin():
    name = "companion_proactive_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py",
                                                submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PluginTests(unittest.TestCase):
    def test_startup_marker_arms_only_the_same_gateway_process(self):
        from datetime import datetime, timezone, timedelta
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            registered = datetime.now(timezone.utc) - timedelta(seconds=1)
            self.assertFalse(guard.gateway_ready(home, registered))
            guard.mark_gateway_ready(home)
            self.assertTrue(guard.gateway_ready(home, registered))
            value = __import__("json").loads((home / "companion/proactivity/gateway-owner.json").read_text())
            value["pid"] += 1
            guard.write_private_json(home / "companion/proactivity/gateway-owner.json", value)
            self.assertFalse(guard.gateway_ready(home, registered))

    def test_gateway_marker_stamped_before_registration_still_arms(self):
        """gateway:startup may fire before plugin registration — arming must not
        depend on that ordering, only on same-process identity and freshness."""
        from datetime import datetime, timezone, timedelta
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            # The hook stamps the marker, then the plugin registers a moment later.
            guard.mark_gateway_ready(home, now=datetime.now(timezone.utc) - timedelta(seconds=3))
            registered = datetime.now(timezone.utc)
            self.assertTrue(guard.gateway_ready(home, registered))

    def test_stale_marker_from_before_process_start_does_not_arm(self):
        """A marker older than this process belongs to a dead earlier owner —
        pid reuse must never arm a runtime that never ran gateway:startup."""
        from datetime import datetime, timezone, timedelta
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            process_start = datetime.now(timezone.utc) - timedelta(minutes=30)
            guard.mark_gateway_ready(home, now=process_start - timedelta(minutes=5))
            with patch.object(guard, "_process_started_at", return_value=process_start):
                self.assertFalse(guard.gateway_ready(home, datetime.now(timezone.utc)))

    def test_reload_long_after_gateway_start_still_arms(self):
        """A plugin reload re-registers inside the long-running gateway; the
        marker this process stamped at startup stays valid however old the
        registration is — freshness is anchored to process start, not to
        registered_at."""
        from datetime import datetime, timezone, timedelta
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            process_start = datetime.now(timezone.utc) - timedelta(hours=2)
            guard.mark_gateway_ready(home, now=process_start + timedelta(seconds=2))
            registered = datetime.now(timezone.utc)
            with patch.object(guard, "_process_started_at", return_value=process_start):
                self.assertTrue(guard.gateway_ready(home, registered))

    def test_process_start_is_probeable_without_proc(self):
        """macOS has no /proc; the ps fallback must still return a real start."""
        from datetime import datetime, timezone
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        started = guard._process_started_at()
        self.assertIsNotNone(started)
        self.assertLess(abs((datetime.now(timezone.utc) - started).total_seconds()), 86400)

    def test_gateway_hook_is_passive_for_non_startup_events(self):
        hook = ROOT / "alans-way/gateway-hook/handler.py"
        spec = importlib.util.spec_from_file_location("proactive_hook_test", hook)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            module.handle("agent:end", {"response": "Never persist this private text"}, home=home)
            self.assertFalse((home / "companion").exists())
            module.handle("gateway:startup", {"platforms": ["telegram"]}, home=home)
            self.assertTrue((home / "companion/proactivity/gateway-owner.json").exists())

    def test_gateway_hook_accepts_the_legacy_plugin_path_environment(self):
        hook = ROOT / "alans-way/gateway-hook/handler.py"
        spec = importlib.util.spec_from_file_location("proactive_hook_legacy_test", hook)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.dict(os.environ, {"HERMES_PROACTIVE_PRIMARY_PLUGIN": str(PLUGIN)}, clear=True):
                module.handle("gateway:startup", {}, home=home)
            self.assertTrue((home / "companion/proactivity/gateway-owner.json").exists())

    def test_dispatch_requires_gateway_marker_and_literal_acceptance(self):
        from types import SimpleNamespace
        import json
        class Facade:
            def __init__(self):
                self.acceptance = "yes"
                self.received = []
            def inject_message(self, message, **kwargs):
                self.received.append((message, kwargs))
                return self.acceptance
        class FakeStore:
            def __init__(self):
                self.finished = []
                self.pending = True
            def load_policy(self):
                return SimpleNamespace(enabled=True, primary_profile="default",
                                       session_key="agent:main:telegram:dm:123456789")
            def claim(self, now=None):
                if not self.pending:
                    return None
                self.pending = False
                return {"id": "sample-event", "kind": "manual_review", "evidence": "a" * 64,
                        "purpose": False, "session_key": self.load_policy().session_key}
            def finish(self, event_id, status):
                self.finished.append((event_id, status))
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            facade, store = Facade(), FakeStore()
            runtime = module.Runtime(facade, Path(directory), store=store,
                                     appraiser=lambda *_: {"useful": True})
            self.assertIsNone(runtime.tick())
            self.assertEqual(facade.received, [])
            guard.mark_gateway_ready(Path(directory))
            result = runtime.tick()
            self.assertEqual(result["status"], "uncertain")
            self.assertEqual(store.finished, [("sample-event", "uncertain")])
            self.assertEqual(facade.received[0][1]["session_key"], store.load_policy().session_key)
            self.assertNotIn("a" * 64, facade.received[0][0])
            self.assertIsNone(runtime.tick())
            runtime.close()

    def test_wake_prompt_names_the_installed_namespaced_skill(self):
        """Hermes qualifies plugin skills as '<plugin name>:<skill>' — the wake
        prompt must name alans-way:proactive-primary or skill_view cannot find it."""
        from types import SimpleNamespace
        class Facade:
            def __init__(self):
                self.received = []
            def inject_message(self, message, **kwargs):
                self.received.append((message, kwargs))
                return True
        class FakeStore:
            def __init__(self):
                self.finished = []
                self.pending = True
            def load_policy(self):
                return SimpleNamespace(enabled=True, primary_profile="default",
                                       session_key="agent:main:telegram:dm:123456789")
            def claim(self, now=None):
                if not self.pending:
                    return None
                self.pending = False
                return {"id": "sample-event", "kind": "manual_review", "evidence": "a" * 64,
                        "purpose": False, "session_key": self.load_policy().session_key}
            def finish(self, event_id, status):
                self.finished.append((event_id, status))
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            facade, store = Facade(), FakeStore()
            runtime = module.Runtime(facade, Path(directory), store=store,
                                     appraiser=lambda *_: {"useful": True})
            guard.mark_gateway_ready(Path(directory))
            self.assertEqual(runtime.tick()["status"], "accepted_unverified")
            message = facade.received[0][0]
            self.assertIn("alans-way:proactive-primary", message)
            self.assertNotIn("proactive-primary:proactive-primary", message)
            runtime.close()

    def test_dispatch_error_after_claim_still_releases_the_event(self):
        """An exception escaping between claim() and finish() must not strand
        the event in 'dispatching' — it would hold the one-wake gate forever."""
        from types import SimpleNamespace
        class FakeStore:
            def __init__(self):
                self.finished = []
                self.policy_calls = 0
            def load_policy(self):
                self.policy_calls += 1
                if self.policy_calls > 1:
                    raise RuntimeError("state backend went away mid-dispatch")
                return SimpleNamespace(enabled=True, primary_profile="default",
                                       session_key="agent:main:telegram:dm:123456789")
            def claim(self, now=None):
                return {"id": "e", "kind": "manual_review", "evidence": "a" * 64,
                        "purpose": False, "session_key": "agent:main:telegram:dm:123456789"}
            def finish(self, event_id, status):
                self.finished.append((event_id, status))
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            store = FakeStore()
            runtime = module.Runtime(SimpleNamespace(), Path(directory), store=store)
            guard.mark_gateway_ready(Path(directory))
            with self.assertRaises(RuntimeError):
                runtime.tick()
            self.assertEqual(store.finished, [("e", "uncertain")])
            runtime.close()

    def test_watch_due_dispatches_without_appraiser_and_re_arms_cadence(self):
        from datetime import datetime, timedelta, timezone
        class Facade:
            def __init__(self):
                self.received = []
            def inject_message(self, message, **kwargs):
                self.received.append((message, kwargs))
                return True
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            facade = Facade()
            runtime = module.Runtime(
                facade, home,
                appraiser=lambda *_: self.fail("approved watches skip appraisal"))
            runtime.store.update_policy({"enabled": True,
                "session_key": "agent:main:telegram:dm:123456789",
                "debounce_seconds": 0, "min_interval_seconds": 0,
                "quiet_start": 0, "quiet_end": 0})
            guard.mark_gateway_ready(home)
            past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            runtime.ledger.record_task({"id": "rent", "title": "Rent",
                "scope": "Check rent posts", "next_action": "Check feed",
                "owner": "primary", "status": "active", "approved": True,
                "next_review_at": past, "cadence_seconds": 3600,
                "notify_when": "payment missing"})
            self.assertEqual(runtime.observe(), 1)
            result = runtime.tick()
            self.assertEqual(result["status"], "accepted_unverified")
            message = facade.received[0][0]
            self.assertIn("[Companion scheduled watch]", message)
            self.assertIn("payment missing", message)
            self.assertEqual(facade.received[0][1]["session_key"],
                             "agent:main:telegram:dm:123456789")
            # The fired instance was re-armed to the next grid point, not replayed.
            watch = runtime.ledger.snapshot()["tasks"][0]
            self.assertGreater(datetime.fromisoformat(watch["next_review_at"]),
                               datetime.now(timezone.utc))
            self.assertEqual(runtime.observe(), 0)
            runtime.close()

    def test_re_armed_or_finished_watch_makes_queued_wake_stale(self):
        from datetime import datetime, timedelta, timezone
        class Facade:
            def __init__(self):
                self.received = []
            def inject_message(self, message, **kwargs):
                self.received.append((message, kwargs))
                return True
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            facade = Facade()
            runtime = module.Runtime(facade, home)
            runtime.store.update_policy({"enabled": True,
                "session_key": "agent:main:telegram:dm:123456789",
                "debounce_seconds": 0, "min_interval_seconds": 0,
                "min_watch_interval_seconds": 0,
                "quiet_start": 0, "quiet_end": 0})
            guard.mark_gateway_ready(home)
            watch = {"id": "flight", "title": "Flight", "scope": "Track fare",
                     "next_action": "Check price", "owner": "primary",
                     "status": "active", "approved": True,
                     "next_review_at": (datetime.now(timezone.utc)
                                        - timedelta(hours=1)).isoformat()}
            runtime.ledger.record_task(watch)
            self.assertEqual(runtime.observe(), 1)
            # The agent handled it early and re-armed — the queued wake is stale.
            watch["next_review_at"] = (datetime.now(timezone.utc)
                                     + timedelta(days=1)).isoformat()
            runtime.ledger.record_task(watch)
            self.assertEqual(runtime.tick()["status"], "stale")
            self.assertEqual(facade.received, [])
            # A finished watch's queued wake is rejected outright.
            watch["next_review_at"] = (datetime.now(timezone.utc)
                                       - timedelta(minutes=5)).isoformat()
            runtime.ledger.record_task(watch)
            self.assertEqual(runtime.observe(), 1)
            runtime.ledger.finish_task("flight", "done")
            self.assertEqual(runtime.tick()["status"], "rejected")
            self.assertEqual(facade.received, [])
            runtime.close()

    def test_deadline_watch_dispatches_with_escalation_context(self):
        from datetime import datetime, timedelta, timezone
        class Facade:
            def __init__(self):
                self.received = []
            def inject_message(self, message, **kwargs):
                self.received.append((message, kwargs))
                return True
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            facade = Facade()
            runtime = module.Runtime(facade, home)
            runtime.store.update_policy({"enabled": True,
                "session_key": "agent:main:telegram:dm:123456789",
                "debounce_seconds": 0, "min_interval_seconds": 0,
                "quiet_start": 0, "quiet_end": 0})
            guard.mark_gateway_ready(home)
            runtime.ledger.record_task({"id": "visa", "title": "Visa",
                "scope": "Track visa renewal", "next_action": "Check status",
                "owner": "primary", "status": "active", "approved": True,
                "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()})
            self.assertEqual(runtime.observe(), 1)
            result = runtime.tick()
            self.assertEqual(result["status"], "accepted_unverified")
            message = facade.received[0][0]
            self.assertIn("[Companion scheduled watch]", message)
            self.assertIn("Deadline:", message)
            runtime.close()

    def test_watch_command_manages_the_ledger_directly(self):
        import json as _json
        module = load_plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            self.assertIn("No standing watches", runtime.watch_command("list"))
            payload = {"id": "rent", "title": "Rent", "scope": "Check rent",
                       "next_action": "Check", "owner": "primary",
                       "status": "active",
                       "next_review_at": "2026-02-01T09:00:00+00:00",
                       "cadence_seconds": 86400}
            # A typed /watch add is the consent — no approved flag needed.
            self.assertIn("recorded", runtime.watch_command("add " + _json.dumps(payload)))
            self.assertIn("rent", runtime.watch_command("list"))
            self.assertIn("every 86400s", runtime.watch_command("list"))
            self.assertIn("failed", runtime.watch_command("add {bad json"))
            self.assertNotIn("bad json", runtime.watch_command("list"))
            self.assertIn("now waiting", runtime.watch_command("pause rent"))
            self.assertIn("active again", runtime.watch_command("resume rent"))
            self.assertIn("Signal recorded", runtime.watch_command("signal rent posted"))
            self.assertEqual(runtime.ledger.snapshot()["tasks"][0]["signal"], "posted")
            self.assertIn("cancelled", runtime.watch_command("cancel rent"))
            self.assertIn("terminal", runtime.watch_command("resume rent"))
            # A terminal id cannot be resurrected through add either.
            self.assertIn("failed", runtime.watch_command("add " + _json.dumps(payload)))
            self.assertIn("Use /watch", runtime.watch_command("frobnicate"))
            runtime.close()

    def test_report_signal_control_action_round_trips(self):
        module = load_plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            runtime.ledger.record_task({"id": "inbox", "title": "T", "scope": "S",
                "next_action": "N", "owner": "primary", "status": "active", "approved": True})
            result = __import__("json").loads(runtime.control(
                {"action": "report_signal", "task_id": "inbox", "signal": "2 unread"}))
            self.assertIs(result["ok"], True)
            task = runtime.ledger.snapshot()["tasks"][0]
            self.assertEqual(task["signal"], "2 unread")
            self.assertTrue(task["signal_at"])
            result = __import__("json").loads(runtime.control(
                {"action": "report_signal", "task_id": "ghost", "signal": "x"}))
            self.assertIs(result["ok"], False)
            runtime.close()

    def test_tool_mutations_stay_on_the_bound_route_but_the_operator_does_not(self):
        import json as _json
        module = load_plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            runtime.store.update_policy({"session_key": "agent:main:telegram:dm:1"})
            with patch.dict(os.environ, {"HERMES_SESSION_KEY": "agent:other:telegram:dm:9"}):
                denied = _json.loads(runtime.tool_control({"action": "resume"}))
                status = _json.loads(runtime.tool_control({"action": "status"}))
            self.assertIs(denied["ok"], False)
            self.assertIs(status["ok"], True)
            self.assertFalse(runtime.store.load_policy().enabled)
            with patch.dict(os.environ, {"HERMES_SESSION_KEY": "agent:main:telegram:dm:1"}):
                allowed = _json.loads(runtime.tool_control({"action": "resume"}))
            self.assertIs(allowed["ok"], True)
            self.assertTrue(runtime.store.load_policy().enabled)
            os.environ.pop("HERMES_SESSION_KEY", None)
            operator = _json.loads(runtime.control({"action": "pause"}))
            self.assertIs(operator["ok"], True)
            self.assertFalse(runtime.store.load_policy().enabled)
            runtime.close()

    def test_register_uses_the_plugin_load_scope_home_not_the_launch_environment(self):
        """Under gateway multiplex one process serves many profiles and
        os.environ['HERMES_HOME'] keeps the launch profile's home; the plugin
        load binds the owning profile through the hermes_constants contextvar,
        so register() must resolve its home there and never from the env."""
        import types
        module = load_plugin()
        class Facade:
            def register_tool(self, **kwargs): pass
            def register_command(self, *args, **kwargs): pass
            def register_skill(self, *args, **kwargs): pass
            def on_unload(self, *args): pass
        with tempfile.TemporaryDirectory() as launch_home, \
                tempfile.TemporaryDirectory() as owning_home:
            fake = types.ModuleType("hermes_constants")
            fake.get_hermes_home = lambda: Path(owning_home)
            sys.modules["hermes_constants"] = fake
            try:
                with patch.dict(os.environ, {"HERMES_HOME": launch_home}):
                    runtime = module.register(Facade(), background=False)
            finally:
                del sys.modules["hermes_constants"]
            self.assertEqual(runtime.home, Path(owning_home))
            runtime.close()

    def test_register_without_hermes_falls_back_to_the_environment_home(self):
        """Hosts without hermes_constants (tests, plain subprocesses) keep the
        documented HERMES_HOME/default-home resolution."""
        module = load_plugin()
        class Facade:
            def register_tool(self, **kwargs): pass
            def register_command(self, *args, **kwargs): pass
            def register_skill(self, *args, **kwargs): pass
            def on_unload(self, *args): pass
        with tempfile.TemporaryDirectory() as directory:
            self.assertNotIn("hermes_constants", sys.modules)
            with patch.dict(os.environ, {"HERMES_HOME": directory}):
                runtime = module.register(Facade(), background=False)
            self.assertEqual(runtime.home, Path(directory))
            runtime.close()

    def test_observer_starts_only_for_the_primary_profile(self):
        """A non-primary profile's runtime owns its own store but never
        observes or dispatches: proactivity belongs to the default primary."""
        module = load_plugin()
        class Facade:
            def __init__(self, profile):
                self.profile_name = profile
            def register_tool(self, **kwargs): pass
            def register_command(self, *args, **kwargs): pass
            def register_skill(self, *args, **kwargs): pass
            def on_unload(self, *args): pass
        with tempfile.TemporaryDirectory() as directory:
            secondary = module.register(Facade("coder"), home=Path(directory) / "coder",
                                        background=True)
            self.assertIsNone(secondary.worker)
            secondary.close()
            primary = module.register(Facade("default"), home=Path(directory) / "default",
                                      background=True)
            self.assertIsNotNone(primary.worker)
            self.assertTrue(primary.worker.is_alive())
            primary.close()

    def test_registration_does_not_start_another_agent_or_cli_injection(self):
        class Facade:
            def __init__(self):
                self.calls = []
            def get_config(self, name, default=None):
                return default
            def register_tool(self, **kwargs):
                self.calls.append(("tool", kwargs["name"]))
            def register_command(self, name, handler, **kwargs):
                self.calls.append(("command", name))
            def register_skill(self, name, path, **kwargs):
                self.calls.append(("skill", name))
            def register_hook(self, name, callback):
                self.calls.append(("hook", name))
            def on_unload(self, callback):
                self.cleanup = callback
            def inject_message(self, *args, **kwargs):
                raise AssertionError("Plugin registration must never inject")
        module = load_plugin()
        with tempfile.TemporaryDirectory() as directory:
            facade = Facade()
            runtime = module.register(facade, home=Path(directory), background=False)
            self.assertIn(("tool", "proactive_control"), facade.calls)
            self.assertIn(("command", "proactivity"), facade.calls)
            self.assertIn(("command", "watch"), facade.calls)
            self.assertIn(("skill", "proactive-primary"), facade.calls)
            self.assertIn(("skill", "workspace-operations"), facade.calls)
            self.assertIn(("skill", "workspace-setup"), facade.calls)
            self.assertFalse(runtime.gateway_ready())
            self.assertIsNone(runtime.tick())
            runtime.close()


if __name__ == "__main__":
    unittest.main()
