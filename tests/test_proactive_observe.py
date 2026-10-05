"""Own-profile observations are hashes; idle observation never calls an LLM."""
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def plugin():
    name = "companion_proactive_observe_test"
    path = ROOT / "alans-way"
    spec = importlib.util.spec_from_file_location(name, path / "__init__.py", submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ObservationTests(unittest.TestCase):
    def test_native_changes_wake_once_and_completed_tasks_cannot_continue(self):
        class Host:
            status = "running"
            def dispatch_tool(self, name, args):
                self.last_call = (name, args)
                return {"task": {"id": "native-card", "status": self.status}}
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            host = Host()
            runtime = module.Runtime(host, Path(directory))
            runtime.store.update_policy({"session_key": "agent:main:telegram:dm:123456789"})
            runtime.ledger.record_task({"id": "watch", "title": "Approved work", "scope": "Review approved draft",
                "next_action": "Verify result", "owner": "primary", "status": "active", "approved": True,
                "native_task_id": "native-card"})
            self.assertEqual(runtime.observe(), 0)
            host.status = "done"
            self.assertEqual(runtime.observe(), 1)
            self.assertEqual(runtime.observe(), 0)
            self.assertEqual(runtime.review_context()["tasks"][0]["status"], "done")
            self.assertEqual(host.last_call, ("kanban_show", {"task_id": "native-card"}))
            self.assertEqual(runtime.store.status()["counts"], {"pending": 1})
            runtime.close()

    def test_missing_native_task_never_falls_back_to_ledger_approval(self):
        from types import SimpleNamespace
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(SimpleNamespace(dispatch_tool=lambda *_: {"error": "offline"}), Path(directory))
            runtime.ledger.record_task({"id": "watch", "title": "Approved work", "scope": "Review draft",
                "next_action": "Verify", "owner": "primary", "status": "active", "approved": True,
                "native_task_id": "native-card"})
            self.assertEqual(runtime.review_context()["tasks"][0]["status"], "blocked")
            self.assertEqual(runtime.ledger.snapshot()["tasks"][0]["status"], "active")
            runtime.close()

    def test_actual_reviewer_accepts_the_collected_authorized_task_shape(self):
        from types import SimpleNamespace
        module = plugin()
        review = __import__(module.__name__ + ".proactive_review", fromlist=["review"]).review
        class LLM:
            def __init__(self): self.calls = 0
            def complete_structured(self, **kwargs):
                self.calls += 1
                return SimpleNamespace(content_type="json", parsed={"useful": True, "action": "draft", "task_id": "handoff"})
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            runtime.ledger.record_task({"id": "handoff", "title": "Handoff", "scope": "Draft approved acceptance cases",
                                        "next_action": "Draft test matrix", "owner": "primary", "status": "active", "approved": True})
            llm = LLM()
            context = runtime.review_context()
            self.assertIn("reviewed_at_utc", context["preferences"])
            self.assertEqual(context["goals"][0]["source"], "approved-watch")
            result = review(SimpleNamespace(llm=llm), context, "manual_review")
            self.assertTrue(result["useful"])
            self.assertEqual(llm.calls, 1)
            runtime.close()

    def test_due_watch_admits_one_event_and_writes_heartbeat(self):
        from datetime import datetime, timedelta, timezone
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            runtime.store.update_policy({"session_key": "agent:main:telegram:dm:123456789"})
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            runtime.ledger.record_task({"id": "rent", "title": "Rent", "scope": "Check rent posts",
                "next_action": "Check feed", "owner": "primary", "status": "active",
                "approved": True, "next_review_at": past})
            self.assertEqual(runtime.observe(), 1)
            # A pending wake for the same watch suppresses pile-up, even as the
            # lag bucket would escalate the evidence.
            self.assertEqual(runtime.observe(), 0)
            self.assertEqual(runtime.store.status()["counts"], {"pending": 1})
            self.assertIsNotNone(runtime.ledger.snapshot()["observed_at"])
            runtime.close()

    def test_deadline_escalates_through_distinct_buckets(self):
        from datetime import datetime, timedelta, timezone
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            runtime.store.update_policy({"enabled": True,
                "session_key": "agent:main:telegram:dm:123456789",
                "debounce_seconds": 0, "min_interval_seconds": 0,
                "quiet_start": 0, "quiet_end": 0})
            due = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
            watch = {"id": "visa", "title": "Visa", "scope": "Track renewal",
                     "next_action": "Check status", "owner": "primary", "status": "active",
                     "approved": True, "due_at": due}
            runtime.ledger.record_task(watch)
            self.assertEqual(runtime.observe(), 1)  # enters the 3-day window
            self.assertEqual(runtime.observe(), 0)  # same pending wake
            event = runtime.store.claim()
            runtime.store.finish(event["id"], "resolved")
            # Moving the deadline mints a fresh event for the new instance.
            watch["due_at"] = (datetime.now(timezone.utc) + timedelta(days=6)).isoformat()
            runtime.ledger.record_task(watch)
            self.assertEqual(runtime.observe(), 1)
            runtime.close()

    def test_unapproved_or_terminal_watches_never_fire(self):
        from datetime import datetime, timedelta, timezone
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            runtime.store.update_policy({"session_key": "agent:main:telegram:dm:123456789"})
            past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            runtime.ledger.record_task({"id": "gone", "title": "T", "scope": "S",
                "next_action": "N", "owner": "primary", "status": "active",
                "approved": True, "next_review_at": past})
            runtime.ledger.finish_task("gone", "done")
            self.assertEqual(runtime.observe(), 0)
            runtime.close()

    def test_signal_change_wakes_but_repeats_and_first_baseline_do_not(self):
        from types import SimpleNamespace
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(SimpleNamespace(), Path(directory))
            runtime.store.update_policy({"session_key": "agent:main:telegram:dm:123456789"})
            runtime.ledger.record_task({"id": "inbox", "title": "Inbox", "scope": "Watch thread",
                "next_action": "Diff thread", "owner": "primary", "status": "active", "approved": True})
            runtime.ledger.report_signal("inbox", "thread quiet")
            self.assertEqual(runtime.observe(), 0)  # first observation baselines
            runtime.ledger.report_signal("inbox", "thread quiet")  # unchanged
            self.assertEqual(runtime.observe(), 0)
            runtime.ledger.report_signal("inbox", "new reply from Dana")
            self.assertEqual(runtime.observe(), 1)
            self.assertEqual(runtime.observe(), 0)
            runtime.close()

    def test_report_signal_rejects_unknown_terminal_and_malformed_input(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            for task_id, signal in [("missing", "x"), ("bad id!", "x"),
                                    ("ok", "x" * 1001), ("ok", 42)]:
                with self.subTest(task_id=task_id):
                    with self.assertRaises(ValueError):
                        runtime.ledger.report_signal(task_id, signal)
            runtime.ledger.record_task({"id": "term", "title": "T", "scope": "S",
                "next_action": "N", "owner": "primary", "status": "active", "approved": True})
            runtime.ledger.finish_task("term", "cancelled")
            with self.assertRaises(ValueError):
                runtime.ledger.report_signal("term", "x")
            runtime.close()

    def test_memory_change_is_observed_once_without_persisting_its_text(self):
        module = plugin()
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "memories").mkdir()
            memory = home / "memories/MEMORY.md"
            memory.write_text("Private approved project evidence", encoding="utf-8")
            runtime = module.Runtime(None, home)
            runtime.store.update_policy({"session_key": "agent:main:telegram:dm:123456789"})
            self.assertEqual(runtime.observe(), 0)
            memory.write_text("Private approved project evidence updated", encoding="utf-8")
            self.assertEqual(runtime.observe(), 1)
            self.assertEqual(runtime.observe(), 0)
            self.assertEqual(runtime.store.status()["counts"], {"pending": 1})
            context = runtime.review_context()
            self.assertEqual(context["memory"][0]["text"], memory.read_text())
            ledger = (home / "companion/proactivity/ledger.json").read_text()
            self.assertNotIn("Private approved project evidence", ledger)
            restarted = module.Runtime(None, home)
            self.assertEqual(restarted.observe(), 0)
            runtime.close()
            restarted.close()


if __name__ == "__main__":
    unittest.main()
