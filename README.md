# Alan's Way — agent plugin

**The behavior half of [Hermes — Alan's Way](https://github.com/capthvnsen/alans-way).**
This repo is what you install *on the machine running your Hermes agents*
(usually a VPS). The companion repo holds the Mac desktop app — this one holds
what your agents need to think and act:

- **`alans-way/`** — a native Hermes plugin: one designated primary bot
  gets bounded, event-driven proactivity — reviewing its own work, watching
  approved tasks, and surfacing useful things to do, on a schedule you control.
- **`hooks/alans-way/`** — a gateway startup hook that arms the plugin
  only inside the real gateway process.
- **Workspace browser wiring** — `setup-workspace.sh` writes a managed
  `workspace_browser` block into your Hermes config pointing at
  `scripts/workspace-router.cjs`, which probes your Mac first and falls
  back to the VPS browser when the Mac is asleep.
- **`skills/`** — the `proactive-primary` and `workspace-operations` skills ship
  inside the plugin so agents know how to use the tools correctly.

Works with stock Hermes `>= 0.21`. No Hermes source is patched: your existing
Telegram gateway keeps owning the conversation exactly as before — the plugin
adds tools and an optional review loop inside it, it is not a second gateway.

## What it does and does not do

- **Two browser hosts, no silent migration.** Bots get per-tab Chromium access
  on the Mac (through the desktop app's connector) and on the VPS (the managed
  browser). When the Mac is unreachable, *new* browser work routes to the VPS
  host automatically. Work already in flight in a Mac tab blocks while the Mac
  is asleep and resumes when it returns — the live tab is not moved between
  machines. Watching the VPS desktop from inside the Mac app additionally needs
  a VNC server and a noVNC viewer that you run on the VPS; see the app repo's
  [deployment guide](https://github.com/capthvnsen/alans-way/blob/main/docs/deployment.md).
- **Proactivity is read/research/draft by default.** The designated primary may
  read its own state, research, and draft proposals inside bounded budgets and
  quiet hours. Consequential actions — sending external messages or posts,
  purchases, credential or permission changes, production changes, destructive
  operations, new scope — always ask first. Details in
  [docs/proactivity.md](docs/proactivity.md).
- **No bundled account connections.** Email, calendar, Notion and similar
  connectors exist for an agent only if you install and authorize them
  separately in Hermes; this plugin provisions none of them.

## Install

On the host that runs your Hermes gateway:

```sh
git clone https://github.com/capthvnsen/alans-way-agents
cd alans-way-agents

# 1. Plugin + bundled skills (tools, observer, /proactivity commands)
hermes plugins install "file://$(pwd)#alans-way"
# or straight from GitHub, no clone:
# hermes plugins install https://github.com/capthvnsen/alans-way-agents#alans-way

# 2. Gateway hook — arms proactivity only inside the gateway process
cp -r hooks/alans-way ~/.hermes/hooks/

# 3. Browser tools for one bot profile (repeat per bot)
./setup-workspace.sh --bot-id YOUR_BOT_ID --bot-name "Scout" \
    --mac-ssh you@your-mac --config ~/.hermes/config.yaml
```

Restart the gateway. `hermes plugins list` should show `alans-way`.

Upgrading is the same path: `git pull`, re-run `setup-workspace.sh` if its
flags changed, and restart the gateway — a running gateway keeps already
imported code until restarted. Then verify one ordinary Telegram reply and one
bounded browser action before relying on it.

### What each piece does

| Piece | Effect |
|---|---|
| `proactive_control` tool | `/proactivity` pause/resume/status, budgets, quiet hours — bound to one designated chat |
| Observer | 30s check for approved watches, bounded automatic opportunities |
| Gateway hook | Flips the plugin's "armed" flag only when running inside the gateway (not TUI/CLI probes) |
| `workspace_browser` MCP | `status`, `tabs`, `open`, `snapshot`, `screenshot`, `action` — per-bot scoped Chromium tabs on Mac or VPS |
| Router | probes the Mac's ssh alias for ~8s; unreachable → VPS browser host. Mac asleep mid-session → the in-flight Mac call fails visibly and the next MCP connection re-routes to a fresh VPS session; live Mac tabs are never migrated. Tool results carry the serving host and mac-watch state |
| mac-watch | optional systemd watcher (`deploy/`) probes the Mac every 30s and publishes a JSON state file the router and observer read |

## The workspace_browser tools

Each bot needs its own `--bot-id` — it owns that bot's tabs. The router passes
`--bot-name` through so the on-page agent cursor carries the bot's name and
color. Multi-bot setups: run `setup-workspace.sh` once per profile, each with
its own bot id (the script replaces only its own managed block).

Mac path requirements: the Hermes Workspace app running on the Mac, SSH from
this host to it (BatchMode/key auth — the probe uses `StrictHostKeyChecking`),
and the app's bundled `browser-mcp.cjs` (inside the installed `.app`).
VPS-only usage works with no Mac: the router detects the missing/unreachable
host and serves the local VPS browser host directly.

## Mac availability watcher

`alans-way/scripts/mac-watch.sh` probes the Mac over ssh on an
interval (default 30s) and keeps a JSON state file —
`{"state","since","lastSeenOnline","lastTransition"}` — that the router and
the proactive observer read instead of probing themselves. The router adds
the serving host and Mac state to `workspace_browser` results; the observer
turns an offline→online flip into a context event for the lead bot's review,
so kanban cards blocked on Mac-only work can resume. Transitions are logged
to `mac-events.log` beside the state file.

The observer also sweeps the shared `kanban.db` read-only
(`proactive_board.py`): open and recently-closed cards ride into the primary
bot's review context, so a blocked or changed card from another agent can
surface as one bounded opportunity — never a reason to touch someone else's
card. Combined with the connector's overseer role (`HERMES_OVERSEER_BOTS` /
`HERMES_OVERSEER_BOT_IDS`, see `integration.md` in the app repo), the primary
can answer "who is working where" and release a runaway tab.

Review context also carries `documents` — excerpts and modified times of the
primary's own identity files (`SOUL.md`, `AGENTS.md`, `IDENTITY.md`) — and
`capabilities`, the installed skill names. With `schedule` (enabled cron
metadata) that lets the appraiser weigh the wider remit: an upcoming
commitment worth surfacing, a capability gap worth one `ask` or a bounded
skill-building proposal, or a stale identity document worth a draft update.

```sh
sudo cp deploy/mac-watch.service /etc/systemd/system/
sudo mkdir -p /etc/hermes-alans-way
echo 'HERMES_WORKSPACE_MAC_SSH=you@your-mac' | sudo tee /etc/hermes-alans-way/mac-watch.env
sudo systemctl enable --now mac-watch.service
```

Adjust `ExecStart` to the installed script path and `User=` to the account
whose ssh keys reach the Mac. Environment variables:
`HERMES_WORKSPACE_MAC_SSH` (required — the same ssh alias the router probes),
`HERMES_MAC_STATE_FILE` (default `/var/lib/hermes-alans-way/mac-state.json`;
the unit's `StateDirectory` creates the parent directory).

Hermes's stock `browser_exec` (Browser Use) tool connects to its own
`browser.cdp_url` (default `http://127.0.0.1:9222`) — nothing shares it.
Run a dedicated Chromium there via `deploy/browser-exec-chromium.service`
reusing the same `vps-chromium-host.cjs` supervisor with
`deploy/browser-exec-config.json` under
`$HERMES_VPS_BROWSER_DATA/config.json`. It keeps its own
`--user-data-dir`; never point browser_exec at :9223, which the workspace
VPS browser owns.

## Safety model (short version)

- Human takeover wins always: control epochs invalidate queued agent actions.
- Per-tab ownership is cooperative policy between bots sharing the connector —
  not a crypto boundary. See the [security note](https://github.com/capthvnsen/alans-way/blob/main/desktop/docs/integration.md)
  for the trust model before exposing a connector beyond `127.0.0.1`.
- The proactivity observer is read-only about the world until an approved
  opportunity fires inside its one bound conversation. Budgets and quiet
  hours are in `docs/proactivity.md`.

## Layout

```
alans-way/            the plugin (plugin.yaml + tools + observer + skills + router + mac-watch)
deploy/               systemd unit for the Mac availability watcher
hooks/                gateway startup hook (manual copy — see Install)
docs/                 proactivity guide
tests/                unittest suite — python3 -m unittest discover -s tests
setup-workspace.sh    per-bot mcp_servers config writer
```

## Tests

```sh
python3 -m unittest discover -s tests -v
```

## License

MIT — see [LICENSE](LICENSE).
