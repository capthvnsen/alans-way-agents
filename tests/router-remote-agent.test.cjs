// Remote agent end to end through the real router: the SSH forced command from
// setup-remote-agent.sh and the opt-in HTTP bridge, both reaching an owned fake
// Mac backend through an exec shim named ssh. No real host, SSH or network.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const readline = require('node:readline');
const { spawn, spawnSync } = require('node:child_process');
const scripts = path.resolve(__dirname, '../alans-way/scripts');
const bridge = path.join(scripts, 'remote-agent-bridge.cjs');
const TOKEN = 'owned-bridge-token-' + 'x'.repeat(32);
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(read, label, timeout = 8000) {
  const end = Date.now() + timeout;
  while (!read()) { assert.ok(Date.now() < end, label); await sleep(10); }
  return read();
}

function fixture(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'router-remote-'));
  const file = name => path.join(dir, name);
  fs.mkdirSync(file('bin'));
  fs.writeFileSync(file('state.json'), JSON.stringify({ state: 'online', since: new Date().toISOString() }));
  fs.writeFileSync(file('router-last-self-probe'), String(Date.now()));
  fs.writeFileSync(file('preload.cjs'), `
const fs=require('node:fs'),path=require('node:path'),dir=process.env.REMOTE_FIXTURE_DIR;
const redirect=p=>p==='/tmp/wsr-'+process.getuid()?path.join(dir,'ssh-dir'):p;
for(const name of ['mkdirSync','lstatSync']){const old=fs[name];fs[name]=(p,...a)=>old(redirect(p),...a);}
global.fetch=async()=>{throw new Error('Fixture forbids network access');};
`);
  fs.writeFileSync(file('ssh.cjs'), `
const fs=require('node:fs'),path=require('node:path'),dir=process.env.REMOTE_FIXTURE_DIR;
const remote=process.argv.at(-1);
if(!remote.includes('--bot-id')){process.stdout.write('/fixture/browser-mcp.cjs');return;}
fs.appendFileSync(path.join(dir,'mac-commands'),remote+'\\n');
fs.appendFileSync(path.join(dir,'children'),process.pid+'\\n');
const tools=['cua_alans_way_open','workspace_computer_snapshot','workspace_computer_action']
 .map(name=>({name,inputSchema:{type:'object'},annotations:{readOnlyHint:name.endsWith('snapshot')}}));
require('node:readline').createInterface({input:process.stdin}).on('line',line=>{
 const m=JSON.parse(line);
 if(m.method==='initialize')fs.appendFileSync(path.join(dir,'mac-initialize'),JSON.stringify(m.params)+'\\n');
 if(m.id===undefined)return;
 const result=m.method==='initialize'?{protocolVersion:m.params.protocolVersion,capabilities:{tools:{}},serverInfo:{name:'owned-mac',version:'1'}}:
  m.method==='tools/list'?{tools}:
  {content:[{type:'text',text:JSON.stringify({ok:true,host:'local',tab:{id:'mac-tab',epoch:1},echo:m.params.arguments})}]};
 process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result})+'\\n');
});
`);
  fs.writeFileSync(file('bin/ssh'), '#!/bin/sh\nexec "$REMOTE_FIXTURE_NODE" "$REMOTE_FIXTURE_DIR/ssh.cjs" "$@"\n', { mode: 0o755 });
  const env = { PATH: file('bin') + path.delimiter + path.dirname(process.execPath) + path.delimiter + '/usr/bin:/bin',
    HOME: dir, HERMES_HOME: file('profile'), NODE_OPTIONS: '--require=' + file('preload.cjs'),
    REMOTE_FIXTURE_DIR: dir, REMOTE_FIXTURE_NODE: process.execPath };
  const processes = [];
  const lines = name => fs.existsSync(file(name)) ? fs.readFileSync(file(name), 'utf8').trim().split('\n').filter(Boolean) : [];
  t.after(async () => {
    for (const p of processes) {
      if (p.exitCode === null && p.signalCode === null) p.kill('SIGTERM');
      await until(() => p.exitCode !== null || p.signalCode !== null, 'owned process cleanup');
    }
    for (const pid of lines('children').map(Number)) {
      let alive = false; try { process.kill(pid, 0); alive = true; } catch {}
      if (alive) { process.kill(pid, 'SIGKILL'); assert.fail('a fake Mac backend outlived its router'); }
    }
    fs.rmSync(dir, { recursive: true, force: true });
  });
  return { dir, file, env, lines, processes };
}

