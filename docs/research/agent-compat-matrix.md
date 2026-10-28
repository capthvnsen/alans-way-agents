# Alan's Way: agent compatibility and one shared MCP surface

Research date: **2026-10-27**. Recommendation: **go-with-changes**. Reuse the shared router and computer/browser services; add thin client configuration and profile adapters. Do not claim five-client approval, screenshot, or proactivity parity yet.

## Scope and evidence

Source snapshots: `alans-way-agents` at [`4da7c64bcf11fec0c10c1cddc569ec125a93a032`](https://github.com/capthvnsen/alans-way-agents/tree/4da7c64bcf11fec0c10c1cddc569ec125a93a032), and a separate temporary, read-only clone of `alans-way` at [`7e05d521c2a2f9add46423e39a4b27d6e67049e3`](https://github.com/capthvnsen/alans-way/tree/7e05d521c2a2f9add46423e39a4b27d6e67049e3). Repository citations below pin file paths and line ranges to these snapshots. Official online documentation was searched and read; its behavior can change after this date. **UNVERIFIED** means the inspected primary sources do not establish the claim or the necessary live-client behavior was not tested. An undocumented limit is not an unlimited allowance.

This is research only: no client was configured, no real desktop was driven, no secrets or private profile files were read, and no application code, configuration, tests, or CI were changed. The only repository change is this report.

“One server” should mean **one implementation and tool contract**, with authenticated per-bot sessions. It need not mean one process for all agents: today's bridge starts one router child per MCP session using the bridge's fixed bot arguments. Multiple sessions on one bridge therefore do **not** automatically become distinct bot identities. [A2]

## Compatibility matrix

Limits are client limits unless explicitly labeled as Alan's Way limits. “SSE” below means the legacy HTTP+SSE transport; Streamable HTTP can itself use SSE responses without being that legacy transport.

| Agent | Transport: stdio / Streamable HTTP / SSE | Auth: OAuth / bearer / none | Tool count, size, and timeout limits | Images / screenshots | Approval and elicitation | Applying a per-bot profile | Existing implementation vs. missing |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Hermes** | All three documented; legacy SSE selected explicitly. [H1] | OAuth 2.1 PKCE, HTTP headers including bearer; local stdio needs no MCP-layer auth. [H1] | Upstream defaults: 300 s tool, 60 s connection, configurable. Numeric count/schema/result ceiling **UNVERIFIED**. [H1] This repo writes **120 s tool / 25 s connection**. [A3] | MCP image content reaches vision models; up to **4 images/result**; text-only models get file paths. [H2] | Form elicitation supported; URL mode unsupported. [H2] `trust: untrusted` prompts for tools not marked read-only; default is `full`. [H1] Browser commits already require elicitation. [A4] | Separate Hermes profiles have `SOUL.md`, config, skills and state. Render voice into identity instructions; retain plugin hooks for output polishing and scheduling. [H3, A1, A6] | **Have:** complete Hermes plugin, skills, browser MCP wiring, native `computer_use` provider. **Missing:** neutral profile-file schema/adapter; portability of hooks and scheduler. [A1, A3, A5, A6] |
| **Grok Bot** (product client) | Official docs support custom MCP **URL or command on its cloud computer**. Exact stdio/HTTP/SSE protocol versions are **UNVERIFIED**. [G1] Repo records outbound SSH blocked on Oct 26; HTTP is the intended fallback. That is a repo observation, not a vendor guarantee. [W1] | OAuth connector infrastructure documented; arbitrary custom bearer-header configuration and no-auth mode **UNVERIFIED** for Bot. [G1] Current bridge requires bearer. [A2] | Count/schema/result ceilings **UNVERIFIED**. Published Aug 12 changelog says unresponsive connectors time out after **3 min**; current configurability/continued applicability **UNVERIFIED**. [G2] | General computer vision is not proof of MCP image consumption: MCP `ImageContent` delivery to Bot's model **UNVERIFIED**. Server emits it already. [W2] | Auto Review and user approval cards exist; Custom Rules allow Ask first/Allow automatically. MCP form/URL elicitation **UNVERIFIED**. [G3] HTTP bridge cannot carry browser approval requests. [A2, A4] | Put job, voice and boundaries into Bot memory/chat, reusable skill, and routines for proactive work. Map trusted tools to Custom Rules plus server allowlists. Automatic loading of a repo profile file **UNVERIFIED**. [G3–G5] | **Have:** generic restricted SSH setup, HTTP bridge, fixed bot identity, app desktop permission and lease. **Missing:** verified Bot header/auth, image and elicitation handshake; profile installer; live remote-MCP acceptance evidence. [A2, A7, W3, W4] |
| **Claude Code** | stdio, Streamable HTTP, legacy SSE. Configure using `.mcp.json` or `claude mcp add`. [C1] | OAuth, static headers/bearer, or none for an appropriately configured server. [C2] | Numeric tool-count ceiling **UNVERIFIED**. Output warns at **10k tokens**, default cap **25k**; successful text above **50k characters** normally saved to file. Per-server timeout configurable; default wall cap ~28 h, idle **5 min remote / 30 min stdio**. [C1] | Inline PNG/JPEG/GIF/WebP; may resize. [C1] | Tool permissions and form/URL elicitation supported; inspect negotiated capability. [C1] | Prefer `CLAUDE.md` importing a rendered profile, or a skill/plugin. Current versions can read `AGENTS.md`, conditional on settings, version and competing `CLAUDE.md` files. Prose is guidance; permission settings enforce tool policy. [C3, C4] | **Have:** reusable router, schemas, images and form approval path over stdio. **Missing:** Claude packaging/profile adapter and verified end-to-end approvals; HTTP bridge currently removes elicitation. [A2, A4, W2] |
| **Codex CLI** | stdio and Streamable HTTP documented; standalone legacy SSE **UNVERIFIED**. `~/.codex/config.toml` → `[mcp_servers.NAME]`. [O1] | OAuth or bearer environment variable/headers; unauthenticated connections possible when server permits. [O1] | Default **10 s startup / 60 s tool**, configurable. Numeric count/schema/image-size ceilings **UNVERIFIED**; per-tool output token budget configurable. [O1] | Image input documented, but the inspected official CLI docs do not explicitly guarantee rendering arbitrary MCP image results: **UNVERIFIED for this integration**, requires smoke test. [O4] | Tool approval modes/allowlists configurable. [O1] MCP elicitation has its own approval-policy switch; app-server documents form and URL request/response paths. Exact CLI/version/approval-mode behavior needs verification. [O2, O3] | Render voice/workflow into `AGENTS.md` or skill; isolated bot launch environment supplies its own config and identity. `AGENTS.md` loads instructions before work. A profile alone cannot start scheduled turns. [O5, A6] | **Have:** protocol-compatible transport candidate, bounded observations, host binding, images. **Missing:** Codex profile/config adapter; increase default timeouts for this router; confirm image and interactive approval behavior. [A3, A4, W2] |
| **Claude Duet** | **Exists**, US Pro/Max waitlist research preview launched Oct 21. Existing Claude connectors carry over. [D1, D2] Proposed route: hosted remote connector; stdio and Duet-specific HTTP/SSE versions **UNVERIFIED**. | Inherited connector options: OAuth, static header credentials, none. Whether a specific option is available to a Duet preview account is **UNVERIFIED**. [C2, D2] | Duet-specific count/schema/size/time limits **UNVERIFIED**. General hosted Claude connector docs state ~**150k characters/result / 240 s/tool**; these are reference values, **not a Duet guarantee**. [C2] | General Claude connector docs accept text/images; Duet-specific MCP screenshot delivery **UNVERIFIED**. [C2] | Duet says it asks before consequential actions; MCP elicitation and its integration with that policy **UNVERIFIED**. [D2] | Existing skills, memory and plugins carry over. Use those for voice/workflow; exact per-bot file/system-prompt hook and external scheduling interface **UNVERIFIED**. [D2] | **Have:** remote bridge candidate and shared tools. **Missing:** preview access/client conformance, profile adapter, auth fit and browser commit approval path. Do not equate its cloud computer with the user's Mac or the configured VM. [A2, W1, D2] |

### Grok API is a separate integration

The xAI **Remote MCP API** documents Streamable HTTP and SSE, **not stdio**, with caller-provided `authorization`, extra `headers`, and `allowed_tools`. `require_approval` and `connector_id` are unsupported. These facts must not be transferred to Grok Bot's product client; they establish a possible custom API harness, not Bot connector compatibility. API-specific MCP image results, elicitation, numeric count/size caps and MCP timeout guarantees remain **UNVERIFIED**. [G6]

### Small client configuration examples

These are documentation examples only, not installed configuration. The endpoint must identify the bot through operator-controlled credentials/configuration. The current bridge is bearer-only, not an OAuth authorization server. [A2]

Claude Code project `.mcp.json` (existing bridge; browser commits remain blocked):

```json
{
  "mcpServers": {
    "alans_way": {
      "type": "http",
      "url": "https://YOUR_PROXY/mcp",
      "headers": {"Authorization": "Bearer ${ALANS_WAY_MCP_TOKEN}"},
      "timeout": 180000
    }
  }
}
```

Equivalent installation entry point: `claude mcp add --transport http --scope project alans_way https://YOUR_PROXY/mcp`; supply its authentication through the client's supported secure mechanism. Project MCP entries require workspace/server approval. [C1]

Codex CLI `~/.codex/config.toml` (timeout choices are recommendations):

```toml
[mcp_servers.alans_way]
url = "https://YOUR_PROXY/mcp"
bearer_token_env_var = "ALANS_WAY_MCP_TOKEN"
startup_timeout_sec = 30
tool_timeout_sec = 180
```

For stdio-capable clients, use the dedicated restricted-SSH command generated by `setup-remote-agent.sh`; it starts the same router and can preserve bidirectional approval requests. This does not make blocked outbound SSH work in a hosted client. [A7, W1]

## What the repositories actually implement

1. **The neutral tools already exist, with historical names.** `browser-mcp.cjs` declares 14 tools: eight `cua_alans_way_*` browser/recording tools and six `workspace_computer_*` native-app tools. Its schemas include bounded observations, browser epochs, native generations, window IDs and `expect_host`; screenshots return MCP image blocks plus geometry. Names such as `browser.*` and `computer.*` describe a proposed vocabulary, not existing registered names. Hermes can normalize dots to underscores, so avoid assuming the client-visible spelling. [W2, H1]
2. **Router and transport do not need five rewrites.** The agents repo already provides per-bot forced-command SSH setup and an HTTP front for the router. HTTP accepts POST/DELETE with JSON replies, has no GET event stream, rejects server-to-client requests, and strips elicitation/sampling/roots capabilities. JSON-only responses are permitted by Streamable HTTP; lack of SSE alone does not invalidate a basic tool server. Full client conformance is **UNVERIFIED**. [A2, A7, M1]
3. **Current bridge limits matter independently of client limits.** Requests are capped at **1 MiB**, **4 concurrent sessions**, **15 min idle**, and **5 min reply wait**. Those constants are not screenshot response-size limits. Each session gets the same configured router arguments; a shared token/listener is not a per-bot authorization mapping. [A2]
4. **Browser and desktop approvals differ.** Router browser commits require a `commit` summary and client form elicitation, refuse when unavailable, and bind approval to observed tab/page/epoch. Desktop launch/action opt-in is separate; the app asks unknown bots locally with a **40 s** prompt, temporary **30 min idle** grants, and denial cooldown. Trusted Hermes/overseer identities bypass that local prompt because their own client is expected to gate input. Broad desktop permission is not per-purchase browser approval. [A4, A8, W3]
5. **Leases and handoffs exist below MCP, not as a complete public tool family.** On Mac the app serializes launch/menu/action by bot identity with active-call exclusion and **20 s** idle expiry; competing input returns `desktop_busy` and retry timing. Reads can still expose shared desktop state, and the app constructs this lease only on Darwin: equivalent cross-agent Windows/Linux lease behavior is **UNVERIFIED**. Browser `action` supports claim/release. The app has a cross-host checkpoint/restore handoff function with `review_required`, while the router handles failover. No dedicated `lease.*` or `handoff.*` tools appear in the inspected MCP tool list. [W2, W4, W5]
6. **Hermes has extra adapter behavior.** The provider starts its own router with desktop input enabled, converts native controls into Hermes computer-use observations, attaches screenshots when needed, and waits up to 30 s for desktop contention. It registers only when Hermes exposes its provider API. Removing it would discard behavior that raw MCP clients do not automatically inherit. [A5]
7. **A prompt profile cannot replace runtime hooks.** Current voice reads per-plugin state and transforms output; proactivity depends on gateway session binding, scheduling and `ctx.inject_message`. A shared instruction file can communicate voice and limits, but cannot itself watch inactivity, deliver messages or reproduce those transformations. [A1, A6]

The sibling remote-agent guide says the bridge is still being finished, while the pinned agents main already contains it. Treat the source code as evidence of implementation, and the guide's connection report as historical evidence; neither proves installed deployment or a successful Grok run. [A2, W1]

## Minimum common tool contract (proposal)

Keep the current tool names for compatibility. Use `browser.*`, `computer.*`, `lease.*` and `handoff.*` as conceptual groups first; aliases or renames are separate implementation decisions. MCP supports named tools, object schemas, text/image content and structured results, but does not mandate an agent's approval UI or a universal tool-count limit. [M2]

| Group | Minimum contract | Reuse / required gap |
| --- | --- | --- |
| Discovery/session | `initialize`, `tools/list`, `tools/call`; authenticated principal maps to a fixed bot ID. Report host, capabilities and supported approval path. Do not take authoritative identity/trust from model arguments. | Reuse router and `--bot-id`; a multi-bot HTTP listener needs credential-to-bot mapping. Current fixed-bot listeners are a smaller interim option. [A2, A7] |
| `browser.*` | status/tabs/open/snapshot/screenshot/action/close; target tab and current epoch; refs from current observation; bounded text; errors distinguish stale state, human hold and uncertain execution. | Existing tools largely cover this. Preserve names and failover semantics. [W2] |
| `computer.*` | apps/launch/snapshot/screenshot/menu/action; bind actions to observed host, PID, window and generation; return changed/removed state or fresh observation. Screen/image geometry must say how pixels map to input coordinates. | Existing shared tools supply these; do not require Hermes element numbering. [W2, A5] |
| `lease.*` | Expose current holder, acquisition result and `retryAfter`; exclusive input, human priority, bounded idle expiry. Release must not grant another bot permission or interrupt a still-running input. | Mac enforcement exists; explicit public status/release contract and other-OS parity need design and verification. [W4] |
| `handoff.*` | Distinguish human claim/release, host continuation, and agent-to-agent reassignment. Return source/destination identity and tab IDs, host, fresh epoch/generation, review status and verification result. Failed handoff must not imply success or replay uncertain input. | Reuse claim/release and checkpoint/restore. Explicit cross-agent reassignment and MCP handoff tools are missing; do not promise browser session/login migration from checkpoint restoration. [W2, W5] |
| Results/errors | Short text summary plus structured fields; retain text JSON for clients ignoring `structuredContent`. Screenshots use `content: [{type:"image", data, mimeType}, {type:"text", text}]`, ideally one bounded image per result. Include stable error code, execution status and recovery advice. | Existing image/geometry shape fits. Structured error normalization and per-client image consumption require checks. [W2, M2] |
| Approval | Treat client permission, desktop grant and consequential-action consent as separate checks. Use negotiated form elicitation where available; otherwise refuse commits until an app-side, authenticated, action-bound consent flow exists. Never accept an approval invented by the model or retry uncertain input blindly. | Stdio has browser gating. HTTP needs a real bidirectional request path or shared app approval workflow; a profile's `trusted_tools` never substitutes for either. [A2, A4, W3] |

Recommended budgets, **not vendor guarantees**: retain the 14-tool surface initially, use root object schemas and short names, return text/controls before pixels, and configure clients above existing action budgets. Hermes setup already chooses 120 s; native batches document a shared 45 s budget, up to 25 steps. A **180 s client timeout** is a practical starting point, but long human approval waits need their own tested budget; increasing a timeout cannot fix an absent approval channel. The HTTP bridge still imposes its 5 min cap. [A3, W2, A2]

## Per-bot profile boundary (proposal)

Use one operator-owned, non-secret profile document as input to small adapters; no new profile format was implemented by this research. Minimum fields: stable bot ID/display name, voice instructions, proactivity enabled/quiet hours/timezone/delivery target, and allowed/trusted tool names. Keep credentials in each client's secret mechanism.

Render **instructions** into Hermes `SOUL.md`/skill, Claude Code `CLAUDE.md` import/skill, Codex `AGENTS.md`/skill, Grok Bot memory/skill, and Duet skill/plugin when available. Apply **enforcement** to the authenticated server principal and client permissions, not only to prose. Set **proactivity** through a host runtime that can schedule and deliver: current Hermes plugin, Grok routines, or a separately verified integration. Do not infer unattended-turn capability from MCP connectivity. [H3, C3, C4, O5, G4, G5, D2, A6]

This preserves one policy source without pretending every client loads the same file automatically. A client that cannot apply a profile field must report it unsupported rather than silently dropping a quiet-hours or approval rule. Shared desktop visibility, shared browser sign-ins and Grok account-wide connectors also mean per-bot profiles are not data-isolation sandboxes. [W1, W2, G1, H3]

## Gaps and recommendation

**Go-with-changes:** keep Hermes working through its current plugin/provider, bring Claude Code and Codex in through the existing stdio-over-SSH path when feasible, and validate Grok Bot against authenticated HTTPS. Treat Duet as an experimental connector target until preview access establishes its exact behavior. Do not build five independent computer drivers or replace the Hermes scheduler as part of this migration.

Before claiming shared production support:

1. **Fix HTTP approval coverage.** Carry negotiated server-to-client requests or supply a shared action-bound app approval path; keep current fail-closed browser behavior until then. Generic client permission cards do not supply the router's form response. [A2, A4]
2. **Bind bot identity to credentials.** Start with one restricted SSH key or fixed-bot bridge endpoint per bot; a single multiplexed endpoint later needs authenticated principal-to-profile mapping. Model-selected bot IDs and shared tokens must not inherit trusted Hermes privileges. [A2, A7, W3]
3. **Adapt profiles without promising runtime parity.** Keep voice text portable, enforce tool access outside prompts, and explicitly map scheduling/delivery and output transforms per client. [A1, A6]
4. **Complete ownership semantics.** Expose/verify lease status and human handback, define agent reassignment separately from host failover, and verify Windows/Linux behavior before claiming the Mac lease applies everywhere. [W4, W5]
5. **Run a narrow conformance exercise per client/version.** Verify auth refusal and bot isolation; list tools; read a page; receive one real screenshot; perform one harmless native action with correct host/window/generation; decline and accept an approval; hit stale-state and `desktop_busy`; release to the human; simulate failover without repeating uncertain input. For Grok and Duet, record actual transport, headers, image consumption and elicitation. This exercise was **not run**.

Open questions for Alex:

- Is “one server” one maintained implementation, or a single shared endpoint with independently revocable bot credentials?
- Is Claude Duet preview access available to test this, and is it the intended product rather than Claude Code/Cowork?
- Must Grok Bot complete consequential browser actions, or is staging for human completion acceptable until HTTP approval works?
- Should proactive delivery remain Hermes-led, or should every agent receive its own native schedule and delivery target?

Skipped live clients, installed versions, deployment checks and runtime tests; this documentation-only change does not need application tests. Main risks: HTTP browser approval is currently unavailable, hosted-client limits are partly undocumented, and a profile alone cannot enforce trust or create proactive execution.

## Sources

### Pinned repository evidence

- [A1] [`alans-way-agents/alans-way/__init__.py:53–84,117–193`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/__init__.py#L53-L193): context hooks, skills, profile scope, commands and runtime registration.
- [A2] [`alans-way-agents/alans-way/scripts/remote-agent-bridge.cjs:1–31,61–64,74–118,133–197`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/remote-agent-bridge.cjs#L1-L197): JSON HTTP bridge, bearer auth, fixed router arguments, limits, missing reverse request channel and removed capabilities.
- [A3] [`alans-way-agents/setup-workspace.sh:187–189,311–325`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/setup-workspace.sh#L187-L325): managed Hermes MCP configuration and timeouts.
- [A4] [`alans-way-agents/alans-way/scripts/workspace-router.cjs:2472–2479,2733–2803`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L2472-L2803): form capability check, refused unavailable approval, bound request and no-replay policy.
- [A5] [`alans-way-agents/alans-way-computer/__init__.py:177–204,304–345,501–550,934–973`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way-computer/__init__.py#L177-L973): private router, host reset, lease wait, image/observation adapter and provider API guard.
- [A6] [`alans-way-agents/alans-way/voice.py:161–204`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/voice.py#L161-L204) and [`alans-way/proactivity.py:329–380,576–617`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/proactivity.py#L329-L617): state, voice transform, injected turns and scheduler lifecycle.
- [A7] [`alans-way-agents/alans-way/scripts/setup-remote-agent.sh:33–58,102–152`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/setup-remote-agent.sh#L33-L152): validated identity and restricted SSH setup.
- [A8] [`alans-way-agents/alans-way/scripts/workspace-router.cjs:338–347`](https://github.com/capthvnsen/alans-way-agents/blob/4da7c64bcf11fec0c10c1cddc569ec125a93a032/alans-way/scripts/workspace-router.cjs#L338-L347): desktop input opt-in.
- [W1] [`alans-way/desktop/docs/remote-agents.md:3–22,48–76`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/docs/remote-agents.md#L3-L76): topology, Oct 26 Grok SSH observation, app grants, shared sign-ins and recommended instructions.
- [W2] [`alans-way/desktop/scripts/browser-mcp.cjs:39–55,110–201,417–482`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/scripts/browser-mcp.cjs#L39-L482): identity, 14 tools, schema limits, generation/host binding, image content and claim/release.
- [W3] [`alans-way/desktop/src/desktop-approval.cjs:3–31`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/desktop-approval.cjs#L3-L31) and [`desktop/src/main.cjs:2995–3010,3088–3119`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/main.cjs#L2995-L3119): trust exceptions, prompt, grants and route enforcement.
- [W4] [`alans-way/desktop/src/computer.cjs:72–89`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/computer.cjs#L72-L89) and [`desktop/src/main.cjs:2995,3094–3119`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/main.cjs#L2995-L3119): Mac-only construction, lease holder/refcount, expiry and route use.
- [W5] [`alans-way/desktop/src/main.cjs:2617–2647`](https://github.com/capthvnsen/alans-way/blob/7e05d521c2a2f9add46423e39a4b27d6e67049e3/desktop/src/main.cjs#L2617-L2647): host handoff, checkpoint/restore and review-required destination.

### Official client and protocol documentation

- [H1] [Hermes MCP configuration reference](https://hermes-agent.nousresearch.com/docs/reference/mcp-config-reference): transport/auth/timeouts/trust/tool filtering and name normalization.
- [H2] [Hermes MCP guide](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp): image results and form elicitation.
- [H3] [Hermes profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles): profile identity, config, skills and isolation limitations.
- [G1] [Grok Bot computer and apps](https://docs.x.ai/grok-bot/computer-and-apps): URL/command custom MCP, account-wide app connections and shared computer.
- [G2] [Grok Bot changelog](https://x.ai/changelog/bot): Aug 12 v0.17.0 unresponsive connector timeout; historical, not a current SLA.
- [G3] [Grok Bot approvals, security and privacy](https://docs.x.ai/grok-bot/approvals-security-and-privacy): Auto Review and Custom Rules.
- [G4] [Grok Bot management](https://docs.x.ai/grok-bot/bots): chat/memory-based job instructions.
- [G5] [Grok Bot skills, routines and automations](https://docs.x.ai/grok-bot/skills-routines-and-automations): reusable instructions and scheduled/event work.
- [G6] [xAI Remote MCP API](https://docs.x.ai/developers/tools/remote-mcp): API-specific transport, headers, tool filtering and unsupported approval parameter.
- [C1] [Claude Code MCP reference](https://code.claude.com/docs/en/mcp): installation, output/time limits, image results and elicitation.
- [C2] [Build an MCP server for Claude](https://claude.com/docs/connectors/building): shared connector infrastructure, auth, transports, image support and hosted-client reference limits.
- [C3] [Claude Code memory/instruction files](https://code.claude.com/docs/en/memory): `CLAUDE.md` imports and conditional `AGENTS.md` support.
- [C4] [Claude Code settings](https://code.claude.com/docs/en/settings): instruction/configuration scopes and permission configuration.
- [O1] [OpenAI MCP documentation, CLI surface](https://learn.chatgpt.com/docs/extend/mcp?surface=cli): direct stdio/HTTP configuration, auth, timeouts and tool controls; reached from the official Codex documentation URL.
- [O2] [OpenAI configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference): granular MCP elicitation approval policy.
- [O3] [Codex app-server reference](https://learn.chatgpt.com/docs/app-server): MCP form/URL elicitation request and response contract; does not alone verify a CLI UI.
- [O4] [OpenAI image inputs](https://learn.chatgpt.com/docs/image-inputs): CLI image input, distinct from unverified MCP image result handling.
- [O5] [OpenAI AGENTS.md instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md): instruction discovery and scope.
- [D1] [Introducing Claude Duet](https://claude.com/resources/articles/claude-duet): Oct 21 launch/research preview.
- [D2] [Get started with Claude Duet](https://support.claude.com/en/articles/17631495-get-started-with-claude-duet): availability, inherited memory/skills/connectors/plugins and cloud computer.
- [M1] [MCP 2025-11-25 transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports): stdio, Streamable HTTP JSON/SSE responses, legacy SSE replacement.
- [M2] [MCP 2025-11-25 tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools): schemas, pagination, image/structured content and user interaction model. This is a deliberate compatibility baseline, not a claim that it is the newest protocol revision.
