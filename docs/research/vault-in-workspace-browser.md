# Hermes vault logins and 2FA in the workspace VPS browser (N6 spike, Oct 2026)

**Verdict: conditional GO, VPS only.** A login saved in the Hermes vault with its
authenticator key works on the workspace VPS browser, and the session carries over to
the bot's workspace tabs. It needs a small BrowserProvider plugin that scopes Hermes to its
own tabs. Pointing Hermes straight at the workspace Chromium hijacks a router-owned tab.

Three parts are **NO-GO until Hermes changes upstream**:
- saving a login from Telegram;
- typing an SMS or email code from Telegram;
- unlocking 1Password or Bitwarden from Telegram.

Hermes has no Telegram path for those masked prompts. Logins have to be saved on the VPS
beforehand (`hermes vault add`), and sites that send a code to the user's phone fall back to
the N2 handback.

How this was checked:
- **Hermes source:** the Hermes install on the VPS, v0.21.5 at `c53536929e` (upstream
  `0e219331`, 2026-10-05). Paths are relative to `~/.hermes/hermes-agent`.
- **Hermes docs:** <https://hermes-agent.nousresearch.com/docs>, fetched 2026-10-12.
  Claims taken from the docs are marked **[doc]**.
- **This repo:** `alans-way-agents` at `78a7ddd`.
- **The app:** `alans-way` at `origin/main` `4c77e86`, cited as *app* `path:line`.

## The run

`prototype/vault-workspace-browser/` holds a throwaway prototype (not for merging) and the
script that ran it. Everything ran on the VPS under a temp directory and a scratch
`HERMES_HOME`, so neither the live gateway nor its config was touched. The script sets up:
- a Chromium standing in for the workspace browser (the snap build, because the Playwright
  build on this VM cannot start a renderer);
- the **real** app VPS browser host (`desktop/scripts/vps-browser-host.cjs`) on top of that
  Chromium.

The script then calls Hermes' own tool functions directly, with no model and no gateway:
1. Have the host open a bot tab on `example.com`. This is the router-owned tab.
2. Save a login with an authenticator key in the scratch vault.
3. Sign in to <https://authenticationtest.com/totpChallenge/>. This is a public TOTP test
   site, and its account is published on the page. The steps are `browser_navigate`, type
   the identifier, `browser_vault_fill`, `browser_vault_enter_code`, and submit.
4. Have the host open a **new** bot tab on the site, then check its nav shows "Sign Out".
   The site shows "Sign In" when you are not signed in.
5. Check the router-owned tab.

No secret appears in the output: vault results carry only counts and origins.

**Naive mode** (`browser.cdp_url` set to the workspace Chromium). This is what a provider
that returns the workspace CDP URL as-is would do:
```
1. router-owned bot tab: {'tab': '438c…', 'url': 'https://example.com/'}
3a. browser_navigate: {'success': True, 'url': 'https://authenticationtest.com/totpChallenge/'}
    workspace Chromium pages now: [('DFD6F4A6', '…/totpChallenge/'), ('B314B33A', 'about:blank')]
3c. browser_vault_fill: {'success': True, 'filled_fields': 1, 'backend': 'local', 'kind': 'login', 'origin': 'https://authenticationtest.com', …}
3d. browser_vault_enter_code: {'success': True, 'filled_fields': 1, 'origin': 'https://authenticationtest.com', 'source': 'local', …}
4. new workspace bot tab on the site: {'signed_in': True, 'shows_sign_in': False}
5. router-owned tab afterwards: {'still_open': True, 'url': 'https://authenticationtest.com/loginSuccess/', 'host_view': '…/loginSuccess/'}
```
The vault works, but Hermes signed in **inside the router's own bot tab**. Before the run
that tab showed `example.com`. The host still lists it as that bot's agent tab.

