# Alan's Plugin for Grok Bot

A **scaffold** for a Grok Bot skill and settings package in
`capthvnsen/alans-way-agents`. Grok Bot cannot load Hermes plugins, so this
package contains Markdown instructions and a JSON settings reference, with no
Python entry point or Hermes hooks.

## Package contents

- [`SKILL.md`](SKILL.md): instructions to read and validate the shared config,
  apply persona, text voice and identity preferences, and check native support
  before promising proactivity.
- [`settings.json`](settings.json): points to the one user config at
  `~/.config/alans-way/config.json` and the repository's
  [`shared/config.schema.json`](../shared/config.schema.json). These two keys
  are scaffold metadata read by the skill, **not a verified Grok Bot native
  settings format**.

Read the [shared contract and example](../shared/README.md) before preparing a
config. There is no plugin-specific copy of persona, voice, proactivity or
identity here. Keep this directory beside `shared/` and `docs/` when reviewing
the scaffold so its relative references resolve. No installer, automatic config
loader or background scheduler is included, and native Grok Bot loading has
not been verified.

## Workspace connection

Alan's Workspace is the Mac/iOS app and VM handoff product. Alan's CU MCP is the
shared Node `workspace-mcp` server that any agent can connect to. Both live in
[`capthvnsen/alans-way`](https://github.com/capthvnsen/alans-way).
This skill configures neither. An existing Grok Bot MCP connection can use
the workspace independently of the Hermes packages; see
[remote-agent setup](../docs/remote-agents.md).

## Decisions for Alex

- TODO: confirm Grok Bot's supported skill installation/discovery location,
  native settings format and how to package access to the shared schema.
- TODO: confirm available native scheduling and operator-consent controls
  before implementing proactive check-ins.

The [shared contract](../shared/README.md#decisions-for-alex) also lists schema
and future Hermes adapter decisions.

## License

MIT License. Copyright (c) 2026 Alex Hansen. See [LICENSE](LICENSE).

Community: [Discord](https://discord.gg/jBQCPUsVE) ·
[openalan.com](https://openalan.com).
