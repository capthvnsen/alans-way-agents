"""Offline security cases for the throwaway secure form, never a live bot/vault."""
import contextlib
import hashlib
import hmac
import http.client
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
SPIKE = ROOT / 'prototype' / 'secure-form'
spec = importlib.util.spec_from_file_location('secure_form_spike', SPIKE / 'service.py')
sf = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sf
spec.loader.exec_module(sf)

# Synthetic identities and token, not Telegram credentials.
TOKEN = 'fixture-bot-token'
USER = 101
NOW = 1000000
CANARY = 'fixture-secret-canary-$()`-do-not-echo'


def signed(*, user=USER, when=NOW, query='fixture-query', chat=None, token=TOKEN):
    fields = {'user': json.dumps({'id': user}), 'auth_date': str(when), 'query_id': query}
    if chat is not None:
        fields['chat'] = json.dumps(chat)
    key = hmac.digest(b'WebAppData', token.encode(), 'sha256')
    data = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
    fields['hash'] = hmac.digest(key, data.encode(), 'sha256').hex()
    return urlencode(fields)


class SecureFormTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.calls = []
        self.service = sf.FormService(TOKEN, self.sink, clock=lambda: self.now)
        self.rid = self.service.issue('Example login', user_id=USER, chat_id=USER)

    def sink(self, request, value):
        self.calls.append(hashlib.sha256(value.encode()).hexdigest())
        return True

    def submit(self, data=None, value=CANARY, rid=None):
        return self.service.submit(rid or self.rid, data or signed(), value)

    def test_valid_and_model_visible_status(self):
        result = self.submit()
        self.assertEqual(result, {'label': 'Example login', 'request_id': self.rid,
                                  'status': 'submitted'})
        self.assertEqual(self.calls, [hashlib.sha256(CANARY.encode()).hexdigest()])
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertNotIn(CANARY, repr(self.service.requests))

    def test_tampered(self):
        with self.assertRaises(sf.Rejected):
            self.submit(signed().replace('101', '102'))
        self.assertEqual(self.calls, [])

    def test_stale_and_future(self):
        for when in (NOW - 301, NOW + 31):
            with self.subTest(when=when), self.assertRaises(sf.Rejected):
                self.submit(signed(when=when))

    def test_wrong_user_bot_and_chat(self):
        for data in (signed(user=102), signed(token='other-fixture-token'),
                     signed(chat={'id': 102, 'type': 'private'}),
                     signed(chat={'id': USER, 'type': 'group'})):
            with self.subTest(data=data), self.assertRaises(sf.Rejected):
                self.submit(data)
        self.assertEqual(self.calls, [])

    def test_only_private_trusted_issuance(self):
        with self.assertRaises(sf.Rejected):
            self.service.issue('Login', user_id=USER, chat_id=-202)

    def test_duplicate_fields_and_malformed_init_data(self):
        for data in (signed() + '&user=%7B%22id%22%3A101%7D', 'hash=x',
                     signed(user=True), signed(user='101'), signed(query='')):
            with self.subTest(data=data), self.assertRaises(sf.Rejected):
                self.submit(data)

    def test_expiry_and_predates_request(self):
        self.now += 120
        with self.assertRaises(sf.Rejected):
            self.submit(signed(when=self.now))
        self.assertEqual(self.service.status(self.rid, signed(when=self.now))['status'], 'expired')
        self.assertEqual(self.calls, [])
        other = self.service.issue('Second', user_id=USER, chat_id=USER)
        with self.assertRaises(sf.Rejected):
            self.submit(signed(when=NOW), rid=other)

    def test_single_use_and_replay_across_requests(self):
        self.submit()
        with self.assertRaises(sf.Rejected):
            self.submit()
        other = self.service.issue('Second', user_id=USER, chat_id=USER)
        with self.assertRaises(sf.Rejected):
            self.submit(rid=other)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.service.status(self.rid, signed())['status'], 'submitted')

    def test_sink_failure_never_reports_submitted_or_exception_value(self):
        def broken(request, value):
            raise RuntimeError(value)
        self.service.sink = broken
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = self.submit()
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn(CANARY, output.getvalue() + json.dumps(result))
        with self.assertRaises(sf.Rejected):
            self.submit()

    def test_sink_false_and_secret_input_limits(self):
        for value in ('', 'x' * 4097, 'two\nlines', 'nul\0byte'):
            with self.subTest(value=value[:10]), self.assertRaises(sf.Rejected):
                self.submit(value=value)
        self.service.sink = lambda request, value: False
        self.assertEqual(self.submit()['status'], 'failed')

    def test_parallel_double_submit(self):
        entered, release = threading.Event(), threading.Event()
        def waiting(request, value):
            entered.set()
            release.wait(3)
            return self.sink(request, value)
        self.service.sink = waiting
        result = []
        thread = threading.Thread(target=lambda: result.append(self.submit()))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.service.status(self.rid, signed())['status'], 'writing')
            with self.assertRaises(sf.Rejected):
                self.submit()
        finally:
            release.set()
            thread.join(3)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result[0]['status'], 'submitted')

    def test_button_payload_only_nonsecret_metadata(self):
        payload = sf.button_payload(self.service.requests[self.rid], 'https://form.example')
        self.assertEqual(payload['reply_markup']['inline_keyboard'][0][0]['web_app'],
                         {'url': 'https://form.example/form/' + self.rid})
        self.assertNotIn(TOKEN, json.dumps(payload))
        with self.assertRaises(sf.Rejected):
            sf.button_payload(self.service.requests[self.rid], 'http://form.example')

    def test_public_hook_uses_admitted_identity_and_fixture_sender(self):
        registered, messages = {}, []
        class Context:
            def register_hook(self, name, callback):
                registered[name] = callback
        sf.register_trigger(Context(), self.service,
                            lambda payload: messages.append(payload) or True,
                            public_origin='https://form.example', profile='fixture')
        callback = registered['post_gateway_admission']
        source = {'chat_type': 'dm', 'user_id': str(USER), 'chat_id': str(USER), 'profile': 'fixture'}
        result = callback(platform='telegram', source=source, text='/secure-form')
        self.assertEqual(result, {'action': 'handled'})
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['chat_id'], USER)
        for changed in ({'chat_type': 'group'}, {'user_id': '102'}, {'profile': 'other'}):
            with self.subTest(changed=changed):
                result = callback(platform='telegram', source={**source, **changed}, text='/secure-form')
                self.assertEqual(result['action'], 'handled')
                self.assertEqual(len(messages), 1)

    def test_restart_and_other_profile_requests_fail_closed(self):
        other = sf.FormService(TOKEN, self.sink, clock=lambda: self.now)
        with self.assertRaises(sf.Rejected):
            other.submit(self.rid, signed(), CANARY)
        self.assertEqual(self.calls, [])

    def test_bot_api_sender_mock_only_and_no_token_in_result_or_logs(self):
        sender = sf.BotApiSender(TOKEN)
        payload = sf.button_payload(self.service.requests[self.rid], 'https://form.example')
        output = io.StringIO()
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"ok":true,"result":{"message_id":77}}'
        with mock.patch.object(sf, 'urlopen', return_value=response) as open_mock:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertIs(sender(payload), True)
            sent = open_mock.call_args.args[0]
            self.assertEqual(sent.full_url, 'https://api.telegram.org/bot' + TOKEN + '/sendMessage')
            self.assertEqual(json.loads(sent.data), payload)
            self.assertEqual(open_mock.call_count, 1)
        with mock.patch.object(sf, 'urlopen', side_effect=RuntimeError(TOKEN + CANARY)):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertIs(sender(payload), False)
        self.assertNotIn(TOKEN, output.getvalue())
        self.assertNotIn(CANARY, output.getvalue())

    def test_hook_send_failure_expires_request_without_echoing_token(self):
        registered = {}
        class Context:
            def register_hook(self, name, callback):
                registered[name] = callback
        def broken(payload):
            raise RuntimeError(TOKEN)
        sf.register_trigger(Context(), self.service, broken,
                            public_origin='https://form.example', profile='fixture')
        result = registered['post_gateway_admission'](
            platform='telegram', text='/secure-form',
            source={'profile': 'fixture', 'chat_type': 'dm', 'user_id': str(USER), 'chat_id': str(USER)})
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertEqual(list(self.service.requests.values())[-1].status, 'expired')


