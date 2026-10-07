# VPS desktop operations

These tools follow the connector. When the user's computer (a Mac, or a Windows PC configured with `--host-os windows`) is reachable they are that machine's apps; on Windows the calls reach the desktop through the app's local API, so the app must be running. When the user's computer is unreachable they are the desktop on the machine where the agent runs (Linux or a macOS VM).

Managed Chromium tabs use `cua_alans_way_snapshot` and `cua_alans_way_action`.

Other applications are driven by the `computer_use` tool, which asks the user for approval before each action: `list_apps` names the running apps, `capture` with `app` returns the app's numbered element list, and `click`, `key`, `set_value`, `scroll`, `drag` and `focus_app` act on it. That reads the accessibility tree and does not move the pointer. Leave the focused window alone. Password fields are off limits.

`workspace_computer_apps`, `workspace_computer_snapshot`, `workspace_computer_menu` and `workspace_computer_screenshot` still read the desktop without asking; `workspace_computer_screenshot` is one window, a small jpeg, and only when the element list has no named control. Do not screenshot a window you can already read as names and refs.

If `computer_use` is not loaded, stop and report that. Do not fall back to an external computer-use driver or a full-desktop screenshot.
