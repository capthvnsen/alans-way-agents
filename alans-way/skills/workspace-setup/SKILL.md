---
name: workspace-setup
description: Set up Alan's Way after this plugin is installed — connect the user's computer (Mac or Windows PC), install the desktop app, wire the workspace browser, and bind proactivity. Use when the user asks to install, connect, onboard, or repair Alan's Way.
---

# Workspace setup

This plugin is the piece that runs inside Hermes. The desktop app and the
machine-to-machine setup live in a separate repo. Do not copy that app into
this plugin, and do not replace this plugin with a git checkout.

The user's computer may be a Mac (`--host-os mac`, the default) or a Windows
PC (`--host-os windows`). The computer Hermes runs on may be a Linux VPS or a
macOS virtual machine. Host scripts differ per OS — use `connect-mac.sh` on a
Mac and `connect-windows.ps1` on Windows; everything else in this skill is the
same.

## Drive the other repo; don't reimplement it

Fetch this page and follow it for Tailscale, the Mac app, and SSH keys. Both
remotes stay pinned to the commits the catalog submission was reviewed
against — do not substitute `main` or a newer tip:

https://raw.githubusercontent.com/capthvnsen/alans-way/13f50f0be5cabaca56989b8bbc0d020c37e034bb/docs/setup-prompt.md

Repo: https://github.com/capthvnsen/alans-way

The Mac app requires an Apple Silicon Mac; the Windows app requires Windows
10/11 x64. This plugin is already installed, so do not run a `setup.sh` line
from that page that omits `--skip-plugin`. Use this command instead.
`--non-interactive` means you do not wait for `setup.sh` prompts; ask the
proactivity question yourself first. Add `--profile <name>` unless the profile
is `default`, and `--host-os windows` when the user's computer is a PC.

```sh
git clone https://github.com/capthvnsen/alans-way-agents ~/alans-way-agents
git -C ~/alans-way-agents checkout 80aa518049b89c42c84ce642f2a7fefc03ba7a41
~/alans-way-agents/setup.sh --skip-plugin \
    --desktop-ref 13f50f0be5cabaca56989b8bbc0d020c37e034bb \
    --bot-id <numeric-telegram-bot-id> \
    --mac-ssh <user>@<host> --host-os <mac|windows> \
    --timezone <IANA-zone> --non-interactive \
    --bind --proactive <yes|no> [--profile <name>] --restart
```

`setup.sh` is idempotent. Re-run it, or run `setup.sh --verify` alone, to
audit. If it asks which Telegram route is the primary, pick the bot matching
the conversation you're in unless the user said otherwise — do not bind a
different bot's route silently.

## Order of work

1. **Tailscale first when the two machines can't see each other.** If the VPS
   can't reach the Mac (or vice versa) and neither is on a tailnet, install
   `tailscale`/`tailscaled`, `tailscale up`, and report both tailnet addresses.
   Use the tailnet name for `--mac-ssh`, not a public IP.
2. **Telegram gateway must exist before the plugin matters.** If the script
   reports no `TELEGRAM_BOT_TOKEN`, tell the user to run
   `hermes gateway setup` → Telegram → Automatic (QR scan) — that step needs a
   human holding a phone; don't work around it.
3. **SSH trust runs both ways, with pinned keys.** This host reaches the
   user's computer for the browser and the computer reaches back for its
   preview and path test, all with `BatchMode=yes` and
   `StrictHostKeyChecking=yes`. Have the human run the connect script from the
   alans-way repo on their computer with this host's address, host key and
   public key — `scripts/connect-mac.sh` on a Mac, or
   `scripts/connect-windows.ps1` in an elevated PowerShell on Windows (it
   installs OpenSSH Server and sets PowerShell as the default shell); it
   prints the values to pin here. On Windows, computer-use calls run through
   the app's local API — an SSH session cannot reach the desktop — so the app
   must be running for computer control even when the PC is reachable.
   Follow the steps in the app's `docs/setup-prompt.md`. Never use
   `StrictHostKeyChecking=accept-new` or ask for a password.
4. **The display stack is guided, never auto-installed.** On a Linux guest
   that means X11/VNC — if the bootstrap prints display-stack instructions,
   relay them verbatim; browser services without a display fail-loop quietly.
   A macOS guest needs no X11 — `scripts/mac-guest-services.sh` installs
   launchd agents, and the user grants Accessibility and Screen Recording
   once in the VM's System Settings (cannot be scripted; TCC is
   SIP-protected).
5. **Restart the gateway through its real owner.** `hermes gateway restart`
   first; if a PM/launchd supervisor owns it, let that supervisor restart it —
   never kill -9 a gateway mid-message.
6. **Bind only after a real DM route exists.** If no routes are listed, the
   user messages the bot once, then `setup.sh --bind`.

## Report, don't claim

After `setup.sh` finishes, run `setup.sh --verify` and report its summary
verbatim: plugin installed, hook present, browser host state, managed config
block, and any FAIL lines. "Installed" means the verify output says so — not
that the commands ran without visible errors.
