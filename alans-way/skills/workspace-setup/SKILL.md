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
Hermes runs on may be a Linux VPS or a macOS virtual machine. Host scripts
differ per OS: use `connect-mac.sh` on a Mac, `connect-windows.ps1` on Windows
and `connect-linux.sh` on Linux; everything else in this skill is the same.

## Drive the other repo; don't reimplement it

Fetch this page and follow it for Tailscale, the Mac app, and SSH keys. Both
remotes stay pinned to the commits the catalog submission was reviewed
against: do not substitute `main` or a newer tip:

https://raw.githubusercontent.com/capthvnsen/alans-way/0a22055b534b847fab8f3e617a5c80f65af93622/docs/setup-prompt.md

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
git -C ~/alans-way-agents checkout 756500daf159a9b11ddf03849b5378162f41d179
~/alans-way-agents/setup.sh --skip-plugin \
    --desktop-ref 0a22055b534b847fab8f3e617a5c80f65af93622 \
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
   adds it once; do not append pasted values to `authorized_keys` or
   `known_hosts` yourself. On Windows, computer-use calls run through
   the app's local API: an SSH session cannot reach the desktop: so the app
   must be running for computer control even when the PC is reachable.
   Follow the steps in the app's `docs/setup-prompt.md`. Never use
   `StrictHostKeyChecking=accept-new` or ask for a password.
4. **The display stack is guided, never auto-installed.** On a Linux guest
   that means X11/VNC: if the bootstrap prints display-stack instructions,
   relay them verbatim; browser services without a display fail-loop quietly.
   A macOS guest needs no X11: `scripts/mac-guest-services.sh` installs
   launchd agents, and the user grants Accessibility and Screen Recording
   once in the VM's System Settings (cannot be scripted; TCC is
   SIP-protected).
5. **The gateway restart ends your own session, so it comes last.** You are
   most likely running inside this gateway. `setup.sh --restart` installs,
   binds, sets the timezone and verifies first, prints its summary, and only
   then schedules the restart, detached, about ten seconds later. As soon as
   `setup.sh` returns, send your final message to the user with the summary and
   what to check next, and start no further tool calls: the restart can cut the
   conversation off. It goes through the gateway's real owner (`hermes gateway
   restart`, or the supervisor that owns it), so never kill -9 a gateway
   mid-message. If the restart was skipped, a check failed: say which one.
6. **Bind only after a real DM route exists.** If no routes are listed, the
   user messages the bot once, then `setup.sh --bind`.

## Report, don't claim

`setup.sh` ends with its own Verify section before the restart. Report that
output verbatim in your final message: plugin enabled, workspace browser block,
browser host state, and any FAIL lines. "Installed" means the verify output
says so, not that the commands ran without visible errors. After the gateway has
restarted (the next time the user writes to you), run `setup.sh --verify` for a
full audit of the running install. Remind the user that a proposed watch only runs once they approve it with the
Telegram button or `/watch approve <id> <code>`, and that desktop control asks
for approval per action unless they re-run setup with `--allow-desktop-actions`
(offer that, never add it yourself). Tell the user that setup turned off Hermes'
built-in browser toolset for Telegram so you use their workspace browser, and
that `--keep-browser` undoes that.