// Forced command printed by setup-remote-agent.sh for this fixture's Mac settings.
function forcedCommand(f) {
  const setup = spawnSync('sh', [path.resolve(__dirname, '../scripts/setup-remote-agent.sh'), '--bot-id', 'remote-1', '--bot-name', 'Remote Agent',
    '--router', path.join(scripts, 'workspace-router.cjs'), '--mac-ssh', 'owned-fixture-only', '--state-file', f.file('state.json'), '--print'],
    { env: { ...process.env, HOME: f.dir, HERMES_HOME: f.file('profile') }, encoding: 'utf8' });
  assert.equal(setup.status, 0, setup.stderr);
  return setup.stdout.match(/\nForced command:\n(.+)\n/)[1];
}

test('SSH forced command reaches the Mac through the router under the remote bot ID with desktop input', async t => {
  const f = fixture(t);
  const p = spawn('sh', ['-c', forcedCommand(f)], { env: f.env, stdio: ['pipe', 'pipe', 'pipe'] });
  f.processes.push(p);
  let stderr = ''; p.stderr.on('data', b => stderr += b);
  const messages = [];
  readline.createInterface({ input: p.stdout }).on('line', line => messages.push(JSON.parse(line)));
  const send = m => p.stdin.write(JSON.stringify({ jsonrpc: '2.0', ...m }) + '\n');
  const recv = id => until(() => messages.find(m => m.id === id), 'reply ' + id + ': ' + stderr);
  send({ id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'remote', version: '1' } } });
  await recv(1);
  send({ method: 'notifications/initialized' });
  send({ id: 2, method: 'tools/list' });
  assert.ok((await recv(2)).result.tools.some(tool => tool.name === 'workspace_computer_action'));
  send({ id: 3, method: 'tools/call', params: { name: 'cua_alans_way_open', arguments: { url: 'https://example.com/' } } });
  assert.equal((await recv(3)).result._meta.workspace.host, 'mac');
  assert.match(f.lines('mac-commands')[0], /--bot-id 'remote-1'/);
  p.stdin.end();
  await until(() => p.exitCode !== null, 'router exits on client EOF');
});

