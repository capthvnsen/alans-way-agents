# Security policy

This is an alpha. Review the plugin folder and `setup.sh` before running them on a host that holds real accounts.

## Scope

The plugin runs inside your existing Hermes gateway. It adds workspace browser tools, a Mac/VPS router, a Mac availability watcher, and optional proactive check-ins. It stores no credentials and patches no Hermes source.

- **Browser control.** Bots can drive tabs on your Mac and the VPS through the Alan's Way app. Human takeover always wins, but per-tab ownership between bots is cooperative policy, not a cryptographic boundary. Read the app's [trust model](https://github.com/capthvnsen/alans-way/blob/main/desktop/docs/integration.md) before exposing a connector beyond `127.0.0.1`.
- **Proactivity.** A due check-in injects one internal prompt into the one bound conversation — the reply is an ordinary bot turn, limited to your waking hours, and `[SILENT]` replies are never delivered (`docs/proactivity.md`). Check-ins are off until you bind a route.

## SSH and host identity

- The VPS reaches your Mac over SSH you set up yourself. Every hop uses `BatchMode=yes` and `StrictHostKeyChecking=yes`; do not disable host-key checking to work around a connection error.
- Use a dedicated key, and prefer a private network such as Tailscale. SSH login may still grant broad shell access even though the tools themselves are narrow.
- Never share or commit private keys, bot tokens, session databases, transcripts, browser profiles or raw logs.

## Reporting

For an exploitable vulnerability, use GitHub's private vulnerability reporting on this repository. If it is unavailable, open a minimal issue asking for a private channel, without exploit details, keys, logs, machine addresses or transcripts. Non-sensitive bugs can be reported publicly with synthetic fixtures.
