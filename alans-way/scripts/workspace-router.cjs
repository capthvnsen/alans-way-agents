#!/usr/bin/env node
// workspace-router.cjs — failover launcher for the workspace browser MCP server.
//
// Routes the `workspace_browser` MCP server to the Mac browser host when the
// Mac is reachable, and transparently falls back to the VPS browser host when
// the Mac is offline/asleep. Exposes the same stdio MCP surface either way, so
// the Hermes side never knows which host answered.
//
// Why a launcher (not a proxy): both hosts serve identical tools through the
// same `browser-mcp.cjs` script. Deciding the backend at connection time and
// forwarding stdio transparently is the smallest correct mechanism. Hermes
// re-spawns a lazy MCP server when its child exits, so if the Mac dies
// mid-session the ssh child exits and the next connection re-runs this probe
// and routes to the VPS.
//
// Configuration (all optional unless noted):
//   --bot-id ID                required: this bot's tab-owner identity
//   --bot-name NAME            optional display name for the agent cursor
//   --mac-ssh USER@HOST        ssh alias/host for the user's computer
//   --host-os mac|windows      OS of the user's computer (default: mac)
//   --mac-node PATH            node binary on the user's computer
//                              (default: the app's own runtime; mac only)
//   --mac-script PATH          browser-mcp.cjs path on the user's computer
//                              (default: the installed app's bundled copy; mac only)
//   --vps-script PATH          browser-mcp.cjs path on this host
//                              (default: sibling copy, then the deployed copy)
//   --vps-connection PATH      local browser host connection.json
//   --mac-state-file PATH      mac-watch state file
//                              (default: /var/lib/hermes-alans-way/mac-state.json,
//                               ~/Library/Application Support/... on a macOS guest)
//   --probe                    run the host probe once, print the decision,
//                              and exit — read-only, for install/verify checks
// Environment fallbacks: HERMES_WORKSPACE_BOT_ID, HERMES_BOT_NAME,
//   HERMES_WORKSPACE_MAC_SSH, HERMES_WORKSPACE_HOST_OS,
//   HERMES_WORKSPACE_MAC_NODE, HERMES_WORKSPACE_MAC_MCP,
//   HERMES_WORKSPACE_VPS_MCP, HERMES_WORKSPACE_CONNECTION,
//   HERMES_MAC_STATE_FILE.
// With no Mac ssh configured the router always serves the local VPS host.
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const readline = require('node:readline');

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const botId = arg('--bot-id') || process.env.HERMES_WORKSPACE_BOT_ID || '';
const botName = arg('--bot-name') || process.env.HERMES_BOT_NAME || '';
const macSsh = arg('--mac-ssh') || process.env.HERMES_WORKSPACE_MAC_SSH || '';
const macNode = arg('--mac-node') || process.env.HERMES_WORKSPACE_MAC_NODE || '';
// The user's machine runs either macOS or Windows; everything else would
// silently probe POSIX shell on a Windows sshd and never converge.
const hostOs = (arg('--host-os') || process.env.HERMES_WORKSPACE_HOST_OS || 'mac') === 'windows' ? 'windows' : 'mac';
const hostName = hostOs === 'windows' ? 'Windows host' : 'Mac';
const configuredMacScript = arg('--mac-script') || process.env.HERMES_WORKSPACE_MAC_MCP;
const macScripts = configuredMacScript
  ? [configuredMacScript]
  : hostOs === 'windows'
    ? []
    : [
        '/Applications/alans-way-localapp.app/Contents/Resources/app/scripts/browser-mcp.cjs',
        '/Applications/Open Alan.app/Contents/Resources/app/scripts/browser-mcp.cjs',
        "/Applications/Hermes- Alan's way.app/Contents/Resources/app/scripts/browser-mcp.cjs",
        '/Applications/Hermes Workspace.app/Contents/Resources/app/scripts/browser-mcp.cjs',
      ];
const connectorSuffix = hostOs === 'windows'
  ? 'connector\\scripts\\browser-mcp.cjs'
  : 'Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs';
const siblingScript = path.join(__dirname, 'browser-mcp.cjs');
// setup.sh installs the app copy under /opt when root and under
// ~/.local/share otherwise — probe both well-known locations.
const vpsScriptCandidates = [
  siblingScript,
  '/opt/hermes-alans-way/browser/desktop/scripts/browser-mcp.cjs',
  path.join(os.homedir(), '.local', 'share', 'hermes-alans-way', 'app', 'desktop', 'scripts', 'browser-mcp.cjs'),
];
const vpsScript =
  arg('--vps-script') ||
  process.env.HERMES_WORKSPACE_VPS_MCP ||
  vpsScriptCandidates.find(p => fs.existsSync(p)) ||
  '/opt/hermes-alans-way/browser/desktop/scripts/browser-mcp.cjs';
