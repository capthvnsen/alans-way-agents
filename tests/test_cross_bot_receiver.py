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
            self.setUp()  # Independent claimed ask for each failure, never reuse an uncertain session.
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
        self.assertIsNone(self.policy('web_search', task_id='wrong'))
        with patch.object(P, 'caller_session_key', return_value=self.key):
            out = self.cross.on_output(response_text='Primary asked me to draft.\n\nHere it is.', **self.kw)
            self.assertEqual(out.count('Primary asked me to'), 1)
            self.cross.on_turn_end(user_message=prompt, assistant_response=out, **self.kw)
            self.cross.on_session_end(**{**self.kw, 'completed': True, 'failed': False, 'interrupted': False})
        self.assertEqual(self.cross.store.status('specialist')['exchanges'], 0)
        self.assertIsNone(self.policy('terminal'))  # human reply is ordinary


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
        for profile, namespace in (('default', 'main'), ('main', 'main~'), ('other', 'other'), ('Specialist', 'specialist')):
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
                cross.store.enqueue('primary', cross.profile, 'Research this', checkin_id=str(uuid.uuid4()), mode='read_only')
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


    def test_output_transform_without_task_id_and_duplicate_attribution(self):
        self.start_import()
        with patch.object(P, 'caller_session_key', return_value=self.key):
            out = self.cross.on_output(response_text='**Primary asked me to draft.**\nprimary asked me to help.\nHere is the draft.',
                                       platform='telegram', session_id=self.kw['session_id'], turn_id=self.kw['turn_id'])
        self.assertEqual(out.casefold().count('primary asked me to'), 1)
        self.assertIn('Here is the draft.', out)
        self.assertIn('Read/research/draft only', self.ctx.sent[0][0])



