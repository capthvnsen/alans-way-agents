"""The external setup handoff must keep preference consent before restart."""
from pathlib import Path
import json
import re
import unittest


class SetupRestartOrderTests(unittest.TestCase):
    def test_autonomy_consent_precedes_checkout_plan_and_external_restart(self):
        skill = (Path(__file__).resolve().parents[1] / "alans-way" / "skills" /
                 "workspace-setup" / "SKILL.md").read_text(encoding="utf-8")
        offer = ("Want me to work on my own? I'll keep going until a job is done instead of "
                 "stopping to check in, double-check code changes before calling them done, "
                 "and fold in anything you send while I'm working. "
                 "(Recommended. Say no to keep things as they are.)")
        normalized = " ".join(skill.split())
        self.assertIn(offer, normalized)
        self.assertLess(normalized.index(offer), normalized.index("# Prepare a new checkout"))
        self.assertLess(normalized.index("# Prepare a new checkout"), normalized.index("**JSON setup plan**"))
        self.assertLess(normalized.index("**JSON setup plan**"),
                        normalized.index("**The gateway restart comes last, outside the gateway.**"))

    def test_app_plan_and_external_shell_use_the_same_desktop_pin(self):
        skill = (Path(__file__).resolve().parents[1] / "alans-way" / "skills" /
                 "workspace-setup" / "SKILL.md").read_text(encoding="utf-8")
        plan = json.loads(re.search(r"```json\n(.*?)\n```", skill, re.S).group(1))
        shell_pin = re.search(r"--desktop-ref ([0-9a-f]{40})", skill).group(1)
        self.assertEqual(plan["desktopRef"], shell_pin)
