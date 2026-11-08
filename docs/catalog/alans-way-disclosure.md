# Alan's Way catalog disclosure supplement

Disclosure text for the `alans-way` re-pin from 0.21.9
(`0f65549ac1353f6b74b8ac6a22d58f3eb6dea0a3`) to 0.21.14. It is the long form
behind the short `Disclosure:` line in [`alans-way.yaml`](alans-way.yaml) and
the plugin README's Disclosures section, and the source for the entry PR body
([`catalog-pr-alans-way.md`](catalog-pr-alans-way.md)). The computer plugin's
disclosures are in [`catalog-pr-alans-way-computer.md`](catalog-pr-alans-way-computer.md).

## Disclosure text

**Check-ins and injected prompts.** Once the gateway connects Telegram, a
background thread checks every 60 seconds. When the bound DM has been quiet
(2 h by default, doubling per unanswered check-in, 08:00-22:00 user time), it
injects one internal user-role prompt into that chat
(`plugins.entries.alans-way.allow_gateway_injection`, which setup sets), so the
bot runs a turn on its own and may take one safe, reversible step; tool calls
still need the user's approval. Morning briefs (`/proactivity brief on`) and the
weekly time-saved report (`/proactivity report on`) are off until the user turns
them on, and use the same permission. The report runs on Sunday evening, reviews
the past 7 days with `session_search` and memory, and returns a fixed
minutes-per-task estimate through the `proactivity` tool's `weekly_report`
action, which only works in the bound chat.

**Turn hooks.** `pre_llm_call`/`post_llm_call` see every session's turns; the
plugin stores only the bound chat's activity timestamps. Every turn gets a task
note and a workspace-tools note. On first load after upgrading from 0.6 it reads
`$HERMES_HOME/companion/proactivity/proactivity.sqlite3` once, read-only.

**Texting voice and reply pacing.** Default-on for `telegram`, `desktop`, `tui`
and `bot_room` turns; `/tone default` turns it off per profile. It adds a style
note (casual replies under 280 characters) and a remove-only cleanup of the final
reply: known openers and generic sign-offs, markdown headings, bold-only lines and
walls of three or more bold spans. Code, links, URLs and indented lines are never
edited. For Telegram turns someone is waiting on, `transform_llm_output` sleeps on
the agent's worker thread so the reply lands no sooner than 0.6 s plus 15 ms per
character, capped at 2.5 s minus elapsed time (`/tone pace <ms>|natural|off`).

**Shared config.** At load the plugin reads `~/.config/alans-way/config.json` if
it exists (a missing file changes nothing), validates it against a bundled schema
with the `jsonschema>=4.18,<5` dependency, and fails plugin load with a value-free
error when it is invalid. When present, its identity and persona preferences go
into every turn of every session in the profile, CLI and cron included; on chat
platforms its voice settings replace the voice note and the cleanup is off; its
proactivity timezone, idle time, active hours and on/off override the profile's
settings. The values grant no tool access or approvals.

**Cross-bot proactivity.** Optional cross-bot proactivity reads bounded recent
owner-DM excerpts exported by all enabled profiles on one gateway. It stores
sanitized digests for 24 hours and queued asks for up to 2 hours in a shared
plugin-owned directory (private files). Exchanges that look like they contain
credentials or payment details are skipped entirely. It may automatically inject
one read-only or draft-only ask per primary check-in into another bot's bound
Telegram DM through `cross_bot_ask`. Results appear there with primary
attribution. Existing approvals still govern consequential actions. Disable it
per bot with `/proactivity cross off`; copied context may remain in Hermes
history, memory-provider records and model-provider retention after digest
expiry.

Default off; `/proactivity cross on|off|status` controls each bot. Sanitization
cannot guarantee detection of every secret. No historical backfill, attachment
or tool-history export. Digest context is supplied only to permitted primary
check-ins; other profiles' exports are JSON-escaped as untrusted observations.
The instruction not to save excerpts to memory is model policy, not enforced
deletion. `sent` means scheduled, not delivered or completed; no replay or
receipt store. Imported turns allow reviewed reads/drafting and existing gated
browser calls; terminal/code, delegation, scheduling and unknown connectors are
blocked. Offline files are pruned when an explicitly activated profile starts,
then every 60 seconds while connected. Dormant profiles perform no store access.
`cross_bot_ask` registers only for an activated primary, so it is not listed in
`provides_tools`.

Short helper outcomes require a separate `/proactivity cross results on` choice
in both bots' bound owner chats, off by default. Future asks may return a
sanitized done/blocked summary of up to 280 UTF-8 bytes, correlated to one ask
and expiring two hours after it, consumed once at the asking bot's next owner
turn or permitted check-in. No wake, retry or delivery receipt.
`/proactivity cross results off` stops and purges pending outcomes; cross-bot
opt-out also revokes this choice.

