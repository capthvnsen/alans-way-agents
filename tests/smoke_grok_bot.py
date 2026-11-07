#!/usr/bin/env python3
"""Live Grok Bot smoke test: shared config -> generated package -> restricted SSH -> real tool calls.

Runs the path a Grok Bot connector uses (ssh -> forced command -> workspace-router -> browser-mcp.cjs
-> browser host -> Chromium) with a private sshd, a temporary HOME and a throwaway headless Chromium.
It never reads your Workspace connection file, config, SSH keys or Hermes state. Needs node, sshd,
network access to example.com and jsonschema (shared/requirements.txt). Not run by CI: it needs all that.

    python tests/smoke_grok_bot.py --workspace-mcp /path/to/desktop/scripts/browser-mcp.cjs --chromium /path/to/chromium
"""
import argparse
import glob
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
APP_MCP = '/Applications/alans-way-localapp.app/Contents/Resources/app/scripts/browser-mcp.cjs'
PLAYWRIGHT = '~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell'
BOT = 'grok-smoke'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def until(check, label, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f'timed out waiting for {label}')


def check_package(home, output):
    config = json.loads((ROOT / 'shared/config.example.json').read_text())
    config['identity']['name'] = 'Smoke Alan ☀'
    config['proactivity']['enabled'] = True
    path = home / '.config/alans-way/config.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(config), encoding='utf-8')
    # No --config: this has to find the file through the default path under HOME.
    subprocess.run([sys.executable, str(ROOT / 'scripts/generate_grok_bot.py'), '--output', str(output)],
                   env={**os.environ, 'HOME': str(home)}, check=True)
    settings = json.loads((output / 'settings.json').read_text(encoding='utf-8'))
    schema = json.loads((ROOT / 'alans-way-grok-bot/settings.schema.json').read_text())
    Draft202012Validator(schema).validate(settings)
    assert settings['persona']['name'] == 'Smoke Alan ☀', 'settings did not come from the shared config'
    assert len(settings['routines']) == 1, 'enabled proactivity should produce one routine'
    skill = (output / 'SKILL.md').read_text(encoding='utf-8')
    assert skill.startswith('---\nname: alans-way-grok-bot\ndescription: '), 'bad skill frontmatter'
    assert 'Smoke Alan ☀' in skill, 'skill did not come from the shared config'
    print('ok  package: default config path, settings schema, skill frontmatter')


class Client:
    """Line-delimited JSON-RPC over the exact client command setup-remote-agent.sh prints."""

    def __init__(self, argv, log):
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log, text=True)
        self.lines = queue.Queue()
        self.next_id = 0
        threading.Thread(target=lambda: [self.lines.put(line) for line in self.proc.stdout], daemon=True).start()

    def request(self, method, params, timeout=60):
        self.next_id += 1
        self.proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.next_id, 'method': method, 'params': params}) + '\n')
        self.proc.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            reply = json.loads(self.lines.get(timeout=max(0, deadline - time.monotonic())))
            if reply.get('id') == self.next_id:
                assert 'result' in reply, f'{method} failed: {reply.get("error")}'
                return reply['result']

    def call(self, name, **arguments):
        result = self.request('tools/call', {'name': name, 'arguments': arguments})
        text = result['content'][0]['text']
        assert not result.get('isError'), f'{name} failed: {text}'
        return text


def round_trip(client):
    client.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                  'clientInfo': {'name': 'grok-bot-smoke', 'version': '1'}})
    client.proc.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    client.proc.stdin.flush()
    names = {tool['name'] for tool in client.request('tools/list', {})['tools']}
    print(f'ok  tools/list over SSH: {len(names)} tools')
    assert {'cua_alans_way_open', 'workspace_computer_snapshot'} <= names, f'missing tools: {sorted(names)}'
    tab = json.loads(client.call('cua_alans_way_open', url='https://example.com'))
    print(f"ok  cua_alans_way_open: tab {tab['id']}")
    assert 'Example Domain' in client.call('cua_alans_way_snapshot', tabId=tab['id']), 'page text missing'
    print('ok  cua_alans_way_snapshot: read "Example Domain" back from Chromium')
    client.call('cua_alans_way_close', tabId=tab['id'], epoch=tab['epoch'])
    print('ok  cua_alans_way_close')


