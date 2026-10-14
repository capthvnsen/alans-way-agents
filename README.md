# Alan's Way Plugin

[![GitHub stars](https://img.shields.io/github/stars/capthvnsen/alans-way?style=social)](https://github.com/capthvnsen/alans-way)
[Discord](https://discord.gg/jBQCPUsVE) · [X @alexhvnsen](https://x.com/alexhvnsen) · [openalan.com](https://openalan.com)

**The plugin half of Alan's Way: fast, reliable browser and computer control for stock Hermes.**
The companion desktop app, Alan's Workspace, lives at [capthvnsen/alans-way](https://github.com/capthvnsen/alans-way)
(download at [openalan.com](https://openalan.com)). This repo is what you install
*on the machine running your Hermes agents* (a Linux VPS, a macOS VM, or a Windows
PC you keep on). The app runs on your own computer (macOS or Windows). This repo
holds what your agents need to think and act:

- **`alans-way/`** — a native Hermes plugin: your primary Telegram bot checks
  in on its own when you've gone quiet — an idle nudge on a schedule you
  control, tuned by talking to the bot.
- **Workspace browser wiring** — `setup-workspace.sh` writes a managed
  `workspace_browser` block into your Hermes config pointing at
  `scripts/workspace-router.cjs`, which probes your computer first and falls
  back to the VPS browser when it is asleep. Pass `--host-os windows` or `--host-os linux`
  when the user's computer is not a Mac (default `mac`).
- **`alans-way/skills/`** — the `workspace-setup`, `workspace-operations`,
  `web-errands` and `integrations` skills ship inside the plugin so agents know
  how to use the tools correctly.
- **`alans-way-computer/`**: a second plugin (v0.21.5): a computer-use provider
  for Hermes. It drives desktop apps on your computer through the same router,
  and on the VM desktop when your computer is offline. Actions go through
  Hermes' approval-gated `computer_use` tool: you approve each action type on
  Telegram and choose what to always allow. Needs a Hermes build with the
  pluggable computer-use API described below.

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
- **Check-ins are one internal prompt.** When the bound chat goes quiet past
  its wait, the plugin injects one prompt and the bot decides what to do with
  it — or replies `[SILENT]` and nothing is sent. Consequential actions —
  sending external messages or posts, purchases, credential or permission
  changes, production changes, destructive operations — always ask first.
  Details in [docs/proactivity.md](docs/proactivity.md).
- **Web errands stop at your Approve tap.** The `web-errands` skill drives
  the research → stage → commit → verify → report loop for shopping, cart
  comparison, booking and travel, job applications, form and civic-portal
  filing, cancellations, refunds and document-driven claims — in your real
  browser session on your computer, or on the VPS browser while it's
  asleep. Every purchase, booking, send, submission and deletion waits for
  the commit gate's Approve prompt; a CAPTCHA, sign-in or card-entry wall
  hands the tab back to you with a reason instead of working past it, and
  after each commit the bot reads the confirmation, captures the reference
  number and sends a Telegram receipt.
- **Telegram replies read like texts.** In every profile the plugin is enabled
  in, the bot's Telegram replies use a short, warm texting voice. A minimal
  send-time polish only drops a leading "Certainly!"-style opener, and only
  from a message with no indented line, backtick or quotation mark. Fixed
  Hermes messages (approval cards, errors, progress) and cron reports are not
  changed. It layers on top of your SOUL.md and `agent.system_prompt` and never
  edits them. `/tone default` turns it off for that bot. Details in [docs/voice.md](docs/voice.md).
- **Progress while working.** Multi-step Telegram tasks get short updates about
  what is happening and what comes next, including side effects and mistakes;
  mid-task messages can be folded into the running task with `steer`.
  Neither setup script writes `display.busy_input_mode` or
  `display.interim_assistant_messages`. Guided setup asks once when the
  profile's effective busy mode is `interrupt` and no remembered choice exists.
  Only an explicit answer lets the setup skill set busy mode through
  `hermes -p NAME config set`; the choice applies to all platforms in that
  profile and is read back afterwards. Keeping interrupt also records
  `skills.config.workspace-setup.busy_input_choice: keep-interrupt` in that
  profile's config through the CLI, after disclosure and the answer, so reruns
  do not ask again. Silence and non-interactive runs write nothing; already
  `steer` or `queue` profiles are skipped. Later user changes are preserved.
  For `steer`, guided setup checks Telegram's platform override first and
  preserves it, reports whether its extra bubble remains on, and skips the offer
  when that override exists. Otherwise it separately offers to remove Hermes' extra status
  bubble with `display.busy_steer_ack_enabled=false`, asks for an explicit
  answer and remembers it in `skills.config.workspace-setup.busy_steer_ack_choice`
  only after the effective Telegram readback matches. The global change also
  applies to other platforms that inherit it; their explicit overrides remain;
  the bot still acknowledges additions itself. Setup scripts never write it.
  Hermes already defaults interim messages to `true`
  ([`hermes_cli/config_defaults.py:919` at `d97007c`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/hermes_cli/config_defaults.py#L919));
  the skill only reports an effective `false` choice and preserves it.
  To change an existing `interrupt` choice, run
  `hermes -p NAME config set display.busy_input_mode steer`; to enable interim
  texts, set `display.interim_assistant_messages true` the same way (and check
  `display.platforms.telegram.interim_assistant_messages` for an override).
  Restart the gateway through its supervisor to load the changes.
- **Connect your stuff from Telegram.** The [integrations skill](alans-way/skills/integrations/SKILL.md)
  checks account access before promising a task, reuses Hermes' Google,
  Himalaya, Home Assistant, Honcho and X routes, and offers pinned rclone,
  Taskwarrior and Mastodon.py recipes. Package installs on the VM require your
  agreement; account authorization stays private, with secure handback when
  phone-only auth cannot finish. Installing the plugin connects no accounts
  and starts no integration services.

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
pruning, see [Long chats](docs/long-chats.md).

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
`6e7b83a2f1c093e992a8d838ed77ea320fbd8e51` reports **CAUTION: 1 HIGH,
2 MEDIUM and 3 LOW findings** in `alans-way/`. These are real capabilities
documented in the bundled skills:

- The optional Mastodon identity probe reads only `MASTODON_API_BASE_URL` and
  `MASTODON_ACCESS_TOKEN` from its process environment, uses the token to
  authenticate to the user's chosen HTTPS instance, and prints the account
  handle. The user enters the token privately and explicitly grants this
  profile's environment passthrough; it does not dump the environment.
- Workspace setup runs two bounded, read-only local Git subprocess helpers
  to validate the setup checkout and a file-source install's origin before
  selecting the reviewed revision.
- With explicit consent, the viewer handoff uses a temporary SSH forward
  bound to computer loopback, checks the loopback URL with curl, and gives
  that same URL to the app. The human enters the VNC password privately.

A manual/file install needs review of every finding at the exact candidate
revision and explicit confirmation of that tree. `--enable` and setup consent
do not confirm a scanner warning. Follow the bundled
[reviewed-install confirmation steps](alans-way/skills/workspace-setup/SKILL.md#reviewed-plugin-install-confirmation);
`--force` can confirm CAUTION and replace an install, but cannot override
DANGEROUS. A catalog install uses the catalog's reviewed pin; it does not
approve a newer checkout. Changed revisions and unknown findings need a new
review. See the [complete inventory and catalog disclosure supplement](docs/catalog/alans-way-disclosure.md).

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

### What each piece does

| Piece | Effect |
|---|---|
| `proactivity` tool + `/proactivity` + `hermes proactivity` CLI | bind the chat, tune the wait, level, timezone and pause — bound to one designated chat |
| Idle-nudge loop | a 60-second daemon started when Telegram connects; injects one internal prompt when a check-in is due |
| Turn hooks | `pre_llm_call`/`post_llm_call` note when the bound chat was last active and whether the bot is mid-turn |
| `workspace_browser` MCP | Call `cua_alans_way_status`, `cua_alans_way_tabs`, `cua_alans_way_open`, `cua_alans_way_snapshot`, `cua_alans_way_screenshot`, `cua_alans_way_action`, `cua_alans_way_close`. An action that buys, books, sends, posts, submits, deletes or changes an account carries a `commit` object: the router asks you to approve it in Telegram (MCP elicitation) and runs it only on Approve, refuses a commit-looking click without one, never retries it, and logs each decision to `commit-decisions.jsonl` next to the mac-watch state file. The name check reads ref names, `name` targets and selector text. Input it cannot judge by name (keys other than Tab, arrows, Escape or a plain character; clicks, drags and selects by position, on unnamed controls or by selectors that name no commit; `eval`; `cdp` calls other than reads, `Emulation.*` and `Page.navigate`/`reload`; accepting a page dialog) needs `commit` on a page that shows a commit control, and a snapshot first on a page whose controls the router has not seen in full, including after a reply that listed only what changed. On a page that embeds a frame from another site, a key aimed at no control or a click by position never counts as judged. A reload of a commit page, typing then pressing Enter in one batch, and following a link to, opening, navigating, or going back or forward to an address that reads like an action on any site (`/checkout/complete`, `?step=confirm`, `/orders/7/delete`, `/buy`) need `commit`; a ref the router has not seen on the current page is refused, and `Page.addScriptToEvaluateOnNewDocument` is never allowed. Awaiting-human, CAPTCHA and recording holds, the Take-back cooldown, and stale control epochs are refused with the browser's own reason before anyone is asked. With automatic takeover enabled, a bot acting on a tab the human holds on the user's computer can take it back after the grace period: act or claim. A commit still needs fresh user approval, which the app honors across that automatic takeover exactly once. Refused actions leave the human's focus, tab owner and control epoch untouched; with automatic takeover off, `human_has_control` means wait or ask the user to hand the tab back. A new control epoch drops what the router knew of the page. On Approve the router adds the app's single-use `approval` receipt (`{nonce, kind, summary, issuedAt, tabId, epoch}`, bound to the approved tab and epoch) to that one forwarded call; an `approval` the agent sends is dropped from every call and step, and an approval whose tab changed page or epoch while it waited is refused with `page_changed`. The name list lives in `alans-way/scripts/commit-patterns.json`, which the app's own dispatch check mirrors. Approvals need Hermes v0.21.6 or newer (it includes commit 239740a19e, first in date tag v2026.6.19); older Hermes cannot show them, so every commit is refused with `approval_unavailable`. Desktop apps on the Mac and the Linux machine are read with `workspace_computer_apps`, `workspace_computer_snapshot`, `workspace_computer_menu` and `workspace_computer_screenshot`, and driven by the approval-gated `computer_use` tool (the `alans-way-computer` provider). `workspace_computer_action` is excluded from the managed block unless setup ran with `--allow-desktop-actions`. The config key is not a tool name. |
| Router | probes the Mac's ssh alias for ~8s; unreachable → VPS browser host. Mac drops mid-session → the router fails over in-process within ~10s, restoring the agent's tabs and cookies on the VPS; the call that was in flight fails visibly and is never retried. Tool results carry the serving host and mac-watch state |
| mac-watch | optional watcher probes the user's computer every 10s (systemd unit in `deploy/`; setup.sh installs a LaunchAgent on a macOS guest) and publishes a JSON state file the router reads |
| Texting voice + `/tone` + `hermes tone` CLI | on Telegram turns, `pre_llm_call` adds the voice note and `transform_llm_output` polishes the final reply; every profile, on by default. Fixed Hermes messages (approvals, errors, progress) are not changed; see [docs/voice.md](docs/voice.md) |

**Commit gate limit.** The commit gate protects against agent mistakes and against clicks steered by prompt injection or a malicious website. It does not stop a deliberately hostile agent that also has terminal or file tools: that agent runs as the same OS user as the router and the browser services, so it can reach them directly. Full isolation (a separate OS account plus router-signed approvals) is planned for v0.21.6.

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

## The workspace_browser tools

Each bot needs its own `--bot-id` — it owns that bot's tabs. The router passes
`--bot-name` through so the on-page agent cursor carries the bot's name and
color. Multi-bot setups: run `setup-workspace.sh` once per profile, each with
its own bot id (the script replaces only its own managed block).

Host path requirements: the Alan's Workspace app running on the user's
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
interval (10s in the units setup installs) and keeps a JSON state file —
`{"state","since","lastSeenOnline","lastTransition"}` — that the router reads
instead of probing itself. The router adds
the serving host and Mac state to `workspace_browser` results. Transitions are logged
to `mac-events.log` beside the state file.

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
`--user-data-dir`. The workspace VPS browser's CDP port is not fixed at
9223: `setup.sh` honors `--cdp-port`/`ALANS_WAY_CDP_PORT` and picks the
first free port at or above 9223 when that port is already taken, and the
chosen port is the `cdpUrl` in that config.json. Never point browser_exec
at it.

## Safety model (short version)

- Human takeover wins always: control epochs invalidate queued agent actions.
- Per-tab ownership is cooperative policy between bots sharing the connector —
  not a crypto boundary. See the [security note](https://github.com/capthvnsen/alans-way/blob/main/desktop/docs/integration.md)
  for the trust model before exposing a connector beyond `127.0.0.1`.
- Check-ins inject one internal prompt into the bound conversation, only
  inside the user's waking hours, and a `[SILENT]` reply is never delivered.
  The schedule is in `docs/proactivity.md`.

## Layout

```
alans-way/            the plugin (plugin.yaml + tool + idle-nudge and voice hooks + skills + router + mac-watch)
alans-way/skills/     workspace-setup, workspace-operations, web-errands and integrations (with recipes)
deploy/               systemd unit for the Mac availability watcher, example browser_exec Chromium unit
alans-way-computer/   the computer-use provider plugin (approval-gated computer_use)
docs/                 proactivity and voice guides, agent-driven setup prompt
docs/catalog/         Hermes plugin-catalog entry drafts (alans-way-computer.yaml)
scripts/              check_publication.py, the pre-publication secret and path check CI runs;
                      voice_eval.py, a local-only model-judged eval of the texting voice
tests/                unittest suite — python3 -m unittest discover -s tests
setup.sh              one-command bootstrap (install, wire, restart, bind, verify)
setup-workspace.sh    per-bot mcp_servers config writer (called by setup.sh)
bootstrap-orgo.sh     fresh Orgo computer -> Hermes + alans-way + Tailscale
migrate.sh            move an existing ~/.hermes to a new computer over ssh
```

## Roadmap

The roadmap lives in the
[Alan's Way GitHub project](https://github.com/users/capthvnsen/projects/5).
Fastest updates are on X: [@alexhvnsen](https://x.com/alexhvnsen).

## Tests

```sh
python3 -m unittest discover -s tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request and
[SECURITY.md](SECURITY.md) to report a vulnerability.

## License

MIT — see [LICENSE](LICENSE).
