// The resume file remembers where the Mac was so failover can reopen it in the
// VM browser. It keeps origin and path only, never a query or fragment, is
// readable by its owner only, and never remembers an address that acts on load.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const router = require('../alans-way/scripts/workspace-router.cjs');
const routerPath = path.resolve(__dirname, '../alans-way/scripts/workspace-router.cjs');
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'router-resume-'));
const toolResult = (url) => ({ result: { content: [{ type: 'text', text: JSON.stringify({ effect: { url } }) }] } });

test('only origin and path are kept', () => {
  assert.equal(router.safeResumeUrl('https://shop.example/search?q=lamps&token=SECRET#frag'), 'https://shop.example/search');
  assert.equal(router.pageUrlFromMessage(toolResult('https://shop.example/p/1?reset=SECRET#x')), 'https://shop.example/p/1');
});

test('an address that acts on load is never remembered, query included', () => {
  for (const url of ['https://shop.example/checkout/complete', 'https://shop.example/orders/7/delete', 'https://shop.example/cart?step=confirm', 'https://shop.example/placeOrder?x=1']) {
    assert.equal(router.safeResumeUrl(url), null, url);
    assert.equal(router.pageUrlFromMessage(toolResult(url)), null, url);
  }
});

test('an old record with a query is read back without it', () => {
  const dir = tmp();
  const file = path.join(dir, 'resume-url.json');
  fs.writeFileSync(file, JSON.stringify({ url: 'https://shop.example/a?token=SECRET', at: Date.now() }));
  assert.equal(router.readResume(file), 'https://shop.example/a');
  fs.writeFileSync(file, JSON.stringify({ url: 'https://shop.example/a?step=confirm', at: Date.now() }));
  assert.equal(router.readResume(file), null);
});

test('the resume file is written with mode 0600, query-free, and so is the opened mark', () => {
  const dir = tmp();
  const file = path.join(dir, 'state', 'resume-url-bot.json');
  // writes are debounced and flushed at exit, so run the writer to completion in a child
  const run = spawnSync(process.execPath, ['-e', `require(${JSON.stringify(routerPath)}).writeResume(${JSON.stringify(file)}, ${JSON.stringify('https://shop.example/a?token=SECRET')});`], { encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  assert.doesNotMatch(fs.readFileSync(file, 'utf8'), /SECRET|\?/);
  const record = router.readResumeRecord(file);
  fs.chmodSync(file, 0o644);
  router.markResumeOpened(file, record, 'tab-1');
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).tabId, 'tab-1');
});

test('failover opens the origin and path only, and opens an action address not at all', async () => {
  const dir = tmp();
  const connectionFile = path.join(dir, 'connection.json');
  fs.writeFileSync(connectionFile, JSON.stringify({ url: 'http://127.0.0.1:9', token: 'AAFakeTokenForTests' }));
  const calls = [];
  const fetchImpl = async (url, opts = {}) => {
    calls.push({ method: opts.method || 'GET', body: opts.body || '' });
    return { ok: true, json: async () => ((opts.method || 'GET') === 'GET' ? { tabs: [] } : { id: 'tab-9' }) };
  };
  const now = Date.now();
  const opened = await router.continueRememberedPage({ connectionFile, record: { url: 'https://shop.example/a?token=SECRET#x', at: now, openedAt: 0, tabId: '' }, botId: 'bot', fetchImpl });
  assert.deepEqual(opened, { url: 'https://shop.example/a', tabId: 'tab-9', already: false });
  assert.equal(JSON.parse(calls.find((call) => call.method === 'POST').body).url, 'https://shop.example/a');
  calls.length = 0;
  for (const url of ['https://shop.example/orders/7/delete', 'https://shop.example/cart?step=confirm']) {
    assert.equal(await router.continueRememberedPage({ connectionFile, record: { url, at: now, openedAt: 0, tabId: '' }, botId: 'bot', fetchImpl }), null, url);
  }
  assert.deepEqual(calls, [], 'nothing is fetched or opened for an action address');
});