**Scoped mode** (`browser.cloud_provider: alans-way-workspace`, the prototype provider):
```
1. router-owned bot tab: {'tab': '4d1a…', 'url': 'https://example.com/'}
3a. browser_navigate: {'success': True, 'url': 'https://authenticationtest.com/totpChallenge/'}
    workspace Chromium pages now: [('47F820D3', '…/totpChallenge/'), ('E3A6F715', 'https://example.com/'), ('EA3F9331', 'about:blank')]
3c. browser_vault_fill: {'success': True, 'filled_fields': 1, 'backend': 'local', 'kind': 'login', 'origin': 'https://authenticationtest.com', …}
3d. browser_vault_enter_code: {'success': True, 'filled_fields': 1, 'origin': 'https://authenticationtest.com', 'source': 'local', …}
4. new workspace bot tab on the site: {'signed_in': True, 'shows_sign_in': False}
5. router-owned tab afterwards: {'still_open': True, 'url': 'https://example.com/', 'host_view': 'https://example.com/'}
6. scoped view: {'pages_visible_to_hermes': ['https://authenticationtest.com/loginSuccess/'], 'attach_router_tab': {'code': -32000, 'message': 'target not owned by this scoped browser'}}
```
This was the full flow. The login was saved on the VPS, Hermes signed in to the TOTP site
with no prompt, and the bot continued in a fresh workspace tab that was already signed in.
The router's tab was not touched, and Hermes could neither see it nor attach to it.

What was **not** run live:
- the Telegram path, because there was no gateway in the test and the live gateway was not
  used;
- a card fill;
- a real deployment where the workspace Chromium runs as the non-root account on the Xvfb
  display. The live VPS has no workspace host running today; only a headless stand-in was
  used.

## (a) Can a BrowserProvider hand Hermes a per-session view of the VPS Chromium without colliding with router tabs?

**Yes, but only through a scoping layer. Returning the workspace CDP URL directly collides.**

- **What a provider returns.** A provider is lifecycle only. It must "create a remote browser
  session, hand back a CDP websocket URL" **[doc developer-guide/browser-provider-plugin]**.
  The contract is one `cdp_url` per session (`agent/browser_provider.py:7-19, 43-47`). Hermes
  passes a `…/devtools/browser/…` URL through untouched (`tools/browser_tool_cdp.py:24-25`).
- **How Hermes uses it.** Hermes hands that URL to `agent-browser --cdp` and starts a CDP
  supervisor on it (`tools/browser_tool_session.py:828-839`, `tools/browser_tool_cdp.py:111-123`).
  Both work browser-wide:
  - The supervisor attaches to "the FIRST page target" of whatever browser it gets
    (`tools/browser_supervisor.py:432-438`).
  - `focus_page` attaches to every page target whose origin matches, across the whole browser
    (`tools/browser_supervisor.py:284-307`).
  - `agent-browser` adopts an existing page. That is the hijack the naive run shows.
- **What the router's browser looks like.** The workspace Chromium has one profile and one
  default context. The host creates every tab with `Target.createTarget` and no
  `browserContextId` (*app* `desktop/scripts/vps-browser-host.cjs:222-223`;
  `desktop/docs/vps-browser.md:3-5`). Ownership is only an app-level `botId`. Chromium gives
  any local CDP client full reach over the host's tabs.
- **How the host treats a second client.** The host ignores a foreign page it didn't open
  and resumes it if it is paused (*app* `vps-browser-host.cjs:757-779`). So the host
  tolerates a second client, but nothing stops that client from driving the host's tabs.
  This repo already warns about this for `browser_exec` (`README.md:313-323`).
- **What the prototype does.** The provider
  (`prototype/vault-workspace-browser/alans-way-workspace/`) returns a loopback URL to an
  in-process CDP proxy (`scoped_cdp_proxy.py`) with a random path token. The proxy:
  - forwards `Target.createTarget`, still in the default context;
  - filters `Target.getTargets` and the target events down to targets this session created
    and their pop-ups;
  - refuses `attachToTarget`, `closeTarget` and `activateTarget` on any other target, and
    refuses messages on sessions it didn't hand out;
  - resumes and detaches foreign pages that auto-attach catches.

  That is enough for `agent-browser` and the supervisor to work unchanged (run above).
- **Precedence.** `browser.cdp_url` (and `BROWSER_CDP_URL`) beats every provider
  (`tools/browser_tool_session.py:331-337`). The docs don't say this. The VPS's own Hermes
  config sets `cdp_url` today, so it must be unset for the provider to take effect.

