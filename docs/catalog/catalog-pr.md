# Draft PR for NousResearch/hermes-agent (not submitted)

**Title:** plugin-catalog: re-pin both Alan's Way plugins to 0.21.14

Re-pins `alans-way` and `alans-way-computer` to
`957d07fd7f93e17d38af30c6a6abbcd7bd05f4f8` (capthvnsen/alans-way-agents `main`),
version label `0.21.14` on both. Entry files: `docs/catalog/alans-way.yaml` and
`docs/catalog/alans-way-computer.yaml`, built from the live entries with only the
pin, version, capabilities and disclosure text changed.

Ranges to review (rule 4):

- `alans-way`: `0f65549ac1353f6b74b8ac6a22d58f3eb6dea0a3..957d07fd7f93e17d38af30c6a6abbcd7bd05f4f8` (`alans-way/`: 12 files, +885/-135)
- `alans-way-computer`: `23cce292c867a42ccf9853b99d798add028788f0..957d07fd7f93e17d38af30c6a6abbcd7bd05f4f8` (`alans-way-computer/`: 4 files, +51/-4)

## Disclosure lines (rule 13)

alans-way:

- **Reply pacing, on by default.** For Telegram turns someone is waiting on, `transform_llm_output` sleeps on the agent's worker thread so a reply lands no sooner than 0.6 s + 15 ms/char, capped at 2.5 s minus elapsed time. `/tone pace off` turns it off; `/tone default` turns off the voice note, cleanup and pacing.
- **Broader send-time cleanup** (remove-only): openers, generic sign-offs, headings, bold-only lines, and walls of three or more bold spans. Code, links and URLs are never edited. Casual-reply target of 280 characters (`/tone length`).
- **Reads outside plugin data:** `~/.config/alans-way/config.json` at load, if present. It is validated with the new dependency `jsonschema>=4.18,<5`, and an invalid file fails plugin load. When the file is present, its identity and persona preferences go into every turn of every session in the profile (CLI and cron included). It also overrides voice and proactivity hours, timezone and on/off. It grants no tools or approvals.
- **Weekly time-saved report**, off by default; only the user can enable it (`/proactivity report on`). On Sunday evening it injects a `[Weekly report]` prompt into the bound DM through the existing gateway-injection permission. The bot reviews 7 days with `session_search` and memory, and the new `proactivity` action `weekly_report` returns a fixed-minutes estimate. No new tool name.
- **Bundled `scripts/remote-agent-bridge.cjs`**, never started by the plugin. When the operator starts it (`ALANS_WAY_REMOTE_BRIDGE=1`, a token of 32+ characters), it serves the router over plain HTTP on 127.0.0.1:8790 by default. It refuses non-private binds, caps bodies at 1 MiB and sessions at 4.
- `capabilities.provides_tools` drops `cross_bot_ask`, matching `alans-way/plugin.yaml` at this pin: it registers only on an activated primary cross-bot profile, which the isolated probe never activates. The tool itself is unchanged, and the entry's description still discloses it.
- Repository-level `scripts/setup-remote-agent.sh` (not bundled) and `setup.sh --defer-bot` run only when the operator runs them. The workspace-setup skill pins desktopRef `3b3f2597d5aa7b646e1161e0e75496049cd0a94d` and tag `v0.21.14`, and may ask once about Telegram reactions.

alans-way-computer:

- **Busy-desktop retry.** When the Mac answers launch/menu/action with `desktop_busy`, the provider resends the same call (honouring retry-after, else every 2 s) for up to 30 s of waiting. Hermes's approval is not asked again for the resend; the host refused the call before running it.
- `requires_hermes` stays `>=0.21.6`, which `alans-way-computer/plugin.yaml` now declares too (rule 14).

## Checks run at the pin

- `hermes plugins validate alans-way` / `alans-way-computer` (Hermes v0.22.7): both "Validation passed". alans-way has no warnings. alans-way-computer warns about the private import `tools.mcp_tool_config._resolve_stdio_command`.
- Unmodified scanner at `08165d58931841cee713468ae89032af7c57060a`: both SAFE. alans-way has 2 MEDIUM + 3 LOW, the same five findings as before. alans-way-computer has 2 MEDIUM (`__init__.py:190`, `:951`).
- `hermes_cli.plugin_catalog.load_catalog` parses both entries; sha, version, floor and capabilities equal `plugin.yaml`.
- Not run: `hermes plugins validate --install-deps` (it would install into the local Hermes venv). That venv already has jsonschema 4.26.0.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
