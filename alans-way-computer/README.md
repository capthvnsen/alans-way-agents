# Alan's Way Plugin: computer-use provider

With backend `alans-way-computer`, Hermes's stock `computer_use` tool is Alan's Way's native Mac app control.
It drives the user's own computer through Alan's Workspace. When that computer is offline it drives the VM's desktop
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
- Targets one app. On Mac, it can read that app in front and drive or raise it after the user has been idle for
  at least 2 seconds. Foreground requests ask the host to activate only that target before acting.
  `focus_app` launches a missing named app when the host advertises `computer-launch-v1`;
  `raise_window` asks the host to raise it with `activate`.
  Keychains, password managers and password fields stay off limits. Other hosts keep their own restrictions.
- `capture` (`mode="som"`) returns the element list alone when its named controls cover most of the window; when
  they don't (a canvas, a game, a web area) it attaches the window screenshot and says why. `mode="vision"` is the
  screenshot alone.
- On a Mac or Windows computer, each action's reply says which element numbers changed or disappeared and updates
  the list in place, so a number keeps meaning the same control and no capture is needed to read the result. Linux
  (the VM desktop, or a Linux computer) numbers controls by position, so there the reply describes the change and
  asks for a capture before acting by number again.
- Captures request only changed controls when the app supports it, and recover with a full list if the held
  generation does not match. Older apps still return full lists or reuse an unchanged list.
- When the app identifies a window, later captures, screenshots and actions stay on that window. Select another
  with `capture(window_id=...)`; a mismatched window reply requires a fresh capture before acting again.
- Errors carry a code and a next step: `in_front` means wait a few seconds and retry once, then briefly report
  the refusal; `locked` and `no_window` need the user's help, and `stale_ref` means capture again.
  A capture of an app whose windows are on another Space says so in its note.
- After a switch between the computer and the VM, app ids and element numbers no longer mean anything. The
  next action returns `host_changed`: call `list_apps` and `capture` again.
- Prefer `set_value` with a field's element number. Free typing depends on the host's support; middle and triple
  clicks and modifier clicks return `unsupported_action`.

## Approvals

Approvals follow the user's Hermes settings. The plugin uses that gate without adding per-action chat questions.
For an unattended Telegram bot, either tap Always in Telegram when asked,
or add these entries to `command_allowlist` in the profile's config.yaml, one each, and restart the gateway (`hermes gateway restart`; on a supervisord host `supervisorctl signal USR1 <program>` on the program running `hermes gateway run`; a plain `restart`/`stop` can SIGKILL it mid-drain and corrupt `state.db`):

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

Serving diagnostics go to the selected profile's `logs/workspace-router.log` as well as stderr. Each line names
the host, request id and tool, without page content or arguments. Rerunning workspace setup binds the profile log
directory for the browser connector; the computer provider also passes Hermes's currently bound profile home.

## Limits

- It runs inside the Hermes process, so it cannot load under `plugins.isolation: host`.
- It spawns `node`, resolved the way Hermes resolves an MCP server command.
- Screenshots have no numbered overlays: use the element numbers in the list. Scroll amounts are wheel ticks,
  converted to pages at a quarter page per tick.

## License

MIT License. Copyright (c) 2026 Alex Hansen. See [LICENSE](LICENSE).
