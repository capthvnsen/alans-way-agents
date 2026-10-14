---
name: workspace-setup
description: Set up the Alan's Way Plugin after this plugin is installed: connect the user's computer (Mac, Windows PC or Linux), install the Alan's Workspace desktop app, wire the workspace browser, and bind proactivity. Use when the user asks to install, connect, onboard, or repair Alan's Way.
---

# Workspace setup

This plugin is the piece that runs inside Hermes. Alan's Workspace (the desktop app) and the
machine-to-machine setup live in a separate repo. Do not copy that app into
this plugin, and do not replace this plugin with a git checkout.

The user's computer may be a Mac (`--host-os mac`, the default), a Windows
PC (`--host-os windows`) or a Linux desktop (`--host-os linux`). The computer
Hermes runs on may be a Linux VPS, a macOS virtual machine or a Windows PC. Host scripts
differ per OS: use `connect-mac.sh` on a Mac, `connect-windows.ps1` on Windows
and `connect-linux.sh` on Linux; everything else in this skill is the same.

## Drive the other repo; don't reimplement it

Fetch this page and follow it for Tailscale, the Mac app, and SSH keys. Both
remotes stay pinned to the commits the catalog submission was reviewed
against: do not substitute `main` or a newer tip. This repo's clone is pinned
to the commit this install was reviewed and checked out at. A catalog install
records that sha in the profile's `plugins/.install-metadata.json`; read it,
check it out and hand it to `setup.sh` as `--repo-ref`, which hard-stops if
the clone is not at that commit: fix the checkout, never drop the flag. Only
when there is no catalog record (a manual or developer install) is the pin the
release tag matching this plugin's `version:` field in plugin.yaml (`v` + that
version): the tag must exist, and if the clone cannot resolve it the release
was never tagged, so stop and report instead of checking out `main`.

https://raw.githubusercontent.com/capthvnsen/alans-way/31ac0de9ee22307e2df03feb08a5e5217a90243b/docs/setup-prompt.md

Repo: https://github.com/capthvnsen/alans-way

The Mac app requires an Apple Silicon Mac; the Windows app requires Windows
10/11 x64. This plugin is already installed, so do not run a `setup.sh` line
from that page that omits `--skip-plugin`. Use this command instead.
`--non-interactive` means you do not wait for `setup.sh` prompts; ask the
proactivity question yourself first. The bots text on Telegram in the plugin's
texting voice by default; pass `--tone default` only when the user asked for
Hermes' own voice (they can also send `/tone default` any time). Add `--profile <name>` unless the profile
is `default`. Give `--mac-ssh` the computer's Tailscale name or IP; `setup.sh`
refuses anything else.

**Messages while working (before setup and the gateway restart).** For each
Telegram profile using this plugin, read `hermes -p <profile> config get
display.busy_input_mode` (use `-p default` for the default profile). Use the
effective value, including Hermes's defaults when no key is stored. If it is
already `steer` or `queue`, continue without asking. Preserve unknown values and
unreadable config. If it is `interrupt`, first read `hermes -p <profile> config
get skills.config.workspace-setup.busy_input_choice`. A recorded `keep-interrupt`
means the user already chose to keep it; continue without asking or rewriting
busy mode. An absent marker means ask once in plain words:
“When you message me while I'm working, should I fold it into the current task (recommended) or stop and start over?”
Explain that the choice applies to every platform in that profile and takes
effect after the current step finishes; guidance waits for the current tool
batch to return. Apply only the answered choice with the supported CLI:
`hermes -p <profile> config set display.busy_input_mode steer` for folding it
in, or `hermes -p <profile> config set display.busy_input_mode interrupt` for
stopping and starting over. Read back that key and report a failure before
continuing. Never treat silence or non-interactive runs as consent; with no
answer, leave the mode and marker untouched and continue the other setup work.
General setup or proactivity consent does not answer this question.

Use no marker for `steer`: the value itself makes this check stateless. To avoid
re-asking a user who explicitly keeps `interrupt` on every setup rerun, disclose
that you will remember that answer in this profile's `config.yaml`, then run
`hermes -p <profile> config set skills.config.workspace-setup.busy_input_choice keep-interrupt`
only after that answer and a successful mode readback. If the marker cannot be
read except for a confirmed “Config key not set” result, skip the question and
report the unknown state. If its write fails, report that the answer could not
be remembered; never invent a successful choice. This marker records only the
setup answer: never restore a mode from it or override later user changes.
The user can explicitly revisit the choice at any time, or remove the marker
with `hermes -p <profile> config unset skills.config.workspace-setup.busy_input_choice`.

