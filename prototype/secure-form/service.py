"""Throwaway, stdlib-only Secure Form spike. Never install as a live service.

Default CLI runs a loopback-only demo with synthetic Telegram identity and a
discarding CLI fixture. No bot requests, tunnel, browser, or real vault access.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

MAX_BODY = 16384
MAX_AGE = 300
TTL = 120


class Rejected(Exception):
    """Deliberately has no caller-supplied error text."""


@dataclass
class Request:
    request_id: str
    label: str
    user_id: int
    chat_id: int
    issued_at: int
    expires_at: int
    status: str = 'pending'

    def visible(self):
        return {'label': self.label, 'request_id': self.request_id, 'status': self.status}


def validate_init_data(raw, token, now):
    """Telegram HMAC scheme: raw signed initData, never initDataUnsafe."""
    try:
        if not isinstance(raw, str) or len(raw.encode()) > 8192:
            raise Rejected()
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=32)
        fields = dict(pairs)
        if len(fields) != len(pairs) or any('\n' in k or '\r' in k or not k for k in fields):
            raise Rejected()
        supplied = fields.pop('hash')
        if not re.fullmatch(r'[0-9a-f]{64}', supplied):
            raise Rejected()
        check = '\n'.join(f'{key}={value}' for key, value in sorted(fields.items()))
        key = hmac.digest(b'WebAppData', token.encode(), 'sha256')
        expected = hmac.digest(key, check.encode(), 'sha256').hex()
        if not hmac.compare_digest(supplied, expected):
            raise Rejected()
        when = int(fields['auth_date'])
        if not now - MAX_AGE <= when <= now + 30:
            raise Rejected()
        user = json.loads(fields['user'])
        if type(user.get('id')) is not int or user['id'] <= 0 or not fields.get('query_id'):
            raise Rejected()
        chat = json.loads(fields['chat']) if 'chat' in fields else None
        if chat is not None and (type(chat.get('id')) is not int or chat.get('type') != 'private'):
            raise Rejected()
        # query_id is signed and unique for this inline launch; do not retain full initData.
        replay_key = hashlib.sha256(fields['query_id'].encode()).hexdigest()
        return user['id'], chat, when, replay_key
    except (ValueError, KeyError, TypeError, AttributeError, UnicodeError):
        raise Rejected() from None


class FormService:
    """One service instance = one fixed bot/profile/sink, trusted issuance only.

    No HTTP issuance endpoint: model arguments cannot set user/chat/destination.
    In-memory state is deliberately lost on restart, so old requests fail closed.
    """
    def __init__(self, token, sink, *, clock=time.time):
        self.token, self.sink, self.clock = token, sink, clock
        self.requests = {}
        self.used_launches = {}
        self.lock = threading.Lock()

    def issue(self, label, *, user_id, chat_id):
        if (type(user_id) is not int or user_id <= 0 or chat_id != user_id
                or not isinstance(label, str) or not re.fullmatch(r'[\w .()-]{1,80}', label)):
            raise Rejected()
        with self.lock:
            # Bounded demo, no unbounded state. Production needs retention/reaping.
            if len(self.requests) >= 128:
                raise Rejected()
            rid = secrets.token_urlsafe(32)
            now = int(self.clock())
            self.requests[rid] = Request(rid, label, user_id, chat_id, now, now + TTL)
            return rid

    def _authorized(self, rid, raw):
        request = self.requests.get(rid)
        if request is None:
            raise Rejected()
        user, chat, when, replay = validate_init_data(raw, self.token, int(self.clock()))
        if (user != request.user_id or request.chat_id != user
                or when < request.issued_at - 30
                or (chat is not None and chat['id'] != request.chat_id)):
            raise Rejected()
        if request.status == 'pending' and self.clock() >= request.expires_at:
            request.status = 'expired'
        return request, replay

    def status(self, rid, raw):
        with self.lock:
            request, _ = self._authorized(rid, raw)
            return request.visible()

    def submit(self, rid, raw, value):
        if (not isinstance(value, str) or not 1 <= len(value.encode()) <= 4096
                or any(c in value for c in '\r\n\0')):
            raise Rejected()
        with self.lock:
            request, replay = self._authorized(rid, raw)
            if request.status != 'pending' or replay in self.used_launches:
                raise Rejected()
            request.status = 'writing'
            self.used_launches[replay] = rid
        # Claim once before the external write. Failure/uncertain outcome is terminal;
        # never retry a potentially completed vault write under this request ID.
        try:
            confirmed = self.sink(request, value) is True
        except Exception:
            confirmed = False  # Never stringify/log an exception containing a secret.
        finally:
            value = None  # Best effort only: Python does not guarantee zeroization.
        with self.lock:
            request.status = 'submitted' if confirmed else 'failed'
            return request.visible()


class VaultCliSink:
    """Bounded bridge to public `hermes vault add --kind login`, no private imports.

    Fixed administrator argv, home, origin and identifier; never set by form POST.
    Detached session avoids a controlling TTY; getpass uses the private stdin pipe.
    Captured stdout/stderr stay local and are discarded, including on failure.
    This drives the current interactive wizard, NOT a promised automation API.
    Only the fixture is exercised in this spike. Production needs an upstream
    structured stdin+idempotency contract, not dependence on prompt wording.
    """
    def __init__(self, argv, home, *, origin, identifier, timeout=10):
        self.argv = list(argv)
        self.home, self.origin, self.identifier, self.timeout = str(home), origin, identifier, timeout
        parsed = urlsplit(origin)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise Rejected()
        if any(c in origin + identifier for c in '\r\n\0') or not identifier:
            raise Rejected()

    def __call__(self, request, value):
        # Login only; no fake login for a DB URL/token, no payments/codes/unlocks.
        if any(c in request.label + value for c in '\r\n\0'):
            return False
        payload = '\n'.join((request.label, self.origin, 'username', self.identifier, value, '', ''))
        try:
            result = subprocess.run(
                self.argv, input=payload, text=True, encoding='utf-8',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.timeout,
                start_new_session=True, check=False,
                env={'PATH': '/usr/bin:/bin', 'HOME': self.home, 'HERMES_HOME': self.home,
                     'NO_COLOR': '1', 'TERM': 'dumb', 'PYTHONIOENCODING': 'utf-8'})
            # Hermes currently exits 0 even for some VaultError paths: require the
            # positive receipt too. Never return a handle/output/exception to model.
            receipt = re.search(r'Stored\. handle=vault_[0-9a-f]{12} kind=login origin=([^\s]+)',
                                result.stdout)
            return result.returncode == 0 and receipt is not None and receipt.group(1) == self.origin
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return False
        finally:
            payload = None


def button_payload(request, public_origin):
    """Dry payload for sendMessage; NO outbound network call in this spike."""
    parsed = urlsplit(public_origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or request.chat_id != request.user_id):
        raise Rejected()
    return {'chat_id': request.chat_id, 'text': request.label + ' — Secure Form',
            'reply_markup': {'inline_keyboard': [[{'text': 'Open Secure Form',
                'web_app': {'url': public_origin.rstrip('/') + '/form/' + request.request_id}}]]}}


def register_trigger(ctx, service, sender, *, public_origin, profile):
    """Public plugin hook seam; tests inject a sender that only collects JSON.

    Not auto-registered by the demo/plugin. Production sender/token provisioning
    and consent belong to a later reviewed implementation. Fixed form label and
    sink; raw slash-command arguments cannot select identity or destination.
    """
    def admitted(*, platform, source, text, **unused):
        if platform != 'telegram' or text != '/secure-form':
            return None
        rid = None
        try:
            if (source.get('chat_type') != 'dm'
                    or (source.get('profile') or 'default') != profile):
                raise Rejected()
            user, chat = source.get('user_id'), source.get('chat_id')
            if not isinstance(user, str) or not isinstance(chat, str):
                raise Rejected()
            rid = service.issue('Example login', user_id=int(user), chat_id=int(chat))
            if sender(button_payload(service.requests[rid], public_origin)) is not True:
                raise Rejected()
            return {'action': 'handled'}
        except Exception:
            if rid is not None:
                with service.lock:
                    service.requests[rid].status = 'expired'
            # No exception text or provider response enters the gateway reply.
            return {'action': 'handled', 'reply': 'Secure Form unavailable. Use Workspace sign-in.'}
    return ctx.register_hook('post_gateway_admission', admitted)


def form_html(request, nonce, fixture_init_data):
    fixture = fixture_init_data is not None
    init = json.dumps(fixture_init_data).replace('<', '\\u003c') if fixture else 'Telegram.WebApp.initData'
    sdk = '' if fixture else '<script src="https://telegram.org/js/telegram-web-app.js"></script>'
    disclosure = ('Fixture only: value is discarded; no encrypted vault.' if fixture
                  else 'Sent directly to the vault service. Not included in chat or model messages.')
    return f'''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Secure Form spike</title>
{sdk}</head><body><h1>{html.escape(request.label)}</h1><p>{disclosure}</p>
<form><label>Password <input type="password" autocomplete="off" required maxlength="4096"></label>
<button>Save securely</button></form><p role="status">Pending</p>
<script nonce="{nonce}">
const rid = {json.dumps(request.request_id)}, initData = {init};
const form = document.querySelector('form'), input = document.querySelector('input');
const status = document.querySelector('[role=status]'), button = document.querySelector('button');
async function post(kind, fields) {{
  const response = await fetch('/' + kind + '/' + rid, {{method:'POST', cache:'no-store',
    headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{init_data:initData,...fields}})}});
  if (!response.ok) throw new Error('rejected');
  return response.json();
}}
function show(result) {{
  status.textContent = result.status === 'submitted' ? 'Submitted' : result.status;
  button.disabled = result.status !== 'pending';
}}
form.onsubmit = async event => {{
  event.preventDefault(); button.disabled = true; status.textContent = 'Saving';
  let value = input.value; input.value = '';
  try {{ show(await post('submit', {{secret:value}})); }}
  catch {{ status.textContent = 'Unconfirmed. Check status; use a new form only after checking the vault.'; }}
  finally {{ value = null; }}
}};
// An authenticated reconnect can read status without re-sending the secret.
post('status', {{}}).then(show).catch(() => {{status.textContent = 'Unavailable'; button.disabled = true;}});
</script></body></html>'''.encode()


def make_server(service, *, port=0, fixture_init_data=None, public_origin=None):
    # A future dedicated TLS proxy may preserve this exact Host/Origin. No trust
    # in X-Forwarded-*; fixture/demo never creates or configures that proxy.
    if public_origin is not None:
        parsed = urlsplit(public_origin)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.query or parsed.fragment or parsed.path):
            raise Rejected()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def log_message(self, *args):
            pass  # Access logs otherwise include request URLs; no logging here.

        def respond(self, code, body, *, content_type='application/json', nonce=None):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Connection', 'close')
            scripts = f"'nonce-{nonce}'" if nonce else "'none'"
            if fixture_init_data is None:
                scripts += ' https://telegram.org'
            self.send_header('Content-Security-Policy', "default-src 'none'; connect-src 'self'; "
                             f"script-src {scripts}; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def route(self, verb):
            try:
                if self.headers.get('Host') != self.server.authority:
                    raise Rejected()
                match = re.fullmatch(r'/(form|submit|status)/([A-Za-z0-9_-]{43})', self.path)
                if not match:
                    raise Rejected()
                kind, rid = match.groups()
                if verb == 'GET' and kind == 'form':
                    request = service.requests.get(rid)
                    if request is None:
                        raise Rejected()
                    nonce = secrets.token_urlsafe(24)
                    self.respond(200, form_html(request, nonce, fixture_init_data),
                                 content_type='text/html; charset=utf-8', nonce=nonce)
                    return
                if verb != 'POST' or kind not in ('submit', 'status'):
                    raise Rejected()
                if (self.headers.get('Origin') != self.server.allowed_origin
                        or self.headers.get('Content-Type') != 'application/json'
                        or self.headers.get('Transfer-Encoding') is not None
                        or len(self.headers.get_all('Content-Length', [])) != 1):
                    raise Rejected()
                length = int(self.headers['Content-Length'])
                if not 0 < length <= MAX_BODY:
                    raise Rejected()
                body = self.rfile.read(length)
                data = json.loads(body)
                expected = {'init_data', 'secret'} if kind == 'submit' else {'init_data'}
                if not isinstance(data, dict) or set(data) != expected:
                    raise Rejected()
                result = (service.submit(rid, data['init_data'], data['secret']) if kind == 'submit'
                          else service.status(rid, data['init_data']))
                self.respond(200, json.dumps(result).encode())
            except (Rejected, ValueError, TypeError, UnicodeError):
                self.respond(403, b'{"status":"rejected"}')
            except Exception:
                self.respond(503, b'{"status":"unavailable"}')

        def do_GET(self):
            self.route('GET')

        def do_POST(self):
            self.route('POST')

    class LocalServer(ThreadingHTTPServer):
        # Suppress default traceback machinery: even an exception may hold a value.
        def handle_error(self, request, client_address):
            pass

    server = LocalServer(('127.0.0.1', port), Handler)
    server.authority = (urlsplit(public_origin).netloc if public_origin
                        else f'127.0.0.1:{server.server_port}')
    server.allowed_origin = public_origin or 'http://' + server.authority
    return server


def demo():
    """Never accepts real config/token/home arguments or reads runtime auth files."""
    token = 'fixture-bot-token'
    now = int(time.time())
    fields = {'auth_date': str(now), 'user': json.dumps({'id': 101}), 'query_id': 'fixture-launch'}
    key = hmac.digest(b'WebAppData', token.encode(), 'sha256')
    check = '\n'.join(f'{k}={v}' for k, v in sorted(fields.items()))
    fields['hash'] = hmac.digest(key, check.encode(), 'sha256').hex()
    with tempfile.TemporaryDirectory(prefix='secure-form-fixture-') as home:
        sink = VaultCliSink([sys.executable, str(Path(__file__).with_name('fixture_vault_cli.py')),
                             'vault', 'add', '--kind', 'login'], home,
                            origin='https://login.example', identifier='fixture-user')
        service = FormService(token, sink)
        rid = service.issue('Example login', user_id=101, chat_id=101)
        server = make_server(service, fixture_init_data=urlencode(fields))
        print(f'Fixture only; use a synthetic value. http://{server.authority}/form/{rid}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    demo()
