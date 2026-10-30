"""Shared preferences: validation, Hermes application and standalone packaging."""
from datetime import timedelta
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_proactivity import P, FakeCtx, FakeState, at, KEY

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = sys.modules[P.__package__]
C = importlib.import_module(P.__package__ + '.shared_config')
V = importlib.import_module(P.__package__ + '.voice')


def example():
    return json.loads((ROOT / 'shared/config.example.json').read_text())


class ConfigTests(unittest.TestCase):
    def test_example_and_packaged_schema_match(self):
        self.assertEqual(C.validate_config(example()), example())
        self.assertEqual((ROOT / 'shared/config.schema.json').read_bytes(),
                         (ROOT / 'alans-way/config.schema.json').read_bytes())

    def test_rejects_schema_and_semantic_errors_without_values(self):
        cases = [
            ('schema_version', True), ('schema_version', 2), ('persona', {}),
            ('persona.description', ''), ('persona.description', 42),
            ('voice.reply_length', 'unrecognized-private-value'),
            ('proactivity.enabled', 1), ('proactivity.idle_minutes', 0),
            ('proactivity.idle_minutes', 1.5), ('proactivity.timezone', 'private-value'),
            ('proactivity.active_hours.start', '24:00'),
            ('proactivity.active_hours.start', '22:00'),
            ('proactivity.active_hours.end', '07:00'),
            ('identity.name', None), ('identity.extra-private-value', 'private-value'),
        ]
        for path, value in cases:
            with self.subTest(path=path, value=value):
                data = example()
                target = data
                parts = path.split('.')
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                with self.assertRaises(C.ConfigError) as error:
                    C.validate_config(data)
                self.assertNotIn('private-value', str(error.exception))
        for data in ([], None, {'private-value': 'private-value'}):
            with self.assertRaises(C.ConfigError):
                C.validate_config(data)

    def test_load_missing_malformed_utf8_and_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            self.assertIsNone(C.load_config(path))
            with self.assertRaisesRegex(C.ConfigError, 'not found'):
                C.load_config(path, missing_ok=False)
            for content in (b'{"private-value":', b'\xff', b'{"schema_version": NaN}'):
                path.write_bytes(content)
                with self.assertRaises(C.ConfigError) as error:
                    C.load_config(path)
                self.assertNotIn('private-value', str(error.exception))
            path.write_text('{"schema_version": 1, "schema_version": 1}')
            with self.assertRaisesRegex(C.ConfigError, 'duplicate'):
                C.load_config(path)
            path.unlink()
            path.mkdir()
            with self.assertRaisesRegex(C.ConfigError, 'read'):
                C.load_config(path)

    def test_home_path_is_independent_of_hermes_profile(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(Path, 'home', return_value=Path(tmp)):
            path = Path(tmp) / '.config/alans-way/config.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(example()))
            self.assertEqual(C.load_config(), example())

    def test_packaged_reader_works_without_repo_shared_directory(self):
        import shutil
        import importlib.util
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('shared_config.py', 'config.schema.json'):
                shutil.copyfile(ROOT / 'alans-way' / name, Path(tmp) / name)
            spec = importlib.util.spec_from_file_location('standalone_config', Path(tmp) / 'shared_config.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.validate_config(example()), example())

    def test_missing_validator_has_an_install_hint(self):
        import builtins
        original = builtins.__import__
        def without_jsonschema(name, *args, **kwargs):
            if name == 'jsonschema':
                raise ImportError()
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=without_jsonschema):
            with self.assertRaisesRegex(C.ConfigError, 'install jsonschema'):
                C.validate_config(example())


class HermesTests(unittest.TestCase):
    def register(self, path, profile='default'):
        hooks = {}
        ctx = FakeCtx()
        ctx.profile_name = profile
        ctx.register_hook = lambda name, fn: hooks.setdefault(name, []).append(fn)
        ctx.register_tool = lambda **kw: None
        ctx.register_skill = lambda *a: None
        ctx.register_command = lambda *a, **kw: None
        ctx.on_unload = self.addCleanup
        runtime = PACKAGE.register(ctx, background=False, shared_config_path=path)
        return ctx, hooks, runtime

    def test_register_applies_identity_persona_and_voice_to_all_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            config = example()
            config['voice']['reply_length'] = 'detailed'
            path.write_text(json.dumps(config))
            for profile in ('default', 'secondary'):
                ctx, hooks, runtime = self.register(path, profile)
                notes = [result['context'] for fn in hooks['pre_llm_call']
                         if isinstance(result := fn(user_message='Explain the tradeoffs', platform='telegram'), dict)]
                combined = '\n'.join(notes)
                for value in (config['identity']['name'], config['identity']['role'],
                              config['persona']['description'], config['voice']['tone'], 'detailed'):
                    self.assertIn(value, combined)
                self.assertNotIn('under 280 characters', combined)
                self.assertEqual(ctx.state.data, {})
                self.assertEqual(runtime is None, profile == 'secondary')

    def test_invalid_config_fails_before_any_registration_or_state_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_text('{}')
            with self.assertRaises(C.ConfigError):
                PACKAGE.register(SimpleNamespace(), background=False, shared_config_path=path)

    def test_missing_config_preserves_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, runtime = self.register(Path(tmp) / 'missing.json')
            self.assertEqual(runtime.settings({}), P.Settings(timezone='UTC'))

    def test_exact_shared_schedule_does_not_bind_resume_or_persist(self):
        config = example()
        config['proactivity'].update(enabled=True, idle_minutes=1500,
                                     active_hours={'start': '08:30', 'end': '21:45'})
        ctx = FakeCtx()
        runtime = P.Proactivity(ctx, shared_config=config)
        runtime.clock = lambda: at('2026-10-07T10:00')
        runtime.gateway = True
        self.assertIsNone(runtime.tick())
        self.assertEqual(ctx.sent, [])
        runtime.bind(KEY)
        runtime.update({'paused_until': 'off'})
        settings = runtime.settings(runtime.load())
        self.assertEqual(settings.base_minutes, 1500)
        self.assertTrue(P.is_paused(settings, runtime.clock()))
        self.assertFalse(P.in_window(settings, at('2026-10-07T08:29')))
        self.assertTrue(P.in_window(settings, at('2026-10-07T08:30')))
        self.assertTrue(P.in_window(settings, at('2026-10-07T21:44')))
        self.assertFalse(P.in_window(settings, at('2026-10-07T21:45')))
        self.assertEqual(P.next_active(settings, at('2026-10-07T08:29')), at('2026-10-07T08:30'))
        self.assertEqual(P.day_start(settings, at('2026-10-07T00:00').date()), at('2026-10-07T08:30'))
        self.assertIn('8:30-21:45', runtime._status_text())
        self.assertNotIn(1500, ctx.state.get(P.STATE_KEY)['settings'].values())
        self.assertIsNone(runtime.tick())

    def test_disabled_shared_proactivity_blocks_all_unsolicited_messages(self):
        runtime = P.Proactivity(FakeCtx(), shared_config=example())
        runtime.gateway = True
        runtime.clock = lambda: at('2026-10-07T12:00')
        runtime.bind(KEY)
        runtime.update({'morning_brief': True, 'weekly_report': True})
        self.assertTrue(runtime.status()['paused'])
        self.assertIsNone(runtime.tick())
        self.assertEqual(runtime.ctx.sent, [])

    def test_configured_voice_preserves_format_and_operator_tone_switch(self):
        voice = V.Voice(SimpleNamespace(state=FakeState()), shared_config=example())
        self.assertIsNone(voice.on_output('## A heading', platform='telegram'))
        self.assertIn('Warm, direct', voice.on_turn_start(platform='telegram')['context'])
        self.assertIn('come from shared config', voice.settings_text())
        self.assertIn('Shared config controls reply length', voice.command('length 100'))
        voice.set('default')
        self.assertIsNone(voice.on_turn_start(platform='telegram'))

    def test_shared_schedule_errors_do_not_change_state_and_pause_still_works(self):
        runtime = P.Proactivity(FakeCtx(), shared_config=example())
        runtime.bind(KEY)
        before = runtime.load()
        with self.assertRaisesRegex(ValueError, 'Shared config controls'):
            runtime.update({'timezone': 'UTC'})
        with self.assertRaisesRegex(ValueError, 'disabled in shared config'):
            runtime.update({'paused_until': ''})
        with patch.object(P, 'caller_session_key', return_value=KEY):
            self.assertIn('Shared config controls', runtime.command('hours 9-20'))
            self.assertFalse(json.loads(runtime.tool({'action': 'set', 'level': 'less'}))['ok'])
            self.assertTrue(json.loads(runtime.tool({'action': 'set', 'paused_until': 'off'}))['ok'])
        self.assertEqual(runtime.load()['settings']['paused_until'], 'off')
        self.assertEqual(before['session_key'], runtime.load()['session_key'])

    def test_enabled_config_uses_native_idle_backoff_and_exact_hours(self):
        config = example()
        config['proactivity'].update(enabled=True, idle_minutes=30, timezone='America/Denver',
                                     active_hours={'start': '08:30', 'end': '09:00'})
        now = at('2026-11-01T08:00', 'America/Denver')
        runtime = P.Proactivity(FakeCtx(), shared_config=config, clock=lambda: now)
        runtime.gateway = True
        runtime.bind(KEY)
        self.assertIsNone(runtime.tick())
        now += timedelta(minutes=29)
        self.assertIsNone(runtime.tick())
        now += timedelta(minutes=1)
        self.assertTrue(runtime.tick())
        now += timedelta(minutes=60)
        self.assertIsNone(runtime.tick())
        self.assertEqual(len(runtime.ctx.sent), 1)
        settings = runtime.settings(runtime.load())
        self.assertEqual(P.next_active(settings, now), at('2026-11-02T08:30', 'America/Denver'))

    def test_idle_longer_than_a_week_remains_a_minimum(self):
        settings = P.Settings(base_minutes=15 * 24 * 60)
        anchor = at('2026-10-07T10:00')
        self.assertGreaterEqual(P.due_at(settings, anchor, 4), anchor + timedelta(days=15))
