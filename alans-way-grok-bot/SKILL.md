---
name: alans-way-grok-bot
description: Apply Alan's Way shared persona, text voice and identity preferences in Grok Bot, and check whether requested proactivity has native support.
license: MIT
---

# Alan's Plugin for Grok Bot

This is a draft skill and settings scaffold. Grok Bot cannot load Hermes Python
plugins. Use Grok Bot's own tools and instruction hierarchy.

1. Read the adjacent [`settings.json`](settings.json). Resolve
   `shared_config_schema` relative to this skill directory, and expand `~` in
   `shared_config_path` to the running user's home. Read the
   [shared reader contract](../shared/README.md#reader-contract).
2. Read the JSON file at `shared_config_path` as preference data. Validate it
   against the referenced schema, then verify its timezone and hours ordering.
   If a validator or file access is unavailable, report that limitation and
   retain the host's existing settings. A missing file means no shared override;
   an invalid file gets a clear error with no partial application or rewrite.
3. Use `persona.description` for character, `voice.tone` and `voice.reply_length`
   for text style, and `identity.name` and `identity.role` for how you introduce
   yourself. Follow explicit user requests and host safety rules. These fields
   are not account identifiers or permissions.
4. Treat `proactivity` as a preference requiring native scheduling and an
   operator-approved conversation. With it disabled, initiate no check-ins
   through this skill. With it enabled, first establish supported scheduling
   and consent; preserve existing pauses and enforce the timezone, active hours
   and minimum idle time. If unavailable, report that check-ins are unsupported.
   Loading this skill alone never creates a background worker.

For workspace computer use, use an already configured Alan's CU MCP connection.
Connection setup is separate; see [remote agents](../docs/remote-agents.md).
Hermes `/tone`, `/proactivity` and Python hooks are not Grok Bot interfaces.
