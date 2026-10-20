'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const router = require(process.env.HERMES_NOTICE_ROUTER || '../alans-way/scripts/workspace-router.cjs');
const offline = { state: 'offline', since: 'fixture-offline', lastSeenOnline: null };
const status = { protocol: 1, host: 'vps', capabilities: ['tabs'], tabCount: 1 };
const tab = { id: 'current', url: 'https://example.com/', botId: 'reader', controller: 'agent', epoch: 7, humanHold: false, handback: null };
const tabs = { tabs: [tab] };
function fixture(t, ctx = {}, host = 'vps', label = 'Mac') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'router-notice-'));
  const state = path.join(dir, 'state.json');
  fs.writeFileSync(state, JSON.stringify(offline));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const context = { botId: 'reader', ...ctx };
  const annotate = router.makeAnnotator(host, true, state, label, context);
  let id = 1;
  function call(name, data = name === 'status' ? status : tabs, extra = {}, args = {}) {
    const request = { method: 'tools/call', name: 'cua_alans_way_' + name,
      line: JSON.stringify({ method: 'tools/call', params: { name: 'cua_alans_way_' + name, arguments: args } }) };
    const original = { jsonrpc: '2.0', id: id++, result: { content: [{ type: 'text', text: JSON.stringify(data) }],
      _meta: { backend: { kept: true } }, structuredContent: { nested: { workspace: 'business', approvalContext: 'kept' } }, ...extra } };
    const reply = JSON.parse(annotate(JSON.stringify(original), 3, request));
    assert.deepEqual(reply.result.content[0], Array.isArray(data?.tabs)
      ? { type: 'text', text: JSON.stringify({ ...data, requestingBotId: context.botId }) } : original.result.content[0]);
    assert.deepEqual(reply.result.structuredContent, original.result.structuredContent);
    assert.deepEqual(reply.result._meta.backend, original.result._meta.backend);
    return reply;
  }
  const notice = reply => reply.result.content.at(-1).text;
  // The annotator is stateless: every offline VPS reply carries the full
  // standalone notice verbatim; no reply ever claims observations are stable.
  const full = reply => {
    assert.equal(notice(reply), router.workspaceNotice(host, JSON.parse(fs.readFileSync(state)), null, null, label, context.restoredNote) + ' (took 3ms)');
    assert.doesNotMatch(notice(reply), /Reuse current observations/);
  };
  return { dir, state, context, annotate, call, notice, full };
}
test('repeated identical reads always carry the verbatim full recovery notice', t => {
  const f = fixture(t);
  for (let i = 0; i < 4; i++) { f.full(f.call('status')); f.full(f.call('tabs')); }
});
test('unknown requests and missing request proof keep the full notice', t => {
  const f = fixture(t); f.full(f.call('status')); f.full(f.call('status'));
  const line = JSON.stringify({ jsonrpc: '2.0', id: 1, result: { content: [{ type: 'text', text: JSON.stringify(status) }] } });
  for (const req of [undefined, { method: 'tools/call', name: 'unrecognized' }, { method: 'tools/call', name: 'cua_alans_way_status', line: '{}' }]) {
    const reply = JSON.parse(f.annotate(line, 3, req)); f.full(reply);
  }
});
for (const [name, changed] of [
  ['owner', { ...tab, botId: 'other' }], ['epoch', { ...tab, epoch: 8 }],
  ['controller', { ...tab, controller: 'human' }], ['human hold', { ...tab, humanHold: true }],
  ['handback', { ...tab, handback: { reason: 'login' } }], ['destination', { ...tab, id: 'next' }],
  ['URL', { ...tab, url: 'https://example.com/next' }], ['review', { ...tab, review: ['current'] }],
  ['human lock', { ...tab, humanLock: true }], ['human held', { ...tab, humanHeld: true }],
  ['blocked', { ...tab, blocked: { reason: 'captcha' } }], ['handoff', { ...tab, handoff: { to: 'human' } }],
  ['busy', { ...tab, agentBusy: true }], ['loading', { ...tab, loading: true }],
]) test('changed ' + name + ' keeps the full notice', t => {
  const f = fixture(t); f.full(f.call('status')); f.full(f.call('tabs'));
  f.full(f.call('tabs', { tabs: [changed] })); f.full(f.call('status'));
});
for (const [name, data, extra] of [
  ['error', status, { isError: true }], ['unknown success', { value: 1 }, {}],
  ['status error', { ...status, error: 'unknown outcome' }, {}], ['invalid tabs', { tabs: [{}] }, {}],
  ['metadata error', status, { _meta: { browserRequest: { status: 409 } } }],
  ['large text', { ...status, text: 'x'.repeat(110000) }, {}],
  ['unavailable browser', { ...status, browserUp: false }, {}], ['busy browser', { ...status, busy: true }, {}],
  ['false success', { ...status, ok: false }, {}], ['empty tabs', { tabs: [] }, {}],
]) test(name + ' never produces a shortened notice', t => {
  const f = fixture(t); f.full(f.call('status')); f.full(f.call(name === 'invalid tabs' ? 'tabs' : 'status', data, extra));
  f.full(f.call('status')); f.full(f.call('tabs'));
});
test('actions and snapshots keep full notices', t => {
  const f = fixture(t); f.full(f.call('status')); f.full(f.call('tabs'));
  for (const name of ['action', 'snapshot', 'other']) {
    f.full(f.call(name, { tab, generation: 1 })); f.full(f.call('status')); f.full(f.call('tabs'));
  }
});
test('continuation, review, move and id-change notices remain exact and one-shot', t => {
  const moved = router.continuationNotice({ status: 'restored', map: { old: 'current' }, review: ['current'] });
  const changed = ['[workspace] tab id changed: old -> current, reason: fixture'];
  let take = moved, ids = changed;
  const f = fixture(t, { takeMoveNotice() { const n = take; take = null; return n; }, takeTabIdChanged() { const n = ids; ids = null; return n; } });
  const first = f.call('status'); assert.equal(f.notice(first), moved + ' (took 3ms)');
  assert.deepEqual(first.result._meta.workspace.tabIdChanged, changed);
  f.full(f.call('status')); f.full(f.call('status'));
  assert.equal(f.call('tabs').result._meta.workspace.tabIdChanged, undefined);
  f.context.restoredNote = 'Review these destination ids: current';
  for (let i = 0; i < 2; i++) { f.full(f.call('status')); f.full(f.call('tabs')); }
});
test('remembered/continued pages always retain destination and login recovery text', t => {
  const f = fixture(t); f.full(f.call('status')); f.full(f.call('tabs'));
  const record = { url: tab.url, at: Date.now(), openedAt: Date.now(), tabId: tab.id };
  fs.writeFileSync(path.join(f.dir, 'resume-url-reader.json'), JSON.stringify(record));
  for (const name of ['status', 'tabs', 'status', 'tabs']) {
    const text = f.notice(f.call(name)); assert.match(text, /Continued https:\/\/example.com\/ in the VPS browser as tab current/);
    assert.match(text, /sign in, tell the user/); assert(!text.includes('Reuse current observations'));
  }
});
test('state flips, unknown state, failed-over context and different hosts stay full', t => {
  const f = fixture(t); f.full(f.call('status')); f.full(f.call('tabs'));
  const online = { state: 'online', since: 'fixture-online', lastSeenOnline: null };
  fs.writeFileSync(f.state, JSON.stringify(online));
  assert.equal(f.notice(f.call('status')), router.workspaceNotice('vps', online) + ' (took 3ms)');
  assert.equal(f.call('status').result.content.length, 1);
  fs.unlinkSync(f.state); assert.equal(f.call('tabs').result.content.length, 1);
  fs.writeFileSync(f.state, JSON.stringify(offline)); f.full(f.call('status'));
  f.context.failedOver = true; f.full(f.call('status')); f.full(f.call('tabs')); f.full(f.call('status'));
  for (const host of ['mac', 'vm']) { const other = fixture(t, {}, host); assert.equal(other.call('status').result.content.length, 1); }
});
test('large unparsed image replies keep the full recovery notice', t => {
  const f = fixture(t); f.full(f.call('status')); f.full(f.call('tabs'));
  const original = JSON.stringify({ jsonrpc: '2.0', id: 7, result: { content: [{ type: 'image', data: 'x'.repeat(110000), mimeType: 'image/png' }] } });
  const req = { method: 'tools/call', name: 'cua_alans_way_status', line: '{}' };
  f.full(JSON.parse(f.annotate(original, 3, req))); f.full(f.call('status')); f.full(f.call('tabs'));
  const sdk = JSON.stringify({ result: { content: [{ type: 'image', data: 'x'.repeat(110000), mimeType: 'image/png' }] }, jsonrpc: '2.0', id: 8 });
  f.full(JSON.parse(f.annotate(sdk, 3, req)));
});
test('changed business values, structured content and backend metadata keep full notices', t => {
  const f = fixture(t); f.full(f.call('status')); f.full(f.call('tabs'));
  f.full(f.call('status', { ...status, business: { value: 'changed' } }));
  f.full(f.call('tabs')); f.full(f.call('status', { ...status, business: { value: 'changed' } }));
  f.full(f.call('tabs', tabs, { _meta: { backend: { kept: 'changed' } } })); f.full(f.call('status'));
  f.full(f.call('tabs', tabs, { structuredContent: { nested: { workspace: 'changed business' } } })); f.full(f.call('status'));
});
test('RPC errors and unrecognized content pass through with full notices intact', t => {
  const f = fixture(t); f.full(f.call('status')); f.full(f.call('tabs'));
  const error = JSON.stringify({ jsonrpc: '2.0', id: 9, error: { code: -32000, message: 'Outcome unknown' } });
  assert.equal(f.annotate(error), error); f.full(f.call('status')); f.full(f.call('tabs'));
  f.full(f.call('status', status, { content: [{ type: 'text', text: 'Unparsed outcome' }] })); f.full(f.call('tabs'));
});