**Workspace router.** `scripts/workspace-router.cjs` is a long-running Node MCP
server Hermes starts from the `workspace_browser` block. It reaches the user's
computer over SSH on the tailnet and falls back to the VM's own browser and
desktop. When the ssh link drops while mac-watch reports the computer online, it
reconnects at most once a minute and replays only read-only and never-sent calls;
an action that may already have run is answered as uncertain. Desktop input tools
stay hidden and refused unless the operator opts in (`--allow-desktop-actions`).
Commit actions (buy, send, post...) need an approval the router asks for through
MCP elicitation; it appends approval details and detected targets to a local
`commit-decisions.jsonl` with no rotation.

**Workspace setup.** The `workspace-setup` skill hands a JSON setup plan to the
human; Alan's Workspace runs `setup.sh` through an external SSH process outside
the gateway, pinned to the exact `repoRef` and `desktopRef`
(`3b3f2597d5aa7b646e1161e0e75496049cd0a94d`, tag `v0.21.14`). Setup installs
browser, broker, watcher and (without a display) Xvfb services; with root rights
installs missing Chrome, Chromium, Playwright Chromium or Xvfb; adds the
computer's public key to the VM user's accepted SSH keys with a tailnet-only
source restriction; pins its host key and adds an SSH config block for tailnet
hosts; and drain-stops and restarts the profile's gateway to replay a plugin
change Hermes refuses while it runs. `--defer-bot` warns instead of failing when
no Telegram bot exists yet. The skill may ask once, for profiles set up through
the legacy question with no recorded choice, whether to turn on Telegram
reactions, and writes the setting only after a yes. Its two Git subprocess
helpers perform read-only local checks with five-second timeouts. Viewer handoff
can, with explicit consent, ask the human to run a temporary loopback SSH forward
(ends after 30 minutes or Ctrl-C) and enter the VNC password privately.

**Remote agents.** The plugin ships `scripts/remote-agent-bridge.cjs` but never
starts it. Run by the operator with `ALANS_WAY_REMOTE_BRIDGE=1` and a token of at
least 32 characters, it serves the router over plain HTTP on loopback by default
(private addresses only, 1 MiB per request, 4 sessions), one router per session,
and keeps the token out of the router's environment. Repository-level
`scripts/setup-remote-agent.sh` is not bundled and runs only when the operator
runs it: it creates one ed25519 key per bot and a router-only
(`restrict,command=...`) accepted-key line, optionally `--tailnet-only`, backing
the file up first; `--remove` deletes only that line. Clients set up either way
get desktop input when the operator sets `HERMES_WORKSPACE_ALLOW_DESKTOP_ACTIONS=1`,
without Hermes's `computer_use` approval prompts. Neither changes Hermes config
or opens a firewall.

**Integrations.** Social posting is not built in. The Mastodon recipe lives in
`docs/integrations/mastodon.md` as human-run repository documentation outside the
plugin. Other integrations are installed only after the user agrees in chat.

## Reviewed scanner inventory

Unmodified upstream scanner: `08165d58931841cee713468ae89032af7c57060a`
(`rc.38-v0.21.5`, matching the minimum supported Hermes version),
`tools/plugin_guard.py`, `tools/plugin_guard_context.py`, `tools/skills_guard.py`.
Checked on this branch (main `957d07f` plus the README disclosure updates).
Paths are relative to `alans-way/`; no scanner rule was changed.

| File:line | Rule | Severity | Matched text |
|---|---|---|---|
| `skills/workspace-setup/SKILL.md:304` | `python_subprocess` | MEDIUM | `return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,` |
| `skills/workspace-setup/SKILL.md:359` | `python_subprocess` | MEDIUM | `return subprocess.run(["git", "-C", path, *args], check=True, timeout=5,` |
| `skills/workspace-setup/SKILL.md:492` | `hardcoded_ip_port` | LOW | `-L 127.0.0.1:16080:127.0.0.1:<viewer-port> <vm-user>@<vm-tailnet-host> 'sleep 1800'` |
| `skills/workspace-setup/SKILL.md:498` | `hardcoded_ip_port` | LOW | `curl --fail --connect-timeout 5 --max-time 10 http://127.0.0.1:16080/vnc.html -o /dev/null` |
| `skills/workspace-setup/SKILL.md:501` | `hardcoded_ip_port` | LOW | `http://127.0.0.1:16080/vnc.html` in Remote desktop connection |

Verdict: **SAFE**, 0 CRITICAL + 0 HIGH + 2 MEDIUM + 3 LOW. `alans-way-computer`:
SAFE, 2 MEDIUM (`python_subprocess` at `__init__.py:190` and `:951`).

The scanner also reads Markdown. Wording a README disclosure with the literal SSH
key-file name or the privilege-escalation command scores CRITICAL `ssh_backdoor`
or MEDIUM `sudo_usage`, and a CRITICAL makes the verdict DANGEROUS, which blocks
installs. `tests/test_plugin_scan.py` asserts the exact inventory; supply the
three upstream files under `$HERMES_SCANNER_ROOT/tools/` to run it (it skips
otherwise).
