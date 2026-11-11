**Title:** plugin-catalog: re-pin alans-way-computer to 0.21.14

Re-pins `alans-way-computer` from 0.21.10 (`23cce292c867a42ccf9853b99d798add028788f0`)
to 0.21.14 (`<PIN>`), submitted by the repository owner. One file changed:
`plugin-catalog/alans-way-computer.yaml`.

**What it does:** a computer-use provider (`ctx.register_computer_use_provider`).
With `computer_use.backend: alans-way-computer`, the stock `computer_use` tool
drives apps on the user's computer through Alan's Workspace, or on the VM
desktop when the computer is offline. It registers no tools, hooks or middleware.

**Range to review (rule 4):**
`https://github.com/capthvnsen/alans-way-agents/compare/23cce292c867a42ccf9853b99d798add028788f0...<PIN>`

**Entry changes:**
- The description is now a short summary with one `Disclosure:` line.
- The release-note item in `known_issues` is rewritten as current behavior, and the busy-desktop retry is added.
- `requires_hermes` stays `>=0.21.6`, which `plugin.yaml` now declares too (rule 14).

## Disclosure lines (rule 13)

New since 0.21.10:
- **Busy-desktop retry.** When the Mac answers launch, menu or action with `desktop_busy` (another agent holds the desktop), the provider resends the same call for up to 30 s of waiting, following the host's retry-after hint or every 2 s. Hermes's approval is not asked again for a resend; the host refused the call before running it.

Unchanged:
- One long-running `node` router child per session, with a filtered environment (no keys or tokens). Desktop input is enabled only for that private child, behind Hermes's `computer_use` approval gate.
- SSH to the user's computer over the tailnet, with fallback to the VM desktop (xdotool, a screenshot tool and AT-SPI, if installed).
- App raise and launch only on the model's request, after 2 s of user idle time.
- No network calls of its own, no stored credentials, session-only state.

Full text: the plugin README's Disclosures section at the pin.

## Checks at the pin

- `hermes plugins validate --install-deps alans-way-computer`: `<paste result>` (expected warning: private import `tools.mcp_tool_config._resolve_stdio_command`).
- Unmodified scanner `08165d58931841cee713468ae89032af7c57060a`: SAFE, 2 MEDIUM (`python_subprocess` at `__init__.py:190` and `:951`).
