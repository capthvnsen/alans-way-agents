"""Exploratory wakes run as one-shot stock cron jobs; watches stay in the main session."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "alans-way"
ROUTE = "agent:main:telegram:dm:123456789"


def load_plugin():
    name = "companion_proactive_isolated_test"
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py",
                                                submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Ctx:
    def __init__(self, create_ok=True, tool="cronjob_manage"):
        self.calls, self.injected, self.jobs, self.created = [], [], {}, 0
        self.create_ok, self.tool = create_ok, tool

    def inject_message(self, message, **kwargs):
        self.injected.append(message)
        return True

    def dispatch_tool(self, name, args, **kwargs):
        self.calls.append((name, dict(args)))
        if name != self.tool:
            return json.dumps({"error": f"Unknown tool: {name}", "success": False})
        if args["action"] == "create":
            if not self.create_ok:
                return json.dumps({"success": False, "error": "Blocked"})
            self.created += 1
            job_id = f"job{self.created}"
            self.jobs[job_id] = {"job_id": job_id, "name": args["name"], "state": "scheduled", "last_status": None}
            return json.dumps({"success": True, "job_id": job_id})
        if args["action"] == "list":
            return json.dumps({"success": True, "jobs": list(self.jobs.values())})
        if args["action"] == "remove":
            self.jobs.pop(args["job_id"], None)
            return json.dumps({"success": True})
        raise AssertionError(args)


class IsolatedWakeTests(unittest.TestCase):
    def runtime(self, ctx, directory, route=ROUTE):
        module = load_plugin()
        guard = sys.modules[module.__name__ + ".gateway_guard"]
        home = Path(directory)
        runtime = module.Runtime(ctx, home, appraiser=lambda *_: {"useful": True, "action": "ask", "task_id": None})
        runtime.store.update_policy({"session_key": route, "debounce_seconds": 0, "min_interval_seconds": 0,
                                     "min_watch_interval_seconds": 0, "quiet_start": 0, "quiet_end": 0})
        guard.mark_gateway_ready(home)
        return runtime

    def watch(self, runtime, kind, **extra):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        runtime.ledger.record_task({"id": "w", "kind": kind, "title": "T", "scope": "S", "next_action": "N",
                                    "owner": "primary", "status": "active", "approved": True,
                                    "next_review_at": past, **extra})
        self.assertEqual(runtime.observe(), 1)

    def test_review_first_run_sweep_and_loop_run_as_isolated_cron_jobs(self):
        arrangers = {
            "review": lambda r: r.store.record_event("context_changed", "e" * 64, purpose=True),
            "first_run": lambda r: r._admit_first_run(),
            "sweep": lambda r: self.watch(r, "sweep"),
            "loop": lambda r: self.watch(r, "loop"),
        }
        for kind, arrange in arrangers.items():
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                ctx = Ctx()
                runtime = self.runtime(ctx, directory)
                arrange(runtime)
                result = runtime.tick()
                self.assertEqual(result["status"], "isolated")
                self.assertEqual(ctx.injected, [])
                (name, args), = ctx.calls
                self.assertEqual(name, "cronjob_manage")
                self.assertEqual((args["action"], args["schedule"], args["deliver"], args["attach_to_session"]),
                                 ("create", "in 1m", "telegram:123456789", True))
                self.assertTrue(args["name"].startswith("aw-wake-"))
                self.assertIn("reply with exactly [SILENT]", args["prompt"])
                self.assertIn("one-shot background run", args["prompt"])
                self.assertEqual(runtime.store.status()["counts"], {"resolved": 1})
                self.assertEqual(list(runtime.ledger.tracked_jobs()), ["job1"])
                runtime.close()

    def test_plain_watch_wakes_keep_using_the_main_session(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = Ctx()
            runtime = self.runtime(ctx, directory)
            self.watch(runtime, "watch")
            self.assertEqual(runtime.tick()["status"], "accepted_unverified")
            self.assertEqual(ctx.calls, [])
            self.assertEqual(len(ctx.injected), 1)
            runtime.close()

    def test_any_cron_problem_falls_back_to_the_main_session(self):
        cases = {
            "create refused": (Ctx(create_ok=False), ROUTE),
            "unknown tool": (Ctx(tool="other"), ROUTE),
            "no dispatch_tool": (type("C", (), {"inject_message": lambda self, m, **k: True})(), ROUTE),
            "not a telegram dm": (Ctx(), "agent:main:discord:dm:5"),
        }
        for label, (ctx, route) in cases.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as directory:
                runtime = self.runtime(ctx, directory, route)
                runtime.store.record_event("context_changed", "e" * 64, purpose=True)
                self.assertEqual(runtime.tick()["status"], "accepted_unverified")
                self.assertEqual(runtime.ledger.tracked_jobs(), {})
                runtime.close()

    def test_older_hermes_tool_name_is_tried_too(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = Ctx(tool="cronjob")
            runtime = self.runtime(ctx, directory)
            runtime.store.record_event("context_changed", "e" * 64, purpose=True)
            self.assertEqual(runtime.tick()["status"], "isolated")
            self.assertEqual([name for name, _ in ctx.calls], ["cronjob_manage", "cronjob"])
            runtime.close()

    def test_finished_jobs_are_removed_and_their_outcome_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = Ctx()
            runtime = self.runtime(ctx, directory)
            for index in range(2):
                runtime.store.record_event("context_changed", f"{index:064d}", purpose=True)
                self.assertEqual(runtime.tick()["status"], "isolated")
                ctx.jobs[f"job{index + 1}"].update(state="completed", last_status="ok")
            runtime.observe()
            self.assertEqual(ctx.jobs, {})
            self.assertEqual(runtime.ledger.tracked_jobs(), {})
            self.assertEqual([entry["outcome"] for entry in runtime.ledger.recent_log()], ["ran", "ran"])
            runtime.close()

    def test_isolated_runs_carry_the_context_they_cannot_read(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = Ctx()
            runtime = self.runtime(ctx, directory)
            runtime.ledger.preferences({"focus": ["rent", "taxes"], "ignore": ["newsletters"], "max_work_minutes": 7})
            runtime.ledger.record_task({"id": "rent", "title": "Rent", "scope": "Check the rent posting",
                "next_action": "Read the bank feed", "owner": "primary", "status": "active", "approved": True})
            runtime._appraiser = lambda *_: {"useful": True, "action": "research", "task_id": "rent"}
            runtime.store.record_event("context_changed", "e" * 64, purpose=True)
            runtime.tick()
            prompt = ctx.calls[0][1]["prompt"]
            for text in ("Focus: rent, taxes", "Ignore: newsletters", "Max work minutes: 7",
                         "Watch rent: scope Check the rent posting", "Next action: Read the bank feed"):
                self.assertIn(text, prompt)
            runtime.close()

    def first_run_done(self, runtime):
        with runtime.ledger.transaction() as data:
            return bool(data["observations"].get("first_run_done"))

    def test_first_run_is_done_only_once_its_job_ran_and_a_missed_one_retries_once(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = Ctx()
            runtime = self.runtime(ctx, directory)
            runtime._admit_first_run()
            self.assertEqual(runtime.tick()["status"], "isolated")
            self.assertFalse(self.first_run_done(runtime))
            runtime.store.record_event("first_run", "firstrun:dup", purpose=True)
            self.assertEqual(runtime.tick()["status"], "stale")
            ctx.jobs["job1"].update(state="completed", last_status="ok")
            runtime.observe()
            self.assertTrue(self.first_run_done(runtime))
            runtime.close()
        for bad in ("failed", "gone"):
            with self.subTest(bad), tempfile.TemporaryDirectory() as directory:
                ctx = Ctx()
                runtime = self.runtime(ctx, directory)
                runtime._admit_first_run()
                runtime.tick()
                if bad == "failed":
                    ctx.jobs["job1"].update(state="completed", last_status="error")
                else:
                    ctx.jobs.clear()
                runtime.observe()
                self.assertFalse(self.first_run_done(runtime))
                self.assertEqual(runtime.store.status()["counts"].get("pending"), 1)
                self.assertEqual(runtime.tick()["status"], "isolated")
                ctx.jobs["job2"].update(state="completed", last_status="error")
                runtime.observe()
                self.assertEqual(runtime.store.status()["counts"].get("pending", 0), 0)
                runtime.close()

    def test_failed_stuck_and_listing_failures_are_handled(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = Ctx()
            runtime = self.runtime(ctx, directory)
            runtime.store.record_event("context_changed", "a" * 64, purpose=True)
            runtime.tick()
            ctx.jobs["job1"].update(state="completed", last_status="delivery_failed")
            runtime.observe()
            self.assertEqual(runtime.ledger.recent_log()[-1]["outcome"], "failed")
            runtime.store.record_event("context_changed", "b" * 64, purpose=True)
            runtime.tick()
            with runtime.ledger.transaction() as data:
                data["observations"]["__cron"]["job2"]["at"] = (
                    datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
            runtime.observe()
            self.assertNotIn("job2", ctx.jobs)
            self.assertEqual(runtime.ledger.recent_log()[-1]["outcome"], "expired")
            runtime.store.record_event("context_changed", "c" * 64, purpose=True)
            runtime.tick()
            ctx.tool = "gone"
            runtime.observe()
            self.assertEqual(list(runtime.ledger.tracked_jobs()), ["job3"])
            runtime.close()

    def test_own_wake_jobs_never_count_as_schedule_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            module = load_plugin()
            observe = sys.modules[module.__name__ + ".proactive_observe"]
            home = Path(directory)
            (home / "cron").mkdir()
            runtime = module.Runtime(None, home)
            def collect(jobs):
                (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": jobs}))
                context, signatures = observe.collect(home, runtime.ledger)
                return context["schedule"], signatures["cron/jobs.json"]
            brief = {"id": "a", "name": "brief", "enabled": True, "schedule": "0 8 * * *"}
            first = collect([brief])
            second = collect([brief, {"id": "z", "name": "aw-wake-1234abcd", "enabled": True, "schedule": "once"}])
            self.assertEqual(first, second)
            runtime.close()

    def test_isolated_runs_may_only_report_signals_and_finish_watches(self):
        from unittest.mock import patch
        import os
        with tempfile.TemporaryDirectory() as directory:
            runtime = self.runtime(Ctx(), directory)
            runtime.ledger.record_task({"id": "w", "title": "T", "scope": "S", "next_action": "N",
                                        "owner": "primary", "status": "active", "approved": True})
            call = lambda args: json.loads(runtime.tool_control(args))["ok"]
            self.assertFalse(call({"action": "report_signal", "task_id": "w", "signal": "x"}))
            with patch.dict(os.environ, {"HERMES_CRON_SESSION": "1"}):
                self.assertTrue(call({"action": "report_signal", "task_id": "w", "signal": "x"}))
                self.assertFalse(call({"action": "pause"}))
                self.assertFalse(call({"action": "record_task", "task": {"id": "n"}}))
                self.assertFalse(call({"action": "configure", "changes": {"quiet_start": 1}}))
                self.assertTrue(call({"action": "finish_task", "task_id": "w", "status": "done"}))
            runtime.close()

    def test_activity_log_records_wakes_and_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            ctx = Ctx()
            runtime = self.runtime(ctx, directory)
            runtime.store.record_event("context_changed", "a" * 64, purpose=True)
            runtime.tick()
            runtime._appraiser = lambda *_: {"useful": False}
            runtime.store.record_event("context_changed", "b" * 64, purpose=True)
            runtime.tick()
            log = runtime.ledger.recent_log()
            self.assertEqual([(e["kind"], e["outcome"]) for e in log], [("review", "queued"), ("review", "rejected")])
            text = runtime.operate("log")
            self.assertIn("review", text)
            self.assertIn("[rejected]", text)
            self.assertNotIn("—", text)
            runtime.close()


if __name__ == "__main__":
    unittest.main()
