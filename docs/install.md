# Install, upgrade and fresh hosts

The full install path for the two plugins. The [README](../README.md) has the short version.

## Requirements

Browser-only setup needs stock Hermes `>= 0.21.5`. Desktop control through
`alans-way-computer` also needs `tools.computer_use.backend.ComputerUseProvider`,
introduced in Hermes commit
[`63f5e0ea45726c5d8d7d207d140613997730aab3`](https://github.com/NousResearch/hermes-agent/commit/63f5e0ea45726c5d8d7d207d140613997730aab3)
and verified in `6e7b83a2f1`. A version string alone does not establish this API.
Set `HERMES_PYTHON` to the interpreter belonging to the selected Hermes install
(`python.exe` on Windows); setup probes that interpreter with a bounded timeout.
“API absent” means the provider module/class is missing; “probe failed”,
“timed out”, or “probe unavailable” means support is unknown, so check the
interpreter/dependencies before retrying. For an absent API, offer a supported
Hermes upgrade with the user's consent, then rerun setup and
`hermes -p <profile> computer-use doctor`. Browser setup can finish meanwhile;
do not claim desktop control is ready until the provider is selected and its
doctor succeeds.

Works with stock Hermes `>= 0.21.5`. No Hermes source is patched: your existing
Telegram gateway keeps owning the conversation exactly as before — the plugin
adds tools and a small check-in loop inside it, it is not a second gateway.

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
- **Plugin** — installs `alans-way`, enables the `proactivity` toolset for
  Telegram sessions (without it, the `proactivity` tool never reaches the bound
  chat's tool list), and removes the stale 0.6 startup hook if one is installed
- **Alan's Tools (VPS browser host)** — fetches the companion repo, installs the connector's
  dependencies, writes `config.json`, and installs the Chromium/broker services:
  systemd units on a Linux host where systemd is live, supervisord programs
  where it is not (VM images, Orgo computers — user units when you're not root;
  as root they run as the account that owns `HERMES_HOME`, and as root with
  `--no-sandbox` only when Hermes itself runs as root), LaunchAgents on a macOS
  guest via `mac-guest-services.sh`, Scheduled Tasks on a Windows guest. Chrome or Chromium from a deb is preferred over snap
  Chromium, and an upgrade rewrites units and `config.json` whose content changed
- **Desktop prerequisites** — on Linux, detects whether an X11/VNC stack
  exists and prints the exact packages to install if not; on a macOS guest it
  prints the one-time TCC grants instead (guided, never auto-installed)
- **Workspace config** — writes the managed `workspace_browser` block into the
  right profile's config, then turns off Hermes' built-in browser toolset for
  Telegram and cron so the agent uses your workspace browser (setup says so;
  pass `--keep-browser` to leave it on)
- **Primary binding** — lists the Telegram DM routes that exist and asks which
  bot is the primary (message your bot once first if none exist yet, then
  re-run `setup.sh --bind`). After a successful bind, uses Hermes' profile-scoped
  config CLI to make that DM the Telegram home for scheduled/cross-platform
  delivery and clear any old topic ID; it loads on gateway restart. If that
  write fails, send `/sethome` in the primary DM and check its confirmation.
- **Verify** — prints a pass/fail summary of the whole install
- **Gateway restart**: last, through the detected supervisor (a SIGUSR1 drain
  under supervisord, a one-shot
  Scheduled Task on Windows), detached and a
  few seconds after the summary, so a restart never cuts setup short. If you
  run setup from a chat on that gateway, the chat pauses briefly

Without `--profile`, setup configures the main profile and every profile with
its own Telegram bot, each under that bot's id (a profile's `.env`
`TELEGRAM_BOT_TOKEN` wins over `config.yaml`, as in Hermes), installs this plugin
in each so every bot has the workspace skills (an existing or catalog install is
left as it is), and removes any older router entries from them (the config is
backed up first). Only the launch profile's runtime runs the check-in loop. It also adds a managed block
to the Hermes user's `~/.ssh/config` so the agent's own ssh commands to your
computer share one connection.

Useful flags:

- `--profile NAME`: configure only one Hermes profile.
- `--host-os windows|linux`: the user's computer is not a Mac.
- `--verify`: audit without changing anything. Exit 0 means a complete local
  audit, 1 means failed required checks, and 2 means partial (warnings or
  skipped browser/services). Repeat the install's skip flags when auditing.
  Computer-side preview/control and Telegram delivery still need their human
  handoffs and end-to-end checks.
- `--non-interactive`: scripted runs.
- `--skip-browser`: proactivity-only installs.
- `--skip-plugin`: leave an already installed plugin as it is (catalog installs).
- `--skip-services`: don't install the Chromium/broker services or scheduled tasks.
- `--keep-browser`: leave Hermes' built-in browser toolset on.
- `--keep-computer-use`: deprecated no-op. Setup never disables `computer_use`.
- `--repo-ref SHA` / `--desktop-ref SHA`: pin this repo and the app repo to a reviewed commit or tag.
- `--cdp-port PORT`: the managed browser's CDP port (default: keep the configured one, else the first free port from 9223 up; `ALANS_WAY_CDP_PORT` works too).
- `--mac-key` / `--mac-host-key`: add your computer's pasted SSH key and host key after checking their format.
- `--dev-plugin-install`: developers only. Installs the computer-use provider from this clone instead of the Hermes catalog.

 When Hermes has the pluggable computer-use API, setup
also installs the `alans-way-computer` provider for the profile (from the
Hermes catalog, never over a catalog install) and selects it once the
workspace browser is configured. Desktop input only ever goes through the
approval-gated `computer_use` tool: the managed `workspace_browser` block
excludes `workspace_computer_action`, and the router hides and refuses it
unless you opted in. Setup never turns `computer_use` off for any platform or
profile, on any Hermes. On a Hermes too old for the provider API,
`--allow-desktop-actions` is a manual opt-in that also exposes that ungated
tool: desktop input then runs with no approval at all, so no skill or prompt
ever passes it for you. A `cua-driver`
MCP server you added yourself is kept, and setup warns that the agent then sees
two computer-use paths and prints the `hermes mcp remove` command. Desktop control asks for approval in
Telegram for each action; `--allow-desktop-actions` adds click, type, key,
scroll and the like (background only) to `command_allowlist` if you would
rather not be asked. The proactivity toolset is enabled for Telegram. Once a
route is bound, check-ins are on by default; `--proactive no` binds them
paused, and the bot tunes them from the bound chat.

For automatic compaction and the setup skill's optional early tool-output
pruning, see [Long chats](long-chats.md).

### Or let your agent do it

Paste the [setup prompt](https://github.com/capthvnsen/alans-way/blob/main/docs/setup-prompt.md)
to the agent with a terminal on the VPS (your Hermes bot works). It connects
the VPS and your computer over Tailscale with pinned SSH keys both ways, runs
the same `setup.sh`, and proves both ends work. The
`workspace-setup` skill (bundled in the plugin) teaches it the same playbook.

### 3. Alan's Workspace (the desktop app)

Download the one-click installer:

- **Mac:** [openalan.com/download/mac](https://openalan.com/download/mac). Developer ID signed and notarized.
- **Windows:** [openalan.com/download/windows](https://openalan.com/download/windows). Unsigned, so SmartScreen warns you. Click **More info → Run anyway**.

Prefer to build it yourself? The app repo has build-from-source scripts
(`curl -fsSL https://openalan.com/install-mac | sh` on a Mac,
`scripts/install-windows.ps1` in an elevated PowerShell on Windows).

The app's first-run wizard hands you the agent setup prompt. Or sign in to
Telegram inside the app, then **Settings → Agent setup**: the checklist shows what's already done: Telegram sign-in,
discovered bots, both SSH addresses, connector status. Save the two SSH
addresses, use **Copy setup command** (the bootstrap above, pre-filled) or
**Copy setup prompt**, then **Test agent path**.

### 4. Verify it end to end

- Desktop app: Test agent path → ✓ this host reaches your computer over ssh
- Telegram: `hermes proactivity status` → route bound, check-ins on
- Browser: ask the bot to open a page — a tab appears in the app (host)
  while your computer is awake, on the VPS host when it isn't

### Plugin security review

For the reviewed release candidate, Hermes' unmodified scanner at
`6e7b83a2f1c093e992a8d838ed77ea320fbd8e51` reports **SAFE: 0 HIGH,
2 MEDIUM and 3 LOW findings** in `alans-way/`. These are real capabilities
documented in the bundled skills:

- Workspace setup runs two bounded, read-only local Git subprocess helpers
  to validate the setup checkout and a file-source install's origin before
  selecting the reviewed revision.
- With explicit consent, the viewer handoff uses a temporary SSH forward
  bound to computer loopback, checks the loopback URL with curl, and gives
  that same URL to the app. The human enters the VNC password privately.

The Mastodon recipe now lives in [human-run repository documentation](integrations/mastodon.md)
outside `alans-way/`; the plugin no longer ships its connector or identity probe.
The scanner and remaining matched commands are unchanged. MEDIUM/LOW findings
alone produce SAFE, which requires no scanner confirmation. If a later revision
receives CAUTION, review every finding and explicitly confirm the exact tree:
`--enable` and setup consent do not confirm a scanner warning. Follow the bundled
[reviewed-install confirmation steps](../alans-way/skills/workspace-setup/SKILL.md#reviewed-plugin-install-confirmation);
`--force` can confirm CAUTION and replace an install, but cannot override
DANGEROUS. A catalog install uses the catalog's reviewed pin; it does not
approve a newer checkout. Changed revisions and unknown findings need a new
review. See the [complete inventory and catalog disclosure supplement](catalog/alans-way-disclosure.md).

### Upgrading

The agent setup prompt pins the plugin clone to a release tag (`v` + the
`version:` in `alans-way/plugin.yaml`) via `--repo-ref`. A catalog install pins
it to the catalog-recorded commit instead. A bare `setup.sh` run with no
`--repo-ref` follows `main`.

Alan's Workspace's update popup updates the app and the plugin on every saved VM
over SSH. Nothing to run by hand.

Manual path: `git pull` (or re-run the `curl|bash` line), then restart the
gateway. A running gateway keeps already-imported code until restarted.
Restart it through its owner: `hermes gateway restart`, or on a host where
supervisord runs the gateway `supervisorctl signal USR1 <program>` on the
program whose command runs `hermes gateway run` — the gateway drains its
turns, exits, and supervisord relaunches it; wait for the new pid, and use
`start`/`restart` only as fallbacks. A plain `supervisorctl restart` or `stop`
escalates SIGTERM to SIGKILL after `stopwaitsecs` (10s by default), which can
kill the gateway mid-checkpoint and corrupt `state.db`. Verify
one ordinary Telegram reply and one bounded browser action before relying on it.

## Orgo / fresh Linux hosts

Two scripts in this repo serve [Orgo](https://orgo.ai) computers and DIY
users who want the same hands-off path on any fresh Linux box with
supervisord.

`bootstrap-orgo.sh` takes a fresh Orgo computer to a running Hermes plus
alans-way plus Tailscale, then waits for pairing. It installs Hermes with
the same installer Orgo's Hermes template uses, runs `setup.sh
--non-interactive` (with `--skip-services` plus supervisord confs, since
Orgo has no systemd), starts `tailscaled` under supervisord, captures the
Tailscale login URL and either POSTs it to `--callback` or prints it.
Every step checks real state before acting, so re-running after a failure
resumes instead of duplicating work, and progress lands in
`/var/lib/alan/state.json` for a poller. DIY run, no callback:

```sh
curl -fsSL openalan.com/bootstrap | bash
```

`migrate.sh` moves an existing `~/.hermes` — profiles, config, `.env`,
`SOUL.md`, `auth.json`, `state.db`, `MEMORY.md`, `USER.md`, skills and
plugins; not caches, logs, venvs or `profiles/.deleted` — to the new
computer over ssh, rewriting absolute paths that pointed at the old home.
An existing remote home is backed up first, and the old gateway stops only
after the copy lands so both hosts never poll the same bot:

```sh
curl -fsSL openalan.com/migrate | bash -s -- --to <tailscale-host> --yes
```

Useful flags: `bootstrap-orgo.sh --dry-run` prints what it would do;
`--wait-paired` polls until the tailnet reports the computer paired.
`migrate.sh --dry-run` prints the plan; `--yes` confirms without prompting
(required on the piped one-liner, since stdin is the script itself);
`--hermes-home`/`--remote-home` cover non-standard layouts.

A private add-on script run right after `bootstrap-orgo.sh` finishes can
rely on [docs/addon-interface.md](addon-interface.md): the CLI flags,
the status file's keys and merge semantics, the `hermes-gateway` supervisord
program, and the `HERMES_HOME` layout.