const vpsConnection =
  arg('--vps-connection') ||
  process.env.HERMES_WORKSPACE_CONNECTION ||
  (process.platform === 'darwin'
    ? path.join(os.homedir(), 'Library', 'Application Support', 'hermes-alans-way', 'browser', 'connection.json')
    : path.join(os.homedir(), '.local', 'share', 'hermes-alans-way', 'browser', 'connection.json'));
const macStateFile =
  arg('--mac-state-file') ||
  process.env.HERMES_MAC_STATE_FILE ||
  (process.platform === 'darwin'
    ? path.join(os.homedir(), 'Library', 'Application Support', 'hermes-alans-way', 'mac-state.json')
    : '/var/lib/hermes-alans-way/mac-state.json');

// Reuse one ssh connection between the probe and the backend spawn: the
// probe's handshake becomes the spawn's (~5ms vs a full handshake), and
// later respawns ride it for ControlPersist seconds. %C hashes the
// destination, so the socket name needs no host-derived parts.
const sshControlPath = path.join(process.env.TMPDIR || '/tmp', 'wsr-%C');
const sshControlArgs = [
  '-o',
  'ControlMaster=auto',
  '-o',
  'ControlPersist=120',
  '-o',
  `ControlPath=${sshControlPath}`,
];

// Quote a value for the remote command line ssh builds from argv.
const shQuote = (value) => `'${String(value).replace(/'/g, "'\\''")}'`;
// Same for a remote PowerShell: single-quoted literal, '' escapes '.
const psQuote = (value) => `'${String(value).replace(/'/g, "''")}'`;

const SELF_PROBE_INTERVAL_MS = 600000;
const RECONVERGE_IDLE_MS = 60000;

function stderrTail(text, maxLen = 200) {
  const s = String(text || '').trim();
  if (!s) return '';
  const tail = s.split(/\r?\n/).filter(Boolean).slice(-3).join('; ');
  return tail.length > maxLen ? tail.slice(-maxLen) : tail;
}

function readSelfProbeAt(file) {
  try {
    const n = Number(fs.readFileSync(file, 'utf8').trim());
    return Number.isFinite(n) ? n : 0;
  } catch {
    return 0;
  }
}

function writeSelfProbeAt(file) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, String(Date.now()));
  } catch {}
}

function selfProbeStampFile(stateFile) {
  return path.join(path.dirname(stateFile), 'router-last-self-probe');
}

function noteClientRpc(line, pending) {
  try {
    const msg = JSON.parse(line);
    if (msg && typeof msg === 'object' && msg.id != null && typeof msg.method === 'string') {
      pending.add(msg.id);
    }
  } catch {}
}

function noteServerRpc(line, pending) {
  try {
    const msg = JSON.parse(line);
    if (msg && typeof msg === 'object' && msg.id != null
        && (msg.result !== undefined || msg.error !== undefined)) {
      pending.delete(msg.id);
    }
  } catch {}
}

function mayReconverge({ mac, onlineStreak, lastActivity, pendingSize, idleMs, now }) {
  return Boolean(
    mac && mac.state === 'online' && onlineStreak >= 2 && pendingSize === 0
      && now - lastActivity > idleMs,
  );
}

// Non-interactive ssh never loads Homebrew's PATH, so a bare `node` is
// usually missing on the Mac. The app bundle already ships a Node runtime:
// its own Electron binary with ELECTRON_RUN_AS_NODE. PATH node is only the
// fallback for bundles without one; an explicit --mac-node always wins.
function macBackendCommand(script, node, id, name) {
  const tail = [shQuote(script), '--bot-id', shQuote(id)];
  if (name) tail.push('--bot-name', shQuote(name));
  const args = tail.join(' ');
  if (node) return `${shQuote(node)} ${args}`;
  const bundle = /^(.*\/([^/]+)\.app)\/Contents\/Resources\//.exec(script);
  if (bundle) {
    const exe = shQuote(`${bundle[1]}/Contents/MacOS/${bundle[2]}`);
    return `if [ -x ${exe} ]; then ELECTRON_RUN_AS_NODE=1 exec ${exe} ${args}; else exec node ${args}; fi`;
  }
  // A connector copied into the home directory is newer than the app bundle.
  // Run it with the app's own Node and modules so a rebuild is not required.
  const apps = [
    '/Applications/alans-way-localapp.app',
    '/Applications/Open Alan.app',
    "/Applications/Hermes- Alan's way.app",
    '/Applications/Hermes Workspace.app',
  ];
  const checks = apps.map((app) => {
    const exe = `${app}/Contents/MacOS/${path.basename(app, '.app')}`;
    const modules = `${app}/Contents/Resources/app/node_modules`;
    return `if [ -x ${shQuote(exe)} ]; then NODE_PATH=${shQuote(modules)} ELECTRON_RUN_AS_NODE=1 exec ${shQuote(exe)} ${args}; fi;`;
  }).join(' ');
  // A non-login ssh spawn has no shell profile PATH: prefer the common
  // user-local install before hoping bare `node` resolves.
  return `${checks} if [ -x "$HOME/.local/bin/node" ]; then exec "$HOME/.local/bin/node" ${args}; fi; exec node ${args}`;
}