def run(args, tmp):
    home = tmp / 'home'
    check_package(home, tmp / 'package')

    procs, logs = [], tmp / 'logs'
    logs.mkdir()
    def start(name, argv, **kwargs):
        log = (logs / name).open('w')
        procs.append(subprocess.Popen(argv, stdout=log, stderr=log, stdin=subprocess.DEVNULL, **kwargs))
    try:
        cdp = free_port()
        start('chromium', [args.chromium, '--headless', f'--remote-debugging-port={cdp}', f'--user-data-dir={tmp}/chromium'])
        until(lambda: urllib.request.urlopen(f'http://127.0.0.1:{cdp}/json/version', timeout=2), 'Chromium')

        data = tmp / 'browser'
        data.mkdir(mode=0o700)
        (data / 'config.json').write_text(json.dumps({'cdpUrl': f'http://127.0.0.1:{cdp}', 'port': free_port()}))
        host_env = {**os.environ, 'HOME': str(home), 'HERMES_VPS_BROWSER_DATA': str(data)}
        start('host', ['node', str(Path(args.workspace_mcp).with_name('vps-browser-host.cjs')), 'serve'], env=host_env)
        until((data / 'connection.json').exists, 'browser host')

        # The real provisioning step: writes the key, authorized_keys and client JSON under the temp HOME.
        setup = subprocess.run(['sh', str(ROOT / 'scripts/setup-remote-agent.sh'), '--bot-id', BOT, '--user', os.environ['USER'],
                                '--router', str(ROOT / 'alans-way/scripts/workspace-router.cjs'),
                                '--state-file', str(tmp / 'mac-state.json')],
                               env={**os.environ, 'HOME': str(home), 'HERMES_HOME': str(home / '.hermes')},
                               check=True, capture_output=True, text=True)
        printed = setup.stdout[setup.stdout.index('{\n  "command"'):]
        client_json = json.JSONDecoder().raw_decode(printed)[0]

        sshd_port = free_port()
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(tmp / 'host_key')], check=True)
        env_line = ' '.join(f'"{key}={value}"' for key, value in {
            'HOME': home, 'HERMES_HOME': home / '.hermes',
            'HERMES_WORKSPACE_VPS_MCP': args.workspace_mcp, 'HERMES_WORKSPACE_CONNECTION': data / 'connection.json'}.items())
        (tmp / 'sshd_config').write_text(f'''Port {sshd_port}
ListenAddress 127.0.0.1
HostKey {tmp}/host_key
AuthorizedKeysFile {home}/.ssh/authorized_keys
PidFile {tmp}/sshd.pid
UsePAM no
StrictModes no
PasswordAuthentication no
SetEnv {env_line}
''')
        start('sshd', [args.sshd, '-D', '-e', '-f', str(tmp / 'sshd_config')])
        until(lambda: socket.create_connection(('127.0.0.1', sshd_port), timeout=1).close() is None, 'sshd')

        assert client_json['command'] == 'ssh'
        destination = client_json['args'][-1].replace('@HOST', '@127.0.0.1')
        argv = ['ssh', '-p', str(sshd_port), '-o', f'UserKnownHostsFile={tmp}/known_hosts', *client_json['args'][:-1], destination]
        with (logs / 'client').open('w') as log:
            client = Client(argv, log)
            try:
                round_trip(client)
            finally:
                client.proc.kill()
                client.proc.wait()
    except BaseException:
        for log in sorted(logs.iterdir()):
            print(f'--- {log.name} log\n{log.read_text(errors="replace")[-1500:]}', file=sys.stderr)
        raise
    finally:
        for proc in reversed(procs):
            proc.terminate()
            proc.wait()


def main():
    found = sorted(glob.glob(os.path.expanduser(PLAYWRIGHT)))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace-mcp', default=APP_MCP, help='browser-mcp.cjs (default: the installed app copy)')
    parser.add_argument('--chromium', default=found[-1] if found else shutil.which('chromium'), help='Chromium binary')
    parser.add_argument('--sshd', default=shutil.which('sshd') or '/usr/sbin/sshd')
    args = parser.parse_args()
    if not args.chromium or not Path(args.workspace_mcp).is_file():
        parser.error('pass --chromium and --workspace-mcp; one was not found')
    # /tmp, not $TMPDIR: the router's ssh control sockets have a short path limit.
    with tempfile.TemporaryDirectory(prefix='grok-smoke-', dir='/tmp') as tmp:
        run(args, Path(tmp).resolve())
    print('PASS')


if __name__ == '__main__':
    main()