class HttpTests(unittest.TestCase):
    def setUp(self):
        SecureFormTests.setUp(self)
        self.server = sf.make_server(self.service, port=0, fixture_init_data=signed())
        self.origin = 'http://' + self.server.authority
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)

    sink = SecureFormTests.sink

    def request(self, path, body=None, headers=None, method='POST'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        base = {'Origin': self.origin, 'Content-Type': 'application/json'}
        base.update(headers or {})
        conn.request(method, path, body, base)
        response = conn.getresponse()
        status, hdrs, content = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return status, hdrs, content

    def body(self):
        return json.dumps({'init_data': signed(), 'secret': CANARY})

    def test_http_form_post_no_logs_and_no_cache(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            status, hdrs, body = self.request('/form/' + self.rid, method='GET')
            self.assertEqual(status, 200)
            self.assertIn(b'type="password"', body)
            self.assertIn(b'Fixture only', body)
            self.assertIn('Content-Security-Policy', hdrs)
            self.assertNotIn(b'telegram.org', body)
            status, hdrs, body = self.request('/submit/' + self.rid, self.body())
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'submitted')
        self.assertEqual(hdrs['Cache-Control'], 'no-store')
        self.assertNotIn(CANARY, output.getvalue() + body.decode())

    def test_http_rejects_cross_origin_rebinding_type_size_unknown_fields(self):
        cases = [({'Origin': 'https://evil.example'}, self.body()),
                 ({'Host': 'evil.example'}, self.body()),
                 ({'Content-Type': 'text/plain'}, self.body()),
                 ({}, 'x' * 20000), ({}, '{'),
                 ({}, json.dumps({'init_data': signed(), 'secret': CANARY, 'sink': '/tmp/file'}))]
        for headers, body in cases:
            with self.subTest(headers=headers, length=len(body)):
                status, _, content = self.request('/submit/' + self.rid, body, headers)
                self.assertGreaterEqual(status, 400)
                self.assertNotIn(CANARY, content.decode())
        self.assertEqual(self.calls, [])

    def test_https_proxy_contract_fixture_only(self):
        server = sf.make_server(self.service, public_origin='https://form.example')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        try:
            conn.request('POST', '/submit/' + self.rid, self.body(),
                         {'Host': 'form.example', 'Origin': 'https://form.example',
                          'Content-Type': 'application/json'})
            response = conn.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())['status'], 'submitted')
        finally:
            conn.close()
            server.shutdown()
            server.server_close()
            thread.join(3)


