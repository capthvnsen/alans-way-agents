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

## Shared config

The plugin reads `~/.config/alans-way/config.json` on load, validated against the
[shared schema](../shared/config.schema.json). A missing file preserves existing
defaults; an invalid file reports an error before registration applies anything.
Install `jsonschema>=4.18,<5` in Hermes's Python environment when needed.

Shared identity/persona reach every profile. With texting voice on, shared tone
and reply length replace the built-in voice prompt. Shared timezone, idle time
and minute-level active hours control the native scheduler, while route binding,
operator pauses and brief/report choices remain local. Shared proactivity off
blocks unsolicited messages; shared on never binds a chat or resumes a pause.
Edit the JSON and reload the plugin to apply changes. See the
[shared usage and precedence rules](../shared/README.md#use-with-hermes-and-grok-bot)
and [Grok Bot generator](../alans-way-grok-bot/README.md).

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
  timestamps. Every turn also gets a task note and a workspace-tools note. With a
  shared config file, every turn of every session (CLI and cron included) also gets
  its identity and persona preferences.
- **Texting voice affects chat replies:** on turns tagged `telegram`, `desktop`,
  `tui` or `bot_room`, it appends a style note (casual replies under 280
  characters; `/tone length`) and runs a remove-only cleanup on the final reply:
  known openers and generic sign-offs are dropped, headings become plain lines,
  and bold is unwrapped on bold-only lines or when a reply has three or more bold
  spans. Code, links, URLs and indented lines are never edited, and nothing is
  added. With a shared config the cleanup is off. On by default; `/tone default`
  or `hermes tone default` turns the note, cleanup and pacing off per profile.
  CLI, cron, webhook and API-server turns keep the default voice. It never writes
  SOUL.md or config.yaml, and does not touch fixed Hermes progress, approval or
  error messages. Consistent quiet behavior from a real model remains unverified.
- **Reply pacing:** on by default for Telegram turns someone is waiting on. The
  final-reply hook sleeps on the agent's worker thread so a reply lands no sooner
  than 0.6 s plus 15 ms per character, at most 2.5 s, minus the time the turn
  already took. `/tone pace <ms>|natural|off` (0-10 s) changes it.
- **Weekly time-saved report:** off until the user sends `/proactivity report on`.
  On Sunday evening it injects one `[Weekly report]` prompt into the bound chat
  (same injection permission as check-ins); the bot reviews the past 7 days with
  `session_search` and memory and replies with a fixed-minutes-per-task estimate
  or stays silent. See [proactivity.md](../docs/proactivity.md#weekly-time-saved-report).
- **Cross-bot proactivity:** off by default; each bot opts in with
  `/proactivity cross on` after operator configuration. It shares sanitized,
  bounded owner-DM excerpts between enabled profiles on one gateway through
  owner-only files (digests 24 h, queued asks 2 h), and a primary check-in may
  schedule one read-only or draft-only ask into another bot's bound DM through the
  `cross_bot_ask` tool. Sanitizing cannot catch every secret, and copied context can
  remain in Hermes and model-provider history after expiry or opt-out. See
  [proactivity.md](../docs/proactivity.md#cross-bot-proactivity).
- **Workspace router:** `scripts/workspace-router.cjs` is a long-running Node MCP
  server that Hermes starts from the `workspace_browser` block. It reaches the
  user's computer over SSH on the tailnet, falls back to the VM's own browser and
  desktop, and appends approval decisions to a local `commit-decisions.jsonl`.
  Desktop input tools stay hidden and refused unless the operator opts in
  (`--allow-desktop-actions`); purchases, sends and other commit actions need an
  approval the router asks for.
- **Remote-agent bridge:** `scripts/remote-agent-bridge.cjs` ships here but the
  plugin never starts it. An operator who runs it with `ALANS_WAY_REMOTE_BRIDGE=1`
  and a token of at least 32 characters serves the router to another MCP client
  over plain HTTP, on loopback by default (private addresses only), one router per
  session. The repository README links the remote-agent guide.
- **Operator surfaces:** the plugin registers the `hermes proactivity` and
  `hermes tone` CLIs and the `/proactivity` and `/tone` slash commands. The model tool can only reduce check-ins;
  increasing them or resuming is operator-only (`/proactivity` or the CLI).
- **Shell commands:** the plugin's Python runs none. The `workspace-setup` skill
  hands a setup plan to the human, and Alan's Workspace runs `setup.sh` outside
  the gateway. Setup can install browser and display services (with root rights
  it may install Chrome, Chromium or Xvfb), adds the computer's public SSH key to
  the VM user's accepted keys, usable only from tailnet addresses, adds an SSH
  config block for tailnet hosts, and drain-stops and restarts the profile's
  gateway to apply plugin changes.
- **Remote-agent SSH setup:** `scripts/setup-remote-agent.sh` lives in the
  repository, not in this plugin, and runs only when the operator runs it. It
  creates one ed25519 key per bot and adds it to the VM user's accepted keys,
  limited to the router (`restrict,command=...`, optionally `--tailnet-only`),
  backing that file up first. Remote clients set up this way, or through the bridge, get desktop input
  when the operator sets `HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS=1`, without
  Hermes's `computer_use` approval prompts.
- No telemetry, no stored credentials.

## License

MIT License. Copyright (c) 2026 Alex Hansen. See [LICENSE](LICENSE).
