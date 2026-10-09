# Alan's Way Plugin: computer-use provider

A computer-use provider for Hermes. Select it and the stock `computer_use` tool drives desktop apps on the
user's own computer through the Alan's Workspace app. When that computer is offline it drives the VM's desktop
instead, with no change on the Hermes side.

It needs a Hermes build with the pluggable computer-use API (pull request 133556, merged after 0.21.5). On older
Hermes the plugin installs and logs that it did nothing.

## Setup

1. Install the `alans-way` plugin and run its workspace setup. That writes the profile's
   `mcp_servers.workspace_browser` block, which this provider reuses.
2. Install this plugin: `hermes plugins install alans-way-computer`.
3. Select it by setting `computer_use.backend: alans-way-computer` in the profile's config.yaml, or run
   `hermes config set computer_use.backend alans-way-computer`.
4. Restart the gateway. Check it with `hermes computer-use doctor`, which runs the router's probe and says
   whether the computer or the VM desktop is answering.

## What it does

- Starts the router from the `workspace_browser` block as a long-lived `node` child, one per Hermes session, and
  talks to it over its stdio. The router reaches the user's computer by SSH over the user's Tailscale tailnet and
  falls back to the VM desktop when that fails. A dead or silent router is restarted on the next call.
- Never takes focus. Input is delivered in the background, `focus_app` only chooses which app later actions
  target, and foreground delivery is refused. Keychains, password managers and password fields are off limits.
- After a switch between the computer and the VM, app ids and element numbers no longer mean anything. The
  next action returns `host_changed`: call `list_apps` and `capture` again.
- Typing needs a field: use `set_value` with an element number. `type` with no target, middle and triple clicks and
  modifier clicks return `unsupported_action`.

## Approvals

Hermes asks for approval before every `computer_use` action except `capture`, `list_apps`, `list_windows` and `wait`, once per action
type. An unattended Telegram bot has nobody to answer, so grant them once. Either tap Always in Telegram when asked,
or add these entries to `command_allowlist` in the profile's config.yaml, one each, and restart the gateway:

```yaml
command_allowlist:
  - cua:click:background
  - cua:double_click:background
  - cua:right_click:background
  - cua:drag:background
  - cua:scroll:background
  - cua:key:background
  - cua:set_value:background
  - cua:focus_app:background
```

`computer_use.permission_mode` applies to the cua driver only and has no effect here.

## Limits

- It runs inside the Hermes process, so it cannot load under `plugins.isolation: host`.
- It spawns `node`, resolved the way Hermes resolves an MCP server command.
- Screenshots have no numbered overlays: use the element numbers in the list. Scroll amounts are wheel ticks,
  converted to pages at a quarter page per tick.
