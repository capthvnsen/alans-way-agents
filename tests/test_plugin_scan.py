"""Run with HERMES_SCANNER_ROOT pointing at an extracted upstream Hermes scanner."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("HERMES_SCANNER_ROOT"), "upstream Hermes scanner not supplied")
class PluginScanTests(unittest.TestCase):
    def test_only_reviewed_local_setup_and_scoped_mastodon_capabilities_are_flagged(self):
        code = '''from pathlib import Path
from tools.plugin_guard import scan_plugin, should_allow_plugin_install
result = scan_plugin(Path("alans-way"))
findings = {(f.pattern_id, f.severity, f.file) for f in result.findings}
assert findings == {
    ("python_os_environ", "high", "skills/integrations/references/mastodon.md"),
    ("python_subprocess", "medium", "skills/workspace-setup/SKILL.md"),
    ("hardcoded_ip_port", "low", "skills/workspace-setup/SKILL.md")}, findings
assert result.verdict == "caution", result.verdict
assert should_allow_plugin_install(result)[0] is None
assert should_allow_plugin_install(result, force=True)[0] is True
result.verdict = "dangerous"
assert should_allow_plugin_install(result, force=True)[0] is False
'''
        env = dict(os.environ, PYTHONPATH=os.environ["HERMES_SCANNER_ROOT"])
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
