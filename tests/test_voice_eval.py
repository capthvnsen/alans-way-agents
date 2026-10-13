"""scripts/voice_eval.py builds valid requests without calling a model."""
from pathlib import Path
import importlib.util
import inspect
import json
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "voice_eval.py"
spec = importlib.util.spec_from_file_location("voice_eval", SCRIPT)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

try:
    import anthropic
except ImportError:
    anthropic = None


class DryRunTests(unittest.TestCase):
    def requests(self):
        out = []
        for s in E.SCENARIOS:
            for on in (False, True):
                system, user, _ = E.build(s, on)
                out.append(E.sdk_request("claude-opus-5-5", system, user))
                out.append(E.sdk_request("claude-opus-5-5", E.RUBRIC, user, E.SCHEMA))
        return out

    def test_requests_use_only_plain_messages_parameters(self):
        for request in self.requests():
            self.assertLessEqual(set(request), {"model", "max_tokens", "system", "messages", "output_config"})
            self.assertNotIn("fallbacks", request)

    @unittest.skipUnless(anthropic, "anthropic not installed (pip install anthropic==0.87.0)")
    def test_requests_bind_to_the_installed_sdk(self):
        create = inspect.signature(anthropic.resources.messages.Messages.create)
        for request in self.requests():
            create.bind(None, **request)   # TypeError on any unsupported argument

    def test_dry_run_calls_nothing(self):
        out = subprocess.run([sys.executable, str(SCRIPT), "--dry-run", "--only", "thanks", "cron_health"],
                             capture_output=True, text=True, timeout=60, env={"PATH": "/nonexistent"})
        self.assertEqual(out.returncode, 0, out.stderr)
        rows = [json.loads(line) for line in out.stdout.splitlines()]
        self.assertEqual([(r["id"], r["voice"]) for r in rows],
                         [("thanks", "before"), ("thanks", "after"), ("cron_health", "before"), ("cron_health", "after")])
        after = {r["id"]: r["request"]["messages"][0]["content"] for r in rows if r["voice"] == "after"}
        self.assertIn("[Texting voice]", after["thanks"])
        self.assertNotIn("[Texting voice]", after["cron_health"])   # cron keeps the default voice

    def test_cron_after_uses_the_identity_transform_like_production(self):
        cron = next(s for s in E.SCENARIOS if s["kind"] == "cron")
        _, _, deliver = E.build(cron, True)
        self.assertEqual(deliver("Certainly! Disk is at 91%."), "Certainly! Disk is at 91%.")
        chat = next(s for s in E.SCENARIOS if s["id"] == "thanks")
        self.assertEqual(E.build(chat, True)[2]("Certainly! Anytime."), "Anytime.")


if __name__ == "__main__":
    unittest.main()