// Windows backend: same idea over PowerShell — run the connector with the
// app's own Electron-as-Node runtime, falling back to the installer's private
// Node then PATH. The spawned process sits in Session 0, which is fine here:
// it only talks HTTP to the app's loopback API; desktop actions are served by
// the app itself. NODE_PATH supplies the pushed connector's dependencies.
function windowsBackendCommand(script, id, name) {
  const tail = [psQuote(script), '--bot-id', psQuote(id)];
  if (name) tail.push('--bot-name', psQuote(name));
  const args = tail.join(' ');
  const exe = '"$env:LOCALAPPDATA\\Programs\\alans-way-localapp\\alans-way-localapp.exe"';
  const modules = '"$env:LOCALAPPDATA\\Programs\\alans-way-localapp\\resources\\app\\node_modules"';
  const node = '"$env:USERPROFILE\\.alans-way\\node\\node.exe"';
  return `$env:NODE_PATH = ${modules}; if (Test-Path ${exe}) { $env:ELECTRON_RUN_AS_NODE = '1'; & ${exe} ${args} } elseif (Test-Path ${node}) { & ${node} ${args} } else { & node ${args} }`;
}

// Probe finds the newest installed bundle AND proves the app is actually
// serving — a closed app still has the script on disk, so file-existence
// alone would route to a dead host. The API answers 401 without auth, which
// still proves liveness; a refused connection means the app is not running.
// Same probe over PowerShell: connection.json proves the app is serving
// (any HTTP response, even 401, means the API is up), then emit the newest
// connector script path — the pushed home copy wins over the install.
function windowsProbeCommand() {
  return [
    // Invoke-WebRequest's progress stream can reach stdout over ssh and would
    // break the single-path output contract below.
    '$ProgressPreference = "SilentlyContinue"',
    '$conn = "$env:APPDATA\\Hermes Workspace\\connection.json"',
    'if (-not (Test-Path $conn)) { exit 1 }',
    '$port = 9464',
    'try { $port = ([uri](Get-Content $conn -Raw | ConvertFrom-Json).url).Port } catch {}',
    '$alive = $false',
    `try { $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 -Uri "http://127.0.0.1:$port/v1/status"; $alive = $true }`,
    'catch { $alive = ($null -ne $_.Exception.Response) }',
    'if (-not $alive) { exit 1 }',
    'foreach ($s in @(' +
      '"$env:APPDATA\\Hermes Workspace\\connector\\scripts\\browser-mcp.cjs",' +
      '"$env:LOCALAPPDATA\\Programs\\alans-way-localapp\\resources\\app\\scripts\\browser-mcp.cjs")) ' +
      '{ if (Test-Path $s) { Write-Output $s; exit 0 } }',
    'exit 1',
  ].join('; ');
}

