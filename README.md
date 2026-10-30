# Alan's Plugin for Hermes

[![Discord](https://img.shields.io/badge/Discord-Alan's%20Way-5865F2?logo=discord&logoColor=white)](https://discord.gg/jBQCPUsVE)
[![GitHub stars](https://img.shields.io/github/stars/capthvnsen/alans-way?style=social)](https://github.com/capthvnsen/alans-way)

**Questions, setup help and release news: join the [Alan's Way Discord](https://discord.gg/jBQCPUsVE).**
Also on X: [@alexhvnsen](https://x.com/alexhvnsen) · [openalan.com](https://openalan.com)

Add a workspace browser, computer use, proactive check-ins and a texting voice to
the production Hermes you already run. Alan's Plugin for Hermes ships as two
Python plugin packages in this repo. Your existing Hermes gateway owns the
conversation; no fork or patched Hermes source is required. Current Hermes
plugin release: **v0.21.13**.

## The four Alan's Way products

| Product | What it is | Where it lives |
|---|---|---|
| **Alan's Workspace** | The Mac desktop app with chat and a browser, the iOS app, and lid-close VM handoff | [capthvnsen/alans-way](https://github.com/capthvnsen/alans-way) |
| **Alan's CU MCP** | The shared Node `workspace-mcp` computer-use server that any agent can connect to | [capthvnsen/alans-way](https://github.com/capthvnsen/alans-way) |
| **Alan's Plugin for Hermes** | Python plugins, hooks and skills for stock Hermes | This repo: [`alans-way/`](alans-way/README.md) and [`alans-way-computer/`](alans-way-computer/README.md) |
| **Alan's Plugin for Grok Bot** | A Grok Bot skill and settings package; Grok Bot cannot load Hermes plugins | This repo: [`alans-way-grok-bot/`](alans-way-grok-bot/README.md), currently a scaffold |

Both agent plugins target **one shared config contract** for persona, voice,
proactivity and identity: [`shared/`](shared/README.md). This change defines the
contract and Grok Bot scaffold only. Hermes does not yet read the shared JSON
config; its existing settings and runtime behavior stay as they are.

## What the Hermes plugin provides

| Plugin | What it adds to Hermes |
|---|---|
| [`alans-way/`](alans-way/README.md) | The `workspace_browser` MCP router (your computer's browser, with the VM browser as failover), the commit gate on purchases, sends and deletes, idle check-ins, the texting voice, and the `workspace-setup`, `workspace-operations`, `web-errands` and `integrations` skills |
| [`alans-way-computer/`](alans-way-computer/README.md) | A provider for Hermes' stock, approval-gated `computer_use` tool. It drives desktop apps on your computer through the app, and the VM desktop when your computer is offline |

Install these packages on the machine running your Hermes agents: a Linux VPS,
macOS VM or Windows PC you keep on. Tailscale connects that host to your own
computer, and every SSH hop runs over your tailnet. The app and CU MCP server
are separate products; these packages adapt Hermes to the workspace.

Browser work falls back to the VM when your computer is unreachable. A failed
call in flight is reported and never retried automatically; carrying that action
across and a "Move to VM" button are not shipped. The app's live VM view needs
VNC and noVNC on the VM.

Idle check-ins run in one bound Telegram chat after 2 hours of quiet, between
08:00 and 22:00 in your timezone. The wait doubles after each unanswered check-in
(capped at a week), and `[SILENT]` replies are not sent. The morning brief,
weekly report and [cross-bot proactivity](docs/proactivity.md#cross-bot-proactivity)
are **off by default**. Other MCP clients, including Grok Bot, connect through
the [remote-agent setup](docs/remote-agents.md); that connection does not install
Hermes hooks or implement the Grok Bot scaffold's preferences.

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
| [Shared config](shared/README.md) | Draft JSON Schema, example and reader contract for both agent plugins |
| [Grok Bot scaffold](alans-way-grok-bot/README.md) | Skill, settings reference and integration TODOs |

## Layout

```
alans-way/            the main plugin: router, hooks, check-ins, voice, skills, remote-agent setup
alans-way-computer/   the computer-use provider plugin
alans-way-grok-bot/   Grok Bot skill + settings scaffold (no Hermes plugin code)
shared/              one config schema, example and contract for both agent plugins
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

All four Alan's Way products—Alan's Workspace, Alan's CU MCP, Alan's Plugin for
Hermes and Alan's Plugin for Grok Bot—use the MIT License.
Copyright (c) 2026 Alex Hansen. See [LICENSE](LICENSE).
