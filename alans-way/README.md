# Alan's Way plugin

Idle check-ins and the workspace-browser skills for a Hermes gateway. This
directory is what `hermes plugins install` loads.

The desktop app (macOS or Windows on the user's computer), Tailscale setup,
and SSH connect scripts are a separate repo:
<https://github.com/capthvnsen/alans-way>. After this plugin is installed,
ask the agent to follow the `workspace-setup` skill. It fetches that repo's
setup page and walks through the rest. It does not replace this plugin.

## Disclosures

- **Background thread:** once the gateway connects Telegram, a daemon thread
  wakes every 60 seconds to check whether a check-in is due. It makes no
  network calls of its own.
- **Injected prompts:** a due check-in injects one internal prompt into the
  bound Telegram chat (needs `plugins.entries.alans-way.allow_gateway_injection: true`).
  The bot's reply is a normal turn, and `[SILENT]` replies are not delivered.
- **Reads outside plugin data:** on first load after upgrading from 0.6, it reads
  `$HERMES_HOME/companion/proactivity/proactivity.sqlite3` once, read-only, to
  keep your bound chat, timezone and pause.
- **Turn hooks see every session:** `pre_llm_call`/`post_llm_call` fire for every
  session's turns; the plugin only compares the bound chat and persists only its
  timestamps.
- **Operator surfaces:** the plugin registers the `hermes proactivity` CLI and
  the `/proactivity` slash command. The model tool can only reduce check-ins;
  increasing them or resuming is operator-only (`/proactivity` or the CLI).
- **Shell commands:** the plugin's Python runs none. The `workspace-setup` skill
  guides the agent through running `setup.sh`, which installs the workspace
  browser router and services over ssh on your own machines.
- No telemetry, no stored credentials.