function probeMac(timeoutMs, connectTimeout = 6) {
  return new Promise((resolve) => {
    const alive =
      `{ conn="$HOME/Library/Application Support/Hermes Workspace/connection.json"; ` +
      `[ -f "$conn" ] && ` +
      `port=$(sed -n 's/.*"url"[^0-9]*[0-9.]*:\\([0-9]*\\).*/\\1/p' "$conn" | head -1) && ` +
      `curl -s -m 4 -o /dev/null "http://127.0.0.1:\${port:-9464}/status"; }`;
    const probe = hostOs === 'windows' ? windowsProbeCommand()
      : `conn_script="$HOME/${connectorSuffix}"; if [ -f "$conn_script" ] && ${alive}; then printf %s "$conn_script"; exit 0; fi; ` + macScripts
        .map(script => `if [ -f ${shQuote(script)} ] && ${alive}; then printf %s ${shQuote(script)}; exit 0; fi`)
        .join('; ') + '; exit 1';
    const child = spawn(
      'ssh',
      [
        '-T',
        '-o',
        'BatchMode=yes',
        '-o',
        `ConnectTimeout=${connectTimeout}`,
        '-o',
        'StrictHostKeyChecking=yes',
        ...sshControlArgs,
        macSsh,
        probe,
      ],
      { stdio: ['ignore', 'pipe', 'pipe'] },
    );
    let output = '';
    let errOutput = '';
    child.stdout.on('data', chunk => { if (output.length < 4096) output += chunk; });
    child.stderr.on('data', chunk => { if (errOutput.length < 4096) errOutput += chunk; });
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      resolve({ script: null, stderr: errOutput });
    }, timeoutMs);
    child.on('error', () => {
      clearTimeout(timer);
      resolve({ script: null, stderr: errOutput });
    });
    child.on('exit', (code) => {
      clearTimeout(timer);
      const found = output.trim();
      const valid = hostOs === 'windows'
        ? /^[A-Za-z]:[\\/].*browser-mcp\.cjs$/i.test(found)
        : macScripts.includes(found) || found.endsWith(connectorSuffix);
      const script = code === 0 && valid ? found : null;
      resolve({ script, stderr: errOutput });
    });
  });
}

// Read the mac-watch state file. A missing or malformed file means
// "unknown": the router still decides on its own probe and reports mac: null.
function readMacState(file) {
  try {
    const doc = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (!doc || (doc.state !== 'online' && doc.state !== 'offline')) return null;
    const text = (key) => (typeof doc[key] === 'string' ? doc[key].slice(0, 64) : null);
    return { state: doc.state, since: text('since'), lastSeenOnline: text('lastSeenOnline') };
  } catch {
    return null;
  }
}

// A state-file verdict only counts while mac-watch is alive to refresh it:
// the watcher rewrites the file every interval (~30s), so an mtime older
// than ~45s is a dead watcher's last word, not a current state.
function freshMacState(file, maxAgeMs = 45000) {
  try {
    if (Date.now() - fs.statSync(file).mtimeMs > maxAgeMs) return null;
  } catch {
    return null;
  }
  return readMacState(file);
}

// Human-readable line appended to tool results — the channel the agent sees.
// Only meaningful when this connection fell back to the VPS host.
const RESUME_MAX_AGE_MS = 6 * 60 * 60 * 1000;

function resumePath(stateFile) {
  return path.join(path.dirname(stateFile), 'resume-url.json');
}

function pageUrlFromMessage(msg) {
  const parts = msg && msg.result && msg.result.content;
  if (!Array.isArray(parts)) return null;
  for (const part of parts) {
    if (!part || part.type !== 'text' || typeof part.text !== 'string') continue;
    // A tab list names every open page. Remembering the first one would
    // replace the page the agent was actually working on.
    if (/"tabs"\s*:/.test(part.text)) continue;
    const match = part.text.match(/"url"\s*:\s*"(https:\/\/[^"\\]{8,500})"/);
    if (!match) continue;
    try {
      const url = new URL(match[1]);
      if (url.username || url.password || url.protocol !== 'https:') continue;
      url.hash = '';
      if (url.href.length > 500) continue;
      return url.href;
    } catch { /* a bad url is not a page to resume */ }
  }
  return null;
}

function writeResume(file, url) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ url, at: Date.now() }));
    fs.renameSync(tmp, file);
  } catch { /* remembering a page must not break the tool result */ }
}

function safeResumeUrl(value) {
  try {
    const url = new URL(value);
    if (url.username || url.password || url.protocol !== 'https:') return null;
    url.hash = '';
    if (url.href.length > 500) return null;
    return url.href;
  } catch { return null; }
}

function readResumeRecord(file, now = Date.now()) {
  try {
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    const url = data && safeResumeUrl(data.url);
    if (!url || typeof data.at !== 'number') return null;
    if (now - data.at > RESUME_MAX_AGE_MS) return null;
    const openedAt = typeof data.openedAt === 'number' ? data.openedAt : 0;
    const tabId = typeof data.tabId === 'string' && /^[\w-]{1,100}$/.test(data.tabId) ? data.tabId : '';
    return { url, at: data.at, openedAt, tabId };
  } catch { return null; }
}

function readResume(file, now = Date.now()) {
  const record = readResumeRecord(file, now);
  return record ? record.url : null;
}

