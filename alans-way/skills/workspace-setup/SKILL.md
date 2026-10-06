---
name: workspace-setup
description: Set up Alan's Way after this plugin is installed — connect a Mac, install the desktop app, wire the workspace browser, and bind proactivity. Use when the user asks to install, connect, onboard, or repair Alan's Way.
---

# Workspace setup

This plugin is the piece that runs inside Hermes. The Mac app and the
machine-to-machine setup live in a separate repo. Do not copy that app into
this plugin, and do not replace this plugin with a git checkout.

## Drive the other repo; don't reimplement it

Fetch and follow this page exactly. Its text block is the setup:

https://raw.githubusercontent.com/capthvnsen/alans-way/main/docs/setup-prompt.md

Repo: https://github.com/capthvnsen/alans-way

That page connects Tailscale, installs the Mac app, and pins SSH keys. When
it tells you to run `setup.sh` from `alans-way-agents`, clone that repo only
to run the script, and pass `--skip-plugin` so this installed copy stays in
place:

```sh
git clone https://github.com/capthvnsen/alans-way-agents ~/alans-way-agents
~/alans-way-agents/setup.sh --skip-plugin --bot-id <numeric-telegram-bot-id> \
    --mac-ssh <user>@<mac-host> --timezone <IANA-zone> --non-interactive \
    --bind --proactive <yes|no> --restart
```

`setup.sh` is idempotent. Re-run it, or run `setup.sh --verify` alone, to
audit. Follow its prompts. If it asks which Telegram route is the primary,
pick the bot matching the conversation you're in unless the user said
otherwise — do not bind a different bot's route silently.

## Order of work

1. **Tailscale first when the two machines can't see each other.** If the VPS
   can't reach the Mac (or vice versa) and neither is on a tailnet, install
   `tailscale`/`tailscaled`, `tailscale up`, and report both tailnet addresses.
   Use the tailnet name for `--mac-ssh`, not a public IP.
2. **Telegram gateway must exist before the plugin matters.** If the script
   reports no `TELEGRAM_BOT_TOKEN`, tell the user to run
   `hermes gateway setup` → Telegram → Automatic (QR scan) — that step needs a
   human holding a phone; don't work around it.
3. **SSH trust runs both ways, with pinned keys.** The VPS reaches the Mac
   for the browser and the Mac reaches the VPS for its preview and path test,
   all with `BatchMode=yes` and `StrictHostKeyChecking=yes`. Have the human
   paste `scripts/connect-mac.sh` from the alans-way repo on the Mac with this
   VPS's address, host key and public key; it prints the Mac's values to pin
   here. Follow the steps in the app's `docs/setup-prompt.md`. Never use
   `StrictHostKeyChecking=accept-new` or ask for a password.
4. **The X11/VNC desktop stack is guided, never auto-installed.** If the
   bootstrap prints display-stack instructions, relay them verbatim. Browser
   services without a display fail-loop quietly.
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
