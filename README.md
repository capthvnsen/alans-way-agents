# Alan's Way — agent plugin

**The behavior half of [Hermes — Alan's Way](https://github.com/capthvnsen/alans-way).**
This repo is what you install *on the machine running your Hermes agents*
(a Linux VPS, a macOS VM, or a Windows PC you keep on). The companion repo holds the desktop app for the
user's computer (macOS or Windows) — this one holds
what your agents need to think and act:

- **`alans-way/`** — a native Hermes plugin: one designated primary bot
  gets bounded, event-driven proactivity — reviewing its own work, watching
  approved tasks, and surfacing useful things to do, on a schedule you control.
- **`alans-way/gateway-hook/`** — the gateway startup hook. `setup.sh` copies
  it to `$HERMES_HOME/hooks/alans-way/` so proactivity arms only inside the
  real gateway process. A catalogue install includes this hook.
- **Workspace browser wiring** — `setup-workspace.sh` writes a managed
  `workspace_browser` block into your Hermes config pointing at
  `scripts/workspace-router.cjs`, which probes your computer first and falls
  back to the VPS browser when it is asleep. Pass `--host-os windows` or `--host-os linux`
  when the user's computer is not a Mac (default `mac`).
- **`alans-way/skills/`** — the `proactive-primary` and `workspace-operations` skills ship
  inside the plugin so agents know how to use the tools correctly.

Works with stock Hermes `>= 0.21.5`. No Hermes source is patched: your existing
Telegram gateway keeps owning the conversation exactly as before — the plugin
adds tools and an optional review loop inside it, it is not a second gateway.

## What it does and does not do

- **Two browser hosts, no silent migration.** Bots get per-tab Chromium access
  on the user's computer (through the desktop app's connector) and on the VPS
  (the managed browser). When the user's computer is unreachable, *new*
  browser work routes to the VPS host automatically. Work already in flight
  in a host tab blocks while the machine is asleep and resumes when it returns
  — the live tab is not moved between machines. Watching the VPS desktop from
  inside the app additionally needs a VNC server and a noVNC viewer on the VPS
  (a macOS guest VM uses `tart --vnc-experimental` instead); see the app repo's
  [deployment guide](https://github.com/capthvnsen/alans-way/blob/main/docs/deployment.md).
- **Proactivity is read/research/draft by default.** The designated primary may
  read its own state, research, and draft proposals inside bounded budgets and
  quiet hours. Consequential actions — sending external messages or posts,
  purchases, credential or permission changes, production changes, destructive
  operations, new scope — always ask first. Details in
  [docs/proactivity.md](docs/proactivity.md).
- **No bundled account connections.** Email, calendar, Notion and similar
  connectors exist for an agent only if you install and authorize them
  separately in Hermes; this plugin provisions none of them.

## Install — zero to working

The full path has four pieces. Most are one step each; `setup.sh` detects
what's already done and skips it, so re-running is always safe.

### 1. Hermes on the VPS, with Telegram

You need a stock Hermes `>= 0.21.5` install whose gateway can answer Telegram.
If your Hermes has never talked to Telegram, that's the first step — and it
doesn't need BotFather: run `hermes gateway setup` on the VPS, choose
**Telegram → Automatic**, and scan the QR code with your phone. Hermes creates
the bot, saves the token, and allowlists your account. (Manual BotFather token
paste works too.)

### 2. The bootstrap (one command)

On the host that runs your Hermes gateway:

```sh
curl -fsSL https://raw.githubusercontent.com/capthvnsen/alans-way-agents/main/setup.sh | bash -s -- \
    --bot-id YOUR_NUMERIC_BOT_ID --mac-ssh you@your-computer --restart
```

or from a clone: `./setup.sh --bot-id ... --mac-ssh ... --restart`.
Add `--host-os windows` or `--host-os linux` when the user's computer runs
Windows or Linux (the default is `mac`). On macOS, Linux and Windows guests
`setup.sh` picks the right service manager itself.

**A Windows PC as the VM.** Run `setup.sh` from Git Bash (the shell Hermes' own
terminal tool uses on native Windows), with Hermes installed natively. WSL2 is
Linux: use the Linux path inside it. The Windows path needs, on the PC: Hermes,
Git for Windows, Node 22+, Python 3 (`winget install Python.Python.3.12`, or set
`HERMES_PYTHON` to a `python.exe`), Tailscale, Chrome or Edge, and OpenSSH Server
if the app should reach the PC (`setup.sh` checks it and prints the exact
elevated PowerShell lines). Instead of systemd, `setup.sh` registers three
Scheduled Tasks that start at logon and restart on failure: `AlansWay_Chromium`,
`AlansWay_Browser` and, with `--mac-ssh`, `AlansWay_MacWatch`. Windows starts them
at logon, not at boot, so keep the PC awake and turn on automatic sign-in
(`netplwiz`) for them to come back after a reboot. The router talks to the
user's computer with the native OpenSSH client (no connection reuse there), and
state lives under `~/.local/share/hermes-alans-way`. Hermes keeps its own data in
`%LOCALAPPDATA%\hermes`, which `setup.sh` uses unless `HERMES_HOME` is set.

`--mac-ssh` must be a Tailscale address: a `.ts.net` name, a tailnet IP, or a
name `tailscale status` lists. Install Tailscale on both machines first;
`setup.sh` refuses public addresses and stops if Tailscale is not running.

The bootstrap runs every step in order and says what it did:

- **Preflight**: hermes version (0.21.5 or newer, or setup stops), python3, Node 22+, HERMES_HOME
- **Telegram check** — if no `TELEGRAM_BOT_TOKEN` is configured it offers to
  launch `hermes gateway setup` right there
- **Plugin + gateway hook** — installs `alans-way`, arms the startup hook, and
  enables the `proactivity` toolset for Telegram sessions (without it,
  `proactive_control` never reaches the bound chat's tool list)
- **VPS browser host** — fetches the companion repo, installs the connector's
  dependencies, writes `config.json`, and installs the Chromium/broker services:
  systemd units on Linux (user units when you're not root; as root they run as
  the account that owns `HERMES_HOME`, and as root with `--no-sandbox` only when
  Hermes itself runs as root), LaunchAgents on a macOS guest via
  `mac-guest-services.sh`, Scheduled Tasks on a Windows guest. Chrome or Chromium from a deb is preferred over snap
  Chromium, and an upgrade rewrites units and `config.json` whose content changed
- **Desktop prerequisites** — on Linux, detects whether an X11/VNC stack
  exists and prints the exact packages to install if not; on a macOS guest it
  prints the one-time TCC grants instead (guided, never auto-installed)
- **Workspace config** — writes the managed `workspace_browser` block into the
  right profile's config, then turns off Hermes' built-in browser toolset for
  Telegram so the agent uses your workspace browser (setup says so; pass
  `--keep-browser` to leave it on)
- **Primary binding** — lists the Telegram DM routes that exist and asks which
  bot is the primary (message your bot once first if none exist yet, then
  re-run `setup.sh --bind`)
- **Verify** — prints a pass/fail summary of the whole install
- **Gateway restart**: last, through the detected supervisor (a one-shot
  Scheduled Task on Windows), detached and a
  few seconds after the summary, so a restart never cuts setup short. If you
  run setup from a chat on that gateway, the chat pauses briefly

Useful flags: `--profile NAME` for a named Hermes profile, `--host-os
windows|linux` when the user's computer is not a Mac, `--verify` to audit
without changing anything, `--non-interactive` for scripted runs,
`--skip-browser` for proactivity-only installs, and `--mac-key` /
`--mac-host-key` to add your computer's pasted SSH key and host key after
checking their format. When Hermes has the pluggable computer-use API, setup
also installs the `alans-way-computer` provider for the profile and selects it
once the workspace browser is configured. Desktop control asks for approval in
Telegram for each action; `--allow-desktop-actions` adds click, type, key,
scroll and the like (background only) to `command_allowlist` if you would
rather not be asked. The proactivity toolset is enabled for Telegram and for
cron, so isolated wakes can report. A proposed watch never runs on its own:
approve it with the Telegram button or `/watch approve <id> <code>`.

### Or let your agent do it

Paste the [setup prompt](https://github.com/capthvnsen/alans-way/blob/main/docs/setup-prompt.md)
to the agent with a terminal on the VPS (your Hermes bot works). It connects
the VPS and your computer over Tailscale with pinned SSH keys both ways, runs
the same `setup.sh`, and proves both ends work. The
`workspace-setup` skill (bundled in the plugin) teaches it the same playbook.

### 3. The desktop app

On the user's Mac:

```sh
curl -fsSL https://openalan.com/install-mac | sh
```

On a Windows PC, run `scripts/install-windows.ps1` from the app repo in an
elevated PowerShell — it builds the app locally with `npm run package:win`
(no installer or SmartScreen prompt).

Either builds and installs the app locally (no release zip or Gatekeeper
workaround). Sign in to Telegram inside the app, then **Settings → Agent
setup**: the checklist shows what's already done — Telegram sign-in,
discovered bots, both SSH addresses, connector status. Save the two SSH
addresses, use **Copy setup command** (the bootstrap above, pre-filled) or
**Copy setup prompt**, then **Test agent path**.

### 4. Verify it end to end

- Desktop app: Test agent path → ✓ this host reaches your computer over ssh
- Telegram: `/proactivity status` → route bound, gateway armed
- Browser: ask the bot to open a page — a tab appears in the app (host)
  while your computer is awake, on the VPS host when it isn't

### Upgrading

`git pull` (or re-run the `curl|bash` line), then restart the gateway — a
running gateway keeps already-imported code until restarted. Verify one
ordinary Telegram reply and one bounded browser action before relying on it.

### What each piece does

| Piece | Effect |
|---|---|
| `proactive_control` tool | `/proactivity` pause/resume/status, budgets, quiet hours — bound to one designated chat |
| Observer | 30s check for approved watches, bounded automatic opportunities |
| Gateway hook | Flips the plugin's "armed" flag only when running inside the gateway (not TUI/CLI probes) |
| `workspace_browser` MCP | Call `cua_alans_way_status`, `cua_alans_way_tabs`, `cua_alans_way_open`, `cua_alans_way_snapshot`, `cua_alans_way_screenshot`, `cua_alans_way_action`, `cua_alans_way_close`. Desktop apps on the Mac and the Linux machine: `workspace_computer_apps`, `workspace_computer_snapshot`, `workspace_computer_action`, `workspace_computer_screenshot` (one window, only when the snapshot cannot name the control). On Linux, press a ref. The config key is not a tool name. |
| Router | probes the Mac's ssh alias for ~8s; unreachable → VPS browser host. Mac asleep mid-session → the in-flight Mac call fails visibly and the next MCP connection re-routes to a fresh VPS session; live Mac tabs are never migrated. Tool results carry the serving host and mac-watch state |
| mac-watch | optional watcher probes the user's computer every 30s (systemd unit in `deploy/`; setup.sh installs a LaunchAgent on a macOS guest) and publishes a JSON state file the router and observer read |

## The workspace_browser tools

Each bot needs its own `--bot-id` — it owns that bot's tabs. The router passes
`--bot-name` through so the on-page agent cursor carries the bot's name and
color. Multi-bot setups: run `setup-workspace.sh` once per profile, each with
its own bot id (the script replaces only its own managed block).

Host path requirements: the alans-way-localapp app running on the user's
computer, SSH from this host to it (BatchMode/key auth — the probe uses
`StrictHostKeyChecking`), and the app's bundled `browser-mcp.cjs` (inside the
installed app, or the copy this repo pushes to the connector directory). On a
Windows host the probe runs through PowerShell (the default sshd shell the
connect script sets) and computer-use calls reach the desktop through the
app's local API — an SSH session cannot drive the interactive desktop.
VPS-only usage works with no host computer: the router detects the
missing/unreachable host and serves the local VPS browser host directly.

## Mac availability watcher

`workspace-router.cjs --watch` (`alans-way/scripts/mac-watch.sh` is a thin wrapper
around it) probes the Mac over ssh on an
interval (default 30s) and keeps a JSON state file —
`{"state","since","lastSeenOnline","lastTransition"}` — that the router and
the proactive observer read instead of probing themselves. The router adds
the serving host and Mac state to `workspace_browser` results; the observer
turns an offline→online flip into a context event for the lead bot's review,
so kanban cards blocked on Mac-only work can resume. Transitions are logged
to `mac-events.log` beside the state file.

The observer also sweeps the shared `kanban.db` read-only
(`proactive_board.py`): open and recently-closed cards ride into the primary
bot's review context, so a blocked or changed card from another agent can
surface as one bounded opportunity — never a reason to touch someone else's
card. Combined with the connector's overseer role (`HERMES_OVERSEER_BOTS` /
`HERMES_OVERSEER_BOT_IDS`, see `integration.md` in the app repo), the primary
can answer "who is working where" and release a runaway tab.

Review context also carries `documents` — excerpts and modified times of the
primary's own identity files (`SOUL.md`, `AGENTS.md`, `IDENTITY.md`) — and
`capabilities`, the installed skill names. With `schedule` (enabled cron
metadata) that lets the appraiser weigh the wider remit: an upcoming
commitment worth surfacing, a capability gap worth one `ask` or a bounded
skill-building proposal, or a stale identity document worth a draft update.

```sh
sudo cp deploy/mac-watch.service /etc/systemd/system/
sudo mkdir -p /etc/hermes-alans-way
echo 'HERMES_WORKSPACE_MAC_SSH=you@your-mac' | sudo tee /etc/hermes-alans-way/mac-watch.env
sudo systemctl enable --now mac-watch.service
```

Adjust `ExecStart` to the installed router path and `User=` to the account
whose ssh keys reach the Mac. Environment variables:
`HERMES_WORKSPACE_MAC_SSH` (required — the same ssh alias the router probes),
`HERMES_MAC_STATE_FILE` (default `/var/lib/hermes-alans-way/mac-state.json`;
the unit's `StateDirectory` creates the parent directory; on a Windows guest
`~/.local/share/hermes-alans-way/mac-state.json`).

Hermes's stock `browser_exec` (Browser Use) tool connects to its own
`browser.cdp_url` (default `http://127.0.0.1:9222`) — nothing shares it.
Run a dedicated Chromium there via `deploy/browser-exec-chromium.service`
reusing the same `vps-chromium-host.cjs` supervisor with
`deploy/browser-exec-config.json` under
`$HERMES_VPS_BROWSER_DATA/config.json`. It keeps its own
`--user-data-dir`; never point browser_exec at :9223, which the workspace
VPS browser owns.

## Safety model (short version)

- Human takeover wins always: control epochs invalidate queued agent actions.
- Per-tab ownership is cooperative policy between bots sharing the connector —
  not a crypto boundary. See the [security note](https://github.com/capthvnsen/alans-way/blob/main/desktop/docs/integration.md)
  for the trust model before exposing a connector beyond `127.0.0.1`.
- The proactivity observer is read-only about the world until an approved
  opportunity fires inside its one bound conversation. Budgets and quiet
  hours are in `docs/proactivity.md`.

## Layout

```
alans-way/            the plugin (plugin.yaml + tools + observer + skills + router + mac-watch + gateway-hook/)
deploy/               systemd unit for the Mac availability watcher, example browser_exec Chromium unit
docs/                 proactivity guide, agent-driven setup prompt
tests/                unittest suite — python3 -m unittest discover -s tests
setup.sh              one-command bootstrap (install, wire, restart, bind, verify)
setup-workspace.sh    per-bot mcp_servers config writer (called by setup.sh)
```

## Tests

```sh
python3 -m unittest discover -s tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request and
[SECURITY.md](SECURITY.md) to report a vulnerability.

## License

MIT — see [LICENSE](LICENSE).
