'use strict';
// Regressions for the retired conditional notice cache. The annotator is
// stateless: identical byte-for-byte replies, connection-file swaps and
// outstanding writes all keep the full standalone recovery notice — no reply
// may claim "host/tab/owner/controller/epoch stay unchanged", because the
// connection identity the connector used is unknowable at annotation time
// (a same-request file swap lands between dispatch and annotation).
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
function fixture(t, ctx = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'router-stateless-'));
  const state = path.join(dir, 'state.json');
  const connection = path.join(dir, 'connection.json');
  fs.writeFileSync(state, JSON.stringify(offline));
  fs.writeFileSync(connection, JSON.stringify({ url: 'http://127.0.0.1:41001', token: 'one' }));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const context = { botId: 'reader', ...ctx };
  const annotate = router.makeAnnotator('vps', true, state, 'Mac', context);
  let id = 1;
  function call(name, data = name === 'status' ? status : tabs, extra = {}, args = {}) {
    const request = { method: 'tools/call', name: 'cua_alans_way_' + name,
      line: JSON.stringify({ method: 'tools/call', params: { name: 'cua_alans_way_' + name, arguments: args } }) };
    const original = { jsonrpc: '2.0', id: id++, result: { content: [{ type: 'text', text: JSON.stringify(data) }], ...extra } };
    return JSON.parse(annotate(JSON.stringify(original), 3, request));
  }
  const notice = (reply) => reply.result.content.at(-1)?.text || '';
  const full = (reply) => {
    assert.match(notice(reply), /routed to VPS browser/);
    assert.match(notice(reply), /unreachable since/);
    assert.match(notice(reply), /do not blindly repeat input/);
    assert.doesNotMatch(notice(reply), /Reuse current observations/);
  };
  const repeat = (n = 2) => { for (let i = 0; i < n; i++) { full(call('status')); full(call('tabs')); } };
  return { dir, state, connection, context, annotate, call, notice, full, repeat };
}
test('identical repeated reads never shorten the standalone notice', t => {
  const f = fixture(t); f.repeat(4);
  f.full(f.call('status')); f.full(f.call('tabs'));
});
test('a replaced connection file changes nothing: replies stay full', t => {
  const f = fixture(t); f.repeat();
  fs.writeFileSync(f.connection, JSON.stringify({ url: 'http://127.0.0.1:42002', token: 'two' }));
  f.repeat();
});
test('a missing or unreadable connection file changes nothing', t => {
  const f = fixture(t); f.repeat();
  fs.rmSync(f.connection);
  f.full(f.call('status')); f.full(f.call('tabs'));
  fs.writeFileSync(f.connection, JSON.stringify({ url: 'http://127.0.0.1:41001', token: 'one' }));
  f.repeat();
});
test('an outstanding mutating call does not shorten adjacent read notices', t => {
  // The annotator takes no pendingRequests view: every reply is annotated the
  // same way, so a held write can neither suppress nor shorten the notice.
  const f = fixture(t); f.repeat();
  const env = { inFlight: true };
  const annotate = router.makeAnnotator('vps', true, f.state, 'Mac', { botId: 'reader', writesInFlight: () => env.inFlight });
  const req = (name) => ({ method: 'tools/call', name: 'cua_alans_way_' + name,
    line: JSON.stringify({ method: 'tools/call', params: { name: 'cua_alans_way_' + name, arguments: {} } }) });
  const reply = JSON.parse(annotate(JSON.stringify({ jsonrpc: '2.0', id: 99,
    result: { content: [{ type: 'text', text: JSON.stringify(status) }] } }), 3, req('status')));
  f.full(reply);
});
test('annotators without connection-file or in-flight hooks stay full', t => {
  const f = fixture(t, {}); f.repeat(3);
});
test('error replies keep the full notice and never compact', t => {
  const f = fixture(t); f.repeat();
  const err = f.call('status', status, { isError: true });
  f.full(err); f.repeat();
});
