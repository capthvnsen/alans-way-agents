---
name: workspace-setup
description: Set up Alan's Way after this plugin is installed: connect the user's computer (Mac, Windows PC or Linux), install the desktop app, wire the workspace browser, and bind proactivity. Use when the user asks to install, connect, onboard, or repair Alan's Way.
---

# Workspace setup

This plugin is the piece that runs inside Hermes. The desktop app and the
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

https://raw.githubusercontent.com/capthvnsen/alans-way/9bcce44224b9f478282209c32ea8eb87aba189f3/docs/setup-prompt.md

Repo: https://github.com/capthvnsen/alans-way

The Mac app requires an Apple Silicon Mac; the Windows app requires Windows
10/11 x64. This plugin is already installed, so do not run a `setup.sh` line
from that page that omits `--skip-plugin`. Use this command instead.
`--non-interactive` means you do not wait for `setup.sh` prompts; ask the
proactivity question yourself first. Add `--profile <name>` unless the profile
is `default`. Give `--mac-ssh` the computer's Tailscale name or IP; `setup.sh`
refuses anything else.

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
[ -n "$PIN" ] || PIN=v0.7.0
git -C ~/alans-way-agents checkout "$PIN"
~/alans-way-agents/setup.sh --skip-plugin \
    --repo-ref "$PIN" \
    --desktop-ref 9bcce44224b9f478282209c32ea8eb87aba189f3 \
    --bot-id <numeric-telegram-bot-id> \
    --mac-ssh <user>@<host> --host-os <mac|windows|linux> \
    --timezone <IANA-zone> --non-interactive \
    --bind --proactive <yes|no> [--profile <name>] --restart
```

`setup.sh` is idempotent. Re-run it, or run `setup.sh --verify` alone, to
audit. With `--restart` it restarts the gateway last, detached, about ten
seconds after it prints its summary. If it asks which Telegram route is the primary, pick the bot matching
the conversation you're in unless the user said otherwise: do not bind a
different bot's route silently.

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
   mid-message. If the restart was skipped, a check failed: say which one.
7. **Bind only after a real DM route exists.** If no routes are listed, the
   user messages the bot once, then `setup.sh --bind`. By hand:
   `hermes proactivity bind --session-key '<key>' --timezone <IANA-zone>`,
   tune with `hermes proactivity set --settings '<json>'`, and check with
   `hermes proactivity status`.

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
