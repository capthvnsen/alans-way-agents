// Owned SSH/stdio fixtures only. An optional installed MCP SDK exercises its
// real initialize/initialized handshake without adding a production dependency.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const readline = require('node:readline');
const router = path.resolve(__dirname, '../alans-way/scripts/workspace-router.cjs');
const sdk = process.env.HERMES_ROUTER_MCP_SDK;
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function until(read, label, timeout = 5000) {
  const end = Date.now() + timeout;
  while (!read()) { assert.ok(Date.now() < end, label); await sleep(10); }
  return read();
}
function fixture(t, { state = 'online', fast = false, slowProbe = false, silent = false } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'router-host-'));
  const file = name => path.join(dir, name);
  fs.mkdirSync(file('bin'));
  fs.writeFileSync(file('clock'), '0');
  fs.writeFileSync(file('router-last-self-probe'), String(Date.now()));
  if (state) fs.writeFileSync(file('state.json'), JSON.stringify({ state, since: new Date().toISOString() }));
  fs.writeFileSync(file('preload.cjs'), `
const fs=require('node:fs'),path=require('node:path'),dir=process.env.HOST_FIXTURE_DIR;
const realNow=Date.now;Date.now=()=>realNow()+Number(fs.readFileSync(path.join(dir,'clock'),'utf8'));
const redirect=p=>p==='/tmp/wsr-'+process.getuid()?path.join(dir,'ssh-dir'):p;
for(const name of ['mkdirSync','lstatSync']){const old=fs[name];fs[name]=(p,...a)=>old(redirect(p),...a);}
if(process.env.HOST_FIXTURE_FAST){const interval=global.setInterval;global.setInterval=(fn,ms,...a)=>interval(fn,ms===10000?25:ms,...a);}
global.fetch=async()=>{throw new Error('Fixture forbids network access');};
`);
  fs.writeFileSync(file('backend.cjs'), `
const fs=require('node:fs'),path=require('node:path'),dir=process.env.HOST_FIXTURE_DIR;
const host=process.env.HOST_FIXTURE_MAC?'mac':'vm';
fs.appendFileSync(path.join(dir,'children'),process.pid+'\\n');
require('node:readline').createInterface({input:process.stdin}).on('line',line=>{
 const m=JSON.parse(line);if(m.id===undefined)return;
 if(host==='mac'&&process.env.HOST_FIXTURE_SILENT)return;
 const a=m.params?.arguments||{};if(a.hang)return;
 const data=m.params?.name==='cua_alans_way_tabs'?{tabs:[{id:host+'-tab',host:host==='mac'?'computer':'vm'}]}:
 {ok:true,host:host==='mac'?'local':'vps',title:'private-title',text:'private-page-content',token:'private-token',botId:'private-bot',url:'https://private.invalid/private-url',tab:{id:host+'-tab',epoch:1}};
 if(a.large)data.text='private-page-content'.repeat(10000);
 const result=m.method==='initialize'?{protocolVersion:m.params.protocolVersion,capabilities:{tools:{}},serverInfo:{name:'owned-fixture',version:'1'}}:{...(a.error?{isError:true}:{}),content:[{type:'text',text:JSON.stringify(data)}]};
 process.stdout.write(JSON.stringify({jsonrpc:'2.0',id:m.id,result})+'\\n');
});
`);
  fs.writeFileSync(file('ssh.cjs'), `
const fs=require('node:fs'),path=require('node:path'),dir=process.env.HOST_FIXTURE_DIR;
if(process.argv.at(-1).includes('--bot-id')){process.env.HOST_FIXTURE_MAC='1';require('./backend.cjs');}
else {
 fs.appendFileSync(path.join(dir,'probes'),'probe\\n');
 setTimeout(()=>{
  if(process.env.HOST_FIXTURE_SLOW_PROBE)fs.writeFileSync(path.join(dir,'state.json'),JSON.stringify({state:'online',since:new Date().toISOString()}));
  if(process.env.HOST_FIXTURE_SLOW_PROBE||fs.existsSync(path.join(dir,'mac-up')))process.stdout.write('/fixture/browser-mcp.cjs');
 },process.env.HOST_FIXTURE_SLOW_PROBE?7500:0);
}
`);
  fs.writeFileSync(file('bin/ssh'), '#!/bin/sh\nexec "$HOST_FIXTURE_NODE" "$HOST_FIXTURE_DIR/ssh.cjs" "$@"\n', { mode: 0o755 });
  const command = { command: process.execPath, args: ['--require', file('preload.cjs'), router,
    '--bot-id', 'private-bot', '--mac-ssh', 'owned-fixture-only', '--mac-script', '/fixture/browser-mcp.cjs',
    '--mac-state-file', file('state.json'), '--vps-script', file('backend.cjs'), '--vps-connection', file('absent.json')],
    env: { PATH: file('bin'), HOME: dir, HOST_FIXTURE_NODE: process.execPath, HOST_FIXTURE_DIR: dir,
      HOST_FIXTURE_FAST: fast ? '1' : '', HOST_FIXTURE_SLOW_PROBE: slowProbe ? '1' : '', HOST_FIXTURE_SILENT: silent ? '1' : '' }, stderr: 'pipe' };
  const processes = [], transports = [];
  const events = name => fs.existsSync(file(name)) ? fs.readFileSync(file(name), 'utf8').trim().split('\n').filter(Boolean) : [];
  t.after(async () => {
    for (const transport of transports) await transport.close();
    for (const p of processes) {
      p.stdin.end();
      await until(() => p.exitCode !== null || p.signalCode !== null, 'owned router cleanup');
    }
    for (const pid of events('children').map(Number)) {
      let alive = false; try { process.kill(pid, 0); alive = true; } catch {}
      if (alive) { process.kill(pid, 'SIGKILL'); assert.fail('router left a connector alive'); }
    }
    fs.rmSync(dir, { recursive: true, force: true });
  });
  const start = () => {
    const p = spawn(command.command, command.args, { env: command.env, stdio: ['pipe', 'pipe', 'pipe'] });
    processes.push(p);p.stdin.on('error', () => {});
    const messages = [];let stderr = '';
    p.stderr.on('data', b => stderr += b);
    readline.createInterface({ input: p.stdout }).on('line', line => messages.push(JSON.parse(line)));
    const send = m => p.stdin.write(JSON.stringify({ jsonrpc: '2.0', ...m }) + '\n');
    const recv = id => until(() => messages.find(m => m.id === id), 'reply ' + id + ': ' + stderr);
    return { p, messages, send, recv, stderr: () => stderr,
      async ready() { send({ id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'owned-client', version: '1' } } });await recv(1);send({ method: 'notifications/initialized' }); },
      call(id, name = 'status', args = {}) { send({ id, method: 'tools/call', params: { name: 'cua_alans_way_' + name, arguments: args } });return recv(id); } };
  };
  return { file, events, command, transports, start,
    advance(ms) { fs.writeFileSync(file('clock'), String(ms));if (fs.existsSync(file('state.json'))) { const at = new Date(Date.now() + ms);fs.utimesSync(file('state.json'), at, at); } } };
}
const serving = c => c.stderr().split('\n').filter(line => line.startsWith('workspace-router: served ')).map(line => JSON.parse(line.slice('workspace-router: served '.length)));

