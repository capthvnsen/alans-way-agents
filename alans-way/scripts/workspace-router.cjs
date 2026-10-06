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
//   --mac-ssh USER@HOST        Mac ssh alias/host for the Mac path
//   --mac-node PATH            node binary on the Mac (default: the app's own runtime)
//   --mac-script PATH          browser-mcp.cjs path on the Mac
//                              (default: the installed app's bundled copy)
//   --vps-script PATH          browser-mcp.cjs path on this host
//                              (default: sibling copy, then the deployed copy)
//   --vps-connection PATH      VPS browser connection.json
//   --mac-state-file PATH      mac-watch state file
//                              (default: /var/lib/hermes-alans-way/mac-state.json)
//   --probe                    run the Mac probe once, print the decision,
//                              and exit — read-only, for install/verify checks
// Environment fallbacks: HERMES_WORKSPACE_BOT_ID, HERMES_BOT_NAME,
//   HERMES_WORKSPACE_MAC_SSH, HERMES_WORKSPACE_MAC_NODE,
//   HERMES_WORKSPACE_MAC_MCP, HERMES_WORKSPACE_VPS_MCP,
//   HERMES_WORKSPACE_CONNECTION, HERMES_MAC_STATE_FILE.
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
const configuredMacScript = arg('--mac-script') || process.env.HERMES_WORKSPACE_MAC_MCP;
const macScripts = configuredMacScript
  ? [configuredMacScript]
  : [
      '/Applications/alans-way-localapp.app/Contents/Resources/app/scripts/browser-mcp.cjs',
      '/Applications/Open Alan.app/Contents/Resources/app/scripts/browser-mcp.cjs',
      "/Applications/Hermes- Alan's way.app/Contents/Resources/app/scripts/browser-mcp.cjs",
      '/Applications/Hermes Workspace.app/Contents/Resources/app/scripts/browser-mcp.cjs',
    ];
const connectorSuffix = 'Library/Application Support/Hermes Workspace/connector/scripts/browser-mcp.cjs';
const siblingScript = path.join(__dirname, 'browser-mcp.cjs');
const vpsScript =
  arg('--vps-script') ||
  process.env.HERMES_WORKSPACE_VPS_MCP ||
  (fs.existsSync(siblingScript)
    ? siblingScript
    : '/opt/hermes-alans-way/browser/desktop/scripts/browser-mcp.cjs');
const vpsConnection =
  arg('--vps-connection') ||
  process.env.HERMES_WORKSPACE_CONNECTION ||
  path.join(os.homedir(), '.local', 'share', 'hermes-alans-way', 'browser', 'connection.json');
const macStateFile =
  arg('--mac-state-file') ||
  process.env.HERMES_MAC_STATE_FILE ||
  '/var/lib/hermes-alans-way/mac-state.json';

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
    return `if [ -x ${shQuote(exe)} ]; then NODE_PATH=${shQuote(modules)} ELECTRON_RUN_AS_NODE=1 exec ${shQuote(exe)} ${args}; fi`;
  }).join(' ');
  return `${checks} exec node ${args}`;
}

