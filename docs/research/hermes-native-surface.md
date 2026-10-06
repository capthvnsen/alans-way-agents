# Hermes native surface (verified on the author's machine, Oct 2026)

Static investigation of the installed Hermes Agent (`~/.hermes/hermes-agent`,
shim `~/.local/bin/hermes`) — what a plugin can rely on. Read-only findings;
live availability of MCP servers and hosted connectors is verified statically
only.

## Installation topology

- Homes: default `~/.hermes` plus named profiles under `~/.hermes/profiles/<name>/`,
  each with its own `config.yaml`, `plugins/`, `cron/`, `state.db`, `cache/`.
- Plugin entry contract: `plugin.yaml` + `__init__.py` exposing `register(ctx)`;
  `PluginContext(manifest, manager)` in `hermes_cli/plugins.py`. Discovery:
  bundled `<repo>/plugins/`, user `$HERMES_HOME/plugins/`, project
  `./.hermes/plugins/` (gated by `HERMES_ENABLE_PROJECT_PLUGINS`), pip entry
  points. Enablement: `plugins.enabled`/`plugins.disabled`.
- Load timeout `plugins.load_timeout_seconds`; late registrations after a
  timed-out load are ignored. Per-registration cleanup runs via
  `PluginRegistration.dispose()` / `on_unload` in reverse order.

## PluginContext surface used or relevant

| Member | Notes |
| --- | --- |
| `register_tool(name, toolset, schema, handler, check_fn, requires_env, is_async, ...)` | Global registry under manager scope; name collision warns unless `override=True` with `allow_tool_override`/`tools.override` capability. |
| `register_command(name, handler, description, args_hint)` | In-session `/<name>`; handler `fn(raw_args)->str|None`. |
| `register_skill(name, path, ...)` | Resolves as `<plugin_key>:<name>`; NOT copied into `~/.hermes/skills`, NOT in `<available_skills>`. |
| `register_cli_command(name, help, setup_fn, handler_fn)` | `hermes <name>` argparse subcommand. |
| `inject_message(content, role="user", *, session_key=None) -> bool` | Non-CLI needs `session_key` + `plugins.entries.<id>.allow_gateway_injection: true`. `True` = accepted/scheduled, never completed. Gateway re-checks auth before routing. |
| `dispatch_tool(tool_name, args, **kwargs) -> str` | `registry.dispatch(scope=manager.scope_key)`; returns handler JSON string. Used by `proactive_native.collect` for `kanban_show`. |
| `llm.complete_structured(instructions, input, json_schema, schema_name, system_prompt, temperature, max_tokens, timeout, purpose, model, provider, task, ...)` | `agent/plugin_llm.py`; `parsed`/`content_type` on result. `model`/`provider`/`profile` overrides each gated by `plugins.entries.<id>.llm.allow_*_override` (fail closed). `task=` routes through plugin-registered auxiliary slots. |
| `ctx.state` | Profile-scoped durable JSON facade (`PluginState`). |
| `spawn_task(coro, *, name)` | Supervised asyncio task cancelled on unload; needs running loop. |
| `platform_actions` | `add_reaction`/`set_thread_title`; default OFF — needs `gateway.platform_actions` + `allow_platform_actions`. |
| `call_mcp(server, tool, arguments, timeout)` | Default-deny via `plugins.entries.<id>.mcp_allowlist`; ~64KB result cap. |
| `emit/subscribe` | `<plugin_key>:<event>` bus. |
| `register_system_prompt_section(id, content, position, max_chars)` | Bounded frozen section per new session — costs context on every session; not used for proactivity. |
| `profile_name` | `get_active_profile_name()`; `"default"` fallback. |
| `register_hook(name, cb)` | `VALID_HOOKS` includes `pre_gateway_dispatch` (pre-auth — never trust), `on_session_start/end`, `kanban_task_*`, `agent_loop_stopped`, etc. |

## Cron