test('serving logs identify default Mac, requested VM, tab affinity and a merged list without private data', async t => {
  const f = fixture(t), c = f.start();await c.ready();
  const mac = await c.call(2, 'open', { url: 'https://private.invalid/private-url' });
  const vm = await c.call(3, 'open', { host: 'vm', url: 'https://private.invalid/private-url' });
  await c.call(4, 'snapshot', { tabId: 'vm-tab' });
  await c.call(5, 'tabs');
  await until(() => serving(c).length === 4, 'one serving log per completed browser call');
  assert.deepEqual(serving(c).map(({ tool, host, selection, reason }) => ({ tool, host, selection, reason })), [
    { tool: 'cua_alans_way_open', host: 'mac', selection: 'defaulted', reason: null },
    { tool: 'cua_alans_way_open', host: 'vm', selection: 'requested', reason: null },
    { tool: 'cua_alans_way_snapshot', host: 'vm', selection: 'defaulted', reason: null },
    { tool: 'cua_alans_way_tabs', host: 'mac', selection: 'defaulted', reason: null },
  ]);
  for (const row of serving(c)) { assert.equal(typeof row.elapsedMs, 'number');assert.ok(row.elapsedMs >= 0);assert.deepEqual(Object.keys(row).sort(), ['elapsedMs','host','reason','selection','tool']); }
  for (const secret of ['private-url','private-title','private-page-content','private-token','private-bot']) assert.ok(!c.stderr().includes(secret), secret);
  assert.equal(mac.result._meta.workspace.host, 'mac');assert.equal(vm.result._meta.workspace.host, 'vm');
});

test('large replies and backend errors each log once; arbitrary tool names cannot leak into stderr', async t => {
  const f = fixture(t), c = f.start();await c.ready();
  await c.call(2, 'screenshot', { large: true });
  const reply = await c.call(3, 'snapshot', { error: true });assert.equal(reply.result.isError, true);
  await c.call(4, 'private-token');
  await until(() => serving(c).length === 2, 'large and error response logs');
  assert.deepEqual(serving(c).map(row => row.tool), ['cua_alans_way_screenshot', 'cua_alans_way_snapshot']);
  assert.ok(!c.stderr().includes('private-'));
});

test('offline fallback log has a fixed reason while an explicit VM call remains requested', async t => {
  const f = fixture(t, { state: 'offline' }), c = f.start();await c.ready();
  const reply = await c.call(2);await c.call(3, 'status', { host: 'vm' });
  await until(() => serving(c).length === 2, 'fallback logs');
  assert.deepEqual(serving(c).map(({ host, selection, reason }) => ({ host, selection, reason })), [
    { host: 'vm', selection: 'fallback', reason: 'watcher_offline' },
    { host: 'vm', selection: 'requested', reason: null },
  ]);
  assert.equal(reply.result._meta.workspace.host, 'vps');
});

