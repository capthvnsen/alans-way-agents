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
//   --mac-node PATH            node binary on the Mac (default: node)
//   --mac-script PATH          browser-mcp.cjs path on the Mac
//                              (default: the installed app's bundled copy)
//   --vps-script PATH          browser-mcp.cjs path on this host
//                              (default: sibling copy, then the deployed copy)
//   --vps-connection PATH      VPS browser connection.json
//   --mac-state-file PATH      mac-watch state file
//                              (default: /var/lib/hermes-alans-way/mac-state.json)
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
const macNode = arg('--mac-node') || process.env.HERMES_WORKSPACE_MAC_NODE || 'node';
const configuredMacScript = arg('--mac-script') || process.env.HERMES_WORKSPACE_MAC_MCP;
const macScripts = configuredMacScript
  ? [configuredMacScript]
  : [
      '/Applications/Open Alan.app/Contents/Resources/app/scripts/browser-mcp.cjs',
      "/Applications/Hermes- Alan's way.app/Contents/Resources/app/scripts/browser-mcp.cjs",
      '/Applications/Hermes Workspace.app/Contents/Resources/app/scripts/browser-mcp.cjs',
    ];
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

// Quote a value for the remote command line ssh builds from argv.
const shQuote = (value) => `'${String(value).replace(/'/g, "'\\''")}'`;

function probeMac(timeoutMs) {
  return new Promise((resolve) => {
    const probe = macScripts.map(script => `if [ -f ${shQuote(script)} ]; then printf %s ${shQuote(script)}; exit 0; fi`).join('; ') + '; exit 1';
    const child = spawn(
      'ssh',
      ['-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', '-o', 'StrictHostKeyChecking=yes', macSsh, probe],
      { stdio: ['ignore', 'pipe', 'ignore'] },
    );
    let output = '';
    child.stdout.on('data', chunk => { if (output.length < 4096) output += chunk; });
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      resolve(null);
    }, timeoutMs);
    child.on('error', () => {
      clearTimeout(timer);
      resolve(null);
    });
    child.on('exit', (code) => {
      clearTimeout(timer);
      resolve(code === 0 && macScripts.includes(output) ? output : null);
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

// Human-readable line appended to tool results — the channel the agent sees.
// Only meaningful when this connection fell back to the VPS host.
function workspaceNotice(host, mac) {
  if (!mac || host !== 'vps') return null;
  if (mac.state === 'online') {
    return (
      `[workspace] Mac is back online as of ${mac.since || 'unknown'} — ` +
      'tasks waiting on Mac-local resources can resume.'
    );
  }
  return (
    `[workspace] Mac unreachable since ${mac.since || 'unknown'} — ` +
    'routed to VPS browser; Mac-local files unavailable.'
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
  return function annotateLine(line) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return line;
    }
    if (!msg || typeof msg !== 'object' || !msg.result || typeof msg.result !== 'object') return line;
    const mac = macConfigured ? readMacState(stateFile) : null;
    let notice = null;
    if (mac && Array.isArray(msg.result.content)) {
      if (mac.state === 'online') {
        if (!onlineAnnounced) notice = workspaceNotice(host, mac);
        onlineAnnounced = true;
      } else {
        onlineAnnounced = false;
        notice = workspaceNotice(host, mac);
      }
    }
    return JSON.stringify(annotateResult(msg, host, mac, notice));
  };
}

async function main() {
  if (!botId) {
    process.stderr.write(
      'workspace-router: --bot-id (or HERMES_WORKSPACE_BOT_ID) is required.\n',
    );
    process.exit(1);
  }
  const macScript = macSsh ? await probeMac(8000) : null;

  let cmd;
  let args;
  if (macScript) {
    // Run browser-mcp.cjs on the Mac over the same ssh session the probe used.
    const remote = [macNode, shQuote(macScript), '--bot-id', shQuote(botId)];
    if (botName) remote.push('--bot-name', shQuote(botName));
    cmd = 'ssh';
    args = [
      '-T',
      '-o',
      'BatchMode=yes',
      '-o',
      'StrictHostKeyChecking=yes',
      macSsh,
      remote.join(' '),
    ];
    process.stderr.write('workspace-router: routing to Mac browser host\n');
  } else {
    // Mac unreachable or unconfigured — fall back to the local VPS browser host.
    cmd = process.execPath;
    args = [vpsScript, '--bot-id', botId];
    if (botName) args.push('--bot-name', botName);
    args.push('--connection', vpsConnection);
    process.stderr.write(
      macSsh
        ? 'workspace-router: Mac unreachable — routing to VPS browser host\n'
        : 'workspace-router: no Mac ssh configured — routing to VPS browser host\n',
    );
  }

  const child = spawn(cmd, args, { stdio: ['inherit', 'pipe', 'inherit'] });
  const annotate = makeAnnotator(macScript ? 'mac' : 'vps', Boolean(macSsh), macStateFile);
  readline
    .createInterface({ input: child.stdout, crlfDelay: Infinity })
    .on('line', (line) => {
      let out;
      try {
        out = annotate(line);
      } catch {
        out = line;
      }
      process.stdout.write(out + '\n');
    });
  child.on('error', (e) => {
    process.stderr.write(`workspace-router: failed to spawn backend: ${e.message}\n`);
    process.exit(1);
  });
  child.on('exit', (code, sig) => {
    process.exit(code === null ? (sig ? 1 : 0) : code);
  });
  for (const s of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(s, () => {
      try {
        child.kill(s);
      } catch {}
    });
  }
}

if (require.main === module) {
  main();
}

module.exports = { readMacState, workspaceNotice, annotateResult, makeAnnotator };