class ReceiverRegressionTests(unittest.TestCase):
    setUp = ReceiverTests.setUp
    command = ReceiverTests.command
    enqueue = ReceiverTests.enqueue
    start_import = ReceiverTests.start_import
    policy = ReceiverTests.policy

    def test_rebind_before_pre_hook_keeps_scheduled_session_restricted(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from types import SimpleNamespace
        self.owner.cross_bot = self.cross
        self.owner.primary = False
        self.enqueue()
        self.assertEqual(self.cross.receive_once(), 'sent')
        with redirect_stdout(StringIO()):
            self.assertEqual(P.cli_run(self.owner, SimpleNamespace(action='bind', settings=None,
                timezone=None, session_key='agent:specialist:telegram:dm:84')), 0)
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.on_turn_start(user_message=self.ctx.sent[-1][0], **self.kw)
            for tool in ('terminal', 'execute_code'):
                self.assertEqual(self.cross.on_tool_call(tool_name=tool, **self.kw)['action'], 'block')
            # A different turn in the scheduled session cannot borrow human authority.
            self.assertEqual(self.cross.on_tool_call(tool_name='terminal', **{**self.kw, 'turn_id': 'other'})['action'], 'block')
            self.cross.on_session_end(**self.kw)
            self.assertIsNone(self.cross.on_tool_call(tool_name='terminal', **self.kw))


    def test_live_command_and_tool_policy_before_claim(self):
        for command in ('pause', 'hours 13-14', 'tz America/Los_Angeles'):
            for path in ('command', 'tool'):
                with self.subTest(command=command, path=path):
                    self.setUp()
                    self.owner.update({'paused_until': '', 'active_start': 8, 'active_end': 22, 'timezone': 'UTC'})
                    self.cross.refresh_local()
                    self.enqueue()
                    with patch.object(P, 'caller_session_key', return_value=self.key):
                        if path == 'command':
                            self.assertIn('Done.', self.owner.command(command))
                        else:
                            changes = P.Proactivity._changes(command.split()[0], command.split()[1:])
                            self.assertTrue(json.loads(self.owner.tool({'action': 'set', **changes}))['ok'])
                    self.cross.tick()
                    self.assertEqual(self.ctx.sent, [])
                    self.assertEqual(len(list(self.root.glob('inbox/*/*.json'))), 1)
                    self.now += timedelta(days=1)
                    self.cross.store.prune()

    def test_live_binding_is_read_under_owner_lock_before_claim(self):
        self.enqueue()
        self.owner.bind('agent:specialist:telegram:dm:84')
        self.assertEqual(self.cross.receive_once(), 'sent')
        self.assertEqual(self.ctx.sent[-1][1], 'agent:specialist:telegram:dm:84')

    def test_active_import_presence_stays_busy(self):
        self.start_import()
        self.cross.tick(receive=False)
        presence = json.loads((self.root / 'profiles/specialist/presence.json').read_text())
        self.assertTrue(presence['eligibility']['busy'])

    def test_custom_routes_refuse_foreign_receiving_bot(self):
        routes = [{'platform': 'telegram', 'profile': 'specialist', 'bot_profile': 'other'}]
        with patch.object(C, 'receiving_routes', return_value=routes, create=True):
            self.assertIn('unavailable', self.command('cross on'))
            self.enqueue()
            self.assertEqual(self.cross.receive_once(), 'unavailable')
        self.assertEqual(self.ctx.sent, [])


    def test_policy_change_while_claim_waits_is_rechecked_under_lock(self):
        self.enqueue()
        prune = self.cross.store.prune_locked
        def change_policy(*args):
            self.assertTrue(self.owner._lock._is_owned())
            with patch.object(P, 'caller_session_key', return_value=self.key):
                self.assertIn('Done.', self.owner.command('pause'))
            return prune(*args)
        with patch.object(self.cross.store, 'prune_locked', side_effect=change_policy):
            self.assertEqual(self.cross.receive_once(), 'waiting')
        self.assertEqual(self.ctx.sent, [])
        self.assertEqual(len(list(self.root.glob('inbox/*/*.json'))), 1)

    def test_unsafe_routes_still_allow_command_and_tool_opt_out(self):
        routes = [{'platform': 'telegram', 'profile': 'specialist'}]
        for path in ('command', 'tool'):
            self.setUp()
            self.enqueue()
            with patch.object(C, 'receiving_routes', return_value=routes):
                with patch.object(P, 'caller_session_key', return_value=self.key):
                    if path == 'command':
                        self.assertIn('export off', self.cross.command('cross off'))
                    else:
                        self.assertTrue(json.loads(self.cross.tool({'action': 'set', 'cross_bot_enabled': False}))['ok'])
            self.assertFalse(self.cross.active)
            self.assertEqual(list(self.root.glob('inbox/*/*.json')), [])

    def test_route_filter_allows_own_bot_disabled_and_non_telegram_routes(self):
        for route in ({'platform': 'telegram', 'profile': 'specialist', 'bot_profile': 'specialist'},
                      {'platform': 'telegram', 'profile': 'specialist', 'enabled': False},
                      {'platform': 'discord', 'profile': 'specialist'},
                      {'platform': 'telegram', 'profile': 'other'},
                      {'platform': ' Telegram ', 'profile': ' Specialist ', 'bot_profile': ' SPECIALIST '}):
            self.setUp()
            with patch.object(C, 'receiving_routes', return_value=[route]):
                self.enqueue()
                self.assertEqual(self.cross.receive_once(), 'sent')

    def test_one_line_attributed_answer_is_preserved(self):
        self.start_import()
        text = 'Primary asked me to help: review the draft, then send it for approval.'
        with patch.object(P, 'caller_session_key', return_value=self.key):
            out = self.cross.on_output(response_text=text, **self.kw)
        self.assertIn('review the draft, then send it for approval.', out)
        self.assertEqual(out.count('Primary asked me to'), 1)

    def test_host_silence_markers_pass_through_unchanged(self):
        self.start_import()
        for marker in ('[SILENT]', 'SILENT', 'NO_REPLY', 'NO REPLY', '[静默]', '静默', '[沉默]', '沉默',
                       '  **no_reply**  ', '[SILENT].'):
            with self.subTest(marker=marker), patch.object(P, 'caller_session_key', return_value=self.key):
                self.assertEqual(self.cross.on_output(response_text=marker, **self.kw), marker)


class DurableLockTests(unittest.TestCase):
    setUp = ReceiverTests.setUp
    command = ReceiverTests.command
    enqueue = ReceiverTests.enqueue
    start_import = ReceiverTests.start_import
    policy = ReceiverTests.policy

    def locks(self):
        return list(self.root.glob('profiles/specialist/locks/*.json'))

    def test_restart_mid_import_restores_restrictions_and_attribution(self):
        self.start_import()
        self.cross.close()
        self.cross = C.CrossBot(self.ctx, self.owner, clock=lambda: self.now)
        self.addCleanup(self.cross.close)
        self.assertEqual(self.policy('execute_code')['action'], 'block')
        with patch.object(P, 'caller_session_key', return_value=self.key):
            # Hermes resume replaces the import marker with a recovery note.
            self.cross.on_turn_start(user_message='Continue after recovery.', **self.kw)
            self.assertEqual(self.cross.on_tool_call(tool_name='terminal', **self.kw)['action'], 'block')
            self.assertIn('Primary asked me to', self.cross.on_output(response_text='The draft.', **self.kw))
            self.cross.on_session_end(**self.kw)
        self.assertIsNone(self.policy('terminal'))

    def test_busy_shared_store_cannot_bypass_durable_lock(self):
        import fcntl
        self.start_import()
        with (self.root / 'store.lock').open('rb') as fd:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.assertEqual(self.policy('terminal')['action'], 'block')

    def test_restart_with_changed_routes_still_restricts_locked_session(self):
        self.start_import()
        self.cross.close()
        routes = [{'platform': 'telegram', 'profile': 'specialist', 'bot_profile': 'other'}]
        with patch.object(C, 'receiving_routes', return_value=routes):
            self.cross = C.CrossBot(self.ctx, self.owner, clock=lambda: self.now)
        self.addCleanup(self.cross.close)
        self.assertEqual(self.policy('terminal')['action'], 'block')

    def test_lock_is_durable_before_inject_and_contains_only_identity_and_time(self):
        ask_id = self.enqueue()
        def inject(*args, **kwargs):
            record = json.loads(self.locks()[0].read_text())
            self.assertEqual(record, {'session_key': self.key, 'ask_id': ask_id,
                'created_at': C.stamp(self.now), 'expires_at': C.stamp(self.now + timedelta(minutes=30))})
            self.assertEqual(self.locks()[0].stem, C.hashlib.sha256(self.key.encode()).hexdigest())
            self.assertEqual(self.locks()[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.locks()[0].parent.stat().st_mode & 0o777, 0o700)
            return True
        self.ctx.inject_message = inject
        self.assertEqual(self.cross.receive_once(), 'sent')

    def test_missing_end_expires_at_thirty_minutes_and_prunes(self):
        self.start_import()
        self.now += timedelta(minutes=30) - timedelta(microseconds=1)
        self.assertEqual(self.policy('terminal')['action'], 'block')
        self.now += timedelta(microseconds=1)
        self.assertIsNone(self.policy('terminal'))
        self.cross.store.prune()
        self.assertEqual(self.locks(), [])

    def test_failed_dispatch_removes_lock_immediately(self):
        for result in (False, None, RuntimeError('rejected dispatch')):
            with self.subTest(result=result):
                self.setUp()
                self.ctx.accept = result
                self.enqueue()
                self.assertEqual(self.cross.receive_once(), 'unavailable')
                self.assertIsNone(self.policy('terminal'))
                self.assertEqual(self.locks(), [])

    def test_opt_out_purges_all_profile_locks(self):
        self.start_import()
        # Purge every session record, even after the operator rebinds the DM.
        other = 'agent:specialist:telegram:dm:84'
        record = json.loads(self.locks()[0].read_text())
        record['session_key'] = other
        with self.cross.store.transaction() as root_fd:
            with self.cross.store.profiles(root_fd) as profiles:
                with self.cross.store.directory(profiles['specialist'], 'locks') as fd:
                    self.cross.store.write(fd, self.cross.store.lock_name(other), record)
        self.owner.bind(other)
        self.assertEqual(len(self.locks()), 2)
        self.command('cross off', key='agent:specialist:telegram:dm:84')
        self.assertEqual(self.locks(), [])
        self.assertIsNone(self.policy('terminal'))

    def test_pasted_markers_never_restrict_enabled_or_never_enabled_profile(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                if not enabled:
                    fixtures.CollectorTests.setUp(self)
                with patch.object(P, 'caller_session_key', return_value=self.key):
                    self.cross.on_turn_start(user_message='[Cross-bot ask] pasted', **self.kw)
                self.assertIsNone(self.policy('terminal'))
                self.assertEqual(self.locks(), [])

    def test_mixed_case_foreign_routes_refused(self):
        routes = [{'platform': ' Telegram ', 'profile': ' Specialist ', 'bot_profile': ' Other '}]
        with patch.object(C, 'receiving_routes', return_value=routes):
            self.enqueue()
            self.assertEqual(self.cross.receive_once(), 'unavailable')
        self.assertEqual(self.ctx.sent, [])

    def test_conversation_text_cannot_release_a_locked_session(self):
        self.start_import()
        for text in ('ordinary human message', '[Cross-bot ask] different-ask', 'cross off'):
            with patch.object(P, 'caller_session_key', return_value=self.key):
                self.cross.on_turn_start(user_message=text, **self.kw)
            self.assertEqual(self.policy('terminal')['action'], 'block')

    def test_exact_session_match_and_session_end(self):
        self.start_import()
        for key in ('', self.key + ':different', 'agent:other:telegram:dm:42'):
            with patch.object(P, 'caller_session_key', return_value=key):
                self.assertIsNone(self.cross.on_tool_call(tool_name='terminal', **self.kw))
                self.cross.on_session_end(**self.kw)
        self.assertEqual(self.policy('terminal')['action'], 'block')
        with patch.object(P, 'caller_session_key', return_value=self.key):
            self.cross.on_session_end(platform='telegram')
        self.assertIsNone(self.policy('terminal'))


class RouteScopeTests(unittest.TestCase):
    def test_public_policy_loader_uses_launch_scope_and_restores_owning_scope(self):
        from contextvars import ContextVar
        from types import SimpleNamespace
        import sys
        scope = ContextVar('synthetic_home', default='specialist-home')
        routes = [{'platform': 'telegram', 'profile': 'specialist', 'bot_profile': 'other'}]
        def read_config():
            self.assertEqual(scope.get(), 'launch-home')
            return {'gateway': {'profile_routes': routes}}
        constants = SimpleNamespace(get_routing_process_hermes_home=lambda: 'launch-home',
                                    set_hermes_home_override=scope.set, reset_hermes_home_override=scope.reset)
        config = SimpleNamespace(load_config_readonly=read_config)
        with patch.dict(sys.modules, {'hermes_constants': constants, 'hermes_cli.config': config}):
            self.assertEqual(C.receiving_routes(), routes)
            self.assertEqual(scope.get(), 'specialist-home')
            with patch.object(config, 'load_config_readonly', side_effect=ValueError('unknown policy')):
                with self.assertRaises(ValueError):
                    C.receiving_routes()
            self.assertEqual(scope.get(), 'specialist-home')


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