for (const state of ['offline', null]) test('idle self-probe escapes a ' + (state ? 'fresh wrong offline marker' : 'dead watcher') + ' and the next connection uses Mac', async t => {
  const f = fixture(t, { state, fast: true }), c = f.start();await c.ready();await c.call(2);
  fs.writeFileSync(f.file('mac-up'), '');f.advance(600001);
  await until(() => c.p.exitCode === 0, 'safe idle must discover recovered Mac despite watcher');
  assert.equal(f.events('probes').length, state ? 1 : 2);
  const next = f.start();await next.ready();const reply = await next.call(2);
  assert.equal(reply.result._meta.workspace.host, 'mac');
  await until(() => serving(next).length === 1, 'recovered Mac log');assert.equal(serving(next)[0].host, 'mac');
});

test('continuous VM work and its current tab stay on VM when Mac returns', async t => {
  const f = fixture(t, { state: 'offline', fast: true }), c = f.start();await c.ready();await c.call(2, 'open');
  fs.writeFileSync(f.file('mac-up'), '');
  for (let i = 0; i < 32; i++) {
    f.advance((i + 1) * 20000);
    const reply = await c.call(i + 3, 'snapshot');assert.equal(reply.result._meta.workspace.host, 'vps');
    await sleep(30);
  }
  assert.equal(f.events('probes').length, 0);assert.equal(c.p.exitCode, null);
});

test('pending VM work blocks self-probe and migration; failed idle probes stay throttled', async t => {
  const f = fixture(t, { state: 'offline', fast: true }), c = f.start();await c.ready();
  c.send({ id: 2, method: 'tools/call', params: { name: 'cua_alans_way_status', arguments: { hang: true } } });
  await sleep(100);f.advance(600001);await sleep(200);
  assert.equal(f.events('probes').length, 0);assert.equal(c.p.exitCode, null);
  c.send({ method: 'notifications/cancelled', params: { requestId: 2 } });
  // EOF cancels the pending fixture call; a separate idle session checks throttling.
  c.p.stdin.end();await until(() => c.p.exitCode === 0, 'pending fixture shutdown');
  const next = f.start();await next.ready();await next.call(2);f.advance(1200002);
  await until(() => f.events('probes').length >= 2, 'idle direct probe');
  const count = f.events('probes').length;await sleep(200);assert.equal(f.events('probes').length, count);
  assert.equal(next.p.exitCode, null);
});

for (const slowProbe of [true, false]) test('MCP connects within setup budget after ' + (slowProbe ? 'slow probe plus silent backend' : 'fresh-online silent retry'), { timeout: 35000 }, async t => {
  const f = fixture(t, { state: slowProbe ? null : 'online', slowProbe, silent: true });
  const setup = spawnSync('/bin/sh', [path.resolve(__dirname, '../setup-workspace.sh'), '--bot-id', 'fixture-only'], { env: { PATH: process.env.PATH, HOME: path.dirname(f.file('clock')) }, encoding: 'utf8' });
  assert.equal(setup.status, 0, setup.stderr);
  const timeout = Number(setup.stdout.match(/connect_timeout: (\d+)/)[1]) * 1000;
  if (!sdk) {
    const c = f.start(), started = Date.now();
    c.send({ id: 1, method: 'initialize', params: { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'owned-client', version: '1' } } });
    await until(() => c.messages.find(m => m.id === 1), 'MCP initialize must fit setup connect timeout', timeout);
    const elapsed = Date.now() - started;
    c.send({ method: 'notifications/initialized' });
    assert.ok(elapsed >= (slowProbe ? 19000 : 12000));assert.match(c.stderr(), /retrying the spawn/);
    assert.equal((await c.call(2)).result._meta.workspace.host, 'vps');
    t.diagnostic('stdio handshake completed in ' + elapsed + 'ms with ' + timeout + 'ms budget');return;
  }
  const { Client } = require(path.join(sdk, 'client/index.js'));
  const { StdioClientTransport } = require(path.join(sdk, 'client/stdio.js'));
  const transport = new StdioClientTransport(f.command);f.transports.push(transport);
  let stderr = '';transport.stderr.on('data', b => stderr += b);
  const client = new Client({ name: 'owned-connect-fixture', version: '1' }, { capabilities: {} });
  const started = Date.now();
  await client.connect(transport, { timeout });
  const elapsed = Date.now() - started;
  assert.ok(elapsed < timeout, 'handshake must fit the configured connect timeout');
  assert.ok(elapsed >= (slowProbe ? 19000 : 12000), 'fixture must exercise real startup windows');
  assert.match(stderr, /retrying the spawn/);assert.match(stderr, /routing to VPS browser host/);
  const reply = await client.callTool({ name: 'cua_alans_way_status', arguments: {} });
  assert.equal(reply._meta.workspace.host, 'vps');
  t.diagnostic('initialize/initialized completed in ' + elapsed + 'ms with ' + timeout + 'ms budget');
});