// Probe finds the newest installed bundle AND proves the app is actually
// serving — a closed app still has the script on disk, so file-existence
// alone would route to a dead host. The API answers 401 without auth, which
// still proves liveness; a refused connection means the app is not running.
function probeMac(timeoutMs, connectTimeout = 6) {
  return new Promise((resolve) => {
    const alive =
      `{ conn="$HOME/Library/Application Support/Hermes Workspace/connection.json"; ` +
      `[ -f "$conn" ] && ` +
      `port=$(sed -n 's/.*"url"[^0-9]*[0-9.]*:\\([0-9]*\\).*/\\1/p' "$conn" | head -1) && ` +
      `curl -s -m 4 -o /dev/null "http://127.0.0.1:\${port:-9464}/status"; }`;
    const probe = `conn_script="$HOME/${connectorSuffix}"; if [ -f "$conn_script" ] && ${alive}; then printf %s "$conn_script"; exit 0; fi; ` + macScripts
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
      const script = code === 0 && (macScripts.includes(output) || output.endsWith(connectorSuffix)) ? output : null;
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

function readResume(file, now = Date.now()) {
  try {
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (!data || typeof data.url !== 'string' || typeof data.at !== 'number') return null;
    if (now - data.at > RESUME_MAX_AGE_MS) return null;
    return data.url;
  } catch { return null; }
}

function workspaceNotice(host, mac, resumeUrl) {
  if (!mac || host !== 'vps') return null;
  if (mac.state === 'online') {
    return (
      `[workspace] Mac is back online as of ${mac.since || 'unknown'} — ` +
      'tasks waiting on Mac-local resources can resume. New web work goes to the in-app Mac browser.'
    );
  }
  const page = resumeUrl ? ` Reopen ${resumeUrl} and continue.` : ' Reopen the same URL and continue.';
  return (
    `[workspace] Mac unreachable since ${mac.since || 'unknown'} — ` +
    `routed to VPS browser.${page} API, MCP, and connector calls that do not run on the Mac keep going. Mac-local files are unavailable.`
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
function makeAnnotator(host, macConfigured, stateFile) {
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
    const resume = host === 'vps' ? readResume(remembered) : null;
    let notice = null;
    if (mac && Array.isArray(msg.result.content)) {
      if (mac.state === 'online') {
        if (!onlineAnnounced) notice = workspaceNotice(host, mac, resume);
        onlineAnnounced = true;
      } else {
        onlineAnnounced = false;
        notice = workspaceNotice(host, mac, resume);
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
      process.stdout.write(`mac: ${probe.script}\n`);
      return;
    }
    const detail = tail ? ` (${tail})` : '';
    process.stdout.write(
      `vps${macSsh ? ` (mac unreachable${detail})` : ' (no mac-ssh)'}\n`,
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

  let cmd;
  let args;
  if (macScript) {
    // Run browser-mcp.cjs on the Mac over the same ssh session the probe used.
    cmd = 'ssh';
    args = [
      '-T',
      '-o',
      'BatchMode=yes',
      '-o',
      'StrictHostKeyChecking=yes',
      ...sshControlArgs,
      macSsh,
      macBackendCommand(macScript, macNode, botId, botName),
    ];
    process.stderr.write('workspace-router: routing to Mac browser host\n');
  } else {
    // Mac unreachable or unconfigured — fall back to the local VPS browser host.
    cmd = process.execPath;
    args = [vpsScript, '--bot-id', botId];
    if (botName) args.push('--bot-name', botName);
    args.push('--connection', vpsConnection);
    let reason = macSeen && macSeen.state === 'offline' ? 'offline per mac-watch' : 'unreachable';
    if (probeErrTail) reason += ` (${probeErrTail})`;
    process.stderr.write(
      macSsh
        ? `workspace-router: Mac ${reason} — routing to VPS browser host\n`
        : 'workspace-router: no Mac ssh configured — routing to VPS browser host\n',
    );
    if (staleSelfProbe && macSeen && macSeen.state === 'offline' && !macScript) {
      process.stderr.write(
        'workspace-router: self-probe despite fresh offline verdict — watcher may be misconfigured\n',
      );
    }
  }

  const child = spawn(cmd, args, { stdio: ['pipe', 'pipe', 'inherit'] });
  const pendingRequests = new Set();

  // Annotation is decoration — a failure here must never take down the
  // transport (that is how a one-line ReferenceError dropped the whole
  // browser surface). Degrade to passthrough instead.
  let annotate;
  try {
    annotate = makeAnnotator(macScript ? 'mac' : 'vps', Boolean(macSsh), macStateFile);
  } catch (e) {
    process.stderr.write(`workspace-router: annotator disabled: ${e.message}\n`);
    annotate = (line) => line;
  }

  let lastActivity = Date.now();
  const touchActivity = () => { lastActivity = Date.now(); };

  readline
    .createInterface({ input: process.stdin, crlfDelay: Infinity })
    .on('line', (line) => {
      touchActivity();
      noteClientRpc(line, pendingRequests);
      child.stdin.write(`${line}\n`);
    });

  readline
    .createInterface({ input: child.stdout, crlfDelay: Infinity })
    .on('line', (line) => {
      touchActivity();
      noteServerRpc(line, pendingRequests);
      let out;
      try {
        out = annotate(line);
      } catch {
        out = line;
      }
      if (out === null) return;
      process.stdout.write(`${out}\n`);
    });
  child.on('error', (e) => {
    process.stderr.write(`workspace-router: failed to spawn backend: ${e.message}\n`);
    process.exit(1);
  });
  child.on('exit', (code, sig) => {
    process.exit(code === null ? (sig ? 1 : 0) : code);
  });
  let routerMtime = 0;
  try { routerMtime = fs.statSync(__filename).mtimeMs; } catch { /* a missing script has nothing newer to load */ }
  const reloadTimer = setInterval(() => {
    if (pendingRequests.size > 0 || Date.now() - lastActivity < 1000) return;
    let mtime = routerMtime;
    try { mtime = fs.statSync(__filename).mtimeMs; } catch { return; }
    if (mtime <= routerMtime) return;
    process.stderr.write('workspace-router: script replaced — exiting so the next connection loads it\n');
    try { child.kill('SIGTERM'); } catch { /* the exit below is what Hermes respawns from */ }
    process.exit(0);
  }, 5000);
  reloadTimer.unref();
  for (const s of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(s, () => {
      try {
        child.kill(s);
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
  if (!macScript && macSsh) {
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
          'workspace-router: Mac is online — exiting so the next connection re-probes and routes to it\n',
        );
        try {
          child.kill('SIGTERM');
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
  writeResume,
  resumePath,
  annotateResult,
  makeAnnotator,
  macBackendCommand,
  shQuote,
  stderrTail,
  noteClientRpc,
  noteServerRpc,
  mayReconverge,
  SELF_PROBE_INTERVAL_MS,
  RECONVERGE_IDLE_MS,
};
