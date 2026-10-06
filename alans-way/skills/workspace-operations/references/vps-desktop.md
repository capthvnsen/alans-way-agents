# VPS desktop operations

Managed Chromium tabs use `cua_alans_way_snapshot` and `cua_alans_way_action`.

Other applications use `workspace_computer_apps`, then `workspace_computer_snapshot`, then `workspace_computer_action` with `press` and a ref. That reads the accessibility tree and does not move the pointer. Leave the focused window alone. Password fields are off limits.

`workspace_computer_screenshot` is one window, a small jpeg, and only when the snapshot has no named control. Do not screenshot a window you can already read as names and refs.

If those tools are missing, stop and report that. Do not fall back to an external computer-use driver or a full-desktop screenshot.
