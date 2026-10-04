"""Shared-board oversight: sweep, signature, and review-contract acceptance."""
from pathlib import Path
import importlib.util
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def plugin():
    name = "companion_board_test"
    path = ROOT / "proactive-primary"
    spec = importlib.util.spec_from_file_location(name, path / "__init__.py", submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_db(home: Path, rows):
    db = sqlite3.connect(home / "kanban.db")
    db.execute("CREATE TABLE tasks (id TEXT, title TEXT, status TEXT,"
               " assignee TEXT, created_by TEXT, created_at REAL)")
    db.executemany("INSERT INTO tasks VALUES (?,?,?,?,?,?)", rows)
    db.commit()
    db.close()


class BoardSweepTests(unittest.TestCase):
    def setUp(self):
        self.mod = plugin()
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_db_returns_empty(self):
        from companion_board_test.proactive_board import collect_board
        self.assertEqual(collect_board(self.home), {})

    def test_schema_mismatch_returns_empty(self):
        db = sqlite3.connect(self.home / "kanban.db")
        db.execute("CREATE TABLE tasks (other TEXT)")
        db.close()
        from companion_board_test.proactive_board import collect_board
        self.assertEqual(collect_board(self.home), {})

    def test_open_and_recently_closed_split(self):
        import time
        now = time.time()
        make_db(self.home, [
            ("t_a", "Draft the launch post", "blocked", "writer", "dashboard", now - 60),
            ("t_b", "Restart dashboard", "done", "@default", "dashboard", now - 30),
            ("t_c", "Ancient archive", "archived", "turing", "dashboard", now - 60 * 86400),
        ])
        from companion_board_test.proactive_board import collect_board
        board = collect_board(self.home)
        self.assertEqual([c["id"] for c in board["open"]], ["t_a"])
        closed_ids = [c["id"] for c in board["recently_closed"]]
        self.assertIn("t_b", closed_ids)
        self.assertNotIn("t_c", closed_ids)

    def test_signature_changes_with_board(self):
        from companion_board_test.proactive_board import collect_board, board_signature
        make_db(self.home, [("t_a", "x", "running", "writer", "d", 1)])
        first = board_signature(collect_board(self.home))
        db = sqlite3.connect(self.home / "kanban.db")
        db.execute("UPDATE tasks SET status='blocked' WHERE id='t_a'")
        db.commit()
        db.close()
        second = board_signature(collect_board(self.home))
        self.assertTrue(first)
        self.assertNotEqual(first, second)

    def test_collect_context_carries_board_and_signature(self):
        import time
        make_db(self.home, [("t_a", "Oversee me", "blocked", "writer", "d", time.time())])
        from companion_board_test import proactive_observe
        context, signatures = proactive_observe.collect(self.home, _Ledger(), None)
        self.assertEqual(context["board"]["open"][0]["id"], "t_a")
        self.assertIn("board", signatures)


class _Ledger:
    def snapshot(self):
        return {"tasks": [], "preferences": {"focus": [], "ignore": []}, "observations": {}}


class ReviewBoardContractTests(unittest.TestCase):
    def setUp(self):
        plugin()

    def _context(self, board):
        return {"memory": [], "schedule": [], "tasks": [], "goals": [],
                "preferences": {}, "board": board}

    def test_valid_board_accepted(self):
        from companion_board_test.proactive_review import _validate_snapshot
        _validate_snapshot(self._context({
            "open": [{"id": "t_a", "title": "x", "status": "blocked",
                      "assignee": "w", "created_by": "d"}],
            "recently_closed": []}))

    def test_bad_card_status_rejected(self):
        from companion_board_test.proactive_review import _validate_snapshot
        with self.assertRaises(ValueError):
            _validate_snapshot(self._context({
                "open": [{"id": "t_a", "title": "x", "status": "bogus",
                          "assignee": "", "created_by": ""}]}))

    def test_open_card_is_evidence(self):
        from companion_board_test.proactive_review import _has_evidence
        context = self._context({"open": [{"id": "t_a", "title": "needs review", "status": "blocked",
                                           "assignee": "", "created_by": ""}]})
        self.assertTrue(_has_evidence(context, set()))

    def test_empty_board_is_not_evidence(self):
        from companion_board_test.proactive_review import _has_evidence
        self.assertFalse(_has_evidence(self._context({"open": []}), set()))


if __name__ == "__main__":
    unittest.main()