// One open per Mac observation. A later Mac snapshot rewrites `at` and this
// opens again; a router respawn while the laptop stays closed does not.
function markResumeOpened(file, record, tabId, now = Date.now()) {
  const url = safeResumeUrl(record && record.url);
  if (!url || typeof record.at !== 'number' || !/^[\w-]{1,100}$/.test(String(tabId || ''))) return;
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ url, at: record.at, openedAt: now, tabId }));
    fs.renameSync(tmp, file);
  } catch { /* the next spawn can open the page again */ }
}

function continuedPage(record) {
  if (!record || !(record.openedAt >= record.at) || !record.tabId) return null;
  return { url: record.url, tabId: record.tabId };
}

// The VPS browser process cannot see the resume file. Pass the tab it should
// keep using, so a call aimed at the old Mac tab can name this one.
function continuedArgs(continued) {
  const url = continued && safeResumeUrl(continued.url);
  const tabId = continued && continued.tabId;
  if (!url || typeof tabId !== 'string' || !/^[\w-]{1,100}$/.test(tabId)) return [];
  return ['--continued-tab', tabId, '--continued-url', url];
}

// Open the last Mac https page in the local VPS browser. Cookies do not copy.
// A tab that already has the URL is reused. A missing browser host returns
// null so the notice can still tell the model to open the page itself.
async function continueRememberedPage({ connectionFile, record, botId, botName, fetchImpl, now = Date.now() }) {
  const safe = record && safeResumeUrl(record.url);
  if (!safe || typeof record.at !== 'number' || now - record.at > RESUME_MAX_AGE_MS) return null;
  if (record.openedAt >= record.at && record.tabId) return { url: safe, tabId: record.tabId, already: true };
  let connection;
  try { connection = JSON.parse(fs.readFileSync(connectionFile, 'utf8')); } catch { return null; }
  let base;
  try { base = new URL(connection.url); } catch { return null; }
  if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1' || !connection.token || !botId) return null;
  const fetch = fetchImpl || globalThis.fetch;
  const headers = {
    Authorization: `Bearer ${connection.token}`,
    'X-Hermes-Bot': botId,
    ...(botName ? { 'X-Hermes-Bot-Name': encodeURIComponent(String(botName).slice(0, 80)) } : {}),
  };
  try {
    const listed = await fetch(new URL('/v1/tabs', base), { headers, signal: AbortSignal.timeout(4000) });
    if (!listed.ok) return null;
    const body = await listed.json();
    const tabs = body && Array.isArray(body.tabs) ? body.tabs : [];
    const existing = tabs.find((tab) => tab && safeResumeUrl(tab.url) === safe && typeof tab.id === 'string' && /^[\w-]{1,100}$/.test(tab.id));
    if (existing) return { url: safe, tabId: existing.id, already: true };
    const opened = await fetch(new URL('/v1/tabs', base), {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: safe, background: true, settle: false }),
      signal: AbortSignal.timeout(12000),
    });
    if (!opened.ok) return null;
    const tab = await opened.json();
    if (!tab || typeof tab.id !== 'string' || !/^[\w-]{1,100}$/.test(tab.id)) return null;
    return { url: safe, tabId: tab.id, already: false };
  } catch { return null; }
}

function workspaceNotice(host, mac, resumeUrl, continued, label = 'Mac') {
  if (!mac || host !== 'vps') return null;
  if (mac.state === 'online') {
    return (
      `[workspace] ${label} is back online as of ${mac.since || 'unknown'} — ` +
      `tasks waiting on ${label}-local resources can resume. New web work goes to the in-app host browser.`
    );
  }
  const page = continued && continued.url && continued.tabId
    ? ` Continued ${continued.url} in the VPS browser as tab ${continued.tabId}. Keep working in that tab. A login does not copy; if the page asks you to sign in, say so and stop only that page.`
    : resumeUrl ? ` Reopen ${resumeUrl} and continue.` : ' Reopen the same URL and continue.';
  return (
    `[workspace] ${label} unreachable since ${mac.since || 'unknown'} — ` +
    `routed to VPS browser.${page} API, MCP, and connector calls that do not run on the ${label} keep going. ${label}-local files are unavailable.`
  );
}

// Additive decoration of one outbound JSON-RPC message: structured host state
// under result._meta.workspace plus, for tool results, the notice as an extra
// text content item. Anything not a result object passes through untouched.
function annotateResult(msg, host, mac, notice) {
  if (!msg || typeof msg !== 'object' || !msg.result || typeof msg.result !== 'object') return msg;
  msg.result._meta = { ...(msg.result._meta || {}), workspace: { host, mac } };
  if (notice && Array.isArray(msg.result.content)) {
    msg.result.content = [...msg.result.content, { type: 'text', text: notice }];
  }
  return msg;
}

