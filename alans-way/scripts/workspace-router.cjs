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
// forwarding stdio transparently is the smallest correct mechanism. If the
// host drops mid-session (ssh keepalive, a stuck call, a fresh mac-watch
// offline verdict, the app quitting) the router moves the session to the VPS
// backend in-process, restoring the host's mirrored tabs there; once the host
// is back and the session is idle it exits so Hermes respawns it onto the host.
//
// Configuration (all optional unless noted):
//   --bot-id ID                required: this bot's tab-owner identity
//   --bot-name NAME            optional display name for the agent cursor
//   --mac-ssh USER@HOST        ssh alias/host for the user's computer
//   --host-os mac|windows|linux  OS of the user's computer (default: mac)
//   --mac-node PATH            node binary on the user's computer
//                              (default: the app's own runtime; mac and linux)
//   --mac-script PATH          browser-mcp.cjs path on the user's computer
//                              (default: the installed app's bundled copy; mac and linux)
//   --vps-script PATH          browser-mcp.cjs path on this host
//                              (default: sibling copy, then the deployed copy)
//   --vps-connection PATH      local browser host connection.json
//   --mac-state-file PATH      mac-watch state file
//                              (default: /var/lib/hermes-alans-way/mac-state.json,
//                               ~/Library/Application Support/... on a macOS guest,
//                               ~/.local/share/hermes-alans-way/... on a Windows guest)
//   --probe                    run the host probe once, print the decision,
//                              and exit — read-only, for install/verify checks
//   --host-timezone-command    print the command that makes the host's node
//                              report its IANA timezone (setup.sh runs it over ssh)
//   --watch [--interval S] [--hysteresis N] [--state-file PATH] [--once]
//                              the availability watcher (mac-watch.sh wraps it):
//                              probe every S seconds (default 30) and publish the
//                              state file the router and observer read
// Environment fallbacks: HERMES_WORKSPACE_BOT_ID, HERMES_BOT_NAME,
//   HERMES_WORKSPACE_MAC_SSH, HERMES_WORKSPACE_HOST_OS,
//   HERMES_WORKSPACE_MAC_NODE, HERMES_WORKSPACE_MAC_MCP,
//   HERMES_WORKSPACE_VPS_MCP, HERMES_WORKSPACE_CONNECTION,
//   HERMES_MAC_STATE_FILE, HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS
//   (exposes workspace_computer_action again: only setup-workspace.sh
//   --allow-desktop-actions or the alans-way-computer provider sets it).
// With no Mac ssh configured the router always serves the local VPS host.
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const readline = require('node:readline');

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const botId = arg('--bot-id') || process.env.HERMES_WORKSPACE_BOT_ID || '';
const botName = arg('--bot-name') || process.env.HERMES_BOT_NAME || '';
const macSsh = arg('--mac-ssh') || process.env.HERMES_WORKSPACE_MAC_SSH || '';
const macNode = arg('--mac-node') || process.env.HERMES_WORKSPACE_MAC_NODE || '';
// Anything that is not windows or linux would silently probe a POSIX shell
// with the Mac layout on a host where it never converges, so it means mac.
const hostOsArg = arg('--host-os') || process.env.HERMES_WORKSPACE_HOST_OS || 'mac';
const hostOs = hostOsArg === 'windows' || hostOsArg === 'linux' ? hostOsArg : 'mac';
const hostName = { windows: 'Windows host', linux: 'Linux host', mac: 'Mac' }[hostOs];
const configuredMacScript = arg('--mac-script') || process.env.HERMES_WORKSPACE_MAC_MCP;
// `npm run package:linux` (electron-packager, x64, no asar) writes
// alans-way-localapp-linux-x64/ (alans-workspace once renamed) with the executable beside resources/app. No
// installer exists for Linux, so these are the places such a folder is
// expected, as-built or renamed.
const linuxAppRoots = [
  '/opt/alans-workspace-linux-x64',
  '/opt/alans-workspace',
  '$HOME/.local/share/alans-workspace-linux-x64',
  '$HOME/.local/share/alans-workspace',
  '/opt/alans-way-localapp-linux-x64',
  '/opt/alans-way-localapp',
  '$HOME/.local/share/alans-way-localapp-linux-x64',
  '$HOME/.local/share/alans-way-localapp',
];
const shellWord = (value) => (value.startsWith('$HOME') ? `"${value}"` : shQuote(value));
const linuxScripts = linuxAppRoots.map((root) => `${root}/resources/app/scripts/browser-mcp.cjs`);
const macScripts = configuredMacScript
  ? [configuredMacScript]
  : hostOs !== 'mac'
    ? []
    : [
        "/Applications/Alan's Workspace.app/Contents/Resources/app/scripts/browser-mcp.cjs",
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
// A native-Windows guest keeps its state beside the browser host's, under the
// profile (the same ~/.local/share tree the app's host scripts default to).
const macStateFile =
  arg('--mac-state-file') ||
  process.env.HERMES_MAC_STATE_FILE ||
  (process.platform === 'darwin'
    ? path.join(os.homedir(), 'Library', 'Application Support', 'hermes-alans-way', 'mac-state.json')
    : process.platform === 'win32'
      ? path.join(os.homedir(), '.local', 'share', 'hermes-alans-way', 'mac-state.json')
      : '/var/lib/hermes-alans-way/mac-state.json');

// Windows guest: Win32-OpenSSH is the ssh the user's keys, agent and
// known_hosts already belong to, and a Git-for-Windows ssh earlier on PATH can
// differ. It has no ControlMaster (privateSocketDir below returns null on
// win32), so every spawn pays a fresh handshake over the tailnet.
function chooseSsh() {
  if (process.platform !== 'win32') return 'ssh';
  const native = path.join(process.env.SystemRoot || process.env.windir || 'C:\\Windows', 'System32', 'OpenSSH', 'ssh.exe');
  return fs.existsSync(native) ? native : 'ssh';
}
const sshBinary = chooseSsh();

// Reuse one ssh connection between the probe and the backend spawn: the
// probe's handshake becomes the spawn's (~5ms vs a full handshake), and
// later respawns ride it for ControlPersist seconds. %C hashes the
// destination, so the socket name needs no host-derived parts. The socket
// lives in a private dir under /tmp, not $TMPDIR: a macOS guest's TMPDIR is
// ~50 chars, and ssh refuses a ControlPath over 104 chars once it appends its
// 17-char temp suffix. Each bot gets its own master (an 8-hex hash of its id
// prefixes %C): the host's sshd allows 10 sessions per connection by default,
// and every bot on the VM sharing one master overruns it. ServerAlive makes
// the master (and so every session on it) drop within ~10s when the host
// vanishes, instead of hanging on a half-open socket.
function privateSocketDir() {
  if (process.platform === 'win32' || typeof process.getuid !== 'function') return null;
  const dir = `/tmp/wsr-${process.getuid()}`;
  try {
    try { fs.mkdirSync(dir, { mode: 0o700 }); } catch (e) { if (e.code !== 'EEXIST') return null; }
    const st = fs.lstatSync(dir);
    return st.isDirectory() && st.uid === process.getuid() && (st.mode & 0o077) === 0 ? dir : null;
  } catch { return null; }
}
const sshKeepaliveArgs = ['-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=2'];
const socketDir = privateSocketDir();
const botControlPrefix = botId ? `${crypto.createHash('sha1').update(botId).digest('hex').slice(0, 8)}-` : '';
const sshControlArgs = [
  ...sshKeepaliveArgs,
  ...(socketDir
    ? ['-o', 'ControlMaster=auto', '-o', 'ControlPersist=600', '-o', `ControlPath=${socketDir}/${botControlPrefix}%C`]
    : []),
];

// Quote a value for the remote command line ssh builds from argv.
const shQuote = (value) => `'${String(value).replace(/'/g, "'\\''")}'`;
// Same for a remote PowerShell: single-quoted literal, '' escapes '.
const psQuote = (value) => `'${String(value).replace(/'/g, "''")}'`;

// ssh's own words when the shared master's session limit (sshd MaxSessions) is
// hit: it then falls back to a full handshake. One clear line, or null.
function muxTrouble(text) {
  return /Session open refused by peer|disabling multiplexing/.test(String(text || ''))
    ? 'workspace-router: ssh multiplexing is being refused (the host sshd MaxSessions is too low for the shared connection): each call pays a full ssh handshake. Raise MaxSessions in the host sshd_config.'
    : null;
}
let muxTroubleLogged = false;
function logMuxTrouble(text) {
  const line = !muxTroubleLogged && muxTrouble(text);
  if (!line) return;
  muxTroubleLogged = true;
  process.stderr.write(`${line}\n`);
}

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

// `pending` is a Set of request ids or, in the router, a Map id -> request
// (method, raw line, start time) so a failover knows what was in flight.
// Returns the request's method (or null) so the caller need not parse again.
function noteClientRpc(line, pending) {
  try {
    const msg = JSON.parse(line);
    if (!msg || typeof msg !== 'object' || typeof msg.method !== 'string') return null;
    if (msg.id != null) {
      if (pending instanceof Map) {
        const args = msg.params && msg.params.arguments;
        pending.set(msg.id, {
          method: msg.method,
          name: msg.params && msg.params.name,
          line,
          at: Date.now(),
          batch: Boolean(args && args.action === 'batch'),
        });
      } else pending.add(msg.id);
    }
    return msg.method;
  } catch { return null; }
}

// A screenshot result is megabytes of base64: find its id from the line's
// head or tail instead of parsing it. The MCP SDK writes
// {"result":...,"jsonrpc":"2.0","id":N}; other servers put the id first.
// An unrecognised shape returns undefined and the caller parses.
const BIG_LINE = 100000;
const ID_AT_HEAD = /^\{\s*"jsonrpc"\s*:\s*"2\.0"\s*,\s*"id"\s*:\s*(\d+|"[^"\\]*")/;
const ID_AT_TAIL = /,\s*"id"\s*:\s*(\d+|"[^"\\]*")\s*\}$/;
function bigLineId(line) {
  const head = ID_AT_HEAD.exec(line.slice(0, 200));
  if (head) return JSON.parse(head[1]);
  const tail = ID_AT_TAIL.exec(line.slice(-120));
  return tail ? JSON.parse(tail[1]) : undefined;
}

// Returns the wall-clock ms a tools/call took when the router timed it.
function noteServerRpc(line, pending) {
  const done = (id) => {
    const req = pending instanceof Map ? pending.get(id) : null;
    pending.delete(id);
    return req && req.method === 'tools/call' && typeof req.at === 'number' ? Date.now() - req.at : undefined;
  };
  try {
    if (line.length > BIG_LINE) {
      const id = bigLineId(line);
      if (id !== undefined) return done(id);
    }
    const msg = JSON.parse(line);
    if (msg && typeof msg === 'object' && msg.id != null
        && (msg.result !== undefined || msg.error !== undefined)) {
      return done(msg.id);
    }
  } catch {}
  return undefined;
}

// The connector's "connection file is gone" error: the host app is not
// running though ssh is. Not the fetch failure/timeout message ("unavailable
// or timed out"): that is also what a slow action on a healthy host
// produces. A short line only, so a screenshot is never scanned.
function hostUnavailableLine(line) {
  return line.length < 4000 && /"isError"\s*:\s*true/.test(line)
    && /Configured browser unavailable: start its app/.test(line);
}

// Tools that only read: safe to run a second time on the VPS if the host
// dropped mid-call. Everything else may have acted.
const READ_ONLY_TOOLS = new Set([
  'cua_alans_way_status',
  'cua_alans_way_tabs',
  'cua_alans_way_snapshot',
  'cua_alans_way_screenshot',
  'workspace_computer_apps',
  'workspace_computer_snapshot',
  'workspace_computer_screenshot',
  'workspace_computer_menu',
]);

// Desktop input is ungated at the MCP layer (this server carries no trust
// key), so workspace_computer_action is hidden from tools/list and refused
// unless the operator opted in: setup-workspace.sh --allow-desktop-actions
// writes HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS into the managed block, and
// the alans-way-computer provider sets it on its own private router child
// (Hermes's computer_use approval gate sits above that path). The read-only
// computer tools above stay exposed either way.
const DESKTOP_INPUT_TOOL = 'workspace_computer_action';
const desktopActionsAllowed = !['', '0', 'false', 'no'].includes(
  (process.env.HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS || '').trim().toLowerCase());

function mayReconverge({ mac, onlineStreak, lastActivity, pendingSize, idleMs, now }) {
  return Boolean(
    mac && mac.state === 'online' && onlineStreak >= 2 && pendingSize === 0
      && now - lastActivity > idleMs,
  );
}

// cua_alans_way_open's host: the shared alias table (the app keeps the same
// list in desktop/src/core.cjs). Anything unrecognized means "no host asked".
function normalizeHost(value) {
  if (typeof value !== 'string') return undefined;
  const host = value.trim().toLowerCase();
  if (host === 'computer' || host === 'mac' || host === 'windows' || host === 'linux'
    || host === 'local' || host === 'pc') return 'computer';
  if (host === 'vm' || host === 'vps' || host === 'remote' || host === 'server') return 'vm';
  return undefined;
}

// Non-interactive ssh never loads Homebrew's PATH, so a bare `node` is
// usually missing on the Mac. The app bundle already ships a Node runtime:
// its own Electron binary with ELECTRON_RUN_AS_NODE. PATH node is only the
// fallback for bundles without one; an explicit --mac-node always wins.
function macBackendCommand(script, node, id, name, scriptWord = shQuote(script)) {
  const tail = id === null ? [scriptWord] : [scriptWord, '--bot-id', shQuote(id)];
  if (name) tail.push('--bot-name', shQuote(name));
  const args = tail.join(' ');
  if (node) return `exec ${shQuote(node)} ${args}`;
  const bundle = /^(.*\/([^/]+)\.app)\/Contents\/Resources\//.exec(script);
  if (bundle) {
    const exe = shQuote(`${bundle[1]}/Contents/MacOS/${bundle[2]}`);
    return `if [ -x ${exe} ]; then ELECTRON_RUN_AS_NODE=1 exec ${exe} ${args}; else exec node ${args}; fi`;
  }
  // A connector copied into the home directory is newer than the app bundle.
  // Run it with the app's own Node and modules so a rebuild is not required.
  const apps = [
    "/Applications/Alan's Workspace.app",
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

// Linux host: same Electron-as-Node idea. The app is an electron-packager
// build, so the executable sits next to resources/app; /opt and the user's
// ~/.local/share are the install locations probed. The connector reads its
// connection file from the macOS path by default, so point it at the Linux
// userData dir ($XDG_CONFIG_HOME or ~/.config, then "Hermes Workspace").
function linuxBackendCommand(script, node, id, name, scriptWord = shQuote(script)) {
  const tail = id === null ? [scriptWord] : [scriptWord, '--bot-id', shQuote(id)];
  if (name) tail.push('--bot-name', shQuote(name));
  const args = tail.join(' ');
  const env = 'HERMES_WORKSPACE_CONNECTION="${XDG_CONFIG_HOME:-$HOME/.config}/Hermes Workspace/connection.json"; export HERMES_WORKSPACE_CONNECTION; ';
  if (node) return `${env}exec ${shQuote(node)} ${args}`;
  const checks = linuxAppRoots.map(shellWord).flatMap((root) =>
    ['alans-workspace', 'alans-way-localapp'].map((exe) =>
      `if [ -x ${root}/${exe} ]; then NODE_PATH=${root}/resources/app/node_modules ELECTRON_RUN_AS_NODE=1 exec ${root}/${exe} ${args}; fi;`,
    ),
  ).join(' ');
  return `${env}${checks} if [ -x "$HOME/.local/bin/node" ]; then exec "$HOME/.local/bin/node" ${args}; fi; exec node ${args}`;
}

// Shell text shared by the mac and linux hosts: set the connector path and
// connection file, then define wsr_alive. A closed app still has its script
// on disk, so file existence alone would route to a dead host. wsr_alive
// proves the app is serving AND accepts this machine's token (a stale
// connection.json fails it); the token goes to curl on stdin, not argv.
function posixPrelude() {
  const dir = hostOs === 'linux'
    ? '${XDG_CONFIG_HOME:-$HOME/.config}/Hermes Workspace'
    : '$HOME/Library/Application Support/Hermes Workspace';
  return (
    `conn_dir="${dir}"; conn_script="$conn_dir/connector/scripts/browser-mcp.cjs"; conn="$conn_dir/connection.json"; ` +
    'wsr_alive() { [ -f "$conn" ] && ' +
    `port=$(sed -n 's/.*"url"[^0-9]*[0-9.]*:\\([0-9]*\\).*/\\1/p' "$conn" | head -1) && ` +
    `tok=$(sed -n 's/.*"token"[^"]*"\\([^"]*\\)".*/\\1/p' "$conn" | head -1) && [ -n "$tok" ] && ` +
    `printf 'header = "Authorization: Bearer %s"\\n' "$tok" | ` +
    'curl -sf -m 4 -o /dev/null -K - "http://127.0.0.1:${port:-9464}/v1/status"; }; '
  );
}

// Each candidate is a shell word for a connector script plus the literal path
// when it is one (the home connector is expanded on the host, not here).
function posixCandidates() {
  const configured = configuredMacScript ? [{ word: shQuote(configuredMacScript), script: configuredMacScript }] : null;
  if (hostOs === 'linux') {
    return configured || [
      { word: '"$conn_script"', script: '' },
      ...linuxScripts.map((s) => ({ word: shellWord(s), script: s })),
    ];
  }
  return [{ word: '"$conn_script"', script: '' }, ...macScripts.map((s) => ({ word: shQuote(s), script: s }))];
}

function posixProbeCommand() {
  return posixPrelude() + posixCandidates()
    .map(({ word }) => `if [ -f ${word} ] && wsr_alive; then printf %s ${word}; exit 0; fi`)
    .join('; ') + '; exit 1';
}

// Probe and exec in one ssh session: used when mac-watch says the host is
// online, so the backend starts without a separate probe round trip. Exit 97
// with no output means "not alive": the dead-on-arrival fallback takes over.
function posixAutoBackendCommand(node, id, name) {
  const build = hostOs === 'linux' ? linuxBackendCommand : macBackendCommand;
  return posixPrelude() + posixCandidates()
    .map(({ word, script }) => `if [ -f ${word} ] && wsr_alive; then ${build(script, node, id, name, word)}; fi`)
    .join('; ') + '; exit 97';
}

// Windows backend: same idea over PowerShell — run the connector with the
// app's own Electron-as-Node runtime, falling back to the installer's private
// Node then PATH. The spawned process sits in Session 0, which is fine here:
// it only talks HTTP to the app's loopback API; desktop actions are served by
// the app itself. NODE_PATH supplies the pushed connector's dependencies.
function windowsBackendCommand(script, id, name) {
  const tail = id === null ? [script] : [psQuote(script), '--bot-id', psQuote(id)];
  if (name) tail.push('--bot-name', psQuote(name));
  const args = tail.join(' ');
  const exe = '"$env:LOCALAPPDATA\\Programs\\alans-way-localapp\\alans-way-localapp.exe"';
  const modules = '"$env:LOCALAPPDATA\\Programs\\alans-way-localapp\\resources\\app\\node_modules"';
  const node = '"$env:USERPROFILE\\.alans-way\\node\\node.exe"';
  return `$env:NODE_PATH = ${modules}; if (Test-Path ${exe}) { $env:ELECTRON_RUN_AS_NODE = '1'; & ${exe} ${args} } elseif (Test-Path ${node}) { & ${node} ${args} } else { & node ${args} }`;
}

// The posix probe (above) finds the newest installed bundle AND proves the
// app is serving and accepts our token. Same probe over PowerShell: like
// wsr_alive, connection.json must hold a token the API accepts — a 401 from a
// stale file means this host is not usable, so only a success counts —
// then emit the newest connector script path; the pushed home copy wins over
// the install.
function windowsProbeCommand() {
  return [
    // Invoke-WebRequest's progress stream can reach stdout over ssh and would
    // break the single-path output contract below.
    '$ProgressPreference = "SilentlyContinue"',
    '$conn = "$env:APPDATA\\Hermes Workspace\\connection.json"',
    'if (-not (Test-Path $conn)) { exit 1 }',
    '$port = 9464',
    '$token = ""',
    'try { $doc = Get-Content $conn -Raw | ConvertFrom-Json; $token = [string]$doc.token; $port = ([uri]$doc.url).Port } catch {}',
    'if ([string]::IsNullOrWhiteSpace($token)) { exit 1 }',
    '$alive = $false',
    `try { $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 4 -Headers @{ Authorization = "Bearer $token" } -Uri "http://127.0.0.1:$port/v1/status"; $alive = $true }`,
    'catch { $alive = $false }',
    'if (-not $alive) { exit 1 }',
    'foreach ($s in @(' +
      '"$env:APPDATA\\Hermes Workspace\\connector\\scripts\\browser-mcp.cjs",' +
      '"$env:LOCALAPPDATA\\Programs\\alans-way-localapp\\resources\\app\\scripts\\browser-mcp.cjs")) ' +
      '{ if (Test-Path $s) { Write-Output $s; exit 0 } }',
    'exit 1',
  ].join('; ');
}

// The user's zone is whatever their computer's own node reports: the same
// Electron-as-node invocation the backend uses, run with -p instead of a script.
// setup.sh runs this over its ssh path, so every host OS answers the same way.
function hostTimezoneCommand() {
  const expr = '-p \'Intl.DateTimeFormat().resolvedOptions().timeZone\'';
  if (hostOs === 'windows') return windowsBackendCommand(expr, null);
  return (hostOs === 'linux' ? linuxBackendCommand : macBackendCommand)('', '', null, '', expr);
}

function probeMac(timeoutMs, connectTimeout = 6) {
  return new Promise((resolve) => {
    const probe = hostOs === 'windows' ? windowsProbeCommand() : posixProbeCommand();
    const child = spawn(
      sshBinary,
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
      { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true },
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
        : hostOs === 'linux'
          ? /^\/.*browser-mcp\.cjs$/.test(found)
          : macScripts.includes(found) || found.endsWith(connectorSuffix);
      const script = code === 0 && valid ? found : null;
      logMuxTrouble(errOutput);
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

// One file per bot: two bots sharing a state dir must not continue each
// other's pages.
function resumePath(stateFile, bot = '') {
  const id = String(bot || '').replace(/[^\w-]/g, '_').slice(0, 64);
  return path.join(path.dirname(stateFile), id ? `resume-url-${id}.json` : 'resume-url.json');
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

function writeResumeNow(file, record) {
  try {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    const tmp = `${file}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(record));
    fs.renameSync(tmp, file);
  } catch { /* remembering a page must not break the tool result */ }
}

// Debounced: a busy Mac session returns a page url on most results, and a
// sync mkdir+write+rename per result sits on the hot path. The latest page
// is flushed within 1s and again synchronously at exit.
const resumeQueue = new Map();
let resumeExitHooked = false;
function flushResumes() {
  for (const [file, queued] of resumeQueue) {
    clearTimeout(queued.timer);
    writeResumeNow(file, queued.record);
  }
  resumeQueue.clear();
}

function writeResume(file, url) {
  const queued = resumeQueue.get(file);
  if (queued) {
    queued.record = { url, at: Date.now() };
    return;
  }
  if (!resumeExitHooked) {
    resumeExitHooked = true;
    process.on('exit', flushResumes);
  }
  const timer = setTimeout(() => {
    const entry = resumeQueue.get(file);
    resumeQueue.delete(file);
    if (entry) writeResumeNow(file, entry.record);
  }, 1000);
  timer.unref();
  resumeQueue.set(file, { record: { url, at: Date.now() }, timer });
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
    const tmp = `${file}.${process.pid}.tmp`;
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

// Auth headers and base URL for the browser host on this machine, or null
// when its connection file is missing or not a loopback http endpoint.
function loopbackClient({ connectionFile, botId, botName }) {
  let connection;
  try { connection = JSON.parse(fs.readFileSync(connectionFile, 'utf8')); } catch { return null; }
  let base;
  try { base = new URL(connection.url); } catch { return null; }
  if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1' || !connection.token || !botId) return null;
  return {
    base,
    headers: {
      Authorization: `Bearer ${connection.token}`,
      'X-Hermes-Bot': botId,
      ...(botName ? { 'X-Hermes-Bot-Name': encodeURIComponent(String(botName).slice(0, 80)) } : {}),
    },
  };
}

// Ask the VPS browser host to rebuild this bot's mirrored host tabs (cookies,
// url, scroll, drafts). Resolves to one of
//   {status:'restored', map:{hostTab:vpsTab}, review:[vpsTab...]}
//   {status:'none'}     the host has no mirror for this bot
//   {status:'pending'}  the host is still restoring (it opens tabs one at a
//                       time, so a few slow pages can outlast one request)
//   {status:'down'}     the host did not answer at all
// The host remembers what it opened, so the one retry after a timeout returns
// the same tabs rather than duplicating them.
async function restoreMirror({ connectionFile, botId, botName, fetchImpl, timeoutMs = 12000, retryMs = 10000 }) {
  const client = loopbackClient({ connectionFile, botId, botName });
  if (!client) return { status: 'down' };
  const fetch = fetchImpl || globalThis.fetch;
  const idOk = (v) => typeof v === 'string' && /^[\w-]{1,100}$/.test(v);
  for (const limit of [timeoutMs, retryMs]) {
    try {
      const response = await fetch(new URL('/v1/restore', client.base), {
        method: 'POST',
        headers: { ...client.headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ bot: botId }),
        signal: AbortSignal.timeout(limit),
      });
      if (response.status === 404) return { status: 'none' };
      if (!response.ok) return { status: 'down' };
      const body = await response.json();
      const entries = Object.entries((body && body.map) || {}).filter(([a, b]) => idOk(a) && idOk(b)).slice(0, 50);
      if (!entries.length) return { status: 'none' };
      const verification = (body && body.verification) || {};
      return {
        status: 'restored',
        map: Object.fromEntries(entries),
        review: entries.filter(([a]) => verification[a] === 'review_required').map(([, b]) => b),
      };
    } catch (e) {
      if (!e || (e.name !== 'TimeoutError' && e.name !== 'AbortError')) return { status: 'down' };
    }
  }
  return { status: 'pending' };
}

// Open the last Mac https page in the local VPS browser. Cookies do not copy.
// A tab that already has the URL is reused. A missing browser host returns
// null so the notice can still tell the model to open the page itself.
async function continueRememberedPage({ connectionFile, record, botId, botName, fetchImpl, now = Date.now() }) {
  const safe = record && safeResumeUrl(record.url);
  if (!safe || typeof record.at !== 'number' || now - record.at > RESUME_MAX_AGE_MS) return null;
  if (record.openedAt >= record.at && record.tabId) return { url: safe, tabId: record.tabId, already: true };
  const client = loopbackClient({ connectionFile, botId, botName });
  if (!client) return null;
  const { base, headers } = client;
  const fetch = fetchImpl || globalThis.fetch;
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

function workspaceNotice(host, mac, resumeUrl, continued, label = 'Mac', pageNote = '') {
  if (!mac || host !== 'vps') return null;
  if (mac.state === 'online') {
    return (
      `[workspace] ${label} is back online as of ${mac.since || 'unknown'}: ` +
      `tasks waiting on ${label}-local resources can resume. New web work goes to the in-app host browser.`
    );
  }
  const page = pageNote ? ` ${pageNote}` : continued && continued.url && continued.tabId
    ? ` Continued ${continued.url} in the VPS browser as tab ${continued.tabId}. Keep working in that tab. A login does not copy; if the page asks you to sign in, tell the user rather than working past it.`
    : resumeUrl ? ` Reopen ${resumeUrl} and continue.` : ' Reopen the same URL and continue.';
  return (
    `[workspace] ${label} unreachable since ${mac.since || 'unknown'}: ` +
    `routed to VPS browser.${page} API, MCP, and connector calls that do not run on the ${label} keep going. ${label}-local files are unavailable.`
  );
}

// What the agent is told once the router moves a live session to the VPS
// browser. `restored` is the {hostTabId: vpsTabId} map from the mirror
// restore; without a mirror it falls back to the single continued page.
function continuationDetail(c, label = 'Mac') {
  const idOk = (v) => typeof v === 'string' && /^[\w-]{1,100}$/.test(v);
  const tabs = Object.entries((c && c.map) || {}).filter(([a, b]) => idOk(a) && idOk(b)).slice(0, 20);
  if (tabs.length) {
    const review = ((c && c.review) || []).filter(idOk).slice(0, 20);
    return (
      `Restored ${tabs.length} tab${tabs.length === 1 ? '' : 's'} (${label} tab to VPS tab): ` +
      `${tabs.map(([a, b]) => `${a} -> ${b}`).join(', ')}. ` +
      'Work in the VPS tabs from now on. Cookies were restored for tabs that had them, so a signed-in site should still be signed in; ' +
      'if a page shows a sign-in wall, tell the user rather than working past it. A restored tab may still be loading, so snapshot it before acting.' +
      (review.length ? ` Look at these before acting, their scroll or drafts were not confirmed: ${review.join(', ')}.` : '')
    );
  }
  if (c && c.status === 'pending') {
    return 'The VPS browser is still restoring the tabs. List tabs again in a few seconds and work in the tab ids it shows. ' +
      'A login may not have carried over; if a page shows a sign-in wall, tell the user rather than working past it.';
  }
  if (c && c.status === 'down') {
    return `The VPS browser is not responding, so no tabs could be restored and ${label} is unreachable too. Try listing tabs again shortly; if it still fails, report that no browser is reachable.`;
  }
  const page = c && c.continued && safeResumeUrl(c.continued.url);
  if (page && idOk(c.continued.tabId)) {
    return (
      `Continued ${page} as VPS tab ${c.continued.tabId}. Keep working in that tab. ` +
      'Logins did not carry over; if the page asks you to sign in, tell the user rather than working past the login wall.'
    );
  }
  return null;
}

function continuationNotice(c, label = 'Mac') {
  const detail = continuationDetail(c, label)
    || 'No tabs were mirrored, so reopen the page you were on in the VPS browser and snapshot it before acting. ' +
       'Logins did not carry over; if a page shows a sign-in wall, tell the user rather than working past it.';
  return `[workspace] the ${label} browser did not answer in time; work moved to the VPS browser. ${detail}`;
}

// One line per tab whose id the handoff changed. A mirror restore names each
// pair; a single continued page stands in for the tab the agent last used,
// since the VPS connector carries calls aimed at a host tab onto it.
function tabIdChanges(c, lastTab, reason) {
  const idOk = (v) => typeof v === 'string' && /^[\w-]{1,100}$/.test(v);
  const pairs = Object.entries((c && c.map) || {}).filter(([a, b]) => idOk(a) && idOk(b) && a !== b).slice(0, 20);
  if (!pairs.length && c && c.continued && idOk(c.continued.tabId) && idOk(lastTab) && lastTab !== c.continued.tabId) {
    pairs.push([lastTab, c.continued.tabId]);
  }
  return pairs.map(([a, b]) => `[workspace] tab id changed: ${a} -> ${b}, reason: ${reason}`);
}

function workspaceMeta(host, mac, ms, tabIdChanged) {
  const meta = ms === undefined ? { host, mac } : { host, mac, ms };
  if (host === 'vps' && tabIdChanged && tabIdChanged.length) meta.tabIdChanged = tabIdChanged;
  return meta;
}

// Older connectors still declare open's `host` as Ignored; the router routes
// it now, so the advertised schema says what it does.
function rewriteOpenHost(result) {
  const tools = result && result.tools;
  if (!Array.isArray(tools)) return;
  for (const tool of tools) {
    const props = tool && tool.name === 'cua_alans_way_open' && tool.inputSchema && tool.inputSchema.properties;
    if (props && typeof props === 'object') {
      props.host = { type: 'string', description: '"computer" or "vm"; omit for the default.' };
    }
  }
}

// action and snapshot no longer demand tabId and epoch on every call: the
// router fills in the tab the agent last used and the epoch that backend last
// returned. Older connectors still require both, so the advertised schema is
// rewritten here the same way open's host is.
function rewriteTabDefaults(result) {
  const tools = result && result.tools;
  if (!Array.isArray(tools)) return;
  for (const tool of tools) {
    if (!tool || (tool.name !== 'cua_alans_way_action' && tool.name !== 'cua_alans_way_snapshot')) continue;
    const schema = tool.inputSchema;
    if (schema && Array.isArray(schema.required)) {
      schema.required = schema.required.filter((key) => key !== 'tabId' && key !== 'epoch');
    }
    const props = schema && schema.properties;
    if (!props || typeof props !== 'object') continue;
    for (const key of ['tabId', 'epoch']) {
      const prop = props[key];
      if (prop && typeof prop === 'object') {
        prop.description = `${prop.description ? `${prop.description} ` : ''}Optional: defaults to the tab you last used.`;
      }
    }
  }
}

// The commit gate. A cua_alans_way_action that buys, books, sends, posts,
// submits, deletes or changes an account carries `commit`; the router asks the
// user to approve it (MCP elicitation, which Hermes shows as chat buttons) and
// forwards it only on Approve. A click on a control named like one of these
// without `commit` is refused before it reaches the browser.
const COMMIT_VERBS = {
  purchase: 'buy',
  booking: 'book',
  send: 'send',
  post: 'post',
  submit: 'submit',
  delete: 'delete',
  account_change: 'change an account',
};
// Control names that commit, and look-alikes that do not (a login or 2FA
// code, a payment-method picker, an order history link, a filter chip's
// delete, a saved-address picker, a sign-up form's confirm fields). The list
// lives in commit-patterns.json so the app's own dispatch check can use the
// same one; that file says how to read it.
const COMMIT_PATTERNS = require(path.join(__dirname, 'commit-patterns.json'));
const SEP = '[\\s_-]+';
const phrase = (text) => text.split(' ').join(SEP);
const COMMIT_NAME = new RegExp(`(?<![\\p{L}\\p{N}])(?:${COMMIT_PATTERNS.names.map(phrase).join('|')})(?![\\p{L}\\p{N}])|${COMMIT_PATTERNS.namesAnywhere.join('|')}`, 'iu');
const NOT_COMMIT = new RegExp(COMMIT_PATTERNS.notCommit.map(phrase).join('|'), 'giu');
const isCommitName = (name) => COMMIT_NAME.test(String(name).replace(NOT_COMMIT, ' '));
// A selector read as words: #placeOrderBtn and [data-test=place-order] both
// say "place order".
const selectorWords = (selector) => selector.replace(/(\p{Ll})(\p{Lu})/gu, '$1 $2').replace(/[^\p{L}\p{N}]+/gu, ' ');
// Keys that only move focus, scroll or type a character. Any other key (Enter
// in any spelling including a raw "\r", Space, Delete, Backspace, a shortcut)
// may act on the focused control, so it is judged against the page.
const SAFE_KEYS = /^(?:tab|escape|esc|arrow(?:up|down|left|right)|up|down|left|right|home|end|pageup|pagedown|[\p{L}\p{N}])$/iu;
const isSafeKey = (step) => typeof step.key === 'string' && SAFE_KEYS.test(step.key)
  && (!Array.isArray(step.modifiers) || step.modifiers.every((m) => m === 'shift'));
// Steps aimed at a control, judged by its name. A drag presses on one end
// and releases on the other, so both ends count; a select fires change.
const TARGET_STEPS = {
  click: ['clicks', 'a click'],
  right_click: ['right-clicks', 'a right-click'],
  double_click: ['double-clicks', 'a double-click'],
  drag: ['drags', 'a drag'],
  select: ['sets', 'setting a value'],
  press: ['presses a key on', 'a key press'],
};
// DevTools calls that only read or set up the view. Any other (Input.*,
// Runtime.evaluate, a DOM edit) can act on the page, as eval can. A reload or
// a navigation is judged on its own.
const READ_ONLY_CDP = /^(?:\w+\.(?:get|describe|query|search|capture|enable|disable)|Emulation\.|Page\.(?:navigate|reload|stopLoading)$)/;
// A script planted for every later page in the tab outlives the gate's view
// of the page it was approved on, so agents never get one.
const BANNED_CDP = /^Page\.addScriptToEvaluateOn(?:NewDocument|Load)$/;
// Steps that leave the page where it is. After any other step a batch may be
// on a page the router has not seen.
const PAGE_STAYS = new Set(['type', 'wait', 'read', 'scroll', 'move', 'viewport']);
// An address whose path or query reads like an action (/orders/7/delete,
// ?step=confirm, /checkout/complete, /buy) can commit just by loading.
// "place" counts only beside "order", since /maps/place/ is an ordinary page.
const ACTION_URL = new RegExp(`(?<![\\p{L}\\p{N}])(?:confirm|place${SEP}order|order${SEP}place|placeorder|(?:checkout|order)${SEP}complete|pay|buy|submit|delete)(?![\\p{L}\\p{N}])`, 'iu');
// Whether an address reads like that, on any site, read the way the app
// reads it (trimmed, and no scheme means https).
function isActionUrl(url) {
  let parsed;
  const address = url.trim();
  try {
    parsed = new URL(/^[a-z][\w+.-]*:\/\//i.test(address) ? address : `https://${address}`);
  } catch {
    return false;
  }
  let words = `${parsed.pathname} ${parsed.search}`;
  try {
    words = decodeURIComponent(words);
  } catch { /* judge it encoded */ }
  return ACTION_URL.test(selectorWords(words));
}
// Tools the gate judges: actions, and opening a tab at an address.
const GATED_TOOLS = new Set(['cua_alans_way_action', 'cua_alans_way_open']);
const COMMIT_LOST = 'It may or may not have happened and was NOT retried. Check the page before repeating it.';

function addCommitParam(result) {
  const tools = result && result.tools;
  if (!Array.isArray(tools)) return;
  for (const tool of tools) {
    const props = tool && GATED_TOOLS.has(tool.name) && tool.inputSchema && tool.inputSchema.properties;
    if (!props || typeof props !== 'object') continue;
    props.commit = {
      type: 'object',
      description: 'Required on the call that places an order, pays, books, sends, posts, publishes, submits, deletes or changes account settings. The user approves it in chat first; it runs only on Approve and is never retried.',
      properties: {
        kind: { type: 'string', enum: Object.keys(COMMIT_VERBS) },
        summary: { type: 'string', maxLength: 200, description: 'What the user is approving, read off the page.' },
        amount: { type: 'string', description: 'Total as shown, e.g. "40.00".' },
        currency: { type: 'string' },
        counterparty: { type: 'string', description: 'Merchant, recipient or venue.' },
      },
      required: ['kind', 'summary'],
    };
  }
}

// One line of plain text for the approval card, or '' when unusable.
const cardText = (value, max) => (typeof value === 'string' || typeof value === 'number'
  ? String(value).replace(/[\u0000-\u001f\u007f]+/g, ' ').trim().slice(0, max)
  : '');

function cleanCommit(commit) {
  if (!commit || typeof commit !== 'object' || typeof commit.kind !== 'string' || !Object.hasOwn(COMMIT_VERBS, commit.kind)) return null;
  if (typeof commit.summary !== 'string' || commit.summary.length > 200) return null;
  const summary = cardText(commit.summary, 200);
  if (!summary) return null;
  return {
    kind: commit.kind,
    summary,
    amount: cardText(commit.amount, 40),
    currency: cardText(commit.currency, 10),
    counterparty: cardText(commit.counterparty, 100),
  };
}

// Additive decoration of one outbound JSON-RPC message: structured host state
// under result._meta.workspace plus, for tool results, the notice as an extra
// text content item. Anything not a result object passes through untouched.
function annotateResult(msg, host, mac, notice, ms, tabIdChanged) {
  if (!msg || typeof msg !== 'object' || !msg.result || typeof msg.result !== 'object') return msg;
  rewriteOpenHost(msg.result);
  rewriteTabDefaults(msg.result);
  addCommitParam(msg.result);
  if (!desktopActionsAllowed && Array.isArray(msg.result.tools)) {
    msg.result.tools = msg.result.tools.filter((tool) => !tool || tool.name !== DESKTOP_INPUT_TOOL);
  }
  msg.result._meta = { ...(msg.result._meta || {}), workspace: workspaceMeta(host, mac, ms, tabIdChanged) };
  if (notice && Array.isArray(msg.result.content)) {
    msg.result.content = [...msg.result.content, { type: 'text', text: notice }];
  }
  return msg;
}

// A screenshot result is one huge content array and nothing else: append the
// metadata to its text instead of parsing and re-serializing megabytes of
// base64. Two exact shapes are recognised (id first, and the MCP SDK's
// result-first order with the id last); anything else returns null and is
// parsed.
const RESULT_ID_FIRST = /^\{"jsonrpc":"2\.0","id":(?:\d+|"[^"\\]*"),"result":\{"content":\[/;
const RESULT_SDK_TAIL = /\]\},"jsonrpc":"2\.0","id":(?:\d+|"[^"\\]*")\}$/;
function resultShape(line) {
  if (line.length < BIG_LINE) return null;
  if (line.endsWith(']}}') && RESULT_ID_FIRST.test(line.slice(0, 200))) return 'id-first';
  if (line.startsWith('{"result":{"content":[') && RESULT_SDK_TAIL.test(line.slice(-120))) return 'sdk';
  return null;
}

function appendResultMeta(line, shape, host, mac, notice, ms, tabIdChanged) {
  const extra = notice ? `,${JSON.stringify({ type: 'text', text: notice })}` : '';
  const meta = `],"_meta":${JSON.stringify({ workspace: workspaceMeta(host, mac, ms, tabIdChanged) })}}`;
  if (shape === 'id-first') return `${line.slice(0, -3)}${extra}${meta}}`;
  const tail = RESULT_SDK_TAIL.exec(line.slice(-120))[0];
  return `${line.slice(0, line.length - tail.length)}${extra}${meta}${tail.slice(2)}`;
}

// Per-connection line annotator for the backend's stdout. The state file is
// re-read per message so a mid-session flip is seen; the "back online" notice
// fires once per online transition while the offline one rides every tool
// result, since either may be the agent's only signal that host changed.
// ctx.botId scopes the resume file; ctx.takeMoveNotice() yields the one-shot
// failover notice; ctx.restoredNote says which tabs the VPS browser restored;
// ctx.takeTabIdChanged() yields the one-shot id map so the first VPS result
// after a change names it in _meta — an agent holding an old host tab id
// learns of the change before it acts on that id.
function makeAnnotator(host, macConfigured, stateFile, label = 'Mac', ctx = {}) {
  let onlineAnnounced = false;
  const remembered = resumePath(stateFile, ctx.botId);
  return function annotateLine(line, ms) {
    const shape = resultShape(line);
    let msg;
    if (!shape) {
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
    }
    const mac = macConfigured ? readMacState(stateFile) : null;
    const record = host === 'vps' ? readResumeRecord(remembered) : null;
    const resume = record ? record.url : null;
    const continued = continuedPage(record);
    let notice = null;
    const hasContent = Boolean(shape) || Array.isArray(msg.result.content);
    const moved = hasContent && host === 'vps' && ctx.takeMoveNotice ? ctx.takeMoveNotice() : null;
    if (moved) notice = moved;
    else if (mac && hasContent) {
      if (mac.state === 'online') {
        // A session that failed over keeps the VPS until the router steps
        // aside on its own; "back online" would mislead before then.
        if (!onlineAnnounced && !ctx.failedOver) notice = workspaceNotice(host, mac, resume, continued, label, ctx.restoredNote);
        onlineAnnounced = true;
      } else {
        onlineAnnounced = false;
        notice = workspaceNotice(host, mac, resume, continued, label, ctx.restoredNote);
      }
    }
    if (notice && ms !== undefined) notice += ` (took ${ms}ms)`;
    // One change is reported once: only the VPS annotator drains it, since
    // _meta drops the list for any other host.
    const tabIdChanged = host === 'vps' && ctx.takeTabIdChanged ? ctx.takeTabIdChanged() : ctx.tabIdChanged;
    if (shape) return appendResultMeta(line, shape, host, mac, notice, ms, tabIdChanged);
    return JSON.stringify(annotateResult(msg, host, mac, notice, ms, tabIdChanged));
  };
}

// What mac-watch.sh used to be, in node so a Windows guest needs no sh, sed or
// timeout. "online" means the app answers, not just sshd (probeMac). A flip
// needs --hysteresis consecutive reads so one dropped probe does not move the
// agent between machines; the pending count rides in the state file so it
// survives --once runs and restarts. The file is rewritten atomically every
// tick: a stale mtime tells freshMacState the watcher is dead. Exit status 2
// is a configuration error a restart cannot fix.
async function watch() {
  const positive = (flag, fallback) => {
    const raw = arg(flag);
    if (raw === undefined) return fallback;
    if (!/^[1-9]\d*$/.test(raw)) {
      process.stderr.write('mac-watch: --interval and --hysteresis must be positive integers\n');
      process.exit(2);
    }
    return Number(raw);
  };
  const interval = positive('--interval', 30);
  const hysteresis = positive('--hysteresis', 2);
  if (!macSsh) {
    process.stderr.write(
      'mac-watch: HERMES_WORKSPACE_MAC_SSH is not set. Set it to user@host-of-your-computer (in /etc/hermes-alans-way/mac-watch.env for the systemd unit), or pass --mac-ssh. Not retrying.\n',
    );
    process.exit(2);
  }
  const file = arg('--state-file') || macStateFile;
  const eventsLog = path.join(path.dirname(file), 'mac-events.log');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const isoNow = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  let st = { state: '', since: '', lastSeen: '', lastTransition: '', pending: '', pendingCount: 0 };
  try {
    if (!fs.lstatSync(file).isSymbolicLink()) {
      const prev = JSON.parse(fs.readFileSync(file, 'utf8'));
      if (prev && (prev.state === 'online' || prev.state === 'offline')) {
        const text = (v) => (typeof v === 'string' ? v : '');
        st = {
          state: prev.state, since: text(prev.since), lastSeen: text(prev.lastSeenOnline),
          lastTransition: text(prev.lastTransition),
          pending: prev.pending === 'online' || prev.pending === 'offline' ? prev.pending : '',
          pendingCount: Number.isInteger(prev.pendingCount) && prev.pendingCount > 0 ? prev.pendingCount : 0,
        };
      }
    }
  } catch { /* no usable previous state: start unknown */ }
  const write = () => {
    const doc = {
      state: st.state, since: st.since, lastSeenOnline: st.lastSeen || null, lastTransition: st.lastTransition,
      ...(st.pending ? { pending: st.pending, pendingCount: st.pendingCount } : {}),
    };
    const tmp = `${file}.tmp.${process.pid}`;
    fs.writeFileSync(tmp, `${JSON.stringify(doc)}\n`);
    fs.renameSync(tmp, file);
  };
  const tick = async () => {
    const ts = isoNow();
    const current = (await probeMac(12000)).script ? 'online' : 'offline';
    if (current === 'online') st.lastSeen = ts;
    if (st.state && current !== st.state) {
      if (current === st.pending) st.pendingCount += 1;
      else { st.pending = current; st.pendingCount = 1; }
      if (st.pendingCount < hysteresis) { write(); return; }
    }
    st.pending = ''; st.pendingCount = 0;
    if (current !== st.state) {
      fs.appendFileSync(eventsLog, `${ts} ${st.state || 'unknown'} -> ${current}\n`);
      st = { ...st, state: current, since: ts, lastTransition: ts };
    }
    write();
  };
  for (;;) {
    await tick();
    if (process.argv.includes('--once')) return;
    await new Promise((resolve) => setTimeout(resolve, interval * 1000));
  }
}

async function main() {
  if (process.argv.includes('--watch')) return watch();
  if (process.argv.includes('--host-timezone-command')) {
    process.stdout.write(hostTimezoneCommand());
    return;
  }
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
  // respawn just adds seconds while the Mac is down. A fresh "online" on a
  // posix host skips it too: the backend command probes and execs in one ssh
  // session, and a host that turns out dead exits 97 into the dead-on-arrival
  // fallback below. A missing or stale file (or a Windows host) probes first.
  const macSeen = macSsh ? freshMacState(macStateFile) : null;
  const probeStampFile = selfProbeStampFile(macStateFile);
  const staleSelfProbe = Date.now() - readSelfProbeAt(probeStampFile) > SELF_PROBE_INTERVAL_MS;
  const autoStart = Boolean(macSeen && macSeen.state === 'online' && hostOs !== 'windows');
  const shouldProbe = !autoStart && (!macSeen || macSeen.state === 'online' || staleSelfProbe);
  const probeResult = macSsh && shouldProbe
    ? await probeMac(8000, macSeen && macSeen.state === 'online' ? 4 : 6)
    : { script: null, stderr: '' };
  const macScript = probeResult.script;
  if (macSsh && shouldProbe) writeSelfProbeAt(probeStampFile);
  const probeErrTail = stderrTail(probeResult.stderr);
  const macCommand = macScript
    ? hostOs === 'windows'
      ? windowsBackendCommand(macScript, botId, botName)
      : hostOs === 'linux'
        ? linuxBackendCommand(macScript, macNode, botId, botName)
        : macBackendCommand(macScript, macNode, botId, botName)
    : autoStart
      ? posixAutoBackendCommand(macNode, botId, botName)
      : null;

  // Request id -> {method, line, at}: what is in flight, so a failover knows
  // what it may replay (reads) and what it must not (actions).
  const pendingRequests = new Map();
  const annotCtx = {
    botId,
    failedOver: false,
    restoredNote: null,
    tabIdChanged: null,
    takeTabIdChanged() {
      const changed = this.tabIdChanged;
      this.tabIdChanged = null;
      return changed;
    },
    moveNotice: null,
    takeMoveNotice() {
      const notice = this.moveNotice;
      this.moveNotice = null;
      return notice;
    },
  };

  // Annotation is decoration — a failure here must never take down the
  // transport (that is how a one-line ReferenceError dropped the whole
  // browser surface). Degrade to passthrough instead.
  const safeAnnotator = (host) => {
    try {
      return makeAnnotator(host, Boolean(macSsh), macStateFile, hostName, annotCtx);
    } catch (e) {
      process.stderr.write(`workspace-router: annotator disabled: ${e.message}\n`);
      return (line) => line;
    }
  };
  let annotate = safeAnnotator(macCommand ? 'mac' : 'vps');

  // A backend that dies before answering anything is dead on arrival — for a
  // Mac spawn that means the remote script crashed (missing module, killed
  // app), and exiting here would leave the MCP client hanging on a dead
  // child until its own connect timeout. Falling back to the VPS host in
  // that window costs ~a second instead. Client lines written to the dead
  // child are buffered and replayed; nothing it could have acted on ever
  // produced a response, so no request executes twice.
  //
  // A backend that already answered and then drops (host asleep, network
  // gone, app quit, a call stuck past its deadline) fails over in-process
  // instead of waiting for Hermes to respawn the router: reads in flight are
  // replayed on the VPS backend, actions in flight are NOT (they may have
  // happened) and answer with an error naming where to continue.
  let activeChild = null;
  let activeHost = null;
  let provedAlive = false;
  let fellBack = false;
  let macRetried = false;
  let shuttingDown = false;
  let watchdog = null;
  let hostStartedAt = 0;
  let unavailableStreak = 0;
  let holdCalls = false;
  const heldCalls = [];
  const bufferedStdin = [];
  const handshake = { initialize: null, initialized: null };
  const swallowIds = new Set();
  const superseded = new Set();

  const MAC_WATCHDOG_MS = Number(process.env.HERMES_ROUTER_MAC_WATCHDOG_MS) || 8000;
  // Hermes gives a tool call 120s and browser-mcp aborts an action at 90s. A
  // call still open after the soft limit gets one liveness probe: an app that
  // answers means the call is just slow, so keep waiting and re-check; a
  // probe that fails or hangs (a half-open connection) fails over now. The
  // hard limit fails over regardless, leaving the rest of the budget for the
  // VPS to redo the work.
  const num = (name, fallback) => Number(process.env[name]) || fallback;
  const CALL_SOFT_MS = num('HERMES_ROUTER_CALL_DEADLINE_MS', 45000);
  const CALL_HARD_MS = num('HERMES_ROUTER_CALL_HARD_MS', 80000);
  const BATCH_SOFT_MS = num('HERMES_ROUTER_BATCH_DEADLINE_MS', 60000);
  const BATCH_HARD_MS = num('HERMES_ROUTER_BATCH_HARD_MS', 100000);
  const RECHECK_MS = num('HERMES_ROUTER_RECHECK_MS', 15000);
  const UNAVAILABLE_LIMIT = num('HERMES_ROUTER_UNAVAILABLE_LIMIT', 2);
  // The retried spawn rides the shared ssh connection, so a shorter second
  // window suffices. Without multiplexing (socketDir is null, e.g. a
  // Windows guest) a retry pays a cold handshake that cannot answer inside
  // it, so the watchdog fails over instead of retrying.
  const MAC_RETRY_MS = num('HERMES_ROUTER_MAC_RETRY_MS', 4000);

  // A wedged remote that never exits is the worst boot stall: without this,
  // the client waits out its full connect_timeout on dead air. Once the
  // client is actually talking to us, a silent Mac backend gets MAC_WATCHDOG_MS
  // to answer before we route around it. Healthy cold starts answer in ~2s;
  // the client sends initialize immediately after spawn. While mac-watch's
  // verdict is a fresh "online" the host provably answered seconds ago, so
  // the first silence is a slow or wedged spawn, not a dead host: retry once
  // on the warm path and fail over only when the retry stays silent too.
  function armWatchdog(ms = MAC_WATCHDOG_MS) {
    if (watchdog || provedAlive || fellBack || activeHost !== 'mac') return;
    watchdog = setTimeout(() => {
      watchdog = null;
      const mac = freshMacState(macStateFile);
      if (!macRetried && socketDir && mac && mac.state === 'online') {
        retryMacBackend();
        return;
      }
      failOver(`${hostName} backend silent ${ms}ms after initialize`);
    }, ms);
    watchdog.unref();
  }

  // The killed spawn's buffered input replays onto the new one verbatim, the
  // same replay the VPS fallback does: a remote action may theoretically have
  // run on it already, which sshd's SIGHUP on the dead session prevents.
  function retryMacBackend() {
    if (activeHost !== 'mac' || !activeChild || fellBack || shuttingDown) return;
    macRetried = true;
    const old = activeChild;
    superseded.add(old);
    try { old.kill('SIGKILL'); } catch { /* already gone */ }
    process.stderr.write(
      `workspace-router: ${hostName} backend silent ${MAC_WATCHDOG_MS}ms after initialize; mac-watch reports it online — retrying the spawn\n`,
    );
    startMacBackend();
    for (const line of bufferedStdin) writeToChild(line);
    armWatchdog(MAC_RETRY_MS);
  }

  function failOver(reason) {
    if (activeHost !== 'mac' || !activeChild || fellBack || shuttingDown) return;
    fellBack = true;
    if (watchdog) { clearTimeout(watchdog); watchdog = null; }
    process.stderr.write(`workspace-router: ${reason} — routing to VPS browser host\n`);
    const old = activeChild;
    superseded.add(old);
    try { old.kill('SIGKILL'); } catch { /* already gone */ }
    annotCtx.failedOver = true;
    if (!provedAlive) {
      startVpsBackend();
      return;
    }
    flushResumes();
    const lost = [];
    const replay = [];
    const reads = [];
    tabMerges.clear();
    for (const [id, req] of pendingRequests) {
      // A commit still awaiting approval was never sent; settleApproval
      // refuses it once it sees the host changed.
      if (req.via === 'vm' || req.awaitingApproval) continue;
      if (req.method !== 'tools/call') replay.push(req);
      else if (READ_ONLY_TOOLS.has(req.name)) reads.push(req.line);
      else lost.push({ id, at: req.at });
    }
    for (const { id } of lost) pendingRequests.delete(id);
    startVpsBackend({ replay, reads, lost });
  }

  function spawnVps(extraArgs) {
    const vpsArgs = [vpsScript, '--bot-id', botId];
    if (botName) vpsArgs.push('--bot-name', botName);
    vpsArgs.push('--connection', vpsConnection, ...extraArgs);
    const c = spawn(process.execPath, vpsArgs, { stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true });
    bindChild(c, 'vps');
    return c;
  }

  // Run browser-mcp.cjs on the user's machine over the same ssh session the
  // probe used. Factored out so the watchdog can kill a wedged spawn and
  // start another in place.
  function startMacBackend() {
    const sshArgs = [
      '-T',
      '-o',
      'BatchMode=yes',
      '-o',
      'ConnectTimeout=6',
      '-o',
      'StrictHostKeyChecking=yes',
      ...sshControlArgs,
      macSsh,
      macCommand,
    ];
    const sshChild = spawn(sshBinary, sshArgs, { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
    sshChild.stderr.on('data', (chunk) => { process.stderr.write(chunk); logMuxTrouble(chunk); });
    bindChild(sshChild, 'mac');
  }

  // A fresh backend has not seen the client's handshake. The client already
  // has its initialize answer, so the replayed one is swallowed — unless the
  // original is still unanswered, in which case this child answers it.
  function replayHandshake(c, replay) {
    if (handshake.initialize) {
      const pendingInit = replay.find((req) => req.method === 'initialize');
      if (pendingInit) {
        c.stdin.write(`${pendingInit.line}\n`);
      } else {
        try {
          const msg = JSON.parse(handshake.initialize);
          msg.id = `wsr-init-${swallowIds.size}`;
          swallowIds.add(msg.id);
          c.stdin.write(`${JSON.stringify(msg)}\n`);
        } catch { /* a handshake that will not parse cannot be replayed */ }
      }
    }
    if (handshake.initialized) c.stdin.write(`${handshake.initialized}\n`);
    for (const req of replay) if (req.method !== 'initialize') c.stdin.write(`${req.line}\n`);
  }

  // What to put on the VPS backend before the agent's first action: the
  // host's mirrored tabs when a mirror exists (cookies, scroll, drafts), else
  // the single remembered page. Slow when there are many tabs, so it runs
  // while the backend already answers initialize and tools/list, and the
  // first tools/call waits for it. A fresh VPS session (not a live failover)
  // only restores when the host was seen recently enough for a mirror to be
  // worth opening. A mirror that exists but is still restoring never falls
  // back to the single page: that would open a cookie-less duplicate.
  async function prepareContinuation(live) {
    const resumeFile = resumePath(macStateFile, botId);
    const record = readResumeRecord(resumeFile);
    const seen = (readMacState(macStateFile) || {}).lastSeenOnline;
    const recent = live || record || (seen && Date.now() - Date.parse(seen) < RESUME_MAX_AGE_MS);
    if (!recent) return { args: [] };
    const restoreMs = num('HERMES_ROUTER_RESTORE_MS', 12000);
    const restored = await restoreMirror({
      connectionFile: vpsConnection,
      botId,
      botName,
      timeoutMs: restoreMs,
      retryMs: Math.round(restoreMs * 0.8),
    });
    if (restored.status === 'restored') {
      return { ...restored, args: ['--tab-map', JSON.stringify(restored.map)] };
    }
    if (restored.status !== 'none') return { status: restored.status, args: [] };
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
    return { continued: continuedTab, args: continuedArgs(continuedTab) };
  }

  // The error an action in flight gets when the host dropped under it. Sent
  // once the restore has settled so it can name the tabs, but never later
  // than ~15s before Hermes's own 120s limit on that call.
  function sendLostCallErrors(lost, notice) {
    const mac = readMacState(macStateFile);
    for (const { id } of lost) {
      const text =
        `This action was in flight when the ${hostName} connection dropped. It may or may not have happened and was NOT retried. ` +
        `${notice} Check the page in the VPS tab before repeating it.`;
      const msg = { jsonrpc: '2.0', id, result: { isError: true, content: [{ type: 'text', text }] } };
      process.stdout.write(`${JSON.stringify(annotateResult(msg, 'vps', mac, null, undefined, annotCtx.tabIdChanged))}\n`);
    }
  }

  function beginContinuation(lost = []) {
    holdCalls = true;
    let settled = false;
    let lostSent = false;
    const answerLost = (notice) => {
      if (lostSent || !lost.length) return;
      lostSent = true;
      sendLostCallErrors(lost, notice);
    };
    const settle = (continuation) => {
      if (settled) return;
      settled = true;
      if (continuation.args.length && activeHost === 'vps' && !shuttingDown) {
        const old = activeChild;
        superseded.add(old);
        try { old.kill('SIGKILL'); } catch { /* already gone */ }
        const pending = [...pendingRequests.values()].filter((req) => req.method !== 'tools/call');
        replayHandshake(spawnVps(continuation.args), pending);
      }
      annotCtx.restoredNote = continuationDetail(continuation, hostName);
      annotCtx.tabIdChanged = tabIdChanges(
        continuation,
        (knownTabs.get(currentTabId) || {}).backend === 'computer' ? currentTabId : '',
        annotCtx.failedOver ? 'handoff' : 'host unreachable',
      );
      if (annotCtx.failedOver) {
        const notice = continuationNotice(continuation, hostName);
        if (lostSent || !lost.length) annotCtx.moveNotice = notice;
        else answerLost(notice);
      }
      holdCalls = false;
      for (const line of heldCalls.splice(0)) {
        const forwarded = routeToolCall(line);
        if (forwarded !== null) writeToChild(forwarded);
      }
    };
    if (lost.length) {
      const wait = Math.max(1000, Math.min(...lost.map((l) => l.at)) + 105000 - Date.now());
      const timer = setTimeout(() => answerLost(continuationNotice({ status: 'pending' }, hostName)), wait);
      timer.unref();
    }
    // The restore bounds itself (one retry); this caps the whole continuation
    // so a held call always leaves most of Hermes's tool budget for the call.
    const cap = setTimeout(() => settle({ status: 'pending', args: [] }), 25000);
    cap.unref();
    prepareContinuation(annotCtx.failedOver).then(
      (continuation) => { clearTimeout(cap); settle(continuation); },
      () => { clearTimeout(cap); settle({ args: [] }); },
    );
  }

  function startVpsBackend({ replay = null, reads = [], lost = [] } = {}) {
    const c = spawnVps([]);
    if (replay) replayHandshake(c, replay);
    else for (const line of bufferedStdin) c.stdin.write(`${line}\n`);
    heldCalls.push(...reads);
    if (macSsh) beginContinuation(lost);
  }

  function writeToChild(line) {
    try {
      if (activeChild && activeChild.exitCode === null && activeChild.stdin.writable) activeChild.stdin.write(`${line}\n`);
    } catch { /* a dying child's pipe is not the router's problem — the fallback replays */ }
  }

  // A second, lazily started connector to this machine's own browser host —
  // the same script and connection as the failover backend — serves explicit
  // host:"vm" work while the computer backend stays the default. VM work
  // never travels through the user's computer. Once a session has failed
  // over, the active backend already is the VM browser and no second
  // connector is spawned.
  let vmChild = null;
  const vmAnnotate = safeAnnotator('vm');
  const vmTabs = new Set();
  // cua_alans_way_tabs while both backends run is answered by each and merged
  // on the client's id: origId -> merge state, merge.vmId -> origId.
  const tabMerges = new Map();

  // A call the router answered itself (hard deadline, connector death) can
  // still have a copy running on the VM connector. Its late reply must never
  // reach the client as a second response for the same id.
  const deadIds = new Set();
  const deadOrder = [];
  function noteDead(id) {
    if (id == null || deadIds.has(id)) return;
    deadIds.add(id);
    deadOrder.push(id);
    if (deadOrder.length > 200) deadIds.delete(deadOrder.shift());
  }
  function deadReplyLine(line) {
    let id;
    if (line.length > BIG_LINE) {
      id = bigLineId(line);
    } else {
      try {
        const msg = JSON.parse(line);
        id = msg && msg.id;
      } catch {
        return false;
      }
    }
    return id !== undefined && deadIds.has(id);
  }

  function emitToolError(id, text, note = annotate) {
    const msg = { jsonrpc: '2.0', id, result: { isError: true, content: [{ type: 'text', text }] } };
    let out;
    try {
      out = note(JSON.stringify(msg));
    } catch {
      out = JSON.stringify(msg);
    }
    process.stdout.write(`${out}\n`);
  }

  // A consumed line must not also replay onto the failover backend.
  function unbuffer(line) {
    const at = bufferedStdin.lastIndexOf(line);
    if (at >= 0) bufferedStdin.splice(at, 1);
  }

  // Initialize replies the router asked a backend for itself are matched by
  // exact id, so a large response line is swallowed rather than leaked.
  function swallowLine(line) {
    if (!swallowIds.size) return false;
    let id;
    if (line.length > BIG_LINE) {
      id = bigLineId(line);
      if (id === undefined) return false;
    } else {
      try {
        id = JSON.parse(line).id;
      } catch {
        return false;
      }
    }
    return swallowIds.has(id);
  }

  function vmAlive() {
    return Boolean(vmChild && vmChild.exitCode === null);
  }

  // A tab a backend closed on its own (the VM reaper reports them under
  // closedTabs on open replies) is forgotten everywhere, so a defaulted call
  // never injects a dead tab and an id is never routed to a tab that is gone.
  function forgetTab(id) {
    if (typeof id !== 'string') return;
    knownTabs.delete(id);
    vmTabs.delete(id);
    tabPages.delete(id);
    if (currentTabId === id) currentTabId = '';
  }

  function forgetClosedTabs(data) {
    if (!data || !Array.isArray(data.closedTabs)) return;
    for (const tab of data.closedTabs) {
      forgetTab(typeof tab === 'string' ? tab : tab && (tab.tabId || tab.id));
    }
  }

  // A tab id the VM browser is known to own: learned from the VM connector's
  // open results and from tab-list entries that carry a VM host.
  function learnVmTabData(data, assumeVm) {
    if (!data || typeof data !== 'object') return;
    const listed = Array.isArray(data.tabs) ? data.tabs : data.id !== undefined ? [data] : [];
    for (const tab of listed) {
      if (!tab || typeof tab.id !== 'string' || !/^[\w-]{1,100}$/.test(tab.id)) continue;
      if (assumeVm || normalizeHost(tab.host) === 'vm') vmTabs.add(tab.id);
    }
    forgetClosedTabs(data);
  }

  function learnVmTabs(line, assumeVm) {
    if (line.length > BIG_LINE) return;
    // Keys inside a text part arrive escaped (\"host\"), so match bare words.
    if (!line.includes('tabs') && !line.includes('host')) return;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return;
    }
    const parts = msg && msg.result && msg.result.content;
    if (!Array.isArray(parts)) return;
    for (const part of parts) {
      if (!part || part.type !== 'text' || typeof part.text !== 'string' || !part.text.includes('"id"')) continue;
      try {
        learnVmTabData(JSON.parse(part.text), assumeVm);
      } catch { /* a result that is not JSON teaches nothing */ }
    }
  }

  function textResultData(msg) {
    const parts = msg && msg.result && msg.result.content;
    const part = Array.isArray(parts) && parts.find((p) => p && p.type === 'text');
    try {
      return part ? JSON.parse(part.text) : null;
    } catch {
      return null;
    }
  }

  // The tab the agent last worked in, and the newest epoch each backend
  // itself returned for every tab it has named. Action and snapshot calls
  // that leave out tabId or epoch get these values injected, which is what
  // lets the advertised schema mark them optional. An epoch is never
  // invented or bumped: a stale one still fails at the backend after a human
  // takeover instead of being silently repaired.
  const knownTabs = new Map(); // tabId -> { backend: 'computer'|'vm', epoch?: number }
  let currentTabId = '';
  const CURRENT_TAB_TOOLS = new Set([
    'cua_alans_way_open',
    'cua_alans_way_snapshot',
    'cua_alans_way_action',
  ]);
  const TAB_DEFAULTED_TOOLS = new Set(['cua_alans_way_action', 'cua_alans_way_snapshot']);
  const TAB_ID = /^[\w-]{1,100}$/;

  // Per tab, the names behind the element refs replies have shown, the
  // page's origin, and the commit-looking controls the current page shows:
  // what the commit gate matches a click against and shows the user. A ref
  // (e12) names one control for its document's life and keeps it when the
  // control is renamed, so a later name replaces an earlier one. Everything
  // resets when the page URL changes: a ref the router has not seen on this
  // page is refused, a key or a click by position on a page that shows a
  // commit control may set it off, and one whose controls the router has not
  // seen in full may hide one.
  // A snapshot lists the page's frames: one from another site is unreadable,
  // so input that may land in it cannot be judged (`frame`, unknown until a
  // snapshot). `visited` is the last address the tab loaded that reads like an
  // action, which back or forward may load again.
  const tabPages = new Map(); // tabId -> { names: Map(ref -> name), origin, url, live: Set(name), full, frame, visited }
  // Action replies carry only the first 40 controls (the app's own cap, with
  // unlisted counting the rest), or with generation only what changed; a
  // snapshot says whether its list was cut.
  const ACTION_ELEMENT_CAP = 40;
  function learnTabPage(tabId, data, acted = []) {
    if (typeof tabId !== 'string' || !data || typeof data !== 'object') return;
    let page = tabPages.get(tabId);
    if (!page) {
      page = { names: new Map(), hrefs: new Map(), origin: '', url: '', live: new Set(), full: false };
      tabPages.set(tabId, page);
    }
    const url = data.url || (data.effect && data.effect.url) || (data.tab && data.tab.url);
    try {
      if (typeof url === 'string' && url) {
        const parsed = new URL(url);
        page.origin = parsed.origin;
        parsed.hash = '';
        if (parsed.href !== page.url) {
          page.url = parsed.href;
          page.names = new Map();
          page.hrefs = new Map();
          page.live = new Set();
          page.full = false;
          page.frame = undefined;
          if (isActionUrl(page.url)) page.visited = page.url;
        }
      }
    } catch { /* keep the last page a reply named */ }
    if (Array.isArray(data.elements)) {
      page.full = data.truncated && typeof data.truncated === 'object'
        ? !data.truncated.elements
        : data.elements.length < ACTION_ELEMENT_CAP;
    } else if (Array.isArray(data.changed) || Array.isArray(data.removed)) {
      page.full = false;
    }
    if (data.truncated && typeof data.truncated === 'object') {
      const frames = Array.isArray(data.iframes) ? data.iframes : [];
      const foreign = frames.map((f) => {
        try {
          return new URL(f.src).origin;
        } catch {
          return 'an unknown site';
        }
      }).find((origin) => origin !== page.origin);
      // The app lists at most 8 frames.
      page.frame = foreign || (frames.length >= 8 ? 'more frames than it lists' : '');
    }
    const overlays = Array.isArray(data.overlays)
      ? data.overlays.map((o) => o && { ref: o.close, name: o.closeName }) : [];
    const lists = [data.elements, data.changed, overlays,
      ...(Array.isArray(data.results) ? data.results.map((r) => r && r.elements) : [])];
    for (const list of lists) {
      if (!Array.isArray(list)) continue;
      for (const el of list) {
        if (!el || typeof el.ref !== 'string') continue;
        const name = typeof el.name === 'string' ? el.name : '';
        page.names.set(el.ref, name);
        if (typeof el.href === 'string' && el.href) page.hrefs.set(el.ref, el.href);
        else page.hrefs.delete(el.ref);
        if (name && isCommitName(name)) page.live.add(cardText(name, 80));
      }
    }
    // A control the call acted on may have been renamed by it. A delta or an
    // unchanged reply would say so; a list that leaves it out does not, so
    // its old name is dropped and the next use needs a fresh one.
    if (Array.isArray(data.elements)) {
      const listed = new Set(data.elements.map((el) => el && el.ref));
      for (const ref of acted) {
        if (listed.has(ref)) continue;
        page.names.delete(ref);
        page.hrefs.delete(ref);
      }
    }
    for (const ref of page.names.keys()) {
      if (page.names.size <= 2000) break;
      page.names.delete(ref);
      page.hrefs.delete(ref);
    }
  }

  // A full tab description (it names its controller) also says who controls
  // the tab and whether it waits for the human (handback); a reply that only
  // names the tab keeps what the last description said. A new control epoch
  // means someone else had the tab, so what the gate knew of its page is
  // dropped.
  function noteKnownTab(id, epoch, backend, info) {
    if (typeof id !== 'string' || !TAB_ID.test(id)) return;
    if (backend === 'vm') vmTabs.add(id);
    const prev = knownTabs.get(id) || {};
    const described = info && typeof info === 'object' && typeof info.controller === 'string';
    const next = Number.isInteger(epoch) ? epoch : prev.epoch;
    if (Number.isInteger(prev.epoch) && next !== prev.epoch) tabPages.delete(id);
    knownTabs.set(id, {
      backend,
      epoch: next,
      controller: described ? info.controller : prev.controller,
      handback: described ? info.handback || null : prev.handback,
    });
  }

  // Every reply shape that names a tab: open and claim answers carry it at
  // top level, snapshot/action answers under `tab`, a tabs list has an entry
  // per tab, and a call retargeted onto a VPS tab names it in continuedTab.
  function learnTabData(data, backend) {
    if (!data || typeof data !== 'object') return;
    if (Array.isArray(data.tabs)) {
      for (const tab of data.tabs) {
        if (tab && typeof tab === 'object') noteKnownTab(tab.id, tab.epoch, normalizeHost(tab.host) || backend, tab);
      }
    }
    if (data.tab && typeof data.tab === 'object') {
      noteKnownTab(data.tab.id, data.tab.epoch, normalizeHost(data.tab.host) || backend, data.tab);
    }
    noteKnownTab(data.id, data.epoch, normalizeHost(data.host) || backend, data);
    if (typeof data.continuedTab === 'string') noteKnownTab(data.continuedTab, data.continuedEpoch, 'vm');
    forgetClosedTabs(data);
  }

  // The pending request a reply line answers, without consuming it — big
  // replies get their id from the fast scanner, like noteServerRpc.
  function pendingRequestFor(line) {
    if (line.length > BIG_LINE) {
      const id = bigLineId(line);
      return id === undefined ? undefined : pendingRequests.get(id);
    }
    try {
      return pendingRequests.get(JSON.parse(line).id);
    } catch {
      return undefined;
    }
  }

  // The refs an action call aimed at.
  function actedRefs(req) {
    if (req.name !== 'cua_alans_way_action') return [];
    try {
      const args = JSON.parse(req.line).params.arguments || {};
      const steps = args.action === 'batch' && Array.isArray(args.steps) ? args.steps : [args];
      return steps.flatMap((step) => (step ? [step.ref, step.toRef] : [])).filter((ref) => typeof ref === 'string');
    } catch {
      return [];
    }
  }

  function argsTabId(req) {
    try {
      return (JSON.parse(req.line).params.arguments || {}).tabId;
    } catch {
      return undefined;
    }
  }

  // A successful open, snapshot or action makes its tab the current one; the
  // reply's own id wins, then a retargeted continued tab, then the id the
  // call named. A successful close forgets its tab entirely.
  function learnTabUse(line, req, backend) {
    if (!req || req.method !== 'tools/call') return;
    if (line.length > BIG_LINE) {
      // Too big to read: whatever page it shows, the gate has not seen it.
      const page = TAB_DEFAULTED_TOOLS.has(req.name) && tabPages.get(argsTabId(req));
      if (page) {
        page.full = false;
        for (const ref of actedRefs(req)) page.names.delete(ref);
      }
      return;
    }
    let data;
    try {
      const msg = JSON.parse(line);
      if (!msg || msg.id == null || !msg.result || msg.result.isError) return;
      data = textResultData(msg);
    } catch {
      return;
    }
    learnTabData(data, backend);
    if (req.name === 'cua_alans_way_close' && data && data.closed) {
      forgetTab(argsTabId(req));
      return;
    }
    if (!CURRENT_TAB_TOOLS.has(req.name)) return;
    const used = (data && data.tab && data.tab.id) || (data && data.id) || (data && data.continuedTab) || argsTabId(req);
    if (typeof used === 'string' && TAB_ID.test(used)) {
      noteKnownTab(used, undefined, backend);
      learnTabPage(used, data, actedRefs(req));
      currentTabId = used;
    }
  }

  // Fill in what the agent may omit: the current tab (which routes the call
  // to whichever backend owns it) and that tab's latest backend-reported
  // epoch. Supplied values are never overwritten; with no known tab the call
  // passes through unchanged so the backend answers its own error.
  function injectTabDefaults(msg) {
    const params = msg && msg.params;
    if (!params || !TAB_DEFAULTED_TOOLS.has(params.name)) return false;
    if (params.arguments === undefined) params.arguments = {};
    const args = params.arguments;
    if (typeof args !== 'object' || args === null) return false;
    let changed = false;
    if (typeof args.tabId !== 'string' || !args.tabId) {
      if (!currentTabId) return false;
      args.tabId = currentTabId;
      changed = true;
    }
    if (args.epoch === undefined) {
      const known = knownTabs.get(args.tabId);
      if (known && Number.isInteger(known.epoch)) {
        args.epoch = known.epoch;
        changed = true;
      }
    }
    return changed;
  }

  // The merged tabs answer keeps the computer's result shape and marks each
  // tab's host. A VM half that never arrived (or errored) simply contributes
  // no tabs.
  function mergedTabsResult(origId, merge) {
    const macData = textResultData(merge.mac);
    const vmData = textResultData(merge.vm);
    learnVmTabData(macData, false);
    learnVmTabData(vmData, true);
    learnTabData(macData, 'computer');
    learnTabData(vmData, 'vm');
    if (!merge.mac || !merge.mac.result || merge.mac.result.isError || !Array.isArray((macData || {}).tabs)) {
      return merge.mac;
    }
    // The computer app already lists the VM tabs it proxies (a VM host on the
    // entry); the VM backend's own record wins and the tab lists once as "vm".
    const vmList = vmData && Array.isArray(vmData.tabs) ? vmData.tabs : [];
    const vmIds = new Set(vmList.map((tab) => tab && tab.id).filter((id) => typeof id === 'string'));
    const seen = new Set();
    const tabs = [];
    const push = (tab, host) => {
      if (!tab || typeof tab !== 'object') {
        tabs.push(tab);
        return;
      }
      if (typeof tab.id === 'string') {
        if (seen.has(tab.id)) return;
        seen.add(tab.id);
      }
      tabs.push({ ...tab, host });
    };
    for (const tab of macData.tabs) {
      const proxied = tab && typeof tab === 'object' && normalizeHost(tab.host) === 'vm';
      if (proxied && vmIds.has(tab.id)) continue;
      push(tab, proxied ? 'vm' : 'computer');
    }
    for (const tab of vmList) push(tab, 'vm');
    return {
      jsonrpc: '2.0',
      id: origId,
      result: { ...merge.mac.result, content: [{ type: 'text', text: JSON.stringify({ ...macData, tabs }) }] },
    };
  }

  function emitTabsMerge(origId, merge) {
    tabMerges.delete(origId);
    tabMerges.delete(merge.vmId);
    const merged = mergedTabsResult(origId, merge);
    let out;
    try {
      out = annotate(JSON.stringify(merged), merge.ms);
    } catch {
      out = JSON.stringify(merged);
    }
    process.stdout.write(`${out}\n`);
  }

  // Both halves of a merged tabs call are held until the other backend
  // answers. The internal reply is matched by its exact id, so a VM tab list
  // of any size reaches the merge and its wsr-tabs id never reaches the client.
  function mergeVmLine(line) {
    let id;
    let msg = null;
    if (line.length > BIG_LINE) {
      id = bigLineId(line);
      if (typeof id !== 'string') return false;
    } else {
      try {
        msg = JSON.parse(line);
      } catch {
        return false;
      }
      id = msg && msg.id;
      if (typeof id !== 'string') return false;
    }
    if (!id.startsWith('wsr-tabs-')) return false;
    const origId = tabMerges.get(id);
    const merge = tabMerges.get(origId);
    // Cleared by a failover mid-merge: the replayed call answers on its own.
    if (!merge || typeof merge !== 'object') return true;
    if (!msg) {
      try {
        msg = JSON.parse(line);
      } catch {
        msg = {};
      }
    }
    merge.vm = msg;
    if (merge.mac) emitTabsMerge(origId, merge);
    return true;
  }

  function mergeMacLine(line, callMs) {
    if (!tabMerges.size) return false;
    let id;
    let msg = null;
    if (line.length > BIG_LINE) {
      id = bigLineId(line);
      if (id === undefined || !tabMerges.has(id)) return false;
    } else {
      try {
        msg = JSON.parse(line);
      } catch {
        return false;
      }
      id = msg && msg.id;
    }
    const merge = id != null && tabMerges.get(id);
    if (!merge || typeof merge !== 'object') return false;
    if (!msg) {
      try {
        msg = JSON.parse(line);
      } catch {
        msg = {};
      }
    }
    merge.mac = msg;
    merge.ms = callMs;
    if (merge.vm) emitTabsMerge(id, merge);
    return true;
  }

  // Same spawn as the failover backend; the replayed handshake's initialize
  // response is swallowed so the client never sees a second answer.
  function spawnVmBackend() {
    const args = [vpsScript, '--bot-id', botId];
    if (botName) args.push('--bot-name', botName);
    args.push('--connection', vpsConnection);
    const c = spawn(process.execPath, args, { stdio: ['pipe', 'pipe', 'inherit'], windowsHide: true });
    vmChild = c;
    c.stdin.on('error', () => {});
    readline
      .createInterface({ input: c.stdout, crlfDelay: Infinity })
      .on('line', (line) => {
        if (c !== vmChild) return;
        touchActivity();
        if (swallowLine(line)) return;
        if (deadReplyLine(line)) return;
        const seenReq = pendingRequestFor(line);
        const callMs = noteServerRpc(line, pendingRequests);
        if (mergeVmLine(line)) return;
        learnVmTabs(line, true);
        learnTabUse(line, seenReq, 'vm');
        let out;
        try {
          out = vmAnnotate(line, callMs);
        } catch {
          out = line;
        }
        if (out === null) return;
        process.stdout.write(`${out}\n`);
      });
    const drop = () => {
      if (c !== vmChild) return;
      vmChild = null;
      for (const [id, merge] of [...tabMerges]) {
        if (typeof merge !== 'object' || merge.vm) continue;
        merge.vm = {};
        if (merge.mac) emitTabsMerge(id, merge);
      }
      for (const [id, req] of pendingRequests) {
        if (req.via !== 'vm') continue;
        pendingRequests.delete(id);
        noteDead(id);
        emitToolError(id, req.committed
          ? `The VM browser connector stopped. ${COMMIT_LOST}`
          : 'The VM browser connector stopped. Retry the call.');
      }
    };
    c.on('error', drop);
    c.on('exit', drop);
    replayHandshake(c, []);
    process.stderr.write('workspace-router: started the VM browser connector\n');
  }

  // Hermes bounds the whole tool call (setup writes timeout: 120), and the
  // approval wait is inside it, so the window closes early enough to leave
  // the action its time. A tap after that changes nothing.
  const APPROVAL_MS = num('HERMES_ROUTER_APPROVAL_MS', 60000);
  const decisionLog = path.join(path.dirname(macStateFile), 'commit-decisions.jsonl');
  const approvals = new Map(); // elicitation id -> { callId, line, child, record, timer }
  let approvalSeq = 0;

  function logDecision(record, decision) {
    try {
      fs.mkdirSync(path.dirname(decisionLog), { recursive: true });
      fs.appendFileSync(decisionLog, `${JSON.stringify({ ts: new Date().toISOString(), bot: botId, ...record, decision })}\n`, { mode: 0o600 });
    } catch (e) {
      process.stderr.write(`workspace-router: could not log a commit decision: ${e.message}\n`);
    }
  }

  // Form-mode elicitation: `elicitation: {}` (form implied) or one naming form.
  function clientElicits() {
    try {
      const caps = JSON.parse(handshake.initialize).params.capabilities;
      const e = caps && caps.elicitation;
      return Boolean(e && typeof e === 'object' && (Object.keys(e).length === 0 || e.form));
    } catch {
      return false;
    }
  }

  // What this call (or any batch step) does, read four ways: `acts`
  // describes each step for the approval card, `commits` says why one looks
  // like a commit, `unseen` names a ref the router has not seen on this page,
  // and `unread` says why the router cannot judge a step and what to do. A
  // control is judged by its name (its ref's, the name it is targeted by, or
  // its selector's words). Input that cannot be judged that way (a key other
  // than a plain move or character, a click by position, on an unnamed
  // control or on a selector that names no commit, page script, a DevTools
  // call that can act, accepting a page dialog) counts as a commit on a page
  // that shows a commit control, and is refused on one the router has not
  // seen in full or that an earlier batch step may have left. Every step runs
  // on the batch's own tab, whatever tabId a step names, so that is the page
  // each is judged against. A reload on a commit page may resubmit it, and a
  // same-site address that reads like an action may commit by loading.
  const keyLabel = (key) => (key === ' ' ? 'Space' : /^[\r\n]+$/.test(key) ? 'Enter' : cardText(key, 10) || 'a control key');
  function clickTargets(args) {
    const found = { acts: [], commits: [], unseen: null, unread: null, banned: null };
    const page = tabPages.get(args.tabId);
    const live = page && page.live.size ? [...page.live][0] : '';
    const steps = args.action === 'batch' ? (Array.isArray(args.steps) ? args.steps : []) : [args];
    let moved = false;
    let typed = false;
    // Untargeted input (a key with no control named, a point) may land in a
    // frame from another site; input aimed at a control lands on that control.
    const blind = (what, untargeted = false) => {
      if (live) {
        found.commits.push(`${what} here could set off "${live}"`);
      } else if (moved) {
        found.unread = found.unread || `an earlier step in this batch can change the page, so this connector cannot tell what ${what} would do. Send the steps from there as a separate call once you have seen the page`;
      } else if (untargeted && page && page.frame) {
        found.unread = found.unread || `this page embeds ${page.frame} in a frame this connector cannot read, so it cannot tell what ${what} would do. Act on the page's own controls by ref or name instead`;
      } else if (!page || !page.full || (untargeted && page.frame === undefined)) {
        found.unread = found.unread || `this connector has not seen all of this page's controls, so it cannot tell what ${what} would do. Take a snapshot (raise maxElements if it is cut off) and try again`;
      }
    };
    // A link whose address reads like an action commits when followed.
    const actionHref = (ref) => {
      const href = page.hrefs.get(ref);
      if (href && isActionUrl(href)) found.commits.push(`the link goes to ${cardText(href, 80)}, an address that confirms, orders, pays, submits or deletes`);
    };
    const accepts = (step) => step.dialog && typeof step.dialog === 'object' && step.dialog.accept === true;
    if (args.action === 'batch' && accepts(args)) {
      found.acts.push('accepts page dialogs');
      blind('accepting a page dialog');
    }
    for (const step of steps) {
      if (!step || typeof step !== 'object') continue;
      if (accepts(step)) {
        found.acts.push('accepts a page dialog');
        blind('accepting a page dialog');
      }
      const safeKey = step.action === 'press' && isSafeKey(step);
      if (step.action === 'press' && typeof step.key === 'string' && !safeKey) {
        const key = keyLabel(step.key);
        found.acts.push(`presses ${key}`);
        // Typing then Enter in one call sends what was typed (a chat message)
        // before the page can be read; on its own the key is judged by the page.
        if (typed && key !== 'Space') found.commits.push(`pressing ${key} right after typing in the same batch could send what was typed. Press it as its own call, or pass commit`);
        const aimed = [step.ref, step.name, step.selector].some((t) => typeof t === 'string' && t);
        blind(`pressing ${key}`, !aimed);
      }
      if (step.action === 'type') typed = true;
      const cdpUrl = step.action === 'cdp' && step.method === 'Page.navigate' && step.params && step.params.url;
      const url = step.action === 'navigate' ? step.url : cdpUrl;
      if (typeof url === 'string' && isActionUrl(url)) {
        found.acts.push(`opens ${cardText(url, 80)}`);
        found.commits.push(`${cardText(url, 80)} looks like an address that confirms, orders, pays, submits or deletes`);
      }
      if ((step.action === 'back' || step.action === 'forward') && page && page.visited) {
        found.acts.push(`goes ${step.action}`);
        found.commits.push(`going ${step.action} may load ${cardText(page.visited, 80)} again`);
      }
      if (step.action === 'cdp' && BANNED_CDP.test(String(step.method))) {
        found.banned = `${step.method} would run a script on every later page in this tab, out of the commit gate's sight`;
      }
      if (step.action === 'reload' || (step.action === 'cdp' && step.method === 'Page.reload')) {
        found.acts.push('reloads the page');
        if (live) found.commits.push(`reloading here could resubmit "${live}"`);
      }
      if (step.action === 'eval') {
        found.acts.push('runs a page script');
        blind('a page script');
      } else if (step.action === 'cdp' && !READ_ONLY_CDP.test(String(step.method))) {
        const method = cardText(String(step.method), 60);
        found.acts.push(`sends ${method}`);
        blind(`the DevTools call ${method}`, /^Input\./.test(method));
      }
      // A click, or a key that acts, follows a link.
      const follows = step.action === 'click' || step.action === 'double_click' || (step.action === 'press' && !safeKey);
      const target = TARGET_STEPS[step.action];
      const ends = !target ? [] : step.action === 'drag'
        ? [step, { ref: step.toRef, selector: step.toSelector, x: step.toX, y: step.toY }] : [step];
      for (const end of ends) {
        const [act, noun] = end === step ? target : ['drops on', 'a drop'];
        if (typeof end.ref === 'string') {
          const name = page ? page.names.get(end.ref) : undefined;
          if (name === undefined) {
            found.unseen = found.unseen || `ref ${cardText(end.ref, 20)} is not from this page as this connector has seen it`;
          } else if (!name) {
            found.acts.push(`${act} an unnamed control`);
            if (step.action !== 'press') blind(`${noun} on an unnamed control`);
          } else {
            found.acts.push(`${act} "${cardText(name, 80)}"`);
            if (isCommitName(name)) found.commits.push(`"${cardText(name, 80)}" looks like it buys, books, sends, posts, submits or deletes`);
            else if (follows) actionHref(end.ref);
          }
        } else if (typeof end.name === 'string' && end.name) {
          // The app acts only on a control with exactly this name.
          const name = cardText(end.name, 80);
          found.acts.push(`${act} "${name}"`);
          if (isCommitName(end.name)) found.commits.push(`"${name}" looks like it buys, books, sends, posts, submits or deletes`);
          else if (page && follows) {
            const wanted = end.name.trim().toLowerCase();
            for (const [ref, known] of page.names) if (known.trim().toLowerCase() === wanted) actionHref(ref);
          }
        } else if (typeof end.selector === 'string' && end.selector) {
          const selector = cardText(end.selector, 80);
          found.acts.push(`${act} ${selector}`);
          if (isCommitName(selectorWords(end.selector))) found.commits.push(`${selector} looks like it buys, books, sends, posts, submits or deletes`);
          else if (step.action !== 'press') blind(`${noun} on ${selector}`);
        } else if (step.action !== 'press' && (typeof end.x === 'number' || typeof end.y === 'number')) {
          found.acts.push(`${act} at ${end.x},${end.y}`);
          blind(`${noun} by position`, true);
        }
      }
      const readOnly = step.action === 'cdp' && READ_ONLY_CDP.test(String(step.method)) && !url && step.method !== 'Page.reload';
      if (!PAGE_STAYS.has(step.action) && !safeKey && !readOnly) moved = true;
    }
    return found;
  }

  const APPROVAL_REFUSALS = {
    declined: 'declined: the user did not approve this, or no one could be asked (in a scheduled job Hermes declines on its own). It did not run. Do not retry it or reach the same result another way. Leave everything staged up to this step and tell the user it is waiting for them.',
    approval_timeout: 'approval_timeout: the user did not answer in time. It did not run. Ask the user in chat before trying again.',
    approval_unavailable: 'approval_unavailable: this session cannot ask the user to approve (for example a scheduled job). It did not run. Leave everything staged up to this step and ask the user to finish it.',
    host_changed: 'host_changed: the browser moved to another machine while the approval was pending. It did not run. Check the page, then ask again.',
    page_changed: 'page_changed: the tab left the approved page, or someone else took control of it, while the approval was pending. It did not run. Check the page, then ask again.',
  };

  // Returns true when the call was refused or is now awaiting approval.
  function gateCommit(msg, line) {
    const args = msg.params.arguments;
    // Opening a tab is judged as navigating to its address.
    const targets = msg.params.name === 'cua_alans_way_open'
      ? clickTargets({ action: 'navigate', url: args.url })
      : clickTargets(args);
    if (args.commit === undefined && !targets.commits.length && !targets.unseen && !targets.unread && !targets.banned) return false;
    unbuffer(line);
    const page = tabPages.get(args.tabId);
    const origin = page ? page.origin : '';
    const refuse = (text) => {
      pendingRequests.delete(msg.id);
      emitToolError(msg.id, text);
      return true;
    };
    // The browser would refuse a tab the human holds or a stale epoch anyway;
    // say so in its words instead of asking the user to approve a call that
    // cannot run, or hiding the handback behind commit_required.
    const known = msg.params.name === 'cua_alans_way_action' ? knownTabs.get(args.tabId) : undefined;
    if (known) {
      const h = known.handback;
      if (h && h.state === 'awaiting_human') {
        return refuse(`awaiting_human: this tab was handed to the human (${cardText(h.reason, 20) || 'other'}). It did not run. Wait until they give it back; read the tab state later.`);
      }
      if (known.controller && known.controller !== 'agent') return refuse('human_has_control: the human has this tab. It did not run.');
      if (Number.isInteger(args.epoch) && Number.isInteger(known.epoch) && args.epoch !== known.epoch) {
        return refuse(h && h.state === 'human_returned'
          ? 'human_returned: the human finished and gave this tab back. It did not run. Read the tab state for its fresh epoch and current page.'
          : 'stale_control_epoch: it did not run. Read the tab state and retry after a fresh snapshot.');
      }
    }
    if (targets.banned) {
      return refuse(`not_allowed: ${targets.banned}. It did not run, and agents cannot run it.`);
    }
    if (targets.unseen) {
      return refuse(`snapshot_required: ${targets.unseen}. It did not run. Take a snapshot and use its refs, or target the control by name.`);
    }
    if (args.commit === undefined && !targets.commits.length) {
      return refuse(`snapshot_required: ${targets.unread}, or pass commit so the user can approve it. It did not run.`);
    }
    if (args.commit === undefined) {
      logDecision({ origin, target: targets.commits[0] }, 'commit_required');
      return refuse(`commit_required: ${targets.commits[0]}. It did not run. Repeat the call with commit: {kind, summary, amount?, currency?, counterparty?} so the user can approve it.`);
    }
    const commit = cleanCommit(args.commit);
    if (!commit) {
      logDecision({ origin }, 'commit_invalid');
      return refuse(`commit_invalid: commit needs kind (${Object.keys(COMMIT_VERBS).join(', ')}) and a summary of 1-200 characters. It did not run.`);
    }
    const record = { origin, ...commit };
    if (!clientElicits()) {
      logDecision(record, 'approval_unavailable');
      return refuse(APPROVAL_REFUSALS.approval_unavailable);
    }
    const req = pendingRequests.get(msg.id);
    // The window runs from when the call arrived, so time it spent held
    // during a failover comes out of the user's share, not the action's.
    const windowMs = APPROVAL_MS - (req ? Date.now() - req.at : 0);
    if (windowMs <= 0) {
      logDecision(record, 'approval_timeout');
      return refuse(APPROVAL_REFUSALS.approval_timeout);
    }
    delete args.commit;
    const forward = JSON.stringify(msg);
    if (req) {
      req.line = forward;
      req.awaitingApproval = true;
    }
    const price = [commit.amount, commit.currency].filter(Boolean).join(' ');
    const what = [commit.summary, price, commit.counterparty].filter(Boolean).join(' · ');
    // The origin and the clicked controls are the router's own reading of
    // the page; everything before them is the agent's description.
    const acts = targets.acts.length ? ` (${targets.acts.join('; ')})` : '';
    const message = `${botName || botId} wants to ${COMMIT_VERBS[commit.kind]}: ${what}${origin ? ` on ${origin}` : ''}${acts}`;
    const id = `wsr-commit-${++approvalSeq}`;
    const timer = setTimeout(() => settleApproval(id, 'approval_timeout'), windowMs);
    timer.unref();
    // The page and control epoch the user approved; the receipt the app
    // checks is bound to the same tab and epoch.
    const bound = msg.params.name === 'cua_alans_way_action' ? { tabId: args.tabId, epoch: args.epoch, origin } : null;
    approvals.set(id, { callId: msg.id, line: forward, child: activeChild, record, timer, bound, commit });
    process.stdout.write(`${JSON.stringify({
      jsonrpc: '2.0',
      id,
      method: 'elicitation/create',
      params: {
        message,
        requestedSchema: {
          type: 'object',
          properties: {
            approve: {
              type: 'boolean',
              title: 'Approve',
              description: targets.acts.length ? `Approve: ${targets.acts.join('; ')}` : 'Approve this action',
            },
          },
          required: ['approve'],
        },
      },
    })}\n`);
    return true;
  }

  // Exactly one outcome per approval: the user's answer, the window closing,
  // or the client cancelling the call. An approved commit runs once, on the
  // backend it was asked about; nothing here ever retries it.
  function settleApproval(id, decision) {
    const entry = approvals.get(id);
    if (!entry) return;
    approvals.delete(id);
    clearTimeout(entry.timer);
    if (decision === 'approved' && entry.child !== activeChild) decision = 'host_changed';
    if (decision === 'approved' && entry.bound) {
      const known = knownTabs.get(entry.bound.tabId);
      const page = tabPages.get(entry.bound.tabId);
      if ((known && Number.isInteger(known.epoch) && known.epoch !== entry.bound.epoch)
        || (page && page.origin && entry.bound.origin && page.origin !== entry.bound.origin)) decision = 'page_changed';
    }
    logDecision(entry.record, decision);
    if (decision === 'approval_timeout' || decision === 'cancelled') {
      process.stdout.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/cancelled', params: { requestId: id, reason: decision } })}\n`);
    }
    const req = pendingRequests.get(entry.callId);
    if (decision === 'cancelled') {
      pendingRequests.delete(entry.callId);
      return;
    }
    if (decision !== 'approved') {
      pendingRequests.delete(entry.callId);
      emitToolError(entry.callId, APPROVAL_REFUSALS[decision]);
      return;
    }
    if (!req) return;
    delete req.awaitingApproval;
    req.committed = true;
    req.at = Date.now();
    let line = entry.line;
    if (entry.bound) {
      // The app runs a commit only with this receipt: one nonce, for this
      // forward alone, bound to the approved tab and epoch.
      const msg = JSON.parse(line);
      msg.params.arguments.approval = {
        nonce: crypto.randomUUID(),
        kind: entry.commit.kind,
        summary: entry.commit.summary,
        issuedAt: Date.now(),
        tabId: entry.bound.tabId,
        epoch: entry.bound.epoch,
      };
      line = JSON.stringify(msg);
    }
    const out = routeToolCall(line, true);
    if (out !== null) writeToChild(out);
  }

  // The client's answer to an elicitation, consumed here even when it comes
  // too late to count; false for any other line.
  function answerApproval(line) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return false;
    }
    if (!msg || msg.method !== undefined || typeof msg.id !== 'string' || !msg.id.startsWith('wsr-commit-')) return false;
    const r = msg.result;
    // Hermes accepts with empty content; only an explicit approve:false says no.
    const approved = r && r.action === 'accept' && !(r.content && r.content.approve === false);
    settleApproval(msg.id, msg.error || !r ? 'approval_unavailable' : approved ? 'approved' : 'declined');
    return true;
  }

  // A cancelled call never runs: withdraw its approval, or drop it from the
  // calls held during a failover before it ever reaches the gate.
  function cancelCall(callId) {
    for (const [id, entry] of approvals) {
      if (entry.callId === callId) settleApproval(id, 'cancelled');
    }
    const req = pendingRequests.get(callId);
    const held = req ? heldCalls.indexOf(req.line) : -1;
    if (held >= 0) {
      heldCalls.splice(held, 1);
      pendingRequests.delete(callId);
    }
  }

  // A tools/call the router answers or diverts itself. host:"computer" while
  // the session already runs on the VM is a clear error; host:"vm" and calls
  // aimed at a known VM tab go to the VM connector; a tabs call while it runs
  // merges both lists. Anything else falls through to the active backend.
  // Returns the line to forward (rewritten when defaults were injected) or
  // null when the call was answered or sent on internally. `approved` is the
  // commit gate's own second pass for a call the user just approved.
  // Only the router's own approved forward may carry an approval receipt,
  // so one the agent sends is dropped, top level and in every step, before
  // the call is buffered, held or routed (a failover replays buffered lines).
  function withoutApproval(line) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return line;
    }
    const args = msg && msg.params && msg.params.arguments;
    if (!args || typeof args !== 'object') return line;
    let found = false;
    for (const target of [args, ...(Array.isArray(args.steps) ? args.steps : [])]) {
      if (target && typeof target === 'object' && 'approval' in target) {
        delete target.approval;
        found = true;
      }
    }
    return found ? JSON.stringify(msg) : line;
  }

  function routeToolCall(line, approved = false) {
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return line;
    }
    const rawArgs = msg && msg.params && msg.params.arguments;
    if (rawArgs !== undefined && (typeof rawArgs !== 'object' || rawArgs === null)) return line;
    const out = injectTabDefaults(msg) ? JSON.stringify(msg) : line;
    if (out !== line) {
      const req = pendingRequests.get(msg.id);
      if (req) req.line = out;
    }
    if (!desktopActionsAllowed && msg.params && msg.params.name === DESKTOP_INPUT_TOOL) {
      pendingRequests.delete(msg.id);
      unbuffer(line);
      emitToolError(
        msg.id,
        'workspace_computer_action is not exposed by this server. Desktop input goes through the approval-gated computer_use tool.',
      );
      return null;
    }
    const args = (msg.params && msg.params.arguments) || {};
    const host = normalizeHost(args.host);
    if (host === undefined && typeof args.host === 'string' && args.host.trim()) {
      pendingRequests.delete(msg.id);
      unbuffer(line);
      emitToolError(msg.id, 'Use host "computer" or "vm", or omit it.');
      return null;
    }
    if (host === 'computer' && activeHost === 'vps') {
      pendingRequests.delete(msg.id);
      unbuffer(line);
      emitToolError(msg.id, 'Your computer is offline. Omit host to use the VM browser, or pass host: "vm".');
      return null;
    }
    // After the host checks, so a call that would fail anyway never asks.
    if (!approved && msg.params && GATED_TOOLS.has(msg.params.name) && gateCommit(msg, line)) return null;
    if (host === 'computer') return out;
    const wantsVm = host === 'vm'
      || (typeof args.tabId === 'string' && vmTabs.has(args.tabId))
      || (Array.isArray(args.steps) && args.steps.some((step) => step && vmTabs.has(step.tabId)));
    if (!wantsVm && msg.params && msg.params.name === 'cua_alans_way_tabs' && activeHost !== 'vps' && vmAlive()) {
      unbuffer(line);
      const merge = { vmId: `wsr-tabs-${msg.id}`, mac: null, vm: null, ms: undefined, at: Date.now() };
      tabMerges.set(msg.id, merge);
      tabMerges.set(merge.vmId, msg.id);
      writeToChild(out);
      try {
        vmChild.stdin.write(`${JSON.stringify({ ...msg, id: merge.vmId })}\n`);
      } catch { /* the merge completes with whatever the computer side answered */ }
      return null;
    }
    if (!wantsVm) return out;
    if (!vmAlive()) {
      if (activeHost === 'vps') return out; // the active backend already is the VM browser
      spawnVmBackend();
    }
    const req = pendingRequests.get(msg.id);
    if (req) req.via = 'vm';
    unbuffer(line);
    try {
      vmChild.stdin.write(`${out}\n`);
    } catch { /* a dead connector fails the call from its exit handler */ }
    return null;
  }

  function bindChild(c, host) {
    activeChild = c;
    activeHost = host;
    if (host === 'mac') hostStartedAt = Date.now();
    // A write after the Mac ssh has already exited emits EPIPE asynchronously.
    // That must not kill the process that is about to answer from the VPS.
    c.stdin.on('error', () => {});
    annotate = safeAnnotator(host);
    readline
      .createInterface({ input: c.stdout, crlfDelay: Infinity })
      .on('line', (line) => {
        if (c !== activeChild) return;
        touchActivity();
        if (swallowLine(line)) return;
        if (host === 'mac') {
          // ssh is up but the app behind it is gone: the backend answers
          // every call with "browser unavailable". The first such error is the
          // agent's to see; a second in a row means the host is not coming back.
          if (hostUnavailableLine(line)) {
            unavailableStreak += 1;
            if (unavailableStreak >= UNAVAILABLE_LIMIT) {
              failOver(`${hostName} browser unavailable ${unavailableStreak} calls in a row`);
              return;
            }
          } else if (line.length > BIG_LINE || line.includes('"result"')) {
            unavailableStreak = 0;
          }
        }
        const seenReq = pendingRequestFor(line);
        const callMs = noteServerRpc(line, pendingRequests);
        if (mergeMacLine(line, callMs)) return;
        learnVmTabs(line, false);
        learnTabUse(line, seenReq, host === 'mac' ? 'computer' : 'vm');
        provedAlive = true;
        if (watchdog) { clearTimeout(watchdog); watchdog = null; }
        bufferedStdin.length = 0;
        let out;
        try {
          out = annotate(line, callMs);
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
        failOver(`${hostName} backend failed to spawn`);
        return;
      }
      process.exit(1);
    });
    c.on('exit', (code, sig) => {
      if (superseded.has(c)) return;
      if (c !== activeChild) return;
      if (host === 'mac' && !shuttingDown) {
        // Spawn can emit error and exit for the same death; failOver only
        // acts once.
        failOver(provedAlive
          ? `${hostName} backend exited (${code === null ? sig : code})`
          : `${hostName} backend died before its first response`);
        return;
      }
      process.exit(code === null ? (sig ? 1 : 0) : code);
    });
  }

  let lastActivity = Date.now();
  const touchActivity = () => { lastActivity = Date.now(); };

  readline
    .createInterface({ input: process.stdin, crlfDelay: Infinity })
    .on('line', (raw) => {
      touchActivity();
      if (raw.includes('wsr-commit-') && answerApproval(raw)) return;
      const line = withoutApproval(raw);
      const method = noteClientRpc(line, pendingRequests);
      if (method === 'initialize') handshake.initialize = line;
      else if (method === 'notifications/initialized') handshake.initialized = line;
      else if (method === 'notifications/cancelled') {
        try { cancelCall(JSON.parse(line).params.requestId); } catch { /* nothing to withdraw */ }
      }
      if (!provedAlive) bufferedStdin.push(line);
      if (holdCalls && method === 'tools/call') {
        heldCalls.push(line);
        return;
      }
      if (method !== 'tools/call') {
        writeToChild(line);
      } else {
        const forwarded = routeToolCall(line);
        if (forwarded !== null) writeToChild(forwarded);
      }
      armWatchdog();
    });

  if (macCommand) {
    process.stderr.write(`workspace-router: routing to ${hostName} browser host\n`);
    startMacBackend();
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
    startVpsBackend();
  }

  // While on the host: watch for it going away faster than Hermes would
  // notice. ssh keepalives kill a half-open connection in ~10s; this also
  // reacts to a fresh mac-watch offline verdict (only one newer than this
  // backend, so a stale "offline" from before the probe never counts) and to
  // a call that has outlived its deadline.
  if (macSsh) {
    const monitor = setInterval(() => {
      if (activeHost !== 'mac' || fellBack || shuttingDown) return;
      const now = Date.now();
      for (const [id, req] of pendingRequests) {
        if (req.method !== 'tools/call' || req.awaitingApproval) continue;
        const age = now - req.at;
        const hard = req.batch ? BATCH_HARD_MS : CALL_HARD_MS;
        if (req.via === 'vm') {
          // There is no second fallback for the VM connector: a call it never
          // answers gets a tool error at the hard deadline, not a failover.
          if (age > hard) {
            pendingRequests.delete(id);
            noteDead(id);
            emitToolError(id, req.committed
              ? `The VM browser did not answer the call in time. ${COMMIT_LOST}`
              : 'The VM browser did not answer the call in time. Retry it.', vmAnnotate);
          }
          continue;
        }
        if (age > hard) {
          failOver(`${hostName} call exceeded ${hard}ms`);
          return;
        }
        if (age > (req.batch ? BATCH_SOFT_MS : CALL_SOFT_MS) && !req.probing && now >= (req.recheckAt || 0)) {
          req.probing = true;
          probeMac(5000).then((probe) => {
            req.probing = false;
            if (pendingRequests.get(id) !== req) return;
            if (probe.script) req.recheckAt = Date.now() + RECHECK_MS;
            else failOver(`${hostName} call open ${Date.now() - req.at}ms and the probe failed`);
          });
        }
      }
      // A merged tabs call whose VM half never arrived answers with the
      // computer half alone rather than waiting out the client's timeout.
      for (const [id, merge] of [...tabMerges]) {
        if (typeof merge !== 'object' || merge.vm || !merge.mac || now - merge.at <= CALL_HARD_MS) continue;
        merge.vm = {};
        emitTabsMerge(id, merge);
      }
      const mac = freshMacState(macStateFile);
      if (mac && mac.state === 'offline' && Date.parse(mac.since) >= hostStartedAt - (hostStartedAt % 1000)) {
        failOver(`mac-watch reports ${hostName} offline since ${mac.since}`);
      }
    }, 1000);
    monitor.unref();
  }

  let routerMtime = 0;
  try { routerMtime = fs.statSync(__filename).mtimeMs; } catch { /* a missing script has nothing newer to load */ }
  const reloadTimer = setInterval(() => {
    if (pendingRequests.size > 0 || Date.now() - lastActivity < 1000) return;
    let mtime = routerMtime;
    try { mtime = fs.statSync(__filename).mtimeMs; } catch { return; }
    if (mtime <= routerMtime) return;
    process.stderr.write('workspace-router: script replaced — exiting so the next connection loads it\n');
    shuttingDown = true;
    try { if (activeChild) activeChild.kill('SIGTERM'); } catch { /* the exit below is what Hermes respawns from */ }
    try { if (vmChild) vmChild.kill('SIGTERM'); } catch {}
    process.exit(0);
  }, 5000);
  reloadTimer.unref();
  for (const s of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(s, () => {
      shuttingDown = true;
      try {
        if (activeChild) activeChild.kill(s);
        if (vmChild) vmChild.kill(s);
      } catch {}
    });
  }

  // Return to the host. A session that is on the VPS (it started there, or
  // failed over) would otherwise stay until someone killed it by hand. Hermes
  // lazy-respawns a dead MCP server and the respawn re-probes, so once
  // mac-watch (which now proves the app answers, not just sshd) reports the
  // host online again this process steps aside. Two consecutive online reads
  // defend against flapping; the idle window plus the pending/held checks keep
  // an in-flight VPS task alive, since the tabs it works in live on the VPS.
  if (macSsh) {
    let onlineStreak = 0;
    const timer = setInterval(() => {
      if (activeHost === 'mac') {
        onlineStreak = 0;
        return;
      }
      const mac = freshMacState(macStateFile);
      onlineStreak = mac && mac.state === 'online' ? onlineStreak + 1 : 0;
      if (mayReconverge({
        mac,
        onlineStreak,
        lastActivity,
        pendingSize: pendingRequests.size + (holdCalls ? 1 : 0),
        idleMs: RECONVERGE_IDLE_MS,
        now: Date.now(),
      })) {
        process.stderr.write(
          `workspace-router: ${hostName} is online — exiting so the next connection re-probes and routes to it\n`,
        );
        shuttingDown = true;
        try {
          if (activeChild) activeChild.kill('SIGTERM');
          if (vmChild) vmChild.kill('SIGTERM');
        } catch {}
        process.exit(0);
      }
    }, 10000);
    timer.unref();
  }
}

if (require.main === module) {
  main();
}

module.exports = {
  isCommitName,
  selectorWords,
  readMacState,
  freshMacState,
  workspaceNotice,
  tabIdChanges,
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
  normalizeHost,
  sshControlArgs,
  muxTrouble,
  sshBinary,
  macStateFile,
  restoreMirror,
  continuationNotice,
  hostUnavailableLine,
  linuxBackendCommand,
  posixProbeCommand,
  posixAutoBackendCommand,
  SELF_PROBE_INTERVAL_MS,
  RECONVERGE_IDLE_MS,
};
