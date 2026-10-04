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
// Environment fallbacks: HERMES_WORKSPACE_BOT_ID, HERMES_BOT_NAME,
//   HERMES_WORKSPACE_MAC_SSH, HERMES_WORKSPACE_MAC_NODE,
//   HERMES_WORKSPACE_MAC_MCP, HERMES_WORKSPACE_VPS_MCP,
//   HERMES_WORKSPACE_CONNECTION.
// With no Mac ssh configured the router always serves the local VPS host.
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const botId = arg('--bot-id') || process.env.HERMES_WORKSPACE_BOT_ID || '';
const botName = arg('--bot-name') || process.env.HERMES_BOT_NAME || '';
if (!botId) {
  process.stderr.write(
    'workspace-router: --bot-id (or HERMES_WORKSPACE_BOT_ID) is required.\n',
  );
  process.exit(1);
}
const macSsh = arg('--mac-ssh') || process.env.HERMES_WORKSPACE_MAC_SSH || '';
const macNode = arg('--mac-node') || process.env.HERMES_WORKSPACE_MAC_NODE || 'node';
const macScript =
  arg('--mac-script') ||
  process.env.HERMES_WORKSPACE_MAC_MCP ||
  '/Applications/Hermes Workspace.app/Contents/Resources/app/scripts/browser-mcp.cjs';
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

// Quote a value for the remote command line ssh builds from argv.
const shQuote = (value) => `'${String(value).replace(/'/g, `'\\''`)}'`;

function probeMac(timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn(
      'ssh',
      ['-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6', '-o', 'StrictHostKeyChecking=yes', macSsh, 'true'],
      { stdio: 'ignore' },
    );
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      resolve(false);
    }, timeoutMs);
    child.on('error', () => {
      clearTimeout(timer);
      resolve(false);
    });
    child.on('exit', (code) => {
      clearTimeout(timer);
      resolve(code === 0);
    });
  });
}

async function main() {
  const macUp = macSsh ? await probeMac(8000) : false;

  let cmd;
  let args;
  if (macUp) {
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

  const child = spawn(cmd, args, { stdio: 'inherit' });
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

main();