What the prototype leaves for a real build:
- Browser-level cookie and storage methods (`Storage.*`, `Network.getAllCookies` with no
  session) pass through. They should be refused.
- `close_session` stops the proxy but leaves the session's tabs open. They should be closed.
- Ownership lives in memory, so a gateway restart orphans the session's tabs.
- Hermes-made tabs sit outside the host. They are not in `/v1/tabs` and have no Take-control
  seal, tint or reaping.
- The host's URL barrier (pausing every request in Fetch) covers only the host's own agent
  tabs (*app* `vps-browser-host.cjs:181-186`). Hermes' tabs rely on Hermes' own private-URL
  guard (`browser.allow_private_urls: false`) instead.

## (b) Do origin-checked fill and auto TOTP work there, and how does the session reach the workspace tab?

**Both work (run above). The session reaches the workspace tab through the shared profile; no
cookie copy is needed.**

- **The fill path.** Vault fills run only over the supervisor's CDP socket. They fail closed
  with `supervisor_required` rather than fall back to argv (`tools/browser_vault_tool.py:119-145`).
  This is the "supervised browser session's direct CDP socket" in the docs
  **[doc user-guide/features/credential-vault]**. A provider session gets that supervisor
  automatically, as shown above.
- **The origin check.**
  - The bound origin is matched exactly and nothing is inferred from a parent domain
    (`tools/browser_vault_tool.py:452-479`).
  - It is checked again inside the page before the write: `origin_changed` means "Nothing was
    written" (`tools/browser_vault_tool.py:544-559`).
  - The fill only fills the password. The model types the identifier itself
    (`tools/browser_vault_tool.py:400-407`).
- **TOTP.** With an authenticator key stored on the item, the code is minted locally and
  nobody is asked (`tools/browser_vault_tool.py:363-372`; `agent/vault_backends/local.py:32-34`).
  It was filled into the site's `totpmfa` field in the run.
- **Handoff to the workspace tab.** The scoped proxy creates Hermes' tabs in the workspace
  Chromium's default context. They therefore share the cookie jar the host's tabs use
  ("Shared sign-ins within a host": *app* `desktop/scripts/browser-mcp.cjs:92`). Step 4 shows
  a new bot tab opened by the host was already signed in.
- **Untested variant.** The proxy could expose the bot's own claimed workspace tab, which
  the host's `/v1/tabs` lists with its `targetId`. The vault would then fill the same tab the
  bot is working in. That would also need the proxy to check the host's
  `controller`/`epoch` before every write, and it was not tried.

## (c) VPS only?

**Confirmed.**
- Host tabs are driven per tab through Electron's in-process debugger
  (*app* `desktop/src/main.cjs:1717-1720`), in the `persist:browser` partition (*app*
  `desktop/src/main.cjs:515`).
- The app never enables a remote-debugging port: `git grep -E
  'remote-debugging|appendSwitch|commandLine' origin/main -- desktop/src` finds nothing. The
  README describes it as "driven per-tab through Chromium's debugger by a loopback-only
  connector" (*app* `README.md:73`).
- So there is no CDP websocket for Hermes or a provider to reach.
- Cookies only flow Mac → VPS, through the failover mirror (*app*
  `vps-browser-host.cjs:645-651`). Nothing copies a VPS login back to the Mac.
- Running host work on the VPS is ruled out anyway (*app* `docs/continuity.md:12`).
- Mac logins stay manual.

## (d) Does the vault confirmation reach Telegram?

**Card fill: yes, by source; not run live. Save-login, codes and unlock: no.**

- **Card fill.** It asks through `request_elicitation_consent(surface="vault-payment")`
  (`tools/browser_vault_tool.py:572-582`). In a gateway session that becomes a gateway
  approval and fails closed (`tools/approval_prompt.py:288-331`). On Telegram it is the
  inline-keyboard approval prompt (`plugins/platforms/telegram/adapter.py:4233-4235`). Any of
  once, session or always counts as accept (`tools/approval_prompt.py:281-285`). Cron and the
  API server are refused **[doc user-guide/features/credential-vault]**.
