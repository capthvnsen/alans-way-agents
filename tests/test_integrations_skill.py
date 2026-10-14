"""Integration skill contract: discovery, real tools, safe opt-in recipes."""
from pathlib import Path
import importlib.util
import json
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "alans-way" / "skills" / "integrations"
SKILL = SKILL_DIR / "SKILL.md"
RECIPES = {"hermes-native.md", "rclone.md", "taskwarrior.md", "mastodon.md"}
# Verified at Hermes 1f6c02c07c and official homeassistant a4e311e433.
TOOLS = {"skills_list", "skill_view", "terminal", "cronjob_manage",
         "ha_list_entities", "ha_get_state"}


def _register_calls(profile_name):
    plugin = ROOT / "alans-way"
    name = "alans_way_integrations_test"
    spec = importlib.util.spec_from_file_location(
        name, plugin / "__init__.py", submodule_search_locations=[str(plugin)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    calls, state = [], {}
    ctx = SimpleNamespace(
        profile_name=profile_name,
        state=SimpleNamespace(get=state.get, set=lambda k, v: state.__setitem__(k, v)),
        register_tool=lambda **kw: None,
        register_hook=lambda *args: None,
        register_skill=lambda skill, path: calls.append(("skill", skill, path)),
        register_command=lambda *args, **kw: None,
        on_unload=lambda fn: None,
    )
    with tempfile.TemporaryDirectory() as home:
        module.register(ctx, legacy_home=home, background=False)
    return calls


class IntegrationsSkillTests(unittest.TestCase):
    def read_skill(self):
        self.assertTrue(SKILL.is_file(), "integration router must ship")
        return SKILL.read_text()

    def read_all(self):
        return self.read_skill() + "\n" + "\n".join(
            p.read_text() for p in sorted((SKILL_DIR / "references").glob("*.md")))

    def test_registration_loads_for_primary_and_secondary_profiles(self):
        for profile in ("default", "secondary"):
            calls = _register_calls(profile_name=profile)
            skills = {c[1]: c[2] for c in calls if c[0] == "skill"}
            self.assertEqual(Path(skills.get("integrations", "missing")), SKILL)
        self.read_skill()

    def test_frontmatter_discovers_missing_connections(self):
        text = self.read_skill()
        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(match)
        self.assertRegex(match[1], r"(?m)^name: integrations$")
        description = re.search(r"(?m)^description: (.+)$", match[1]).group(1)
        description = json.loads(description)  # quoted YAML string, no YAML dependency
        self.assertIsInstance(description, str)
        self.assertLessEqual(len(description), 1024)
        for need in ("email", "calendar", "contacts", "files", "tasks", "home", "social"):
            self.assertIn(need, description)
        self.assertIn("isn't connected", description)

    def test_every_reference_is_reachable_and_every_recipe_is_complete(self):
        text = self.read_skill()
        refs = SKILL_DIR / "references"
        self.assertEqual({p.name for p in refs.glob("*.md")}, RECIPES)
        for name in RECIPES:
            self.assertIn(f"references/{name}", text)
            recipe = (refs / name).read_text()
            for section in re.split(r"(?m)^## Recipe: ", recipe)[1:]:
                for field in ("License:", "Footprint:", "Connect:", "Verify:", "Remove:"):
                    self.assertIn(field, section, f"{name}: {field}")
            self.assertIn("## Recipe:", recipe)
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" not in link:
                self.assertTrue((SKILL_DIR / link.split("#")[0]).resolve().is_file())

    def test_only_real_tools_are_named(self):
        text = self.read_all()
        # Callable tool examples start their inline span with the name.
        # Embedded CLI Python/SDK methods are commands, not Hermes tools.
        calls = set(re.findall(r"`([a-z][a-z_]+)\(", text))
        declared = set(re.findall(r"Tool: `([a-z][a-z_]+)`", text))
        identifiers = {n for n in re.findall(r"`([a-z][a-z_]+)`", text) if "_" in n}
        mentioned = calls | declared | identifiers
        self.assertTrue(mentioned)
        self.assertEqual(mentioned - TOOLS, set())

    def test_no_secrets_or_unfinished_scaffolds(self):
        spec = importlib.util.spec_from_file_location("publication_integrations", ROOT / "scripts/check_publication.py")
        publication = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publication)
        self.read_skill()
        for path in SKILL_DIR.rglob("*"):
            if path.is_file():
                self.assertEqual(publication.inspect_text(str(path.relative_to(ROOT)), path.read_text()), [])
                self.assertNotRegex(path.read_text(), r"\b(?:TODO|TBD|FIXME)\b|(?i:\b(?:YOUR_TOKEN|SECRET_TOKEN|changeme)\b)")
                self.assertNotRegex(path.read_text(), r"(?m)^\s*(?:access_token|refresh_token|client_secret|HASS_TOKEN|MASTODON_ACCESS_TOKEN)\s*=\s*['\"][^'\"]+['\"]")

    def test_installs_are_pinned_and_require_consent(self):
        text = self.read_all()
        self.assertIn("Ask before installing any package", text)
        for filename, pin in (("rclone.md", "1.75.2"), ("taskwarrior.md", "3.5.0"), ("mastodon.md", "2.2.2")):
            recipe = (SKILL_DIR / "references" / filename).read_text()
            self.assertIn(pin, recipe)
            self.assertIn("Install:", recipe)
            self.assertIn("after consent", recipe)

    def test_probe_proves_task_scope_and_handles_revoked_auth(self):
        text = self.read_skill()
        for phrase in ("before promising", "read-only", "requested account", "requested scope",
                       "revoked", "unreachable", "wrong account", "I can't see your calendar yet"):
            self.assertIn(phrase, text)
        self.assertIn("binary presence is not a connection", text)

    def test_credentials_stay_out_of_chat_and_model(self):
        text = self.read_all()
        for phrase in ("Never put secrets in Telegram", "user-controlled terminal",
                       "profile's `.env`", "localhost", "device-code", "pending OAuth"):
            self.assertIn(phrase, text)
        self.assertIn("Do not read credential files", text)
        self.assertNotIn("gws auth login", text)

    def test_reuses_native_routes_and_preserves_write_approval(self):
        text = " ".join(self.read_all().split())
        for native in ("google-workspace", "himalaya", "homeassistant", "honcho", "xurl"):
            self.assertIn(native, text)
        self.assertIn("API writes do not inherit the browser commit gate", text)
        self.assertIn("exact action", text)
        self.assertIn("never retry an ambiguous write", text)
        self.assertIn("no new service", text)

    def test_scheduled_reads_recheck_and_stop_on_auth_failure(self):
        text = self.read_skill()
        for phrase in ("cronjob_manage", "self-contained", "delivery", "reauthorization", "pause"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