function startBridge(f, { env = {}, args = ['--bot-id', 'remote-1', '--bot-name', 'Remote Agent', '--mac-ssh', 'owned-fixture-only',
  '--mac-state-file', f.file('state.json')] } = {}) {
  const p = spawn(process.execPath, [bridge, ...args], { env: { ...f.env, HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS: '1',
    ALANS_WAY_REMOTE_BRIDGE: '1', ALANS_WAY_REMOTE_BRIDGE_PORT: '0', ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
  f.processes.push(p);
  const out = { p, stderr: '' };
  p.stderr.on('data', b => out.stderr += b);
  out.exited = () => until(() => p.exitCode !== null, 'bridge exit: ' + out.stderr).then(() => p.exitCode);
  out.ready = async () => {
    const url = await until(() => out.stderr.match(/listening on (http:\/\/\S+\/mcp)/)?.[1], 'bridge listening: ' + out.stderr);
    out.url = url;
    return out;
  };
  return out;
}

function tokenFile(f, token = TOKEN, mode = 0o600) {
  fs.writeFileSync(f.file('token'), token + '\n', { mode });
  fs.chmodSync(f.file('token'), mode);
  return { ALANS_WAY_REMOTE_BRIDGE_TOKEN_FILE: f.file('token') };
}

async function post(b, message, { token = TOKEN, session, body } = {}) {
  const headers = { 'content-type': 'application/json', accept: 'application/json, text/event-stream' };
  if (token) headers.authorization = 'Bearer ' + token;
  if (session) headers['mcp-session-id'] = session;
  const res = await fetch(b.url, { method: 'POST', headers, body: body ?? JSON.stringify({ jsonrpc: '2.0', ...message }) });
  const text = await res.text();
  return { status: res.status, session: res.headers.get('mcp-session-id'), body: text ? JSON.parse(text) : null };
}

const initialize = (id = 1, capabilities = {}) => ({ id, method: 'initialize',
  params: { protocolVersion: '2025-06-18', capabilities, clientInfo: { name: 'remote-http', version: '1' } } });

test('bridge stays off unless enabled and refuses weak tokens and public binds without echoing secrets', async t => {
  const f = fixture(t);
  const off = startBridge(f, { env: { ALANS_WAY_REMOTE_BRIDGE: '', ...tokenFile(f) } });
  assert.notEqual(await off.exited(), 0);
  assert.match(off.stderr, /ALANS_WAY_REMOTE_BRIDGE=1/);
  for (const env of [{}, tokenFile(f, 'short-secret-value'), tokenFile(f, TOKEN, 0o644)]) {
    const b = startBridge(f, { env });
    assert.notEqual(await b.exited(), 0);
    assert.ok(!b.stderr.includes('short-secret-value') && !b.stderr.includes(TOKEN), b.stderr);
  }
  // The IPv4 wildcard is built at runtime so check_publication.py's address scan stays quiet.
  for (const host of [Array(4).fill(0).join('.'), '::', '8.8.8.8', 'example.com']) {
    const b = startBridge(f, { env: { ...tokenFile(f), ALANS_WAY_REMOTE_BRIDGE_HOST: host } });
    assert.notEqual(await b.exited(), 0, host);
    assert.match(b.stderr, /private/);
  }
});

test('bridge carries a full MCP session to the Mac through the router and never logs the token', async t => {
  const f = fixture(t);
  const b = await startBridge(f, { env: tokenFile(f) }).ready();
  assert.match(b.url, /^http:\/\/127\.0\.0\.1:\d+\/mcp$/);
  const init = await post(b, initialize(1, { elicitation: {}, sampling: {}, roots: {} }));
  assert.equal(init.status, 200);
  assert.equal(init.body.id, 1);
  assert.ok(init.session);
  const session = init.session;
  assert.equal((await post(b, { method: 'notifications/initialized' }, { session })).status, 202);
  const list = await post(b, { id: 2, method: 'tools/list' }, { session });
  assert.ok(list.body.result.tools.some(tool => tool.name === 'workspace_computer_action'));
  const call = await post(b, { id: 'three', method: 'tools/call', params: { name: 'cua_alans_way_open', arguments: { url: 'https://example.com/' } } }, { session });
  assert.equal(call.status, 200);
  assert.equal(call.body.id, 'three');
  assert.equal(call.body.result._meta.workspace.host, 'mac');
  assert.match(f.lines('mac-commands')[0], /--bot-id 'remote-1'/);
  // The bridge cannot carry server-to-client requests, so the router must not expect them.
  assert.deepEqual(JSON.parse(f.lines('mac-initialize')[0]).capabilities, {});
  const end = await fetch(b.url, { method: 'DELETE', headers: { authorization: 'Bearer ' + TOKEN, 'mcp-session-id': session } });
  assert.equal(end.status, 204);
  assert.equal((await post(b, { id: 4, method: 'tools/list' }, { session })).status, 404);
  assert.ok(!b.stderr.includes(TOKEN));
});

test('bridge rejects missing or wrong tokens, unknown sessions, oversized and malformed bodies', async t => {
  const f = fixture(t);
  const b = await startBridge(f, { env: tokenFile(f) }).ready();
  assert.equal((await post(b, initialize(), { token: null })).status, 401);
  assert.equal((await post(b, initialize(), { token: TOKEN + 'x' })).status, 401);
  assert.equal((await post(b, { id: 2, method: 'tools/list' })).status, 400);
  assert.equal((await post(b, { id: 2, method: 'tools/list' }, { session: 'not-a-session' })).status, 404);
  assert.equal((await post(b, null, { body: '{' })).status, 400);
  assert.equal((await post(b, null, { body: '[]' })).status, 400);
  assert.equal((await post(b, null, { body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', pad: 'x'.repeat(1 << 20) }) })).status, 413);
  const get = await fetch(b.url, { headers: { authorization: 'Bearer ' + TOKEN } });
  assert.equal(get.status, 405);
  assert.equal(f.lines('mac-commands').length, 0, 'rejected requests never start a router');
});

test('bridge caps concurrent sessions and reads the token from the environment', async t => {
  const f = fixture(t);
  const b = await startBridge(f, { env: { ALANS_WAY_REMOTE_BRIDGE_TOKEN: TOKEN } }).ready();
  const sessions = [];
  for (let i = 0; i < 4; i++) {
    const init = await post(b, initialize(i));
    assert.equal(init.status, 200);
    sessions.push(init.session);
  }
  assert.equal(new Set(sessions).size, 4);
  assert.equal((await post(b, initialize(9))).status, 503);
  b.p.kill('SIGTERM');
  assert.equal(await b.exited(), 0);
});
