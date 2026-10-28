# Alan's Way Plugins

[![Discord](https://img.shields.io/badge/Discord-Alan's%20Way-5865F2?logo=discord&logoColor=white)](https://discord.gg/jBQCPUsVE)
[![GitHub stars](https://img.shields.io/github/stars/capthvnsen/alans-way?style=social)](https://github.com/capthvnsen/alans-way)

**Questions, setup help and release news: join the [Alan's Way Discord](https://discord.gg/jBQCPUsVE).**
Also on X: [@alexhvnsen](https://x.com/alexhvnsen) · [openalan.com](https://openalan.com)

Two plugins that add a workspace browser, computer use, proactive check-ins and a
texting voice to the production Hermes you already run. There's no fork and no
patched Hermes source, and no second gateway: your Telegram gateway keeps owning
the conversation. Current release: **v0.21.13**.

| Plugin | What it adds to Hermes |
|---|---|
| [`alans-way/`](alans-way/README.md) | The `workspace_browser` MCP router (your computer's browser, with the VM browser as failover), the commit gate on purchases, sends and deletes, idle check-ins, the texting voice, and the `workspace-setup`, `workspace-operations`, `web-errands` and `integrations` skills |
| [`alans-way-computer/`](alans-way-computer/README.md) | A provider for Hermes' stock, approval-gated `computer_use` tool. It drives desktop apps on your computer through the app, and the VM desktop when your computer is offline |

The desktop app, Alan's Workspace, lives at
[capthvnsen/alans-way](https://github.com/capthvnsen/alans-way) (download at
[openalan.com](https://openalan.com)). This repo installs on the machine that runs
your Hermes agents: a Linux VPS, a macOS VM, or a Windows PC you keep on. The
app runs on your own computer (Mac or Windows). Tailscale connects the two, and
every SSH hop runs over your tailnet.

## The seven core features

| # | Feature | What this repo provides | Status |
|---|---|---|---|
| 1 | Simple chat on the left, plus a browser like the one in the ChatGPT desktop app | The chat and the browser are the app. This repo routes the agent's tabs into that browser: each bot owns its own tabs, and an on-page cursor shows the bot's name and color | Shipped |
| 2 | Codex-level computer use through MCP, on the local Mac and in the workspace browser, fast even for remote agents | `alans-way-computer` drives Mac apps through Hermes' `computer_use`, approved per action type in Telegram. Read-only `workspace_computer_*` tools and the `cua_alans_way_*` browser tools come over MCP, and one long-lived router serves each session. Other agents use the same router over [SSH through Tailscale](docs/remote-agents.md) | Shipped |
| 3 | Lid-close handoff of browser work to the VM | When your computer is unreachable, new browser work goes to the VM browser. If it drops mid-session, the router moves the session to the VM and rebuilds the bot's tabs from the app's mirror. The call in flight fails visibly and is never retried | Partial: carrying an in-flight action across, and a "Move to VM" button, are not shipped |
| 4 | Live view of the VM desktop | Setup checks for the VM's X11/VNC stack and prints what is missing. The `workspace-setup` skill hands the app a loopback viewer URL. The view itself is in the app | Shipped, but needs VNC and noVNC on the VM |
| 5 | The same threads on any device, through Telegram or the agent's own app | Both plugins run inside your existing Hermes gateway, so the Telegram thread you already have is the thread on every device. An agent with its own app (for example the Grok Bot app) keeps its own threads and reaches the workspace as a remote agent | Shipped |
| 6 | Add-on tools for production Hermes and Grok Bot, no forks | Hermes plugins plus bundled skills on stock Hermes `>= 0.21.5`. Non-Hermes agents get a router-restricted SSH key from `setup-remote-agent.sh` | Shipped |
| 7 | Proactivity | Idle check-ins in one bound Telegram chat after 2 hours of quiet, only between 08:00 and 22:00 in your timezone. The wait doubles after each unanswered check-in (capped at a week), and a `[SILENT]` reply is never sent. The morning brief and [cross-bot proactivity](docs/proactivity.md#cross-bot-proactivity) are both **off by default** | Shipped |

## Install

**Requirements.** On the host that runs your Hermes gateway: stock Hermes
`>= 0.21.5` with Telegram connected (`hermes gateway setup` → **Telegram →
Automatic**), python3, Node 22+, and Tailscale on both machines.

Desktop control through `alans-way-computer` also needs the pluggable
computer-use API, `tools.computer_use.backend.ComputerUseProvider`. That API
arrived in Hermes commit
[`63f5e0ea45726c5d8d7d207d140613997730aab3`](https://github.com/NousResearch/hermes-agent/commit/63f5e0ea45726c5d8d7d207d140613997730aab3),
and a version string alone does not establish it. Set `HERMES_PYTHON` to that
Hermes install's interpreter so setup can probe it. "API absent" means the
provider class is missing. "probe failed" or "timed out" means support is
unknown. Browser setup finishes either way.

**Easiest:** paste the [setup prompt](docs/setup-prompt.md) to an agent with a
terminal on the VM (your Hermes bot works). It connects the VM and your
computer over Tailscale, runs `setup.sh`, and proves both ends work.

**Or run the bootstrap yourself** on the host that runs your Hermes gateway:

```sh
curl -fsSL https://raw.githubusercontent.com/capthvnsen/alans-way-agents/main/setup.sh | bash -s -- \
    --bot-id YOUR_NUMERIC_BOT_ID --mac-ssh you@your-computer --restart
```

`--mac-ssh` must be a Tailscale address. Add `--host-os windows` or
`--host-os linux` if your computer is not a Mac. `setup.sh` is idempotent, so
it is safe to re-run, and `--verify` audits without changing anything.

Then install the app: [Mac](https://openalan.com/download/mac) (signed and
notarized) or [Windows](https://openalan.com/download/windows) (unsigned:
**More info → Run anyway**). In the app, **Settings → Agent setup → Test agent path**.

Every flag, the Windows-PC-as-VM path, Orgo and fresh Linux hosts, `migrate.sh`,
and the plugin security review are in **[docs/install.md](docs/install.md)**.

## Upgrading

The app's update popup updates the app and the plugin on every saved VM over
SSH. To do it by hand, re-run the bootstrap (or `git pull`), then restart the
gateway through its owner: `hermes gateway restart`, or under supervisord
`supervisorctl signal USR1 <program>`. A plain `supervisorctl restart`
escalates to SIGKILL after `stopwaitsecs` and can corrupt `state.db` mid-checkpoint.
Details are in [docs/install.md](docs/install.md#upgrading).

## Safety

- **Commit gate.** Any browser action that buys, books, sends, posts, submits,
  deletes or changes an account runs only after you tap Approve in Telegram.
  The gate never retries, and it logs every decision. It protects against
  agent mistakes and prompt injection. It does not stop a deliberately hostile
  agent that also has shell access.
- **Desktop input** only goes through the approval-gated `computer_use` tool.
- **Human takeover wins.** When you take a tab back, any queued agent actions on it are cancelled.
- **Check-ins** never send external messages, spend money, change credentials
  or touch production without asking.

Full model: [docs/workspace-browser.md](docs/workspace-browser.md#safety-model-short-version).

## Docs

| Doc | Covers |
|---|---|
| [install.md](docs/install.md) | Setup steps and flags, Windows and Orgo hosts, `migrate.sh`, upgrading, security review |
| [workspace-browser.md](docs/workspace-browser.md) | Every tool and hook, the commit gate, router failover, the mac-watch availability watcher, web errands, integrations |
| [remote-agents.md](docs/remote-agents.md) | Giving Grok Bot or any MCP client the workspace: SSH over Tailscale, or the opt-in HTTP bridge |
| [proactivity.md](docs/proactivity.md) | Check-in schedule, tuning by chat, morning brief, cross-bot proactivity |
| [voice.md](docs/voice.md) | The texting voice and `/tone` |
| [long-chats.md](docs/long-chats.md) | Compaction and tool-output pruning |
| [addon-interface.md](docs/addon-interface.md) | Stable interface for add-on scripts run after `bootstrap-orgo.sh` |

## Layout

```
alans-way/            the main plugin: router, hooks, check-ins, voice, skills, remote-agent setup
alans-way-computer/   the computer-use provider plugin
docs/                 guides (above), catalog drafts, design notes
deploy/               systemd units for mac-watch and an optional browser_exec Chromium
scripts/              pre-publication secret check (CI) and local voice evals
tests/                python3 -m unittest discover -s tests
setup.sh              one-command bootstrap; setup-workspace.sh writes the per-bot MCP block
bootstrap-orgo.sh     fresh Orgo/Linux computer -> Hermes + alans-way + Tailscale
migrate.sh            move an existing ~/.hermes to a new computer over SSH
```

## Contributing

```sh
python3 -m unittest discover -s tests -v
```

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request, and
[SECURITY.md](SECURITY.md) to report a vulnerability. The roadmap is the
[Alan's Way GitHub project](https://github.com/users/capthvnsen/projects/5).
Come say hi on [Discord](https://discord.gg/jBQCPUsVE).

## License

MIT. See [LICENSE](LICENSE).
