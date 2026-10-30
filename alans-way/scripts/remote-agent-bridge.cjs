#!/usr/bin/env node
// remote-agent-bridge.cjs — opt-in HTTP MCP front for workspace-router.cjs.
//
// For a remote MCP client that cannot hold an SSH stdio session (see
// repo-level scripts/setup-remote-agent.sh for the SSH path). Each MCP session started by an
// `initialize` POST runs its own workspace-router.cjs child with this
// process's arguments and environment, so the router behaves exactly as it
// does under the SSH forced command. Replies come back as application/json;
// there is no SSE stream, so the client's elicitation, sampling and roots
// capabilities are withheld from the router.
//
// Off unless ALANS_WAY_REMOTE_BRIDGE=1. It listens on loopback by default and
// refuses any non-private address; put TLS (e.g. a tailnet proxy) in front.
//   ALANS_WAY_REMOTE_BRIDGE_TOKEN_FILE  bearer token file (mode 0600), or
//   ALANS_WAY_REMOTE_BRIDGE_TOKEN       the token itself; at least 32 chars
//   ALANS_WAY_REMOTE_BRIDGE_HOST        bind address (default 127.0.0.1)
//   ALANS_WAY_REMOTE_BRIDGE_PORT        port (default 8790)
// Usage: node remote-agent-bridge.cjs --bot-id ID [--bot-name NAME] [router flags]
const { spawn } = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');
const { StringDecoder } = require('node:string_decoder');

const ROUTER = path.join(__dirname, 'workspace-router.cjs');
const MAX_BODY = 1024 * 1024;
const MAX_SESSIONS = 4;
const IDLE_MS = 15 * 60 * 1000;
const REPLY_MS = 5 * 60 * 1000;
const SECRET_ENV = ['ALANS_WAY_REMOTE_BRIDGE_TOKEN', 'ALANS_WAY_REMOTE_BRIDGE_TOKEN_FILE'];

function fail(message) {
  process.stderr.write(`remote-agent-bridge: ${message}\n`);
  process.exit(2);
}

function readToken(env) {
  let token = env.ALANS_WAY_REMOTE_BRIDGE_TOKEN || '';
  const file = env.ALANS_WAY_REMOTE_BRIDGE_TOKEN_FILE;
  if (file) {
    let stat;
    try { stat = fs.statSync(file); } catch (e) { fail(`cannot read the token file (${e.code})`); }
    if (stat.mode & 0o077) fail('the token file must not be readable by group or others (chmod 600)');
    token = fs.readFileSync(file, 'utf8').trim();
  }
  if (token.length < 32) fail('set ALANS_WAY_REMOTE_BRIDGE_TOKEN_FILE (or _TOKEN) to a token of at least 32 characters');
  return crypto.createHash('sha256').update(token).digest();
}

// Loopback, RFC 1918, CGNAT (tailnet) and IPv6 unique-local addresses only.
function privateAddress(host) {
  if (net.isIPv4(host)) {
    const [a, b] = host.split('.').map(Number);
    return a === 127 || a === 10 || (a === 172 && b >= 16 && b < 32) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b < 128);
  }
  return net.isIPv6(host) && (host === '::1' || /^f[cd]/i.test(host));
}

function authorized(req, digest) {
  const header = req.headers.authorization || '';
  if (!header.startsWith('Bearer ')) return false;
  return crypto.timingSafeEqual(crypto.createHash('sha256').update(header.slice(7)).digest(), digest);
}

function send(res, status, body, headers = {}) {
  res.writeHead(status, body === undefined ? headers : { 'Content-Type': 'application/json', ...headers });
  res.end(body === undefined ? undefined : JSON.stringify(body));
}

const rpcError = (id, code, message) => ({ jsonrpc: '2.0', id: id ?? null, error: { code, message } });

function startSession(sessions, routerArgs, childEnv) {
  const id = crypto.randomUUID();
  const child = spawn(process.execPath, [ROUTER, ...routerArgs], { env: childEnv, stdio: ['pipe', 'pipe', 'inherit'] });
  const session = { id, child, pending: new Map(), timer: null };
  const write = msg => { if (child.stdin.writable) child.stdin.write(JSON.stringify(msg) + '\n'); };
  session.write = write;
  session.touch = () => {
    clearTimeout(session.timer);
    session.timer = setTimeout(() => session.close(), IDLE_MS);
  };
  session.close = () => {
    sessions.delete(id);
    clearTimeout(session.timer);
    child.stdin.end();
    setTimeout(() => { if (child.exitCode === null) child.kill('SIGTERM'); }, 2000).unref();
  };
  child.stdin.on('error', () => {});
  child.on('exit', () => {
    sessions.delete(id);
    clearTimeout(session.timer);
    for (const [key, res] of session.pending) send(res, 502, rpcError(JSON.parse(key), -32603, 'The workspace router exited.'));
    session.pending.clear();
  });
  const decoder = new StringDecoder('utf8');
  let buffer = '';
  child.stdout.on('data', chunk => {
    buffer += decoder.write(chunk);
    let end;
    while ((end = buffer.indexOf('\n')) !== -1) {
      const line = buffer.slice(0, end);
      buffer = buffer.slice(end + 1);
      let msg;
      try { msg = JSON.parse(line); } catch { continue; }
      // Nothing can carry a router-to-client request back, so answer it here.
      if (msg.method && msg.id !== undefined) { write(rpcError(msg.id, -32601, 'The HTTP bridge cannot forward requests to the client.')); continue; }
      const key = JSON.stringify(msg.id);
      const res = session.pending.get(key);
      if (msg.method || !res) continue;
      session.pending.delete(key);
      send(res, 200, msg, { 'Mcp-Session-Id': id });
    }
  });
  sessions.set(id, session);
  session.touch();
  return session;
}

