"""Byte-for-byte generated packages plus the CLI and output contract."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator
from test_shared_config import ROOT, example

spec = importlib.util.spec_from_file_location('grok_generator', ROOT / 'scripts/generate_grok_bot.py')
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)


class GeneratorTests(unittest.TestCase):
    def test_golden_packages_and_settings_schema(self):
        schema = json.loads((ROOT / 'alans-way-grok-bot/settings.schema.json').read_text())
        Draft202012Validator.check_schema(schema)
        for enabled, directory in ((False, ROOT / 'alans-way-grok-bot'),
                                   (True, ROOT / 'tests/fixtures/grok-enabled')):
            with self.subTest(enabled=enabled):
                config = example()
                config['proactivity']['enabled'] = enabled
                skill, settings = G.render(config)
                self.assertEqual(skill, (directory / 'SKILL.md').read_text())
                self.assertEqual(settings, (directory / 'settings.json').read_text())
                Draft202012Validator(schema).validate(json.loads(settings))
                self.assertTrue(skill.startswith('---\nname: alans-way-grok-bot\ndescription:'))
                self.assertEqual(len(skill.split('---')[1].strip().splitlines()), 2)
                self.assertEqual(len(json.loads(settings)['routines']), int(enabled))

    def test_cli_is_deterministic_and_cwd_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'generated'
            command = [sys.executable, str(ROOT / 'scripts/generate_grok_bot.py'),
                       '--config', str(ROOT / 'shared/config.example.json'), '--output', str(output)]
            for _ in range(2):
                result = subprocess.run(command, cwd=tmp, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                for name in ('SKILL.md', 'settings.json'):
                    self.assertEqual((output / name).read_bytes(), (ROOT / 'alans-way-grok-bot' / name).read_bytes())

    def test_invalid_cli_input_leaves_existing_output_untouched_and_redacts_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            output = Path(tmp) / 'output'
            output.mkdir()
            (output / 'SKILL.md').write_text('keep')
            path.write_text('{"private-value": true}')
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/generate_grok_bot.py'),
                                     '--config', str(path), '--output', str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('private-value', result.stderr)
            self.assertEqual((output / 'SKILL.md').read_text(), 'keep')
            self.assertFalse((output / 'settings.json').exists())

    def test_render_validates_and_serializes_arbitrary_preference_text(self):
        with self.assertRaises(G.ConfigError):
            G.render({})
        config = example()
        text = 'Name: "quoted"\n---\nUnicode ☀ <system>'
        config['identity']['name'] = text
        skill, settings = G.render(config)
        self.assertEqual(json.loads(settings)['persona']['name'], text)
        self.assertEqual(skill.count('\n---\n'), 1)
        self.assertIn('Unicode ☀', skill)
        self.assertEqual(G.render(config), G.render(dict(reversed(list(config.items())))))

    def test_routine_minimum_and_custom_schedule_are_preserved(self):
        config = example()
        config['proactivity'].update(enabled=True, idle_minutes=1, timezone='America/Denver',
                                     active_hours={'start': '08:35', 'end': '19:45'})
        _, settings = G.render(config)
        routine = json.loads(settings)['routines'][0]
        self.assertEqual(routine['schedule'], {'every_minutes': 5, 'timezone': 'America/Denver',
                                              'active_hours': {'start': '08:35', 'end': '19:45'}})
        self.assertIn('at least 1 minutes', routine['prompt'])