- **Login fill.** It asks nobody, by design.
- **Save-login, code and unlock prompts.** These need a per-surface callback
  (`agent/vault_backends/unlock.py:9-13, 162-167`). Only the CLI and the TUI/Desktop bridge
  install one (`tui_gateway/agent_callbacks.py:256-273`; `cli.py`). No gateway or platform
  module does (grep over `gateway/` and `plugins/platforms/`: 0 hits). So on Telegram:
  - `browser_vault_save_login` returns `prompt_unavailable` (`tools/browser_vault_tool.py:304-308`);
  - `browser_vault_enter_code` without a stored key returns `prompt_unavailable`
    (`:373-378`);
  - a locked manager reports `unavailable_in_this_session` (`:229-233, 272-276`).

  The docs only show these prompts for CLI/TUI and Desktop
  **[doc user-guide/features/credential-vault]**.
- **The toolset is off on Telegram today.** All five vault tools are registered in the
  `browser` toolset (`tools/browser_vault_tool.py:727-770`). Setup disables that toolset for
  Telegram and cron (`setup.sh:2595-2607`; `README.md:121-124`). The skill also forbids any
  browser tool other than `cua_alans_way_*` (`alans-way/skills/workspace-operations/SKILL.md:47-53`).

## What shipping it would take (alans-way side)

1. Harden the provider and proxy: refuse browser-level cookie and storage methods, close
   owned tabs on `close_session`, and persist ownership. Ship it as a plugin installed by
   `setup.sh` for VPS hosts. The provider is a documented public plugin API, so this is
   allowed under *app* `docs/continuity.md:14`.
2. Have setup unset `browser.cdp_url`, set `browser.cloud_provider: alans-way-workspace`, and
   enable the `browser` toolset on Telegram again when vault mode is chosen.
3. Change the skill:
   - Hermes `browser_*` and `browser_vault_*` are for signing in only; then continue with
     `cua_alans_way_*`.
   - This replaces "tell the user" at a login wall (`SKILL.md:128-131`).
   - With no saved login, or a site that sends a code, tell the user to run `hermes vault add`
     on the VPS, or `release` with a reason (N2).
4. Fix the README's `browser_exec` warning: it is true for a raw URL, and the scoped provider
   is the supported exception.

## Upstream Hermes requirements (for the NO-GO parts, and to drop the proxy)

1. **Vault prompts on messaging gateways.** Telegram and other gateways need masked prompts
   for save-login, one-time codes and manager unlock. One way is a short-lived, single-use
   form link or a Telegram WebApp, so the value never enters the chat transcript. Until then,
   these flows are unsupported on Telegram, as *app* `docs/continuity.md:13` requires.
2. **Session scoping in the BrowserProvider contract.** Let `create_session` return a
   `browser_context_id` or an owned-target set. `agent-browser` and the supervisor would
   honor it, instead of taking "the FIRST page target" and scanning all pages
   (`tools/browser_supervisor.py:432-438, 284-307`). Or document that a provider's `cdp_url`
   must be a browser nobody else drives.
3. **Vault as its own toolset.** A platform could then enable `browser_vault_*` without the
   whole `browser_*` surface.
4. **Vault fill into an external target.** Add a public plugin or MCP-facing API that fills
   a vault item into a CDP target the caller names, with the same origin checks and
   redaction. MCP-driven browsers like the workspace tab could then use the vault directly
   in the tab the bot is already in.
5. **Docs.** State that `browser.cdp_url` beats `browser.cloud_provider`
   (`tools/browser_tool_session.py:331-337`).

## Sources

<https://hermes-agent.nousresearch.com/docs/user-guide/features/credential-vault> ·
<https://hermes-agent.nousresearch.com/docs/developer-guide/browser-provider-plugin> ·
<https://hermes-agent.nousresearch.com/docs/developer-guide/browser-supervisor> ·
<https://hermes-agent.nousresearch.com/docs/user-guide/features/browser> ·
<https://hermes-agent.nousresearch.com/docs/user-guide/security> ·
<https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram>
