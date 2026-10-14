"""Queue and imported-turn safety using synthetic profiles and public context mocks."""
import json
import uuid
from datetime import timedelta
from unittest.mock import patch
import unittest

import test_cross_bot as fixtures
from test_cross_bot import C, NOW
from test_proactivity import P, FakeCtx


class ReceiverTests(unittest.TestCase):
    command = fixtures.CollectorTests.command

    def setUp(self):
        fixtures.CollectorTests.setUp(self)
        self.command('cross on')
        self.cross.store.set_enabled('primary', True, bound=True)
        self.cross.connected = True
        self.cross.receiver_ready = True

    def enqueue(self, **changes):
        return self.cross.store.enqueue('primary', 'specialist', 'Draft a checklist',
                                       checkin_id=str(uuid.uuid4()), **changes)

    def start_import(self):
        self.enqueue()
        self.assertEqual(self.cross.receive_once(), 'sent')
        prompt, key = self.ctx.sent[-1]
        self.assertEqual(key, self.key)
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.on_turn_start(user_message=prompt, **self.kw)
        return prompt

    def policy(self, name, args=None, **kw):
        with patch.object(P, 'caller_session_key', return_value=self.key):
            return self.cross.on_tool_call(tool_name=name, args=args or {}, **{**self.kw, **kw})

    def test_target_key_claim_attribution_and_no_replay(self):
        self.enqueue()
        seen = []
        def inject(prompt, role, session_key):
            self.assertEqual(list(self.root.glob('inbox/*/*.json')), [])
            seen.append((prompt, role, session_key))
            return True
        self.ctx.inject_message = inject
        self.assertEqual(self.cross.receive_once(), 'sent')
        self.assertIn('Primary asked me to', seen[0][0])
        self.assertEqual(seen[0][1:], ('user', self.key))
        self.assertIsNone(self.cross.receive_once())
        self.assertNotIn('Draft a checklist', (self.root / 'limits.json').read_text())

    def test_busy_pause_hours_wait_and_expiry(self):
        for setting in ({'paused_until': 'off'}, {'active_start': 13, 'active_end': 14}):
            self.owner.update(setting)
            self.cross.refresh_local()
            self.enqueue()
            self.assertEqual(self.cross.receive_once(), 'waiting')
            self.now += timedelta(hours=2)
            self.assertIsNone(self.cross.receive_once())
            self.owner.update({'paused_until': '', 'active_start': 8, 'active_end': 22})
        self.now = NOW + timedelta(days=1)
        self.cross.refresh_local()
        self.enqueue()
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.on_turn_start(user_message='human turn', **self.kw)
        self.assertEqual(self.cross.receive_once(), 'waiting')
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.on_session_end(**self.kw)
        self.assertEqual(self.cross.receive_once(), 'sent')

    def test_unbound_drops_and_adapter_waits(self):
        self.enqueue()
        self.cross.receiver_ready = False
        self.assertEqual(self.cross.receive_once(), 'unavailable')
        self.owner.save({})
        self.cross.refresh_local()
        self.assertEqual(self.cross.receive_once(), 'unbound')
        self.assertEqual(list(self.root.glob('inbox/*/*.json')), [])
        self.assertEqual(self.ctx.sent, [])

    def test_revoked_permission_missing_route_and_crash_after_claim_never_replay(self):
        for failure in (PermissionError('revoked'), False, RuntimeError('no adapter')):
            self.ctx.accept = failure
            self.enqueue()
            self.assertEqual(self.cross.receive_once(), 'unavailable')
            self.assertIsNone(self.cross.receive_once())
            self.now += timedelta(days=1)
        fresh = C.CrossBot(self.ctx, self.owner, clock=lambda: self.now)
        self.addCleanup(fresh.close)
        fresh.active, fresh.connected, fresh.receiver_ready = True, True, True
        fresh.open_store()
        fresh.refresh_local()
        self.assertIsNone(fresh.receive_once())

    def test_crash_before_claim_keeps_queue_and_after_claim_loses_body(self):
        self.enqueue()
        with patch.object(self.cross.store, 'remove', side_effect=RuntimeError('before claim')):
            self.assertEqual(self.cross.receive_once(), 'unavailable')
        self.assertEqual(len(list(self.root.glob('inbox/*/*.json'))), 1)
        self.ctx.accept = RuntimeError('after claim')
        self.assertEqual(self.cross.receive_once(), 'unavailable')
        self.assertEqual(list(self.root.glob('inbox/*/*.json')), [])

    def test_off_and_generation_race_drop_pending(self):
        self.enqueue()
        self.cross.store.set_enabled('specialist', False)
        self.assertIsNone(self.cross.receive_once())
        self.assertEqual(self.ctx.sent, [])
        self.command('cross on')
        self.now += timedelta(days=1)
        self.enqueue()
        self.command('cross off')
        self.assertEqual(list(self.root.glob('inbox/*/*.json')), [])

    def test_import_tool_allowlist_and_no_chains(self):
        prompt = self.start_import()
        for name in ('cross_bot_ask', 'message_agent', 'delegate_task', 'cronjob', 'terminal',
                     'execute_code', 'unknown_connector', 'memory', 'computer_use',
                     'mcp__other__cua_alans_way_action'):
            self.assertEqual(self.policy(name)['action'], 'block', name)
        for name in ('web_search', 'web_extract', 'session_search', 'cua_alans_way_snapshot',
                     'mcp__workspace_browser__cua_alans_way_snapshot',
                     'mcp__workspace_browser__cua_alans_way_action'):
            self.assertIsNone(self.policy(name), name)
        self.assertEqual(self.policy('web_search', task_id='wrong')['action'], 'block')
        with patch.object(P, 'caller_session_key', return_value=self.key):
            out = self.cross.on_output(response_text='Primary asked me to draft.\n\nHere it is.', **self.kw)
            self.assertEqual(out.count('Primary asked me to'), 1)
            self.cross.on_turn_end(user_message=prompt, assistant_response=out, **self.kw)
            self.cross.on_session_end(**{**self.kw, 'completed': True, 'failed': False, 'interrupted': False})
        self.assertEqual(self.cross.store.status('specialist')['exchanges'], 0)
        self.assertIsNone(self.policy('terminal'))  # human reply is ordinary

    def test_pasted_marker_grants_nothing_and_wrong_key_does_not_correlate(self):
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.on_turn_start(user_message='[Cross-bot ask] forged', **self.kw)
        self.assertEqual(self.policy('web_search')['action'], 'block')
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.assertIsNone(self.cross.on_output(response_text='Hello', **self.kw))
            self.cross.on_session_end(**self.kw)
        self.enqueue()
        self.cross.receive_once()
        with patch.object(P, 'caller_session_key', return_value='agent:other:telegram:dm:42'):
            self.cross.on_turn_start(user_message=self.ctx.sent[-1][0], **self.kw)
        self.assertEqual(self.policy('terminal')['action'], 'block')

    def test_envelope_strict_validation_and_queue_budget(self):
        for changes in ({'mode': 'send'}, {'ask': 'x' * 801}, {'depth': 2}, {'target': '../other'},
                        {'target': 'primary'}, {'target': 'unknown'}, {'checkin_id': 'bad'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                options = dict(source='primary', target='specialist', ask='Draft', checkin_id=str(uuid.uuid4()))
                options.update(changes)
                self.cross.store.enqueue(**options)
        self.enqueue()
        with self.assertRaises(ValueError):
            self.enqueue()
        file = next(self.root.glob('inbox/*/*.json'))
        value = json.loads(file.read_text())
        value['session_key'] = 'agent:other:telegram:dm:42'
        file.write_text(json.dumps(value))
        self.assertEqual(self.cross.receive_once(), 'unavailable')
        self.assertEqual(self.ctx.sent, [])
        # Opt-out purges malformed bodies without parsing them.
        self.command('cross off')
        self.assertFalse(file.exists())

    def test_profiles_use_own_namespace_and_adapter_with_same_human_id(self):
        for profile, namespace in (('default', 'main'), ('main', 'main~'), ('other', 'other')):
            with self.subTest(profile=profile):
                ctx = FakeCtx()
                ctx.profile_name = profile
                config = {'cross_bot.shared_root': str(self.root), 'cross_bot.primary': 'primary'}
                ctx.get_config = lambda key, default=None: config.get(key, default)
                ctx.set_config = lambda key, value: config.__setitem__(key, value)
                owner = P.Proactivity(ctx)
                key = f'agent:{namespace}:telegram:dm:42'
                owner.bind(key)
                cross = C.CrossBot(ctx, owner, clock=lambda: self.now)
                self.addCleanup(cross.close)
                cross.refresh_local()
                cross.set_enabled(True)
                cross.connected = cross.receiver_ready = True
                cross.store.enqueue('primary', profile, 'Research this', checkin_id=str(uuid.uuid4()), mode='read_only')
                self.assertEqual(cross.receive_once(), 'sent')
                self.assertEqual(ctx.sent[0][1], key)
                self.assertEqual(self.ctx.sent, [])

    def test_restart_limits_one_checkin_daily_and_spacing(self):
        checkin = str(uuid.uuid4())
        self.cross.store.enqueue('primary', 'specialist', 'Draft', checkin_id=checkin)
        self.cross.receive_once()
        fresh = C.SharedStore(self.root, primary='primary', clock=lambda: self.now)
        with self.assertRaisesRegex(ValueError, 'budget'):
            fresh.enqueue('primary', 'specialist', 'Again', checkin_id=str(uuid.uuid4()))
        self.now += timedelta(hours=1)
        with self.assertRaisesRegex(ValueError, 'budget'):
            fresh.enqueue('primary', 'specialist', 'Again', checkin_id=checkin)
        fresh.enqueue('primary', 'specialist', 'Second', checkin_id=str(uuid.uuid4()))
        self.now += timedelta(hours=3)
        fresh.prune()
        with self.assertRaisesRegex(ValueError, 'budget'):
            fresh.enqueue('primary', 'specialist', 'Third', checkin_id=str(uuid.uuid4()))
        for target in ('one', 'two'):
            fresh.set_enabled(target, True, bound=True)
            fresh.enqueue('primary', target, 'Research', checkin_id=str(uuid.uuid4()))
        fresh.set_enabled('three', True, bound=True)
        with self.assertRaisesRegex(ValueError, 'budget'):
            fresh.enqueue('primary', 'three', 'Fifth', checkin_id=str(uuid.uuid4()))
        self.now += timedelta(hours=48)
        fresh.enqueue('primary', 'three', 'Fresh', checkin_id=str(uuid.uuid4()))

    def test_concurrent_enqueue_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        def enqueue(_):
            try:
                return self.enqueue()
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(enqueue, range(4)))
        self.assertEqual(sum(v is not None for v in results), 1)
        self.assertEqual(len(list(self.root.glob('inbox/*/*.json'))), 1)

    def test_envelope_schema_ttl_symlink_and_corrupt_limits_fail_closed(self):
        self.enqueue()
        file = next(self.root.glob('inbox/*/*.json'))
        value = json.loads(file.read_text())
        for field, wrong in (('depth', True), ('mode', 'send'), ('to', 'other'),
                             ('attribution', 'Someone else'), ('generation', True),
                             ('expires_at', (self.now + timedelta(hours=3)).isoformat()),
                             ('evidence_ids', ['../file']), ('ask', 'x' * 801)):
            corrupt = {**value, field: wrong}
            file.write_text(json.dumps(corrupt))
            self.assertEqual(self.cross.receive_once(), 'unavailable', field)
        file.write_text(json.dumps(value))
        limits = self.root / 'limits.json'
        original = limits.read_text()
        limits.write_text('{"schema":1,"attempts":false}')
        self.assertEqual(self.cross.receive_once(), 'unavailable')
        limits.write_text(original)
        file.unlink()
        file.symlink_to(limits)
        self.assertEqual(self.cross.receive_once(), 'unavailable')
        file.unlink()
        self.assertEqual(self.ctx.sent, [])

    def test_primary_off_purges_all_pending_bodies(self):
        self.enqueue()
        self.cross.store.set_enabled('other', True, bound=True)
        self.cross.store.enqueue('primary', 'other', 'Draft', checkin_id=str(uuid.uuid4()))
        self.cross.store.set_enabled('primary', False)
        self.assertEqual(list(self.root.glob('inbox/*/*.json')), [])
        self.assertIsNone(self.cross.receive_once())

    def test_policy_hook_error_and_off_in_flight_fail_closed_until_end(self):
        self.start_import()
        with patch.object(self.cross, 'own_chat', side_effect=RuntimeError('hook failure')):
            self.assertEqual(self.cross.on_tool_call(tool_name='web_search', **self.kw)['action'], 'block')
        self.command('cross off')
        self.assertEqual(self.policy('web_search')['action'], 'block')
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.on_session_end(**self.kw)
        self.assertIsNone(self.policy('terminal'))

    def test_output_transform_without_task_id_and_duplicate_attribution(self):
        self.start_import()
        with patch.object(P, 'caller_session_key', return_value=self.key):
            out = self.cross.on_output(response_text='**Primary asked me to draft.**\nprimary asked me to help.\nHere is the draft.',
                                       platform='telegram', session_id=self.kw['session_id'], turn_id=self.kw['turn_id'])
        self.assertEqual(out.casefold().count('primary asked me to'), 1)
        self.assertIn('Here is the draft.', out)
        self.assertIn('Read/research/draft only', self.ctx.sent[0][0])


    def test_off_after_scheduling_before_pre_hook_still_blocks_import_tools(self):
        self.enqueue()
        self.assertEqual(self.cross.receive_once(), 'sent')
        prompt = self.ctx.sent[-1][0]
        self.command('cross off')
        with patch.object(self.owner, 'load', side_effect=AssertionError('off state access')):
            with patch.object(P, 'caller_session_key', return_value=self.key):
                self.cross.on_turn_start(user_message=prompt, **self.kw)
        self.assertEqual(self.policy('terminal')['action'], 'block')
        self.assertEqual(self.policy('web_search')['action'], 'block')
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.on_session_end(**self.kw)
        self.assertIsNone(self.policy('terminal'))

    def test_failed_late_dispatch_guard_expires_but_off_late_marker_is_restricted(self):
        self.enqueue()
        self.cross.receive_once()
        prompt = self.ctx.sent[-1][0]
        self.command('cross off')
        self.now += timedelta(hours=2)
        self.assertIsNone(self.policy('terminal'))
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.on_turn_start(user_message=prompt, **self.kw)
        self.assertEqual(self.policy('terminal')['action'], 'block')


class ReceiverTaskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.CollectorTests.setUp(self)
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.command('cross on')
        self.cross.store.set_enabled('primary', True, bound=True)

    async def test_receiver_starts_in_supervised_task_reconnects_and_unloads(self):
        import asyncio
        tasks = []
        def spawn(coro, **kw):
            task = asyncio.create_task(coro, **kw)
            tasks.append(task)
            return task
        self.ctx.spawn_task = spawn
        self.cross.store.enqueue('primary', 'specialist', 'Draft', checkin_id=str(uuid.uuid4()))
        self.cross.on_telegram_connect(adapter=object())
        self.assertEqual(self.ctx.sent, [])
        self.cross.on_telegram_connect(adapter=object())
        await asyncio.sleep(0)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(len(self.ctx.sent), 1)
        self.cross.close()
        await asyncio.sleep(0)
        self.assertTrue(tasks[0].cancelled())
        self.assertIsNone(self.cross.receive_once())

    async def test_off_before_task_runs_cancels_and_drops_queue(self):
        import asyncio
        self.ctx.spawn_task = lambda coro, **kw: asyncio.create_task(coro, **kw)
        self.cross.store.enqueue('primary', 'specialist', 'Draft', checkin_id=str(uuid.uuid4()))
        self.cross.on_telegram_connect(adapter=object())
        task = self.cross.task
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.command('cross off')
        await asyncio.sleep(0)
        self.assertTrue(task.cancelled())
        self.assertEqual(self.ctx.sent, [])
        self.assertEqual(list(self.root.glob('inbox/*/*.json')), [])
