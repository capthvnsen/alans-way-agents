# Proactivity and identity: one portable per-agent profile

Research snapshot: 2026-10-27. **Decision proposal, not implemented.** Only this document changes. Source inspection uses `alans-way-agents` at `4da7c64bcf11fec0c10c1cddc569ec125a93a032` and a separate temporary, read-only clone of `alans-way` at `7e05d521c2a2f9add46423e39a4b27d6e67049e3`. All repository evidence below links to those immutable revisions. No private profiles, environment files, credentials, live chats or running gateways were inspected.

## Decision against Alex’s seven authoritative features

**Propose one operator-owned `agent-profile.json` per logical agent, consumed entirely through supported plugins, instructions and added tools.** Required targets are **Hermes and Grok Bot**; **Claude Duet is conditional**. Do not fork agents, replace their main production runtimes or build another conversation system. The file supplies identity/voice to supported instruction seams and a validated policy to Alan’s tool gate. Native provider permissions remain an independent ceiling.

| Authoritative feature | Consequence for this profile proposal and current evidence |
| --- | --- |
| 1. Simple chat on the left; integrated browser feel | Keep profile controls small and approvals in the acting agent’s conversation. The current app embeds Telegram Web and local Chromium; this does not establish a Grok-native chat pane. [`desktop/README.md:3-12`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/README.md#L3-L12) |
| 2. Extremely fast, accurate MCP/CUA on the local Mac and specifically in Workspace, including remote agents | Reuse existing drivers and current refs/effect replies; parse/cache profile policy outside the hot path, revalidate revisions before input, and add no model call for policy decisions. Measure end-to-end remote latency and task success against Alex’s Codex computer-use reference; parity is **UNVERIFIED**, not inferred from common MCP names. Existing remote guidance already favors controls, short batches and avoiding redundant snapshots. [`desktop/docs/remote-agents.md:71-76`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/docs/remote-agents.md#L71-L76) |
| 3. Lid close hands browser work to the VM | Keep logical agent/task identity across execution hosts; invalidate pending approvals on host/document changes. The README says new-task-only fallback, but current router code restores mirrored tabs or continues a remembered page; checkpoint/restore can require review. Treat that documentation/code mismatch explicitly: production seamless continuation remains **UNVERIFIED**. [Router: `alans-way/scripts/workspace-router.cjs:1632-1682`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L1632-L1682) [`README.md:72-75`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/README.md#L72-L75) [`desktop/src/main.cjs:2617-2647`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/main.cjs#L2617-L2647) |
| 4. Live VM desktop window | The profile names the actor, not the stream. Preserve the existing noVNC viewer and distinguish watch/take-control from tool permission or business-action approval. Current app embeds an operator-supplied viewer; it is not evidence that this installation has a running stream. [`desktop/README.md:17-18`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/README.md#L17-L18) [`README.md:75-75`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/README.md#L75-L75) |
| 5. Same threads on any device, through Telegram or the agent’s own app | Keep each agent provider as conversation owner; bind profile to that existing owner/thread and route replies there. Never “sync” transcripts between Hermes and Grok by copying memory. Current app’s Telegram embedding preserves that provider’s thread; a common Grok/Telegram transcript bridge is **UNVERIFIED**. [`README.md:72-72`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/README.md#L72-L72) [`docs/continuity.md:3-15`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/docs/continuity.md#L3-L15) |
| 6. Main production agents, purely added tools; no forks | Hermes’s existing plugin is the concrete loading seam. Grok gets the same MCP implementation over its supported connector; hosted reachability and account-wide connector scope must be checked. Duet remains optional until its supported connector can reach Workspace privately. No agent-specific CUA rewrite. [`desktop/docs/remote-agents.md:3-22`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/docs/remote-agents.md#L3-L22) |
| 7. Proactivity | Separate initiative (`off`, `suggest`, `act`) from cadence; gate actions in Alan’s tools, use the provider’s native scheduler/primary where supported, and avoid competing check-in loops. Hermes already provides cadence and narrowing controls; exact semantics are below. [Timing: `alans-way/proactivity.py:15-74`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L15-L74) [Narrowing: `alans-way/proactivity.py:130-153`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L130-L153) |

### Tailscale: confirm the backbone; challenge an unconditional “everything” promise

**Confirm Tailscale for all Alan-controlled Mac↔VM tool, control and viewer traffic.** The desktop repo explicitly requires it for computer/server communication. Keep MCP HTTPS inside the tailnet if SSH is blocked; do not silently replace private networking with a public tunnel. A network connection provides reachability, not per-agent identity, approval or application permissions. [`README.md:15-17`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/README.md#L15-L17) [`desktop/docs/remote-agents.md:14-22`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/docs/remote-agents.md#L14-L22)

**Challenge universal hosted-client reachability.** Grok Bot’s official private-network guide documents Tailscale through Enterprise Team Setup, with a tested exit-node pattern and separate network policy; subnet-router arrangements need pilot validation. Routing through the member’s laptop is not private-network access and is unsuitable as the sole lid-close path. Alex’s account eligibility and working hosted connector route are **UNVERIFIED**. [Grok Bot private networks](https://docs.x.ai/grok-bot/private-networks) (retrieved lines 104–128, 162–179).

A crucial distinction: Grok Bot’s **remote URL MCP calls originate from its connector servers**, whereas command servers run on its hosted computer. Joining the computer to Tailscale does not establish a private URL connector route. Prefer testing a supported command connector on the tailnet-joined computer, using private HTTP if outbound SSH remains blocked; verify the command process and its network route actually carry the call. [Grok Bot MCP network policy](https://docs.x.ai/grok-bot/security) (retrieved lines 122–127).

Do not confuse that with generic grok.com custom connectors, whose documentation requires public reachability, or with the xAI Remote MCP API. If the actual client is outside the tailnet and cannot join through a supported route, the strict Tailscale-only integration is **blocked for that client**, not solved by MCP configuration. Telegram and vendor app/model services also retain their provider networking; a tools-only extension cannot claim to put those third-party internals onto Alex’s tailnet. [Grok connectors](https://docs.x.ai/grok/connectors) (retrieved lines 136–152), [xAI remote MCP](https://docs.x.ai/developers/tools/remote-mcp) (retrieved lines 232–252).

## What exists today

### Soul, identity and behavior are distributed

| Surface | Verified behavior and implication |
| --- | --- |
| Hermes soul/persona | The plugin describes its texting voice as layering over user-owned `SOUL.md` and `agent.system_prompt`, without writing either; its safety/style wording yields to the user’s own persona. This is the plugin’s contract, not an independent audit of every upstream Hermes precedence rule. [voice: `alans-way/voice.py:1-66`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/voice.py#L1-L66) |
| Per-agent voice | `voice` plugin state holds `texting`/`default`; missing or invalid state selects texting. A pre-model note applies on Telegram, desktop, TUI and bot-room chats; proactive prompts carry their own wording. `/tone default` does not change check-in voice. Output polish affects model replies, not a new renderer for approval cards. [voice loading: `alans-way/voice.py:161-225`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/voice.py#L161-L225) [voice: `alans-way/voice.py:1-66`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/voice.py#L1-L66) |
| Behavioral instructions | `TASK_NOTE` says finish authorized work, verify outcomes, continue without “keep going,” and interrupt for owner decisions, login/CAPTCHA, approval or a real blocker. It is prompt guidance injected through plugin hooks. [task behavior: `alans-way/__init__.py:13-30`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/__init__.py#L13-L30) [plugin hooks: `alans-way/__init__.py:117-193`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/__init__.py#L117-L193) |
| Identity and loading | Plugin home resolution uses the profile-bound Hermes home because a multiplexed gateway can serve multiple profiles; each profile registers voice/hooks, but ordinary spontaneous check-ins belong to the primary unless cross-bot configuration designates another primary. [profile identity: `alans-way/__init__.py:87-114`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/__init__.py#L87-L114) [plugin hooks: `alans-way/__init__.py:117-193`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/__init__.py#L117-L193) |
| Desktop repo | `docs/agent-setup.md` recommends a short user-managed SOUL pointer to the workspace skill and explicitly says it adds neither tools nor approval authority. It documents separate per-profile identity/memory/history, shared host sign-ins and a shared VPS desktop. [SOUL and fleet guidance: `docs/agent-setup.md:9-29`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/docs/agent-setup.md#L9-L29) |
| `IDENTITY.md` / `BEHAVIOR.md` | **UNVERIFIED as runtime inputs.** No common loader for files with these names was established in the reviewed plugin registration, voice or desktop setup contracts. Do not invent automatic loading or claim private installations lack such files. The verified behavior surfaces are the hooks and skills above. [plugin hooks: `alans-way/__init__.py:117-193`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/__init__.py#L117-L193) [voice loading: `alans-way/voice.py:161-225`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/voice.py#L161-L225) [SOUL and fleet guidance: `docs/agent-setup.md:9-29`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/docs/agent-setup.md#L9-L29) |

### Proactivity and scheduling

1. **Current “levels” mean frequency.** `less=240`, `normal=120`, `more=60` minutes; defaults are 120 minutes, 08:00–22:00, morning brief off. Hours use the user’s IANA zone; missing zone falls back to UTC. Each unanswered nudge doubles the wait, capped at seven days, then moves it into active hours. This does not choose a different authority level. [settings and timing: `alans-way/proactivity.py:15-74`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L15-L74)
2. **Runtime is bound and busy-aware.** The timer needs a connected gateway, a bound chat, no pause and no active turn (busy expires after three hours). It anchors on latest activity/nudge/bind, advances state before injecting, and records accepted/refused/failed. An accepted injection is only acceptance, not evidence that useful work or delivery completed. The opt-in brief uses date-stable 0–20 minute jitter and skips when the user was recently active. [timer execution: `alans-way/proactivity.py:310-380`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L310-L380) [settings and timing: `alans-way/proactivity.py:15-74`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L15-L74) The loop starts from Telegram connection, rather than every CLI plugin load. [scheduler startup: `alans-way/proactivity.py:576-624`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L576-L624)
3. **Act-then-report already exists as a prompt choice.** A check-in chooses one safe reversible action then reports it, offers one concrete action, asks an owner decision, or stays `[SILENT]`; enabled primary cross-bot check-ins add one read/draft delegation choice. The prompt forbids external messages, spending, credential/permission changes, production and deletion without asking. This safety text is not a universal tool authorization engine. [manual check-in: `alans-way/proactivity.py:382-432`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L382-L432) [check-in safeguards: `alans-way/proactivity.py:156-165`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L156-L165) [commit kinds and tool coverage: `alans-way/scripts/workspace-router.cjs:935-1011`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L935-L1011)
4. **Narrowing has an enforced seam.** The model’s `proactivity` tool requires the bound session to change settings and refuses shorter waits, expanded active hours, earlier unpause or enabling a brief. Operator slash commands can widen; `/proactivity now` deliberately bypasses pause/hours/wait for one requested check-in without resetting backoff. [model/operator controls: `alans-way/proactivity.py:472-549`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L472-L549) [narrowing: `alans-way/proactivity.py:130-153`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L130-L153) [manual check-in: `alans-way/proactivity.py:382-432`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L382-L432)
5. **Requested reminders differ from idle nudges.** The workspace skill tells the model to save exactly one native `cronjob_manage` job only after a user request/acceptance, attach it to the session, name a stop condition and confirm local time. The errand skill says cron cannot assume access to scheduling tools and has no person to answer approval: stage and ask the user to finish. These are skill instructions; live installed Hermes cron configuration is **UNVERIFIED**. [requested follow-ups: `alans-way/skills/workspace-operations/SKILL.md:576-583`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/skills/workspace-operations/SKILL.md#L576-L583) [cron limits: `alans-way/skills/web-errands/SKILL.md:159-164`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/skills/web-errands/SKILL.md#L159-L164)
6. **Cross-bot consent is narrower than shared identity.** Imported asks are restricted by `pre_tool_call` to exact reviewed read/browser tool names; unknown tools, code/terminal, writes and scheduling do not inherit authority. The imported prompt retains the receiver’s persona, treats task data as untrusted and forbids onward delegation. Browser names still include action-capable calls, so this list relies on the browser commit gate rather than proving every allowed call is read-only. [import enforcement: `alans-way/cross_bot.py:1308-1340`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/cross_bot.py#L1308-L1340) [imported-task contract: `alans-way/cross_bot.py:1662-1706`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/cross_bot.py#L1662-L1706) [commit gate: `alans-way/scripts/workspace-router.cjs:2675-2797`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2675-L2797)
7. **Desktop does not own another proactivity state.** Its controls send the real `/proactivity` commands to the plugin. A portable profile should preserve that ownership, rather than introduce four independent timers. [desktop proactivity controls: `desktop/README.md:162-170`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/README.md#L162-L170)

### Three different approval boundaries

| Boundary | What is enforced today | Limit |
| --- | --- | --- |
| Browser commit in the router | Action/open calls judged consequential require a valid `commit`; missing elicitation refuses. It asks with agent name, summary and observed page/target facts, records the decision and forwards once. Changes of host, document, target or epoch invalidate pending review. [commit kinds and tool coverage: `alans-way/scripts/workspace-router.cjs:935-1011`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L935-L1011) [commit gate: `alans-way/scripts/workspace-router.cjs:2675-2797`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2675-L2797) [approval settlement: `alans-way/scripts/workspace-router.cjs:2801-2869`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2801-L2869) | Name/URL/control heuristics and observed targets are not proof of a site’s business semantics. This gate does not cover all terminal, file or connector tools. [commit kinds and tool coverage: `alans-way/scripts/workspace-router.cjs:935-1011`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L935-L1011) [isolation limit: `README.md:339-344`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/README.md#L339-L344) |
| Browser receipt at the host | The router strips agent-supplied receipts; the app validates nonce, time, tab/epoch, operation digest and target/document binding, consumes the nonce and rechecks live targets. The desktop proxy checks the actual VM backend’s binding capability before forwarding an approved action. [receipt stripping: `alans-way/scripts/workspace-router.cjs:2919-2940`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2919-L2940) [host receipt checks: `desktop/src/agent-input.cjs:595-632`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/agent-input.cjs#L595-L632) [live target checks: `desktop/src/agent-input.cjs:645-671`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/agent-input.cjs#L645-L671) [remote capability check: `desktop/src/main.cjs:3124-3138`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/main.cjs#L3124-L3138) | Current receipts are consistency markers on a trusted channel, not cryptographic isolation from a hostile process with same-user terminal/file access. [isolation limit: `README.md:339-344`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/README.md#L339-L344) |
| Native desktop input | Hermes uses its `computer_use` provider over the router; setup’s explicit `--allow-desktop-actions` can add background action types to Hermes’s command allowlist. The desktop app separately prompts unknown remote clients; an Allow grant slides until 30 minutes idle, denial suppresses prompts for a minute, and Always allow persists trust. Known Workspace bots skip that local prompt. [computer provider transport: `alans-way-computer/__init__.py:1-10`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way-computer/__init__.py#L1-L10) [Hermes desktop opt-in: `setup.sh:2964-2990`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/setup.sh#L2964-L2990) [desktop grant lifetime: `desktop/src/desktop-approval.cjs:3-31`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/desktop-approval.cjs#L3-L31) [desktop trust UI: `desktop/src/main.cjs:2994-3005`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/main.cjs#L2994-L3005) | A desktop-access grant is not request-bound approval of a purchase or message. It must not be translated into blanket permission for consequential app actions. This is a proposed restriction; semantic gating of every native-app transaction was not verified. [desktop grant lifetime: `desktop/src/desktop-approval.cjs:3-31`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/desktop-approval.cjs#L3-L31) [desktop trust UI: `desktop/src/main.cjs:2994-3005`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/main.cjs#L2994-L3005) |

**Remote MCP has a concrete constraint:** the HTTP bridge removes `elicitation`, `sampling` and `roots`, and answers router-to-client requests as unsupported. Consequently browser commit requests cannot obtain the router’s approval through this bridge. SSH setup fixes a bot identity in its forced command and enables desktop actions, which makes server-side policy enforcement particularly important for non-Hermes clients. [HTTP capabilities: `alans-way/scripts/remote-agent-bridge.cjs:164-171`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/remote-agent-bridge.cjs#L164-L171) [remote MCP bridge: `alans-way/scripts/remote-agent-bridge.cjs:99-108`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/remote-agent-bridge.cjs#L99-L108) [commit gate: `alans-way/scripts/workspace-router.cjs:2675-2797`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2675-L2797) [remote connector identity: `alans-way/scripts/setup-remote-agent.sh:134-154`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/setup-remote-agent.sh#L134-L154)

### Native Grok Bot and conditional Duet behavior

Grok Bot has its own durable names/jobs, per-bot memory and a primary that initiates check-ins. Lasting behavior is taught in chat, not a personal-Bot description field; the docs explicitly say memory is not a safety boundary. Native routines can run on schedules or events, use the Bot timezone and expose saved instructions/run history. The correct adapter maps profile intent to these supported features rather than starting a second primary or promising a new provider API. Exact import/export automation for those settings is **UNVERIFIED**. [Bot identity/memory](https://docs.x.ai/grok-bot/bots) (retrieved lines 86–120, 204–213), [routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) (lines 145–152, 187–195).

Grok Bot Auto Review is normally on; owner Custom Rules can say Ask first or Allow automatically, and Ask first wins on overlap. Turning Auto Review off disables those rules. Background email has a separate draft-until-Send policy. These are product controls, not evidence that its permission cards answer this router’s MCP elicitation or bind the same transaction. Profile policy should be an additional restriction on Alan’s tools. [Grok approvals](https://docs.x.ai/grok-bot/approvals-security-and-privacy) (retrieved lines 107–138).

Claude Duet is a US Pro/Max waitlist research preview. It inherits Claude memory, skills, plugins and connectors, runs on its own cloud computer, and has proactive briefs/follow-ups; it is not yet a proven main-production target for this integration. The help page explicitly says users cannot watch or take over its browser. Its native safety system asks for important actions and keeps some categories off limits. Thus it may make sense **only as a supported connector client to Alan’s visible browser**, subject to preview access, private reachability and approval tests; do not adopt its hidden browser as the Workspace/VM view. [Duet getting started](https://support.claude.com/en/articles/17631495-get-started-with-claude-duet) (retrieved lines 43–72, 112–120), [Duet safety](https://claude.com/resources/articles/claude-duet-safety-privacy-and-security) (lines 32–44).

## Proposed format: `agent-profile.json`

Everything from this section through the rollout section is **PROPOSED**. No existing harness is claimed to understand this schema. JSON avoids an extra parser dependency; the schema and example are embedded here so this research PR adds only one file.

The profile belongs in a private operator-managed per-agent directory, not an untrusted checkout. Keep the canonical approved revision available on the always-on VM and authenticated replicas at execution hosts; do not make the sleeping laptop the only policy source. Each host refuses a missing/stale required revision and accepts authority increases only through an authenticated owner update. Replicas are the same profile format, not independent editable copies. Signed distribution and isolation from same-user agent shells are implementation work, not existing guarantees. A small trusted registry outside this file maps authenticated principals to profile IDs, connector server identities and resource handles. `server`, `tool` and `resources` below are exact registry identifiers, never wildcard names or client claims. `native/reply_draft` is a proposed logical operation meaning a draft in the owner’s chat, not an existing tool to register. Adapter mappings must fail if an identifier cannot be implemented exactly.

### Schema (JSON Schema 2020-12)

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "Portable agent profile v1 (proposed)",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "version",
    "id",
    "identity",
    "voice",
    "proactivity",
    "trusted_tools",
    "approvals"
  ],
  "properties": {
    "version": {
      "const": 1
    },
    "id": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9-]{0,63}$"
    },
    "identity": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "name",
        "purpose"
      ],
      "properties": {
        "name": {
          "type": "string",
          "minLength": 1,
          "maxLength": 80
        },
        "purpose": {
          "type": "string",
          "minLength": 1,
          "maxLength": 1000
        }
      }
    },
    "voice": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "instructions",
        "casual_max_sentences"
      ],
      "properties": {
        "instructions": {
          "type": "string",
          "minLength": 1,
          "maxLength": 2000
        },
        "casual_max_sentences": {
          "type": "integer",
          "minimum": 1,
          "maximum": 10
        }
      }
    },
    "proactivity": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "level",
        "idle_minutes",
        "timezone",
        "active_start_hour",
        "active_end_hour",
        "morning_brief"
      ],
      "properties": {
        "level": {
          "enum": [
            "off",
            "suggest",
            "act"
          ]
        },
        "idle_minutes": {
          "type": "integer",
          "minimum": 15,
          "maximum": 1440
        },
        "timezone": {
          "type": "string",
          "minLength": 1,
          "maxLength": 80
        },
        "active_start_hour": {
          "type": "integer",
          "minimum": 0,
          "maximum": 23
        },
        "active_end_hour": {
          "type": "integer",
          "minimum": 0,
          "maximum": 23
        },
        "morning_brief": {
          "type": "boolean"
        }
      }
    },
    "trusted_tools": {
      "type": "array",
      "maxItems": 64,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "server",
          "tool",
          "effects",
          "resources"
        ],
        "properties": {
          "server": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100
          },
          "tool": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100
          },
          "effects": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": true,
            "items": {
              "enum": [
                "read",
                "draft",
                "prepare",
                "commit",
                "desktop_input",
                "schedule",
                "delegate",
                "policy_write",
                "secret_read"
              ]
            }
          },
          "resources": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": true,
            "items": {
              "type": "string",
              "minLength": 1,
              "maxLength": 200
            }
          }
        }
      }
    },
    "approvals": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "read",
        "draft",
        "prepare",
        "commit",
        "desktop_input",
        "schedule",
        "delegate",
        "policy_write",
        "secret_read"
      ],
      "properties": {
        "read": {
          "enum": [
            "allow",
            "ask",
            "deny"
          ]
        },
        "draft": {
          "enum": [
            "allow",
            "ask",
            "deny"
          ]
        },
        "prepare": {
          "enum": [
            "allow",
            "ask",
            "deny"
          ]
        },
        "commit": {
          "enum": [
            "allow",
            "ask",
            "deny"
          ]
        },
        "desktop_input": {
          "enum": [
            "allow",
            "ask",
            "deny"
          ]
        },
        "schedule": {
          "enum": [
            "allow",
            "ask",
            "deny"
          ]
        },
        "delegate": {
          "enum": [
            "allow",
            "ask",
            "deny"
          ]
        },
        "policy_write": {
          "enum": [
            "allow",
            "ask",
            "deny"
          ]
        },
        "secret_read": {
          "enum": [
            "allow",
            "ask",
            "deny"
          ]
        }
      }
    }
  }
}
```

Additional semantic validation is mandatory: timezone must resolve to an installed IANA zone; start/end hours must differ; `(server, tool)` pairs must be unique; resource handles must resolve in the operator registry. Unsupported versions, extra keys, missing values, unmapped tools and unavailable effect classifiers fail closed with a visible configuration error. No silent default may turn proactivity on.

The schema permits representing restrictive choices, but the platform floor additionally requires `policy_write=deny` and `secret_read=deny`, and prohibits `allow` for `commit`, `desktop_input`, `schedule` and `delegate` in v1. Such profiles fail semantic validation. Supporting standing transaction grants would need a reviewed later version with explicit scope and limits, not an undocumented meaning of “trusted.”

### Example file

```json
{
  "version": 1,
  "id": "alan",
  "identity": {
    "name": "Alan",
    "purpose": "Move the owner’s active tasks forward and report verified outcomes."
  },
  "voice": {
    "instructions": "Warm, direct, plain words. Lead with the result; interrupt for real decisions, blockers or material side effects. Keep research complete. Never hide approval prompts or failures.",
    "casual_max_sentences": 3
  },
  "proactivity": {
    "level": "act",
    "idle_minutes": 120,
    "timezone": "America/Denver",
    "active_start_hour": 8,
    "active_end_hour": 22,
    "morning_brief": false
  },
  "trusted_tools": [
    {
      "server": "workspace_browser",
      "tool": "cua_alans_way_snapshot",
      "effects": [
        "read"
      ],
      "resources": [
        "owner-workspace"
      ]
    },
    {
      "server": "workspace_browser",
      "tool": "cua_alans_way_open",
      "effects": [
        "prepare",
        "commit"
      ],
      "resources": [
        "owner-workspace"
      ]
    },
    {
      "server": "workspace_browser",
      "tool": "cua_alans_way_action",
      "effects": [
        "read",
        "prepare",
        "commit"
      ],
      "resources": [
        "owner-workspace"
      ]
    },
    {
      "server": "native",
      "tool": "reply_draft",
      "effects": [
        "draft"
      ],
      "resources": [
        "owner-chat"
      ]
    },
    {
      "server": "native",
      "tool": "cronjob_manage",
      "effects": [
        "read",
        "schedule"
      ],
      "resources": [
        "owner-chat"
      ]
    }
  ],
  "approvals": {
    "read": "allow",
    "draft": "allow",
    "prepare": "allow",
    "commit": "ask",
    "desktop_input": "ask",
    "schedule": "ask",
    "delegate": "deny",
    "policy_write": "deny",
    "secret_read": "deny"
  }
}
```

`owner-workspace` and `owner-chat` are placeholders for operator-bound resources, not credentials. This example does not grant desktop input: the `ask` rule is necessary but insufficient without an explicitly trusted matching tool. The schedule tool may list jobs as a read, but creation/update/removal/resume is `schedule`; a policy evaluator must classify the operation, not just its tool name. No new tool is implied by listing a logical adapter operation.

### Exact initiative and approval semantics

| Initiative | Automatically initiated behavior | Explicitly requested work |
| --- | --- | --- |
| `off` | No idle checks or morning briefs; no spontaneous tool calls or messages. | Continue the requested task using the same tool gate. Existing explicitly authorized reminder jobs remain, unless paused/cancelled separately. |
| `suggest` | At most one useful suggestion/question to the owner per due tick; may use allowed reads to establish current evidence, but no draft writes or browser preparation. No useful evidence → silence. | Same gate as every other level; the user’s request supplies scope, never a bypass of an `ask`/`deny` rule. |
| `act` | May read, draft in the owner chat or private scratch space, and prepare a browser task only when a reviewed classifier proves the operation stays within its safe preparation contract. Then report a verified result; if a commit is next, stop and request review. No arbitrary shell, shared-document edits or native-app input counts as “reversible.” | Complete authorized scope without repeated conversational confirmation for allowed operations; route every protected effect to its approval path. |

`idle_minutes` is independent of initiative. Preserve the existing cadence algorithm as the proposed contract: anchor at latest user/assistant task activity, prior idle attempt or binding; interval `min(idle_minutes × 2^n, 10080)` minutes after `n` unanswered attempts; move outside-window due times to the next start. End hour is exclusive; overnight windows wrap. Each attempted idle injection, including refused or silent ones, spends an attempt; a real owner reply resets `n`. Persist before dispatch, avoid overlap, treat a job/turn acceptance separately from completion. These proposed rules intentionally retain the current timer shape. [settings and timing: `alans-way/proactivity.py:15-74`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L15-L74) [timer execution: `alans-way/proactivity.py:310-380`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L310-L380)

Morning brief is at local window start plus date-stable 0–20 minute jitter, once per local date, with a two-hour lateness window and two-hour recent-user suppression; `off` suppresses it regardless of its flag. A manual “check now” is a single user-requested turn and does not unpause the timer or grant wider action authority. A runtime pause is an immediate ceiling over profile settings; changes that widen cadence, hours, initiative, brief, tools, resources or approval permissions require the operator. This extends the current narrowing principle to every adapter. [settings and timing: `alans-way/proactivity.py:15-74`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L15-L74) [timer execution: `alans-way/proactivity.py:310-380`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L310-L380) [manual check-in: `alans-way/proactivity.py:382-432`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L382-L432) [narrowing: `alans-way/proactivity.py:130-153`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L130-L153)

Profiles describe preferences, not running jobs. Keep pause/revocation, backoff, last brief date, owner-session binding, scheduler lease and job IDs in the authoritative runtime store. Explicit reminder creation requires a trusted user instruction or operation-bound approval, a destination, time/timezone and stop condition; an unanswered offer creates nothing. An explicit “remind me at 5” can satisfy the scheduling approval using that authenticated request, without a redundant question. Scheduled turns cannot schedule/delegate more work or approve commits, even when a foreground profile could ask. A profile change/revocation is rechecked at each tick and protected operation.

Effects have fixed meanings:

| Effect | Meaning | Example policy |
| --- | --- | --- |
| `read` | Inspect an authorized resource without mutation or sending information to a new audience. A URL that performs an action is not a read. | `allow` |
| `draft` | Produce content only in the owner conversation or approved private scratch resource; no shared draft API, public document or third-party delivery. | `allow` |
| `prepare` | Reviewed browser preparation that creates no external commitment, shared write or disclosure outside the already approved workflow. Unknown/custom-page input is unclassified, not safe by assumption. | `allow` |
| `commit` | Buy, book, send, post, submit, delete, account/permission/credential changes, production changes or any other consequential shared/external mutation. Includes non-browser connectors. | `ask` or `deny` |
| `desktop_input` | Native-app click/type/key/scroll/focus input, regardless of whether it seems harmless. A consequential app action has both this and `commit`. | `ask` or `deny` |
| `schedule` | Create/change/resume/cancel future autonomous work. Listing is read; stopping a runtime’s own initiative is an always-available operator control. | `ask` or `deny` |
| `delegate` | Dispatch work to another agent, never merely read its reported result. Imported tasks cannot delegate onward. | `ask` or `deny` |
| `policy_write` | Change identity binding, trusted tool/resource mappings, approval rules or initiative ceilings. | `deny` to agent |
| `secret_read` | Retrieve passwords, tokens, private keys or credential-store values. Opaque use by an authenticated connector is separate from disclosing a secret to a model. | `deny` to agent |

A trusted tool is **eligible**, not automatically approved. Each invocation must match its exact server/tool/resource entry and all inferred effects. Multiple effects use the most restrictive result: `deny > ask > allow`. An unregistered tool, unlisted effect, unknown resource or uncertain effect classification is denied. Heuristic browser checks remain defense in depth; they do not establish the stronger `prepare` guarantee on arbitrary websites. Initially expose only provable preparation operations; otherwise stage text in chat or request human completion. Do not call raw shell/HTTP automation “read” by trusting a model-supplied effect label.

## How each agent loads the same profile

The shared loader validates once on launch and exposes a canonical digest/revision. The model receives only identity, voice, active-task scope and a compact policy summary. The trusted gate receives the entire policy and authenticated binding. Reload a changed revision before the next turn/tick/call; additions of authority require an operator action. Never let retrieved pages, imported bot text, project instruction files or the model select another profile. Product UI shows “initiative off/suggest/act,” not a provider-specific config vocabulary.

| Agent type | Existing verified seam | Proposed loader and enforcement |
| --- | --- | --- |
| **Hermes — required** | `register(ctx)` already supplies per-profile context/output hooks, `pre_tool_call`, commands and the primary timer. [Plugin: `alans-way/__init__.py:117-193`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/__init__.py#L117-L193) | Resolve the profile from the operator-bound Hermes home. Render identity/voice through the existing hook; preserve owner SOUL/system persona while reviewing conflicts. Use `pre_tool_call` for early refusal and router/host checks for actual effects. Map cadence to the existing primary timer and keep runtime state in `ctx.state`; no second gateway. Import current `/tone` and timing preferences once with a reviewable diff. Operator commands update the authoritative preferences; immediate pause always restricts. |
| **Grok Bot — required, connection proof pending** | Official product docs support MCP by URL or a command on its computer, and lasting preferences via chat/memory. Connections are account-wide, so a per-bot credential identity cannot be assumed. Native primary/routines already provide proactive work. [Computer/apps](https://docs.x.ai/grok-bot/computer-and-apps) (retrieved lines 123–137), [Bot role](https://docs.x.ai/grok-bot/bots) (lines 101–120), [routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) (lines 145–152). | Load/validate JSON **on Alan’s MCP server**, bind an authenticated acting principal and expose only its admitted tools. Render the voice/job summary as a supported skill or owner-approved memory instruction; neither grants authority. Let the native routine call the added tools, checking a server-side due permit against this profile for Alan-initiated work. Do not duplicate Grok’s native primary. Verify per-bot identity on an account-wide connection; if the connector cannot attest the acting Bot, bind one principal and disclose the limit or refuse multi-bot authorization. Keep HTTP browser commits blocked until an independent owner-bound approval path works. |
| **Claude Duet — conditional** | Inherits Claude skills/plugins/connectors and has a native cloud proactive loop; exact Workspace MCP/Tailscale operation, per-agent profile loading and elicitation are **UNVERIFIED**. [Duet getting started](https://support.claude.com/en/articles/17631495-get-started-with-claude-duet) (retrieved lines 63–72). | Use only a supported plugin/connector and an owner-approved identity/voice summary; server-side profile controls Alan’s tools. Do not install an alternate Duet runtime or introduce another scheduler. Accept only after private route, visible Workspace browser, correctly bound action approvals and native-thread delivery are demonstrated. Otherwise defer without blocking Hermes/Grok. |

**Coverage limit for tools-only integration:** this profile can enforce restrictions on Alan’s added tools. It cannot stop a hosted agent using its own browser, other connectors or native unsolicited messages. `off` is globally enforceable only if the provider’s owner controls also suppress its native proactivity; exact programmatic synchronization is **UNVERIFIED**. The status must say which fields are enforced at the server, reflected in provider settings, or unsupported. Never advertise a universal safety boundary based on a memory instruction.

**Future CLI note only:** Claude Code and Codex are not target integrations. If later justified, use a thin supported CLI wrapper over Tailscale to the same MCP gate; no new driver, scheduler or agent fork.

Native provider policy and the portable policy intersect: either can restrict, neither can widen the other. “Never ask”/headless modes cannot auto-accept an `ask` operation. If any tool path bypasses the shared gate, the adapter must remove it, sandbox its access to protected resources, or advertise only partial enforcement. An unrestricted same-user shell cannot become policy-enforced by adding instructions.

## Approval gate: proposed decision path

Reuse the existing browser gate’s freeze/ask/validate/execute-once shape and host receipts, but extend its policy inputs to all admitted tool effects. Current code already rejects missing approval transport, strips model receipts and validates bound browser actions; it does not yet read this profile or gate every effect above. [commit gate: `alans-way/scripts/workspace-router.cjs:2675-2797`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2675-L2797) [receipt stripping: `alans-way/scripts/workspace-router.cjs:2919-2940`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2919-L2940) [host receipt checks: `desktop/src/agent-input.cjs:595-632`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/agent-input.cjs#L595-L632)

```text
Authenticated principal -> registry-bound agent/profile/revision + owner session
    -> validate profile, tool identity, arguments and resource scope
    -> trusted adapter infers ALL effects (unknown -> deny)
    -> intersect platform floor, harness policy, profile, invocation scope
       and imported/scheduled-turn restrictions
    -> deny: return reason; no effect
    -> allow: execute within task/initiative scope; verify and report
    -> ask: freeze exact invocation + resource/host + profile revision
         -> authorized owner surface available?
              no: stage and report approval unavailable
              yes: show agent, real target, effect, cost/recipient and scope
                   -> decline/timeout/cancel: no effect; no workaround/retry
                   -> approve: re-read current policy + binding + live target
                       -> stale/revoked/moved: no effect; new review needed
                       -> valid: consume one-use receipt, execute ONCE,
                          verify observed outcome, report receipt or uncertainty
```

The proposed frozen record includes principal/profile ID, profile digest, owner session, tool/server, canonical arguments, resource and host identity, browser document/target/epoch where applicable, expiry and nonce. The owner approval is bound to that record, authenticated independently of model text and unavailable to untrusted page content. Extending the current receipt requires a coordinated router/connector/host capability version; an old host must refuse, not ignore, new required fields. A receipt is never copied into another tab, host, task or agent.

For a batch, classify every step before execution and reject an unclassifiable batch. Approval covers only the frozen listed steps and reviewed targets, not a changing loop. If a later step fails after earlier effects ran, return partial completion and verify state; a batch is not atomic. After a lost reply, outcome is **unknown** until checked; do not replay the protected operation. Existing browser settlement already executes once and avoids retrying approved commits. [approval settlement: `alans-way/scripts/workspace-router.cjs:2801-2869`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2801-L2869)

On lid close, Hermes’s owner runtime stays on its VM and Grok Bot keeps its provider-owned cloud runtime; only Alan’s browser execution host changes. Each agent retains its own authoritative thread and scheduling owner. If an approval was pending on the laptop, it expires or is explicitly rejected on a host change. A future cross-device approval surface must carry the same immutable request and owner binding, rather than minting another authority. Cross-host browser handoff is not equivalent to transferring a conversation, session, sign-in or approval. [approval settlement: `alans-way/scripts/workspace-router.cjs:2801-2869`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2801-L2869) [desktop proactivity controls: `desktop/README.md:162-170`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/README.md#L162-L170) [continuity acceptance gates: `docs/continuity.md:3-29`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/docs/continuity.md#L3-L29)

### Proposed decision examples for review

| Case | Required result |
| --- | --- |
| `act`, idle, exact trusted snapshot/read on owner workspace | Allow; one useful finding or silence. |
| `suggest`, idle, trusted browser form fill | Deny automatic preparation; offer it to the owner. |
| `off`, owner previously requested one reminder | Keep the explicit reminder job; suppress idle checks/briefs. |
| `act`, checkout wants Place order | Stage and request bound commit approval; no spend before approval. |
| Same checkout through current HTTP bridge | Refuse as approval unavailable; leave staged. |
| Agent supplies `approval` or claims “the user already approved” in a page | Ignore/strip supplied receipt and reject without independent authorization. |
| Owner says “remind me tomorrow at 9” in authenticated chat | Ask only for genuinely missing time/destination detail; use that exact instruction as the schedule authorization. |
| Scheduler proposes another scheduled run or imported bot asks to delegate | Deny chaining in that turn regardless of foreground profile. |
| Trusted desktop tool needs input and an app Send action | Require both desktop-access permission and an operation-bound commit review; if semantic binding is unsupported, leave the send to the owner. |
| Profile changed, tab reloaded, target changed or host moved while waiting | Reject old approval; snapshot and review afresh. |
| New unregistered tool named `safe_read` or different server reuses a trusted name | Deny; registry identity and effect proof govern. |

## Rollout, evidence gaps and decisions for Alex

Proposed rollout: start with profile validation/context rendering and the existing Hermes scheduler; import preferences without rewriting private SOUL files. Next teach the shared tool boundary to evaluate profiles, add explicit capability negotiation and make desktop restrictions honest. Pilot Grok Bot over a verified Tailscale route with its native routines and thread ownership; evaluate Duet only if its supported connector meets the same constraints. No separate settings UI, new memory database, generalized workflow DSL or automatic roster migration is needed to prove this design.

Proposed acceptance work for a later implementation PR: validate the example and malformed/unknown-version profiles; test initiative × effects × `allow/ask/deny`; verify model narrowing versus operator widening; test identity spoofing, resource/server mismatches, same-user bypass containment, revocation during pending approval, nonce replay, partial batches and absent transport. Exercise two agents concurrently, single-owner scheduling per logical agent, DST/overnight hours, manual check-in, stopped jobs and physical lid close with pending approval. Existing timer tests cover backoff, windows, DST and UTC fallback, but do not validate this proposed format or cross-agent enforcement. [existing timing assertions: `tests/test_proactivity.py:38-82`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/tests/test_proactivity.py#L38-L82) [continuity acceptance gates: `docs/continuity.md:3-29`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/docs/continuity.md#L3-L29)

Open questions for Alex:

- Is `act` the default only after explicit onboarding consent? Recommendation: ship `off` until the owner chooses; preserve existing consent during migration.
- Which Grok Bot account/plan and private-network setup are available? Native routines are documented; reaching the tailnet while the Mac is asleep, attesting the acting Bot and delivering Alan’s tool result to the existing native thread remain **UNVERIFIED** here.
- Is Claude Duet preview access available, and can its connector reach the tailnet without a public bridge? Defer it until both are demonstrated.
- Should the first portable version include native desktop commits? Recommendation: read/prepare only until action/recipient binding is possible; a 30-minute access grant cannot express the decision being approved.
- Is any standing authorization for purchases, messages or delegation actually needed? Recommendation: omit it from v1; add a bounded grant only for a demonstrated workflow.
- On lid close, which tasks may move to a VM browser versus wait for the owner’s host and sign-in? Recommendation: preserve host-specific intent and never transfer pending approvals.

Related research is deliberately not duplicated. I read [compatibility draft PR #151](https://github.com/capthvnsen/alans-way-agents/pull/151) at `36eaa32d5526b56143a81f97fdd0e29e65068bba` and [simplification draft PR #232](https://github.com/capthvnsen/alans-way/pull/232) at `159f201b6a09093f96ac647b222739e64aaf9d18`. Both belong in the synthesis; this report owns profile semantics and enforcement, not their larger architecture or compatibility work. [Compatibility: `docs/research/agent-compat-matrix.md:86-104`](https://github.com/capthvnsen/alans-way-agents/blob/36eaa32d5526b56143a81f97fdd0e29e65068bba/docs/research/agent-compat-matrix.md#L86-L104), [simplification profile: `docs/research/agent-agnostic-simplification.md:291-334`](https://github.com/capthvnsen/alans-way/blob/159f201b6a09093f96ac647b222739e64aaf9d18/docs/research/agent-agnostic-simplification.md#L291-L334).

**Reconcile, do not ship competing formats:** the simplification draft proposes app-owned YAML with frequency `level` and initiative `mode`, and supports desktop session grants; this report recommends JSON, explicit `idle_minutes`, initiative `level` and effect-scoped `allow/ask/deny`. Adopt one wire format before implementation; use this report’s JSON schema as the proposed v1 and render owner UI without making it the only offline policy authority. The UI wording may say “ask first”/“act then report,” but `suggest` is narrower than allowing actions after one broad chat confirmation. The simplification draft’s Funnel path is a **public-ingress product exception**, not a necessary consequence of Tailscale or a verified substitute for the command-connector pilot. Its identity/isolation concerns remain valid; avoid claiming that a portable profile alone resolves them. [Simplification: `docs/research/agent-agnostic-simplification.md:208-230`](https://github.com/capthvnsen/alans-way/blob/159f201b6a09093f96ac647b222739e64aaf9d18/docs/research/agent-agnostic-simplification.md#L208-L230), [profile/approval: `docs/research/agent-agnostic-simplification.md:291-334`](https://github.com/capthvnsen/alans-way/blob/159f201b6a09093f96ac647b222739e64aaf9d18/docs/research/agent-agnostic-simplification.md#L291-L334).

Validation for this research artifact: JSON blocks parsed; schema/example structure and enum/required-key constraints checked with a dependency-free recursive assertion check; immutable local-source paths and line bounds checked; publication check and one-file diff reviewed. No application code, config, tests or CI changed. No live provider, scheduler, delivery, laptop handoff or approval integration was exercised; all proposed adapters remain **UNVERIFIED** until implemented and tested.

## Ranked top-5 recommendations

1. **Keep one small operator-owned profile and server gate for Hermes and Grok Bot, as added tools.** Render identity/voice without rewriting SOUL files or forking agents; bind real principal, resource and revision before effects. Conditional Duet support must meet the same contract. [Plugin: `alans-way/__init__.py:117-193`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/__init__.py#L117-L193) [Gate: `alans-way/scripts/workspace-router.cjs:2675-2797`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2675-L2797)
2. **Prove fast remote CUA and request-bound approvals on the local Mac and Workspace browser.** Cache validated policy locally, reuse current observations, benchmark against Alex’s Codex CUA reference, and keep HTTP commits unavailable until real owner approval works. A trusted tool or desktop session grant is insufficient. [`desktop/docs/remote-agents.md:14-22`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/docs/remote-agents.md#L14-L22) [`desktop/docs/remote-agents.md:50-76`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/docs/remote-agents.md#L50-L76)
3. **Keep Tailscale as the private backbone and resolve Grok’s supported route before claiming support.** Do not substitute generic grok.com public connectors for Grok Bot networking. Confirm account eligibility, tailnet reach after lid close and per-bot identity on account-wide apps. [Grok private networks](https://docs.x.ai/grok-bot/private-networks) (retrieved lines 104–128, 162–179), [apps](https://docs.x.ai/grok-bot/computer-and-apps) (lines 132–137).
4. **Preserve provider-owned threads and prove in-flight VM browser continuation.** Keep the live desktop viewer, invalidate old approvals on host changes, and treat login/state transfer and physical lid-close testing as acceptance work. No new conversation database or laptop-dependent relay. [`README.md:72-75`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/README.md#L72-L75) [`docs/continuity.md:3-29`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/docs/continuity.md#L3-L29)
5. **Separate initiative from cadence and use each agent’s native proactive engine once.** Define `off/suggest/act` exactly, preserve operator-only widening, and report fields that cannot be enforced outside Alan’s tools. Hermes owns its timer; Grok owns its primary/routines; avoid duplicate check-ins. [Timing: `alans-way/proactivity.py:15-74`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L15-L74) [Narrowing: `alans-way/proactivity.py:130-153`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L130-L153) [Grok routines](https://docs.x.ai/grok-bot/skills-routines-and-automations) (retrieved lines 145–152, 187–195).
