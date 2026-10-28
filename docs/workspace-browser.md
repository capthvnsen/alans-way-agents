# Workspace browser and safety reference

What the `alans-way` plugin and its `workspace_browser` router do, in detail. The [README](../README.md) has the overview.

## What it does and does not do

- **Two browser hosts, visible failover.** Bots get per-tab Chromium access
  on the user's computer (through the desktop app's connector) and on the VPS
  (the managed browser). When the user's computer is unreachable, *new*
  browser work routes to the VPS host automatically. If it drops mid-session,
  the router moves the session to the VPS and rebuilds the bot's tabs there
  from the app's mirror (cookies, scroll, drafts); without a mirror it opens
  only the last page, without cookies. The call that was in flight fails
  visibly and is never retried, and the router tells the agent which tabs
  moved. Continuing an in-flight action across the switch and a "Move to VM"
  button are not shipped. Watching the VPS desktop from
  inside the app additionally needs a VNC server and a noVNC viewer on the VPS
  (a macOS guest VM uses `tart --vnc-experimental` instead); see the app repo's
  [deployment guide](https://github.com/capthvnsen/alans-way/blob/main/docs/deployment.md).
- **Check-ins are one internal prompt.** When the bound chat goes quiet past
  its wait, the plugin injects one prompt and the bot decides what to do with
  it — or replies `[SILENT]` and nothing is sent. Consequential actions —
  sending external messages or posts, purchases, credential or permission
  changes, production changes, destructive operations — always ask first.
  Details in [docs/proactivity.md](proactivity.md).
- **Optional cross-bot proactivity.** Default off, enabled per bot. The primary
  reads bounded fresh exports from other enabled bots during check-ins and may
  dispatch one read-only or draft-only ask with fresh evidence. Results stay in
  the target's bound Telegram DM with primary attribution and existing approval
  gates. Durable permits and gateway-wide limits prevent replay and chains.
  Digests expire after 24 hours, queued asks after two; copied context can remain
  in Hermes/provider history. See [setup and privacy limits](proactivity.md#cross-bot-proactivity).
- **Web errands stop at your Approve tap.** The `web-errands` skill drives
  the research → stage → commit → verify → report loop for shopping, cart
  comparison, booking and travel, job applications, form and civic-portal
  filing, cancellations, refunds and document-driven claims — in your real
  browser session on your computer, or on the VPS browser while it's
  asleep. Every purchase, booking, send, submission and deletion waits for
  the commit gate's Approve prompt; a CAPTCHA, sign-in or card-entry wall
  hands the tab back to you with a reason instead of working past it, and
  after each commit the bot reads the confirmation, captures the reference
  number and sends a Telegram receipt.
- **Chat replies get a texting-style note.** In every profile the plugin is enabled
  in, the bot's Telegram replies use a short, warm texting voice. A minimal
  send-time polish only drops a leading "Certainly!"-style opener, and only
  from a message with no indented line, backtick or quotation mark. Fixed
  Hermes messages (approval cards, errors, progress) and cron reports are not
  changed. It layers on top of your SOUL.md and `agent.system_prompt` and never
  edits them. `/tone default` turns it off for that bot. Details in [docs/voice.md](voice.md).
- **Progress while working.** Multi-step Telegram tasks get short updates about
  what is happening and what comes next, including side effects and mistakes;
  mid-task messages can be folded into the running task with `steer`.
  Neither setup script writes `display.busy_input_mode` or
  `display.interim_assistant_messages`. Guided setup asks once when the
  profile's effective busy mode is `interrupt` and no remembered choice exists.
  Only an explicit answer lets the setup skill set busy mode through
  `hermes -p NAME config set`; the choice applies to all platforms in that
  profile and is read back afterwards. Keeping interrupt also records
  `skills.config.workspace-setup.busy_input_choice: keep-interrupt` in that
  profile's config through the CLI, after disclosure and the answer, so reruns
  do not ask again. Silence and non-interactive runs write nothing; already
  `steer` or `queue` profiles are skipped. Later user changes are preserved.
  Guided setup offers one consented “Make Telegram feel right” choice for typing, updates, quiet delivery, its own steer acknowledgment, reactions, profile-wide cron wrapping and a city-confirmed IANA timezone; existing preferences and silence are preserved, choices remembered, and each CLI write read back.
  To change an existing `interrupt` choice, run
  `hermes -p NAME config set display.busy_input_mode steer`; to enable interim
  texts, set `display.interim_assistant_messages true` the same way (and check
  `display.platforms.telegram.interim_assistant_messages` for an override).
  Restart the gateway through its supervisor to load the changes.
- **Connect your stuff from Telegram.** The [integrations skill](../alans-way/skills/integrations/SKILL.md)
  checks account access before promising a task, reuses Hermes' Google,
  Himalaya, Home Assistant, Honcho and X routes, and offers pinned rclone,
  Taskwarrior recipes. Social posting is not built in; the
  [Mastodon recipe](integrations/mastodon.md) is separate human-run
  documentation. Package installs on the VM require your agreement; account authorization stays private, with secure handback when
  phone-only auth cannot finish. Installing the plugin connects no accounts
  and starts no integration services.

## What each piece does

| Piece | Effect |
|---|---|
| `proactivity` tool + `/proactivity` + `hermes proactivity` CLI | bind the chat, tune the wait, level, timezone and pause — bound to one designated chat |
| Idle-nudge loop | a 60-second daemon started when Telegram connects; injects one internal prompt when a check-in is due |
| Turn hooks | `pre_llm_call`/`post_llm_call` note when the bound chat was last active and whether the bot is mid-turn |
| `workspace_browser` MCP | Call `cua_alans_way_status`, `cua_alans_way_tabs`, `cua_alans_way_open`, `cua_alans_way_snapshot`, `cua_alans_way_screenshot`, `cua_alans_way_action`, `cua_alans_way_close`. An action that buys, books, sends, posts, submits, deletes or changes an account carries a `commit` object: the router asks you to approve it in Telegram (MCP elicitation) and runs it only on Approve, refuses a commit-looking click without one, never retries it, and logs each decision to `commit-decisions.jsonl` next to the mac-watch state file. The name check reads ref names, `name` targets and selector text. Input it cannot judge by name (keys other than Tab, arrows, Escape or a plain character; clicks, drags and selects by position, on unnamed controls or by selectors that name no commit; `eval`; `cdp` calls other than reads, `Emulation.*` and `Page.navigate`/`reload`; accepting a page dialog) needs `commit` on a page that shows a commit control, and a snapshot first on a page whose controls the router has not seen in full, including after a reply that listed only what changed. On a page that embeds a frame from another site, a key aimed at no control or a click by position never counts as judged. A reload of a commit page, typing then pressing Enter in one batch, and following a link to, opening, navigating, or going back or forward to an address that reads like an action on any site (`/checkout/complete`, `?step=confirm`, `/orders/7/delete`, `/buy`) need `commit`; a ref the router has not seen on the current page is refused, and `Page.addScriptToEvaluateOnNewDocument` is never allowed. Awaiting-human, CAPTCHA and recording holds, the Take-back cooldown, and stale control epochs are refused with the browser's own reason before anyone is asked. With automatic takeover enabled, a bot acting on a tab the human holds on the user's computer can take it back after the grace period: act or claim. A commit still needs fresh user approval, which the app honors across that automatic takeover exactly once. Refused actions leave the human's focus, tab owner and control epoch untouched; with automatic takeover off, `human_has_control` means wait or ask the user to hand the tab back. A new control epoch drops what the router knew of the page. On Approve the router adds the app's single-use `approval` receipt (`{nonce, kind, summary, issuedAt, tabId, epoch}`, bound to the approved tab and epoch) to that one forwarded call; an `approval` the agent sends is dropped from every call and step, and an approval whose tab changed page or epoch while it waited is refused with `page_changed`. The name list lives in `alans-way/scripts/commit-patterns.json`, which the app's own dispatch check mirrors. Approvals need Hermes v0.21.6 or newer (it includes commit 239740a19e, first in date tag v2026.6.19); older Hermes cannot show them, so every commit is refused with `approval_unavailable`. Desktop apps on the Mac and the Linux machine are read with `workspace_computer_apps`, `workspace_computer_snapshot`, `workspace_computer_menu` and `workspace_computer_screenshot`, and driven by the approval-gated `computer_use` tool (the `alans-way-computer` provider). `workspace_computer_action` is excluded from the managed block unless setup ran with `--allow-desktop-actions`. The config key is not a tool name. |
| Router | probes the Mac's ssh alias for ~8s; unreachable → VPS browser host. Mac drops mid-session → the router fails over in-process within ~10s, restoring the agent's tabs and cookies on the VPS; the call that was in flight fails visibly and is never retried. Tool results carry the serving host and mac-watch state |
| mac-watch | optional watcher probes the user's computer every 10s (systemd unit in `deploy/`; setup.sh installs a LaunchAgent on a macOS guest) and publishes a JSON state file the router reads |
| Texting voice + `/tone` + `hermes tone` CLI | on Telegram turns, `pre_llm_call` adds the voice note and `transform_llm_output` polishes the final reply; every profile, on by default. Fixed Hermes messages (approvals, errors, progress) are not changed; see [docs/voice.md](voice.md) |

**Commit gate limit.** The commit gate protects against agent mistakes and against clicks steered by prompt injection or a malicious website. It does not stop a deliberately hostile agent that also has terminal or file tools: that agent runs as the same OS user as the router and the browser services, so it can reach them directly. Full isolation (a separate OS account plus router-signed approvals) remains planned.

## The workspace_browser tools

Each bot needs its own `--bot-id` — it owns that bot's tabs. The router passes
`--bot-name` through so the on-page agent cursor carries the bot's name and
color. Multi-bot setups: run `setup-workspace.sh` once per profile, each with
its own bot id (the script replaces only its own managed block).

Host path requirements: the Alan's Workspace app running on the user's
computer, SSH from this host to it (BatchMode/key auth — the probe uses
`StrictHostKeyChecking`), and the app's bundled `browser-mcp.cjs` (inside the
installed app, or the copy this repo pushes to the connector directory). On a
Windows host the probe runs through PowerShell (the default sshd shell the
connect script sets) and computer-use calls reach the desktop through the
app's local API — an SSH session cannot drive the interactive desktop.
VPS-only usage works with no host computer: the router detects the
missing/unreachable host and serves the local VPS browser host directly.

## Mac availability watcher

`workspace-router.cjs --watch` (`alans-way/scripts/mac-watch.sh` is a thin wrapper
around it) probes the Mac over ssh on an
interval (10s in the units setup installs) and keeps a JSON state file —
`{"state","since","lastSeenOnline","lastTransition"}` — that the router reads
instead of probing itself. The router adds
the serving host and Mac state to `workspace_browser` results. Transitions are logged
to `mac-events.log` beside the state file.

```sh
sudo cp deploy/mac-watch.service /etc/systemd/system/
sudo mkdir -p /etc/hermes-alans-way
echo 'HERMES_WORKSPACE_MAC_SSH=you@your-mac' | sudo tee /etc/hermes-alans-way/mac-watch.env
sudo systemctl enable --now mac-watch.service
```

Adjust `ExecStart` to the installed router path and `User=` to the account
whose ssh keys reach the Mac. Environment variables:
`HERMES_WORKSPACE_MAC_SSH` (required — the same ssh alias the router probes),
`HERMES_MAC_STATE_FILE` (default `/var/lib/hermes-alans-way/mac-state.json`;
the unit's `StateDirectory` creates the parent directory; on a Windows guest
`~/.local/share/hermes-alans-way/mac-state.json`).

Hermes's stock `browser_exec` (Browser Use) tool connects to its own
`browser.cdp_url` (default `http://127.0.0.1:9222`) — nothing shares it.
Run a dedicated Chromium there via `deploy/browser-exec-chromium.service`
reusing the same `vps-chromium-host.cjs` supervisor with
`deploy/browser-exec-config.json` under
`$HERMES_VPS_BROWSER_DATA/config.json`. It keeps its own
`--user-data-dir`. The workspace VPS browser's CDP port is not fixed at
9223: `setup.sh` honors `--cdp-port`/`ALANS_WAY_CDP_PORT` and picks the
first free port at or above 9223 when that port is already taken, and the
chosen port is the `cdpUrl` in that config.json. Never point browser_exec
at it.

## Safety model (short version)

- Human takeover wins always: control epochs invalidate queued agent actions.
- Per-tab ownership is cooperative policy between bots sharing the connector —
  not a crypto boundary. See the [security note](https://github.com/capthvnsen/alans-way/blob/main/desktop/docs/integration.md)
  for the trust model before exposing a connector beyond `127.0.0.1`.
- Check-ins inject one internal prompt into the bound conversation, only
  between 08:00 and 22:00 in the user's timezone, and a `[SILENT]` reply is
  never delivered. The schedule is in [proactivity.md](proactivity.md).
