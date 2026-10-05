"""Identity documents and capability inventory: collection and review contract."""
from pathlib import Path
import importlib.util
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def plugin():
    name = "companion_identity_test"
    path = ROOT / "alans-way"
    spec = importlib.util.spec_from_file_location(name, path / "__init__.py", submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _Ledger:
    def snapshot(self):
        return {"tasks": [], "preferences": {"focus": [], "ignore": []}, "observations": {}}


class ObserveIdentityTests(unittest.TestCase):
    def setUp(self):
        self.mod = plugin()
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        from companion_identity_test import proactive_observe
        self.observe = proactive_observe

    def tearDown(self):
        self.tmp.cleanup()

    def test_identity_docs_carry_text_and_modified(self):
        (self.home / "SOUL.md").write_text("# who I am\nAn operator.")
        context, signatures = self.observe.collect(self.home, _Ledger(), None)
        self.assertEqual(len(context["documents"]), 1)
        doc = context["documents"][0]
        self.assertEqual(doc["source"], "SOUL.md")
        self.assertEqual(doc["text"], "# who I am\nAn operator.")
        self.assertTrue(doc["modified"])
        self.assertIn("SOUL.md", signatures)

    def test_doc_edit_changes_signature(self):
        (self.home / "AGENTS.md").write_text("v1")
        _, first = self.observe.collect(self.home, _Ledger(), None)
        (self.home / "AGENTS.md").write_text("v2")
        _, second = self.observe.collect(self.home, _Ledger(), None)
        self.assertNotEqual(first["AGENTS.md"], second["AGENTS.md"])

    def test_skills_dir_inventory(self):
        (self.home / "skills" / "email").mkdir(parents=True)
        (self.home / "skills" / "devops").mkdir()
        (self.home / "skills" / ".hidden").mkdir()
        (self.home / "skills" / "a file.txt").write_text("x")
        context, signatures = self.observe.collect(self.home, _Ledger(), None)
        self.assertEqual(context["capabilities"], ["devops", "email"])
        self.assertIn("skills", signatures)

    def test_missing_or_symlinked_skills_dir_is_absent(self):
        context, signatures = self.observe.collect(self.home, _Ledger(), None)
        self.assertEqual(context["capabilities"], [])
        self.assertNotIn("skills", signatures)


class ReviewIdentityContractTests(unittest.TestCase):
    def setUp(self):
        plugin()
        from companion_identity_test import proactive_review
        self.review = proactive_review

    def _context(self, **extra):
        return {"memory": [], "schedule": [], "tasks": [], "goals": [],
                "preferences": {}, "board": {}, **extra}

    def test_valid_documents_accepted(self):
        self.review._validate_snapshot(self._context(
            documents=[{"source": "SOUL.md", "text": "x", "modified": "2026-01-01T00:00:00+00:00"}],
            capabilities=["email"]))

    def test_unknown_document_source_rejected(self):
        with self.assertRaises(ValueError):
            self.review._validate_snapshot(self._context(
                documents=[{"source": "SECRET.md", "text": "x", "modified": "y"}]))

    def test_non_string_capability_rejected(self):
        with self.assertRaises(ValueError):
            self.review._validate_snapshot(self._context(capabilities=[{"name": "email"}]))

    def test_document_text_is_evidence(self):
        context = self._context(documents=[{"source": "AGENTS.md", "text": "rules", "modified": "x"}])
        self.assertTrue(self.review._has_evidence(context, set()))

    def test_capabilities_alone_are_not_evidence(self):
        self.assertFalse(self.review._has_evidence(self._context(capabilities=["email"]), set()))


if __name__ == "__main__":
    unittest.main()