// Per-connection line annotator for the backend's stdout. The state file is
// re-read per message so a mid-session flip is seen; the "back online" notice
// fires once per online transition while the offline one rides every tool
// result, since either may be the agent's only signal that host changed.
function makeAnnotator(host, macConfigured, stateFile, label = 'Mac') {
  let onlineAnnounced = false;
  const remembered = resumePath(stateFile);
  return function annotateLine(line) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      process.stderr.write(`${line}\n`);
      return null;
    }
    if (!msg || typeof msg !== 'object' || !msg.result || typeof msg.result !== 'object') return line;
    if (host === 'mac') {
      const seen = pageUrlFromMessage(msg);
      if (seen) writeResume(remembered, seen);
    }
    const mac = macConfigured ? readMacState(stateFile) : null;
    const record = host === 'vps' ? readResumeRecord(remembered) : null;
    const resume = record ? record.url : null;
    const continued = continuedPage(record);
    let notice = null;
    if (mac && Array.isArray(msg.result.content)) {
      if (mac.state === 'online') {
        if (!onlineAnnounced) notice = workspaceNotice(host, mac, resume, continued, label);
        onlineAnnounced = true;
      } else {
        onlineAnnounced = false;
        notice = workspaceNotice(host, mac, resume, continued, label);
      }
    }
    return JSON.stringify(annotateResult(msg, host, mac, notice));
  };
}