function main() {
  const env = process.env;
  if (env.ALANS_WAY_REMOTE_BRIDGE !== '1') fail('disabled; set ALANS_WAY_REMOTE_BRIDGE=1 to start it');
  const digest = readToken(env);
  const host = env.ALANS_WAY_REMOTE_BRIDGE_HOST || '127.0.0.1';
  if (!privateAddress(host)) fail(`refusing to listen on ${host}: use loopback or a private interface address`);
  const port = Number(env.ALANS_WAY_REMOTE_BRIDGE_PORT || 8790);
  const childEnv = { ...env };
  for (const name of SECRET_ENV) delete childEnv[name];
  const routerArgs = process.argv.slice(2);
  const sessions = new Map();

  const server = http.createServer((req, res) => {
    if (req.url.split('?')[0] !== '/mcp') return send(res, 404, rpcError(null, -32600, 'Not found'));
    if (!authorized(req, digest)) return send(res, 401, rpcError(null, -32600, 'Unauthorized'), { 'WWW-Authenticate': 'Bearer' });
    const sessionId = req.headers['mcp-session-id'];
    if (req.method === 'DELETE') {
      const session = sessions.get(sessionId);
      if (!session) return send(res, 404, rpcError(null, -32600, 'Unknown session'));
      session.close();
      return send(res, 204);
    }
    if (req.method !== 'POST') return send(res, 405, rpcError(null, -32600, 'Use POST'), { Allow: 'POST, DELETE' });
    if (Number(req.headers['content-length']) > MAX_BODY) {
      res.setHeader('Connection', 'close');
      return send(res, 413, rpcError(null, -32600, 'Request too large'));
    }
    const chunks = [];
    let size = 0;
    req.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_BODY) {
        res.setHeader('Connection', 'close');
        send(res, 413, rpcError(null, -32600, 'Request too large'));
        req.destroy();
      } else chunks.push(chunk);
    });
    req.on('end', () => {
      if (res.headersSent) return;
      let msg;
      try { msg = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch { return send(res, 400, rpcError(null, -32700, 'Parse error')); }
      if (!msg || typeof msg !== 'object' || Array.isArray(msg) || msg.jsonrpc !== '2.0') return send(res, 400, rpcError(null, -32600, 'Send one JSON-RPC 2.0 message'));
      let session;
      if (msg.method === 'initialize' && msg.id !== undefined) {
        if (sessions.size >= MAX_SESSIONS) return send(res, 503, rpcError(msg.id, -32000, 'Too many sessions'));
        const capabilities = { ...msg.params?.capabilities };
        delete capabilities.elicitation;
        delete capabilities.sampling;
        delete capabilities.roots;
        msg = { ...msg, params: { ...msg.params, capabilities } };
        session = startSession(sessions, routerArgs, childEnv);
      } else {
        if (!sessionId) return send(res, 400, rpcError(msg.id, -32600, 'Missing Mcp-Session-Id'));
        session = sessions.get(sessionId);
        if (!session) return send(res, 404, rpcError(msg.id, -32600, 'Unknown session'));
      }
      session.touch();
      if (msg.id === undefined || msg.id === null || !msg.method) {
        session.write(msg);
        return send(res, 202);
      }
      const key = JSON.stringify(msg.id);
      if (session.pending.has(key)) return send(res, 409, rpcError(msg.id, -32600, 'Request id already pending'));
      session.pending.set(key, res);
      const timer = setTimeout(() => {
        if (session.pending.get(key) !== res) return;
        session.pending.delete(key);
        send(res, 504, rpcError(msg.id, -32603, 'The workspace router did not reply in time.'));
      }, REPLY_MS);
      res.on('close', () => {
        clearTimeout(timer);
        if (session.pending.get(key) === res) session.pending.delete(key);
      });
      session.write(msg);
    });
  });
  server.requestTimeout = REPLY_MS + 10000;
  server.listen(port, host, () => {
    const { address, port: bound } = server.address();
    process.stderr.write(`remote-agent-bridge: listening on http://${net.isIPv6(address) ? `[${address}]` : address}:${bound}/mcp\n`);
  });
  server.on('error', e => fail(`cannot listen: ${e.message}`));
  const stop = () => {
    server.close();
    server.closeAllConnections();
    for (const session of [...sessions.values()]) session.close();
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
}

main();
