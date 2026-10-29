# Alan's Plugin for Hermes: main package

A texting voice for chat sessions, idle check-ins and the workspace-browser skills for a
Hermes gateway. This directory is what `hermes plugins install` loads. The
optional [`alans-way-computer`](../alans-way-computer/README.md) package supplies
the computer-use provider. See the [repository README](../README.md) for install
instructions and the four Alan's Way products.

Alan's Workspace (Mac chat/browser, iOS app and lid-close VM handoff) and
Alan's CU MCP (the shared Node `workspace-mcp` server) live in a separate repo:
<https://github.com/capthvnsen/alans-way>. After this plugin is installed,
ask the agent to follow the `workspace-setup` skill. It fetches that repo's
setup page and walks through the rest. It does not replace this plugin.

## Shared config contract (draft)

[`shared/README.md`](../shared/README.md) defines the common persona, voice,
proactivity and identity config for Alan's Plugin for Hermes and
[Alan's Plugin for Grok Bot](../alans-way-grok-bot/README.md). Hermes does not yet
read that JSON file. Keep using the existing [tone](../docs/voice.md) and
[proactivity](../docs/proactivity.md) controls and Hermes persona settings.
This contract adds no hooks, state migration or runtime setting changes.

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
- **Texting voice affects chat replies:** on turns tagged `telegram`, `desktop`,
  `tui` or `bot_room`, it appends a style note to the model's turn and may remove one leading "Certainly!"-style
  opener from the final reply, only when the reply has no indented line,
  backtick or quotation mark. Nothing else in a reply is ever rewritten. It is
  on by default; `/tone default` or `hermes tone default` turns it off per
  profile. CLI, cron, webhook and API-server turns keep the default voice. It never
  writes SOUL.md or config.yaml. The note asks for quiet routine execution, essential
  questions and blockers, and a concise verified result; it does not suppress fixed
  Hermes progress, approval or error messages. Hook delivery has scripted tool tests;
  consistent quiet behavior from a real model remains unverified.
- **Operator surfaces:** the plugin registers the `hermes proactivity` and
  `hermes tone` CLIs and the `/proactivity` and `/tone` slash commands. The model tool can only reduce check-ins;
  increasing them or resuming is operator-only (`/proactivity` or the CLI).
- **Shell commands:** the plugin's Python runs none. The `workspace-setup` skill
  guides the agent through running `setup.sh`, which installs the workspace
  browser router and services over ssh on your own machines.
- No telemetry, no stored credentials.

## License

MIT License. Copyright (c) 2026 Alex Hansen. See [LICENSE](LICENSE).