**Acknowledgment while folding messages in.** When the effective busy mode is
`steer`, first read `hermes -p <profile> config get display.platforms.telegram.busy_steer_ack_enabled`.
Hermes resolves the effective Telegram setting in this order: platform override
→ global value → Telegram default → global default (currently `true`), per
[`gateway/display_config.py:117`](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1c093e992a8d838ed77ea320fbd8e51/gateway/display_config.py#L117).
If a non-null Telegram override exists, skip the offer and leave both the global
setting and marker untouched, even when the global value is false or the marker
is `own-ack`. Tell the user the override remains: for `true`, Telegram's extra
bubble remains on; for `false`, Telegram's extra bubble is already off. For an
unknown value or unreadable config, report the unknown state and skip this choice.
Only a confirmed “Config key not set” or `null` permits inheriting the global
value. Then read `hermes -p <profile> config get display.busy_steer_ack_enabled`
and `hermes -p <profile> config get skills.config.workspace-setup.busy_steer_ack_choice`.
Use the resolver's defaults for an absent/null global value. If the acknowledgment
is already off, or the marker is `keep-ack` or `own-ack`, continue without asking
or restoring a setting. Preserve unknown values and unreadable config; an absent
marker must be a confirmed “Config key not set” result. Otherwise ask once:
“Want just my own acknowledgment when you add something while I'm working?”
Explain that this removes Hermes' extra status bubble on Telegram and the other
platforms that inherit the global setting. Explicit overrides on other platforms
remain unchanged and may keep their extra bubbles. Your own short reply will
acknowledge the addition, and you will remember the answer in this profile's
config. Only after yes, run
`hermes -p <profile> config set display.busy_steer_ack_enabled false` and
read back the acknowledgment setting before recording `own-ack`:
Re-read the Telegram override first, then the global key, resolving them in the
same order. Only when the effective Telegram value is confirmed false and the
global readback is false, record `own-ack` with
`hermes -p <profile> config set skills.config.workspace-setup.busy_steer_ack_choice own-ack`.
If an override appeared, preserve it and disclose its effect; if the effective
value is true or unknown, report the mismatch and leave the marker untouched.
An explicit no records `keep-ack` with the same marker key and preserves the
acknowledgment setting. Report failed writes/readbacks; with no answer, leave
the acknowledgment setting and marker untouched. General setup or busy-mode
consent is not this answer. The user can revisit it or unset the marker via
`hermes -p <profile> config unset skills.config.workspace-setup.busy_steer_ack_choice`.
Hermes `6e7b83a2f1` supports this switch:
[`gateway/display_config.py:28`](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1/gateway/display_config.py#L28),
[`gateway/run_busy.py:893`](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1/gateway/run_busy.py#L893).
It suppresses the bubble after the message is processed; it does not disable
steering. Neither setup script writes this display setting or its marker.

**Interim messages.** Read `hermes -p <profile> config get
display.interim_assistant_messages`. Hermes defaults to `true` at commit
`d97007c32d6340f7ba79ac1dfb5773cc00846448` (which includes `6e7b83a2f1`),
[`hermes_cli/config_defaults.py:919`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/hermes_cli/config_defaults.py#L919).
Only when the effective value is `false`, report that the user's choice disables
interim messages; preserve it and any platform override. Write nothing for this
key. Neither `setup.sh` nor `setup-workspace.sh` writes these two display keys;
the busy-mode choice and marker above are written only through the Hermes CLI
after the user answers.

```sh
git clone https://github.com/capthvnsen/alans-way-agents ~/alans-way-agents
# The commit this install was reviewed and checked out at, from Hermes' own
# install record (empty when the plugin was not installed from the catalog).
# Inside a profile's gateway HERMES_HOME already points at that profile's home;
# outside it, for --profile <name> read profiles/<name>/plugins/ instead.
PIN=$(python3 -c 'import json, os, re
home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
try:
    row = json.load(open(os.path.join(home, "plugins", ".install-metadata.json"))).get("alans-way", {})
except Exception:
    row = {}
cat = row.get("catalog") if isinstance(row, dict) else {}
sha = str((cat or {}).get("sha") or (cat or {}).get("pin") or "")
print(sha if re.fullmatch(r"[0-9a-fA-F]{40}", sha) else "")')
# No catalog record: the release tag is the pin. It must exist; if the checkout
# below cannot resolve it the tag was never pushed, so stop and report.
[ -n "$PIN" ] || PIN=v0.21.5
git -C ~/alans-way-agents checkout "$PIN"
~/alans-way-agents/setup.sh --skip-plugin \
    --repo-ref "$PIN" \
    --desktop-ref 31ac0de9ee22307e2df03feb08a5e5217a90243b \
    --bot-id <numeric-telegram-bot-id> \
    --mac-ssh <user>@<host> --host-os <mac|windows|linux> \
    --timezone <IANA-zone> --non-interactive \
    --bind --proactive <yes|no> [--tone default] [--profile <name>] --restart
```

`setup.sh` is idempotent. Re-run it, or run `setup.sh --verify` alone, to
audit. With `--restart` it restarts the gateway last, detached, about ten
seconds after it prints its summary. If it asks which Telegram route is the primary, pick the bot matching
the conversation you're in unless the user said otherwise: do not bind a
different bot's route silently.

**Long chats (before the gateway restart).** Hermes can prune old tool output early to reduce context buildup without another summarizer. For each Alan's Way profile, follow [the long-chat setup procedure](references/long-chats.md): report the effective compression threshold and `auxiliary.compression` route, then obtain explicit user consent before enabling pruning at 48,000 tokens with 8,000-character eligibility and 4,096-token minimum reclaim. Preserve customized values, leave `micro_compact` unchanged, and use the supported profile-scoped Hermes config CLI. Only suggest a dedicated summary model; never switch it automatically.

## Order of work

1. **Tailscale first when the two machines can't see each other.** If the VPS
   can't reach the Mac (or vice versa) and neither is on a tailnet, install
   `tailscale`/`tailscaled`, `tailscale up`, and report both tailnet addresses.
   Use the tailnet name for `--mac-ssh`, not a public IP.
2. **Telegram gateway must exist before the plugin matters.** If the script
   reports no `TELEGRAM_BOT_TOKEN`, tell the user to run
   `hermes gateway setup` → Telegram → Automatic (QR scan): that step needs a
   human holding a phone; don't work around it.
3. **SSH trust runs both ways, with pinned keys.** This host reaches the
   user's computer for the browser and the computer reaches back for its
   preview and path test, all with `BatchMode=yes` and
   `StrictHostKeyChecking=yes`. Have the human run the connect script from the
   alans-way repo on their computer with this host's address, host key and
   public key: `scripts/connect-mac.sh` on a Mac, `scripts/connect-linux.sh`
   on Linux, or `scripts/connect-windows.ps1` in an elevated PowerShell on
   Windows (it installs OpenSSH Server and sets PowerShell as the default
   shell). It prints `MAC_KEY` and `MAC_HOST_KEY` to pin here: pass them to
   `setup.sh` as `--mac-key "<MAC_KEY>"` and `--mac-host-key "<MAC_HOST_KEY>"`
   (with `--mac-ssh`). It checks that each is one plain public key line and
   adds it once; do not append pasted values to the SSH key list or
   the known-hosts list yourself. On Windows, computer-use calls run through
   the app's local API: an SSH session cannot reach the desktop: so the app
   must be running for computer control even when the PC is reachable.
   Follow the steps in the app's `docs/setup-prompt.md`. Never use
   `StrictHostKeyChecking=accept-new` or ask for a password.
4. **A Windows guest runs `setup.sh` from Git Bash.** Hermes' terminal tool
   already uses Git Bash on native Windows, so run the same command there (WSL2
   counts as Linux). It needs Node 22+, Python 3 (or `HERMES_PYTHON` pointing at
   a `python.exe`), Tailscale and Chrome or Edge. It registers Scheduled Tasks
   instead of systemd units, which start at logon, so tell the user to keep the PC
   awake and turn on automatic sign-in (`netplwiz`). Relay the OpenSSH Server lines
   it prints verbatim: they need an elevated PowerShell that only the human can open.
5. **The display stack is guided, never auto-installed.** On a Linux guest
   that means X11/VNC: if the bootstrap prints display-stack instructions,
   relay them verbatim; browser services without a display fail-loop quietly.
   A macOS guest needs no X11: `scripts/mac-guest-services.sh` installs
   launchd agents, and the user grants Accessibility and Screen Recording
   once in the VM's System Settings (cannot be scripted; TCC is
   SIP-protected).
   When a VNC server and a websockify/noVNC bridge already run on this
   host, the app's VM preview needs wiring, not packages: find the
   websockify listener (`ss -ltn`, or the supervisor's program list) and
   report `http://<this host's tailnet IP>:<its port>/vnc.html`, plus where
   the VNC password lives (the VNC server's `-PasswordFile` argument, or the
   startup config that writes it). The human pastes the URL and password
   into the app's Settings (Remote desktop connection); tell them where the
   password is, do not paste its value into chat.
6. **The gateway restart ends your own session, so it comes last.** You are
   most likely running inside this gateway. `setup.sh --restart` installs,
   binds, sets the timezone and verifies first, prints its summary, and only
   then schedules the restart, detached, about ten seconds later. As soon as
   `setup.sh` returns, send your final message to the user with the summary and
   what to check next, and start no further tool calls: the restart can cut the
   conversation off. It goes through the gateway's real owner (`hermes gateway
   restart`, or the supervisor that owns it), so never kill -9 a gateway
   mid-message. Restarting one by hand on a supervisord host: `supervisorctl
   restart` escalates SIGTERM to SIGKILL after `stopwaitsecs` (10s by default)
   and a kill mid-checkpoint corrupts the gateway's `state.db` — signal the drain
   instead (`supervisorctl signal USR1 <program>` on the program whose command
   runs `hermes gateway run`), wait for the new pid, and use `start`/`restart`
   only as fallbacks. If the restart was skipped, a check failed: say which one.
7. **Bind only after a real DM route exists.** If no routes are listed, the
   user messages the bot once, then `setup.sh --bind`. By hand:
   `hermes proactivity bind --session-key '<key>' --timezone <IANA-zone>`,
   tune with `hermes proactivity set --settings '<json>'`, and check with
   `hermes proactivity status`.
   After setup binds successfully, the same primary DM becomes Hermes' Telegram
   home channel for scheduled and cross-platform delivery. Setup uses the
   profile-scoped `config set TELEGRAM_HOME_CHANNEL` interface and clears an old
   topic with `config set TELEGRAM_HOME_CHANNEL_THREAD_ID ''`; this loads on
   gateway restart. Hermes `6e7b83a2f1` reads these settings at
   [`config_env.py:515`](https://github.com/NousResearch/hermes-agent/blob/6e7b83a2f1/gateway/config_env.py#L515).
   If you bound by hand or setup reports a home-channel failure, tell the user
   to send `/sethome` in that DM and check the confirmation before claiming
   delivery is ready.

## Moved your agent to a new VM?

The VM's address is saved in several places and they mostly do not update
each other. After a move, check each one; a stale copy fails quietly:

- **The app's Settings** on the user's computer: the VM SSH host and the
  Remote desktop URL are separate fields (`vpsBrowser.sshHost` and
  `remoteUrl` in the app's `preferences.json`, under `Hermes Workspace` in
  the app-data directory, readable over the same ssh path the workspace
  uses). Current builds re-derive the URL when it was empty or still on
  the old host; repoint it only if it was meant to follow the VM and
  stayed stale: `http://<new tailnet IP>:<websockify port>/vnc.html`. A
  URL that names the same VM differently (a MagicDNS name where the SSH
  host uses the tailnet IP) never auto-follows, so check it by eye.
- **The Hermes desktop app's saved remote**, on each computer that runs
  it: `connection.json` and `connections.json` under the `Hermes` app-data
  directory keep the old VM's URL until a new remote is saved. A stale
  entry is inert until remote mode is selected.
- **Any phone client**: the saved server URL lives only on the device; the
  user updates it there.
- **The VM's API server binding**: `API_SERVER_HOST` in `~/.hermes/.env` or
  `platforms.api_server` in `config.yaml`. Pinned to the old tailnet
  address it fails to bind (`Could not bind` in `gateway.log`); `ss -tln`
  shows where it actually listens.
- **`tailscale serve` exposure**: `tailscale serve status` on the new VM;
  nothing published on the old host follows. Republish the ports the
  preview or remote mode needs.

## Report, don't claim

`setup.sh` ends with its own Verify section before the restart. Report that
output verbatim in your final message: plugin enabled, workspace browser block,
browser host state, and any FAIL lines. "Installed" means the verify output
says so, not that the commands ran without visible errors. After the gateway has
restarted (the next time the user writes to you), run `setup.sh --verify` for a
full audit of the running install. Remind the user that check-ins are on once bound and are
tuned by talking to the bot ("stop checking in" pauses them; `/proactivity resume` starts them
again), and that desktop control asks
for approval per action unless they re-run setup with `--allow-desktop-actions`
(offer that, never add it yourself: on a Hermes without the computer-use
provider API it also exposes a desktop-input tool that runs with no approval
at all). Tell the user that setup turned off Hermes'
built-in browser toolset for Telegram and cron so you use their workspace
browser, and that `--keep-browser` undoes that. Setup never turns off the
built-in `computer_use` toolset: desktop input always goes through it. If setup
warns about a `cua-driver` MCP server the user added, leave it and tell them the
`hermes -p <profile> mcp remove <name>` command from the warning.
