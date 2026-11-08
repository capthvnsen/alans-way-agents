**Title:** plugin-catalog: re-pin alans-way to 0.21.14

Re-pins `alans-way` from 0.21.9 (`0f65549ac1353f6b74b8ac6a22d58f3eb6dea0a3`) to
0.21.14 (`<PIN>`), submitted by the repository owner. One file changed:
`plugin-catalog/alans-way.yaml`.

**What it does:** idle check-ins from a Hermes gateway's primary bot, a texting
voice for chat sessions, and workspace-browser skills. Opt-in extras: a morning
brief, a weekly time-saved report and cross-bot proactivity. Surfaces used:
`pre_llm_call`, `post_llm_call`, `pre_tool_call`, `on_session_end` and
`transform_llm_output` hooks, the `proactivity` tool (plus `cross_bot_ask` on an
activated primary), the `/proactivity` and `/tone` commands and CLIs, the
Telegram platform handler, and bundled skills.

**Range to review (rule 4):**
`https://github.com/capthvnsen/alans-way-agents/compare/0f65549ac1353f6b74b8ac6a22d58f3eb6dea0a3...<PIN>`

**Entry changes:**
- The description is now a short summary with one `Disclosure:` line. The long form is in the README at the pin and below.
- Release-note items in `known_issues` are rewritten as current behavior. New items cover pacing, shared config, the weekly report, and remote clients' desktop input.
- `provides_tools` drops `cross_bot_ask`, matching `plugin.yaml`: it registers only on an activated primary, which the probe never activates.

## Disclosure lines (rule 13)

New since 0.21.9:
- **Reply pacing**, on by default for Telegram: holds a reply up to 2.5 s on the agent's worker thread (`/tone pace off`).
- **Wider remove-only reply cleanup**: openers, sign-offs, headings and walls of bold. Code, links and URLs are never edited.
- **Reads `~/.config/alans-way/config.json`** when it exists, validated with new dependency `jsonschema>=4.18,<5`; an invalid file fails load. When present, it injects identity and persona into every session's turns and overrides voice and proactivity settings.
- **Weekly time-saved report**, user opt-in. A Sunday prompt injected into the bound DM reviews 7 days with `session_search` and memory.
- **Bundled `scripts/remote-agent-bridge.cjs`**, never started by the plugin. When the operator starts it, it serves plain HTTP on loopback or a private address.
- **Remote clients and desktop input**: remote clients (repo-level `setup-remote-agent.sh` or the bridge) get desktop input without `computer_use` prompts when the operator sets `HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS=1`.

Unchanged and still disclosed: injected check-ins, turn hooks seeing every session, cross-bot proactivity (excerpt sharing, injected asks, retention), the workspace router (SSH to the user's computer over the tailnet, VM fallback, local `commit-decisions.jsonl`), and setup run outside the gateway. Setup installs services and packages, adds a tailnet-only SSH key, pins host keys and restarts the gateway.

Full text: `docs/catalog/alans-way-disclosure.md` and the plugin README's Disclosures section, both at the pin.

## Checks at the pin

- `hermes plugins validate --install-deps alans-way`: `<paste result>`
- Unmodified scanner `08165d58931841cee713468ae89032af7c57060a`: SAFE, 0 HIGH, 2 MEDIUM, 3 LOW (same five findings as 0.21.9).
