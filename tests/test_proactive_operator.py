"""Operator-only route binding and native-model probe contracts."""
from pathlib import Path
from types import SimpleNamespace
import importlib
import json
import tempfile
import unittest
from test_proactive_plugin import load_plugin


class OperatorTests(unittest.TestCase):
    def test_empty_review_is_successful_silence_without_a_provider_call(self):
        module = load_plugin()
        operator = importlib.import_module(module.__name__ + ".proactive_operator")
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(SimpleNamespace(), Path(directory))
            result = operator.probe(runtime)
            self.assertTrue(result["ok"])
            self.assertTrue(result["skipped_no_evidence"])
            self.assertEqual(result["call_count"], 0)
            self.assertFalse(result["injected"])
            runtime.close()

    def test_binding_requires_existing_direct_telegram_route_and_leaves_paused(self):
        module = load_plugin()
        operator = importlib.import_module(module.__name__ + ".proactive_operator")
        route = "agent:main:telegram:dm:123456789"
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            runtime = module.Runtime(None, home)
            with self.assertRaises(ValueError): operator.bind(runtime, route)
            (home / "sessions").mkdir()
            index = home / "sessions/sessions.json"
            index.write_text(json.dumps({route: {"session_key": route, "platform": "telegram", "chat_type": "dm", "session_id": "sample"}}))
            operator.bind(runtime, route)
            self.assertEqual(runtime.store.load_policy().session_key, route)
            self.assertFalse(runtime.store.load_policy().enabled)
            with self.assertRaises(ValueError): operator.bind(runtime, "invented-route")
            runtime.close()

    def test_binding_falls_back_to_state_db_gateway_routing(self):
        """sessions.json is a legacy mirror that may not exist; the
        authoritative record is state.db's gateway_routing table — read-only,
        same validation, still fail-closed on anything else."""
        import sqlite3
        module = load_plugin()
        operator = importlib.import_module(module.__name__ + ".proactive_operator")
        route = "agent:main:telegram:dm:123456789"
        entry = {"session_key": route, "session_id": "abc123",
                 "platform": "telegram", "chat_type": "dm", "suspended": False}
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            db = sqlite3.connect(home / "state.db")
            db.execute("""CREATE TABLE gateway_routing (
                scope TEXT NOT NULL DEFAULT '', session_key TEXT NOT NULL,
                entry_json TEXT NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (scope, session_key))""")
            db.execute("INSERT INTO gateway_routing VALUES ('', ?, ?, 0)",
                       (route, json.dumps(entry)))
            group = dict(entry, session_key="agent:main:telegram:group:5",
                         chat_type="group")
            db.execute("INSERT INTO gateway_routing VALUES ('', ?, ?, 0)",
                       (group["session_key"], json.dumps(group)))
            db.commit(); db.close()
            runtime = module.Runtime(None, home)
            operator.bind(runtime, route)
            self.assertEqual(runtime.store.load_policy().session_key, route)
            self.assertFalse(runtime.store.load_policy().enabled)
            with self.assertRaises(ValueError):
                operator.bind(runtime, "agent:main:telegram:group:5")
            with self.assertRaises(ValueError):
                operator.bind(runtime, "invented-route")
            runtime.close()

    def test_binding_scopes_state_db_rows_to_this_sessions_dir(self):
        """gateway_routing's PK is (scope, session_key) where scope is the
        resolved sessions dir — a row owned by another store's scope must
        never verify this profile's route; the right scope must."""
        import sqlite3
        module = load_plugin()
        operator = importlib.import_module(module.__name__ + ".proactive_operator")
        route = "agent:main:telegram:dm:123456789"
        entry = {"session_key": route, "session_id": "abc123",
                 "platform": "telegram", "chat_type": "dm", "suspended": False}
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            db = sqlite3.connect(home / "state.db")
            db.execute("""CREATE TABLE gateway_routing (
                scope TEXT NOT NULL DEFAULT '', session_key TEXT NOT NULL,
                entry_json TEXT NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (scope, session_key))""")
            db.execute("INSERT INTO gateway_routing VALUES (?, ?, ?, 0)",
                       ("/some/other/sessions", route, json.dumps(entry)))
            db.commit(); db.close()
            runtime = module.Runtime(None, home)
            with self.assertRaises(ValueError):
                operator.bind(runtime, route)
            scope = str((home / "sessions").resolve())
            db = sqlite3.connect(home / "state.db")
            db.execute("INSERT INTO gateway_routing VALUES (?, ?, ?, 0)",
                       (scope, route, json.dumps(entry)))
            db.commit(); db.close()
            operator.bind(runtime, route)
            self.assertEqual(runtime.store.load_policy().session_key, route)
            runtime.close()

    def test_binding_authoritative_db_overrides_a_stale_mirror(self):
        """A sessions.json entry that fails validation cannot veto a route the
        authoritative gateway_routing table confirms — Hermes' own load order
        is DB primary, mirror fills keys the DB lacks."""
        import sqlite3
        module = load_plugin()
        operator = importlib.import_module(module.__name__ + ".proactive_operator")
        route = "agent:main:telegram:dm:123456789"
        entry = {"session_key": route, "session_id": "abc123",
                 "platform": "telegram", "chat_type": "dm", "suspended": False}
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / "sessions").mkdir()
            (home / "sessions/sessions.json").write_text(json.dumps(
                {route: dict(entry, platform="discord")}))
            db = sqlite3.connect(home / "state.db")
            db.execute("""CREATE TABLE gateway_routing (
                scope TEXT NOT NULL DEFAULT '', session_key TEXT NOT NULL,
                entry_json TEXT NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY (scope, session_key))""")
            db.execute("INSERT INTO gateway_routing VALUES ('', ?, ?, 0)",
                       (route, json.dumps(entry)))
            db.commit(); db.close()
            runtime = module.Runtime(None, home)
            operator.bind(runtime, route)
            self.assertEqual(runtime.store.load_policy().session_key, route)
            runtime.close()

    def test_binding_stays_fail_closed_without_any_routing_store(self):
        """No sessions.json and no state.db means no verifiable route — bind
        refuses rather than trusting a caller-supplied key."""
        module = load_plugin()
        operator = importlib.import_module(module.__name__ + ".proactive_operator")
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(None, Path(directory))
            with self.assertRaises(ValueError):
                operator.bind(runtime, "agent:main:telegram:dm:123456789")
            self.assertFalse(runtime.store.load_policy().session_key)
            runtime.close()

    def test_probe_confirms_a_real_facade_response_without_injecting(self):
        module = load_plugin()
        operator = importlib.import_module(module.__name__ + ".proactive_operator")
        class LLM:
            def complete_structured(self, **kwargs):
                return SimpleNamespace(content_type="json", parsed={"useful": False, "action": "ask", "task_id": None})
        with tempfile.TemporaryDirectory() as directory:
            runtime = module.Runtime(SimpleNamespace(llm=LLM()), Path(directory))
            runtime.ledger.record_task({"id": "handoff", "title": "Handoff", "scope": "Draft approved test matrix",
                                       "next_action": "Draft acceptance cases", "owner": "primary", "status": "active", "approved": True})
            result = operator.probe(runtime)
            self.assertTrue(result["provider_completion_returned"])
            self.assertTrue(result["structured_result_valid"])
            self.assertEqual(result["call_count"], 1)
            self.assertFalse(result["appraisal"]["useful"])
            self.assertEqual(runtime.store.status()["counts"], {})
            runtime.close()


if __name__ == "__main__": unittest.main()