- Canonical store `cron/jobs.json` (`{"jobs": [...]}`); `cronjob_manage` tool
  actions `create|list|update|pause|resume|remove|run`.
- Each job spawns a **fresh AIAgent turn** — no direct plugin-handler call;
  plugin tools reachable only via the job's resolved toolsets.
- Useful params: `prompt`, `schedule`, `deliver`, `attach_to_session`,
  `context_from` (imports other jobs' output), `script`, `no_agent`,
  `enabled_toolsets`, `paused`, `failure_deliver`.
- `cronjob`, `messaging`, `clarify` toolsets are disabled inside cron agents
  by default; `cron.allow_agent_scheduling: true` lifts `cronjob`.

## Hooks — four surfaces

1. Plugin lifecycle hooks (`ctx.register_hook`, `VALID_HOOKS`).
2. Plugin middleware (`tool_request|tool_execution|llm_request|llm_execution`).
3. Filesystem gateway hooks `~/.hermes/hooks/<name>/HOOK.yaml`+`handler.py`
   (`handle(event_type, context)`); events: `gateway:startup`,
   `session:start|end|reset`, `agent:start|step|end`, `command:<name>`,
   `command:*` (can deny/handle/rewrite).
4. `hooks:`/`webhooks:` shell hooks in config.yaml (exit-2 blocks
   `pre_tool_call`; per-command allowlist in
   `~/.hermes/shell-hooks-allowlist.json`).

## Sessions, routing, injection

- Authoritative store: `state.db` — `sessions`, `messages`,
  `gateway_routing(scope, session_key, entry_json, updated_at)`,
  `session_model_usage`, `gateway_hygiene_state`.
- `sessions/sessions.json` is a **legacy mirror** of `gateway_routing`,
  disabled by `gateway.write_sessions_json: false`. A plugin must NOT treat
  the mirror as the only binding source.
- `build_session_key`: `<namespace>:<platform>:<chat_type>[:scope][:chat_id]
  [:thread_id][:user]`; `agent:main` for default, `agent:<profile>` otherwise.
- Injected events carry `hermes_plugin_id`, `hermes_plugin_injection`,
  `gateway_session_key`, `gateway_session_strict`; auth re-checked.

## Tools & connectors

- Native built-ins: `memory`, `session_search`, `delegate_task`,
  `cronjob_manage`, `manage_connections` (toolset `connections`, gated by
  `connectors_available()`).
- Kanban: 15 tools (`kanban_show`, `list`, `create`, `complete`,
  `request_review`, `block`, `comment`, `heartbeat`, …) in a **default-off**
  `kanban` toolset.
- Hosted connectors (Gmail, Notion, Google Calendar if cataloged+authorized):
  surface as `connectors__<connector>__<tool>` through progressive disclosure
  (`tool_search`/`tool_describe`/`tool_call`), executed via the hosted tool
  gateway. Disconnect only through the portal.
- Skill-based alternatives (no credentials provisioned by any plugin):
  `productivity/google-workspace` (`gws` CLI or bundled `google_api.py`;
  ships `references/daily-brief.md` — schedule+conflicts+meeting prep+urgent
  mail procedure), `email/himalaya` (IMAP CLI), `email/email-inbox-triage`,
  `productivity/notion` (`ntn` CLI or HTTP).
- MCP servers: config `mcp_servers` → toolset `mcp-<server>` (aliased to the
  bare server name); lazy connect supported.

## Toolset resolution

`platform_toolsets.<platform>` lists built-ins + plugin toolsets + MCP names;
`agent.disabled_toolsets` applies last. `cache/plugin_toolset_keys.json`
persists discovered plugin toolset keys. A saved platform list that predates
this plugin hides `proactive_control` — `hermes tools enable proactivity
--platform <p>` fixes it.

## Config notes for proactivity

- `plugins.entries.alans-way.allow_gateway_injection: true` — required for
  `inject_message` outside CLI.
- `gateway.write_sessions_json` — if `false`, bind must read
  `state.db:gateway_routing` instead of the `sessions.json` mirror.