class CliSinkTests(unittest.TestCase):
    def test_supported_cli_bridge_stdin_only_and_confirmed_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            sink = sf.VaultCliSink([sys.executable, str(SPIKE / 'fixture_vault_cli.py'),
                                   'vault', 'add', '--kind', 'login'], tmp,
                                  origin='https://login.example', identifier='fixture-user')
            request = sf.Request('fixture-request', 'Example login', USER, USER, NOW, NOW + 120)
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertTrue(sink(request, CANARY))
            self.assertNotIn(CANARY, output.getvalue())
            self.assertNotIn(CANARY, repr(sink.argv))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_cli_exit_zero_without_receipt_timeout_and_malicious_stdout(self):
        request = sf.Request('fixture-request', 'Login', USER, USER, NOW, NOW + 120)
        for code in ('pass', 'import time; time.sleep(2)',
                     'import sys; print(sys.stdin.read())', 'raise RuntimeError("failure")'):
            with tempfile.TemporaryDirectory() as tmp, self.subTest(code=code):
                sink = sf.VaultCliSink([sys.executable, '-c', code], tmp,
                                      origin='https://login.example', identifier='fixture-user', timeout=.1)
                output = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                    self.assertFalse(sink(request, CANARY))
                self.assertNotIn(CANARY, output.getvalue())


if __name__ == '__main__':
    unittest.main()