async function main() {
  if (process.argv.includes('--probe')) {
    const probe = macSsh ? await probeMac(12000) : { script: null, stderr: '' };
    const tail = stderrTail(probe.stderr);
    if (probe.script) {
      process.stdout.write(`${hostOs}: ${probe.script}\n`);
      return;
    }
    const detail = tail ? ` (${tail})` : '';
    process.stdout.write(
      `vps${macSsh ? ` (${hostOs} unreachable${detail})` : ' (no mac-ssh)'}\n`,
    );
    return;
  }

  if (!botId) {
    process.stderr.write(
      'workspace-router: --bot-id (or HERMES_WORKSPACE_BOT_ID) is required.\n',
    );
    process.exit(1);
  }
  // A fresh mac-watch "offline" verdict skips the probe entirely: the
  // watcher already paid the ssh timeout, so paying it again on every lazy
  // respawn just adds seconds while the Mac is down. A fresh "online" still
  // probes — the liveness check stays the authority — but on a shorter
  // connect timeout since the file may have just gone stale-positive. A
  // missing or stale file probes as before.
  const macSeen = macSsh ? freshMacState(macStateFile) : null;
  const probeStampFile = selfProbeStampFile(macStateFile);
  const staleSelfProbe = Date.now() - readSelfProbeAt(probeStampFile) > SELF_PROBE_INTERVAL_MS;
  const shouldProbe = !macSeen || macSeen.state === 'online' || staleSelfProbe;
  const probeResult = macSsh && shouldProbe
    ? await probeMac(8000, macSeen && macSeen.state === 'online' ? 4 : 6)
    : { script: null, stderr: '' };
  const macScript = probeResult.script;
  if (macSsh && shouldProbe) writeSelfProbeAt(probeStampFile);
  const probeErrTail = stderrTail(probeResult.stderr);

  const pendingRequests = new Set();

  // Annotation is decoration — a failure here must never take down the
  // transport (that is how a one-line ReferenceError dropped the whole
  // browser surface). Degrade to passthrough instead.
  const safeAnnotator = (host) => {
    try {
      return makeAnnotator(host, Boolean(macSsh), macStateFile, hostName);
    } catch (e) {
      process.stderr.write(`workspace-router: annotator disabled: ${e.message}\n`);
      return (line) => line;
    }
  };
  let annotate = safeAnnotator(macScript ? 'mac' : 'vps');

  // A backend that dies before answering anything is dead on arrival — for a
  // Mac spawn that means the remote script crashed (missing module, killed
  // app), and exiting here would leave the MCP client hanging on a dead
  // child until its own connect timeout. Falling back to the VPS host in
  // that window costs ~a second instead. Client lines written to the dead
  // child are buffered and replayed; nothing it could have acted on ever
  // produced a response, so no request executes twice. A backend that proved
  // itself with a first response still exits the router on death — Hermes
  // respawns it.
  let activeChild = null;
  let activeHost = null;
  let provedAlive = false;
  let fellBack = false;
  let watchdog = null;
  const bufferedStdin = [];
  const superseded = new Set();

  // A wedged remote that never exits is the worst boot stall: without this,
  // the client waits out its full connect_timeout on dead air. Once the
  // client is actually talking to us, a silent Mac backend gets MAC_WATCHDOG_MS
  // to answer before we route around it. Healthy cold starts answer in ~2s;
  // the client sends initialize immediately after spawn.
  const MAC_WATCHDOG_MS = Number(process.env.HERMES_ROUTER_MAC_WATCHDOG_MS) || 8000;
  function armWatchdog() {
    if (watchdog || provedAlive || fellBack || activeHost !== 'mac') return;
    watchdog = setTimeout(() => {
      watchdog = null;
      if (provedAlive || fellBack || activeHost !== 'mac' || !activeChild) return;
      const stuck = activeChild;
      superseded.add(stuck);
      fellBack = true;
      process.stderr.write(
        `workspace-router: ${hostName} backend silent ${MAC_WATCHDOG_MS}ms after initialize — routing to VPS browser host\n`,
      );
      void startVpsBackend();
      try { stuck.kill('SIGKILL'); } catch { /* already gone */ }
    }, MAC_WATCHDOG_MS);
    watchdog.unref();
  }

  async function startVpsBackend() {
    const vpsArgs = [vpsScript, '--bot-id', botId];
    if (botName) vpsArgs.push('--bot-name', botName);
    vpsArgs.push('--connection', vpsConnection);
    if (macSsh) {
      const resumeFile = resumePath(macStateFile);
      const record = readResumeRecord(resumeFile);
      let continuedTab = continuedPage(record);
      if (record && !continuedTab) {
        const continued = await continueRememberedPage({
          connectionFile: vpsConnection,
          record,
          botId,
          botName,
        });
        if (continued) {
          markResumeOpened(resumeFile, record, continued.tabId);
          continuedTab = { url: continued.url, tabId: continued.tabId };
          process.stderr.write(
            `workspace-router: continued ${continued.url} in the VPS browser as tab ${continued.tabId}\n`,
          );
        }
      }
      vpsArgs.push(...continuedArgs(continuedTab));
    }
    const c = spawn(process.execPath, vpsArgs, { stdio: ['pipe', 'pipe', 'inherit'] });
    bindChild(c, 'vps');
    for (const line of bufferedStdin) c.stdin.write(`${line}\n`);
  }

  function bindChild(c, host) {
    activeChild = c;
    activeHost = host;
    // A write after the Mac ssh has already exited emits EPIPE asynchronously.
    // That must not kill the process that is about to answer from the VPS.
    c.stdin.on('error', () => {});
    annotate = safeAnnotator(host);
    readline
      .createInterface({ input: c.stdout, crlfDelay: Infinity })
      .on('line', (line) => {
        touchActivity();
        noteServerRpc(line, pendingRequests);
        provedAlive = true;
        if (watchdog) { clearTimeout(watchdog); watchdog = null; }
        bufferedStdin.length = 0;
        let out;
        try {
          out = annotate(line);
        } catch {
          out = line;
        }
        if (out === null) return;
        process.stdout.write(`${out}\n`);
      });
    c.on('error', (e) => {
      if (superseded.has(c)) return;
      process.stderr.write(`workspace-router: failed to spawn backend: ${e.message}\n`);
      if (host === 'mac' && !provedAlive) {
        if (!fellBack) {
          fellBack = true;
          void startVpsBackend();
        }
        return;
      }
      process.exit(1);
    });
    c.on('exit', (code, sig) => {
      if (superseded.has(c)) return;
      if (c !== activeChild) return;
      // A Mac process that never answered must not take the router down.
      // Spawn can emit error and exit for the same death; the second one
      // only records the fallback that the first one already started.
      if (host === 'mac' && !provedAlive) {
        if (!fellBack) {
          fellBack = true;
          process.stderr.write(
            `workspace-router: ${hostName} backend died before its first response — routing to VPS browser host\n`,
          );
          void startVpsBackend();
        }
        return;
      }
      process.exit(code === null ? (sig ? 1 : 0) : code);
    });
  }

  let lastActivity = Date.now();
  const touchActivity = () => { lastActivity = Date.now(); };

  readline
    .createInterface({ input: process.stdin, crlfDelay: Infinity })
    .on('line', (line) => {
      touchActivity();
      noteClientRpc(line, pendingRequests);
      if (!provedAlive) bufferedStdin.push(line);
      try {
        if (activeChild && activeChild.exitCode === null && activeChild.stdin.writable) activeChild.stdin.write(`${line}\n`);
      } catch { /* a dying child's pipe is not the router's problem — the fallback replays */ }
      armWatchdog();
    });

  if (macScript) {
    // Run browser-mcp.cjs on the user's machine over the same ssh session the probe used.
    const sshArgs = [
      '-T',
      '-o',
      'BatchMode=yes',
      '-o',
      'StrictHostKeyChecking=yes',
      ...sshControlArgs,
      macSsh,
      hostOs === 'windows'
        ? windowsBackendCommand(macScript, botId, botName)
        : macBackendCommand(macScript, macNode, botId, botName),
    ];
    process.stderr.write(`workspace-router: routing to ${hostName} browser host\n`);
    bindChild(spawn('ssh', sshArgs, { stdio: ['pipe', 'pipe', 'inherit'] }), 'mac');
  } else {
    let reason = macSeen && macSeen.state === 'offline' ? 'offline per mac-watch' : 'unreachable';
    if (probeErrTail) reason += ` (${probeErrTail})`;
    process.stderr.write(
      macSsh
        ? `workspace-router: ${hostName} ${reason} — routing to VPS browser host\n`
        : 'workspace-router: no host ssh configured — routing to VPS browser host\n',
    );
    if (staleSelfProbe && macSeen && macSeen.state === 'offline') {
      process.stderr.write(
        'workspace-router: self-probe despite fresh offline verdict — watcher may be misconfigured\n',
      );
    }
    await startVpsBackend();
  }
  let routerMtime = 0;
  try { routerMtime = fs.statSync(__filename).mtimeMs; } catch { /* a missing script has nothing newer to load */ }
  const reloadTimer = setInterval(() => {
    if (pendingRequests.size > 0 || Date.now() - lastActivity < 1000) return;
    let mtime = routerMtime;
    try { mtime = fs.statSync(__filename).mtimeMs; } catch { return; }
    if (mtime <= routerMtime) return;
    process.stderr.write('workspace-router: script replaced — exiting so the next connection loads it\n');
    try { if (activeChild) activeChild.kill('SIGTERM'); } catch { /* the exit below is what Hermes respawns from */ }
    process.exit(0);
  }, 5000);
  reloadTimer.unref();
  for (const s of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(s, () => {
      try {
        if (activeChild) activeChild.kill(s);
      } catch {}
    });
  }

  // Self-correct host drift. A connection that landed on the VPS during a
  // transient probe miss would otherwise pin the session to the wrong host
  // until someone killed the process by hand. Hermes lazy-respawns a dead
  // MCP server and the respawn re-probes, so once mac-watch reports the Mac
  // online again this process steps aside and routing re-converges on its
  // own — no agent shell surgery, no approvals. Two consecutive online
  // reads defend against flapping; the idle window keeps an in-flight tool
  // call alive once no JSON-RPC request is pending.
  if (activeHost !== 'mac' && macSsh) {
    let onlineStreak = 0;
    const timer = setInterval(() => {
      const mac = freshMacState(macStateFile);
      onlineStreak = mac && mac.state === 'online' ? onlineStreak + 1 : 0;
      if (mayReconverge({
        mac,
        onlineStreak,
        lastActivity,
        pendingSize: pendingRequests.size,
        idleMs: RECONVERGE_IDLE_MS,
        now: Date.now(),
      })) {
        process.stderr.write(
          `workspace-router: ${hostName} is online — exiting so the next connection re-probes and routes to it\n`,
        );
        try {
          if (activeChild) activeChild.kill('SIGTERM');
        } catch {}
        process.exit(0);
      }
    }, 30000);
    timer.unref();
  }
}

if (require.main === module) {
  main();
}

module.exports = {
  readMacState,
  freshMacState,
  workspaceNotice,
  pageUrlFromMessage,
  readResume,
  readResumeRecord,
  writeResume,
  resumePath,
  safeResumeUrl,
  markResumeOpened,
  continueRememberedPage,
  continuedPage,
  continuedArgs,
  annotateResult,
  makeAnnotator,
  macBackendCommand,
  windowsBackendCommand,
  windowsProbeCommand,
  shQuote,
  psQuote,
  stderrTail,
  noteClientRpc,
  noteServerRpc,
  mayReconverge,
  SELF_PROBE_INTERVAL_MS,
  RECONVERGE_IDLE_MS,
};
