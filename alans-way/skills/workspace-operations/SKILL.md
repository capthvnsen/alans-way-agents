---
name: workspace-operations
description: Use whenever a task needs a real browser: sites or web apps with no API, logged-in pages, forms, visual verification, or a link worth opening. Also use for installed versions of Hermes, the plugin, Alan's Tools or Alan's Workspace. Covers VPS desktop control, computer/VM browser handoff, human takeover, and sharing a tab with another bot.
---

# Workspace operations

## Report installed versions

When asked what versions are running, check all four pieces in this turn and
give one short line for each: Hermes, plugin, Alan's Tools (the VM browser),
and Alan's Workspace (the app on the user's computer). Say unavailable for
anything you cannot read; a planned pin is not an observed running version.

- Hermes: run `hermes --version` (include its commit if reported).
- Plugin: read the installed `alans-way/plugin.yaml` version and this profile's
  `plugins/.install-metadata.json` entry for `alans-way`. Report the recorded
  revision/catalog SHA as the release SHA, identifying a catalog pin as such.
  For a manual git install, use that installed checkout's `git rev-parse HEAD`;
  if neither has provenance, say the SHA is unavailable. A separate setup clone
  or the current remote tip does not prove what the installed plugin runs.
- Alan's Tools: identify the installed router actually launched by this profile
  (read only its command/args and the relevant environment field). Follow
  `workspace-router.cjs:104` exactly: its nonempty CLI `--vps-script` first,
  then its nonempty `HERMES_WORKSPACE_VPS_MCP`, then the first existing candidate
  in this order: the router's sibling `browser-mcp.cjs`,
  `/opt/hermes-alans-way/browser/desktop/scripts/browser-mcp.cjs`,
  `~/.local/share/hermes-alans-way/app/desktop/scripts/browser-mcp.cjs`.
  If no candidate exists, the router defaults to the `/opt` script above.
  An explicit path wins even if it is missing; report unavailable in that case,
  rather than choosing an inactive checkout. Resolve the selected script's symlinks
  and derive its checkout with
  `git -C <selected-script-directory> rev-parse --show-toplevel`. Run
  `git -C <toolbox-checkout> describe --tags --always --dirty` and
  `git -C <toolbox-checkout> rev-parse HEAD`. For a non-git copy read its
  `desktop/package.json` version and `desktop/build-info.json` only if you can
  establish that the metadata belongs to the selected script; otherwise report
  unavailable. Label missing SHA/tag unavailable. This identifies the toolbox scripts;
  it is separate from Hermes and the computer's app.
- Alan's Workspace: call `cua_alans_way_status` and report its `version` and
  `build` (commit/channel/dirty when supplied) only when the response identifies
  the user's computer. A response with `host: vps` is the VM browser, so the
  computer app version is unavailable from that response; it does not prove
  the computer is offline. Missing fields on an older app are unavailable,
  not the connector's MCP protocol version.
  The existing connector passes `/v1/status` through; no app API token, SSH
  request, install, update or restart is needed for this check.

## Open a browser when the task needs one

Treat the workspace browser as your default surface for anything web-shaped
that a plain lookup cannot answer (see "Search the web" below).
If a task lives in a site or web app and no API or CLI covers it, or driving
the page is simply the most reliable path, open a tab and do the work there.
Open the tab without an extra browser-permission prompt; work it and report
the result, with short progress texts for multi-step work as described below.
There is no handoff, assignment, or grant step for your own tabs: `cua_alans_way_open` IS the handoff, and it never
requires the human. The tab is scoped to your bot id and runs in the
background; it never moves the human's cursor or touches their tabs.

## Tab hygiene

When a task finishes, close the tabs you opened for it with
`cua_alans_way_close`, unless the user may want them: keep a result they need
to inspect, a draft, an unfinished task, or a sign-in/CAPTCHA handback;
say which tabs you kept and why. Keep the task's tab ids in working context,
never durable memory.

Before cleanup, read a fresh `cua_alans_way_tabs` reply. Its `requestingBotId`
is this connector's bot identity, including after `/new` or compaction;
a tab is yours only when its `botId` matches `requestingBotId`.
`allowedBots` is a grant, not ownership; an overseer can see other bots' tabs.
The host-wide tab count is not your tab list. Never close another bot's or
the user's tabs, even if you can access them. Close only a confirmed finished
tab whose `controller` is `agent`, with no pending handback or recording
hold, passing its explicit `tabId` and fresh `epoch` from that reply.
Do not claim a tab just to close it, and respect every refusal.

At the tab limit, close your own confirmed finished tabs first on the host
that is full, then retry opening once. Reacquire the live list after a reset;
do not infer that a tab is finished from its age or URL. If ownership or task
status is uncertain, leave the tab alone and report that you need the user
to free space. Establish eligibility before saying you are closing a tab,
and report it closed only after the close call succeeds.

## Browser authorization policy

Ordinary actions in a bot-owned in-app browser tab are preauthorized and require
no extra browser permission prompt: navigation, typing, forms, upload/download,
research, and normal account work. Never ask merely to use the browser.

Sending messages or posts, purchases, bookings, submissions, deletions, and
account or permission changes need the user's Approve tap, and the connector
enforces it. Pass `commit` on the `cua_alans_way_action` call that does it:
`{kind: purchase|booking|send|post|submit|delete|account_change, summary,
amount?, currency?, counterparty?}`, with the summary, total and merchant or
recipient read off the page. The user gets an approval prompt in chat,
and the action runs only on Approve. Put a whole checkout batch under one
`commit`. `declined`, `approval_timeout` and `approval_unavailable` mean it did
not run: do not retry it or reach the same result another way; tell the user,
and in a scheduled job (where Hermes declines on its own) leave everything
staged and ask them to finish. A click on a control or selector named like
Place order, Pay, Confirm, Reserve, Book now, Send, Reply, Post, Remove or
Delete without `commit` is refused with `commit_required`, whether targeted by
ref, by `name` or by selector, and so is following a link to, opening or
navigating to an address that reads like an action on any site
(`/checkout/complete`, `?step=confirm`, `/orders/7/delete`, `/buy`), going
back or forward after one, and a reload of a page that shows such a control.
Typing and then pressing Enter in the same batch needs `commit` too: press the
key as its own call so it is judged against the page. So is any input the connector cannot judge by name, on
a page that shows such a control, since it can set one off: any key other than
Tab, an arrow, Escape or a plain character; any click, drag or select by
position, on an unnamed control or by a selector that names no commit; and
any `eval` or `cdp` call that can act (`Input.*`, `Runtime.evaluate`, a DOM
edit), and accepting a page dialog. On a
page whose controls the connector has not seen in full (including after a
reply that listed only what changed) it is refused with `snapshot_required`,
so snapshot first; after a batch step that may change the page, send the rest
as a separate call. On a page that embeds a frame from another site (a
booking or payment widget), a key aimed at no control or a click by position
cannot be judged and a snapshot cannot help: act by ref or name, or pass
`commit`. `cdp Page.addScriptToEvaluateOnNewDocument` is never allowed. A ref
the connector has not seen on the current page is refused with
`snapshot_required` too. Awaiting-human, CAPTCHA and recording holds, the
Take-back cooldown, and stale control epochs are refused with the browser's
own reason (`awaiting_human`, `stale_control_epoch`, or the hold reason)
before anyone is asked. Ordinary human control can yield to
automatic takeover as described below; with automatic takeover off,
`human_has_control` means wait or ask the user to hand the tab back.
Never send `approval` yourself:
the connector drops it and adds its own only to the call the user approved.
The gate protects against agent mistakes and against clicks steered by
prompt injection or a malicious website. It does not stop a deliberately
hostile agent that also has terminal or file tools, because that agent runs as
the same OS user as the router and the browser services. Full isolation (a
separate OS account plus router-signed approvals) remains planned.
Never work around the gate with any tool: a refused commit goes to the user.
Ask the user before
any other financial, destructive or production change. Ownership and control
epoch gates remain. With automatic takeover enabled, a bot acting on a tab
the human holds on the user's computer can take it back after the grace
period: act or claim. Awaiting-human, CAPTCHA and recording holds and the
Take-back cooldown still keep the bot out. A commit still needs fresh user
approval; the app honors that accepted approval across the automatic
takeover exactly once. Refused actions leave the human's focus, tab owner
and control epoch untouched. With automatic takeover off, follow
`human_has_control`: wait or ask the user to hand the tab back.

Reach for the browser when:

- the task lives in a web UI (dashboards, admin panels, account settings,
  booking or checkout flows, CMSs, internal tools) with no API to call
- driving the page beats synthesizing requests: the site enforces its own
  auth, validation, and side effects, so the UI path is the honest path
- a link or site comes up in chat; open it in your own tab and look

## Search the web

Take the first of these that answers the question:

1. A plain lookup (a fact, a price, docs, news, an address): use Hermes' own
   `web_search`, then `web_extract` on the best URLs. Do not open a search
   engine page in a tab for this.
2. When you need the real page (maps, shopping, signed-in results, or a page
   you must click through), open a tab on the user's computer: omit `host`.
   Their real connection and session meet far fewer challenges.
3. Use a search engine in the VM browser only on an explicit VM request or a
   router-reported outage, and expect a CAPTCHA there. Follow the host policy
   below.

If `web_search` or `web_extract` is not in your tools, or it fails, go to 2.

## Choose the execution host

The existing VPS Hermes gateway owns the Telegram conversation. Workspace
displays that real conversation; it supplies Mac/VPS browser tools and a
viewer of the VPS desktop.

The in-app host browser is the only default host. The user's computer is
usually a Mac, so this skill says "Mac", but it can be a Windows or Linux PC
instead, and every rule below is identical either way. (Likewise "VPS" is
Hermes' own computer, which can be a Linux VPS or a macOS virtual machine.)
All web work goes through the `cua_alans_way_*` tools, never another browser
tool (browser_exec, computer-use drivers), and never opening a URL in the
human's personal browser via terminal/`open`. Never call the app's HTTP API
yourself (curl or a script with its `connection.json` token, locally or over
SSH): those tabs carry another bot id, and the tools refuse them afterwards.
If a workspace browser call fails, report the failure; do not silently
substitute another browser.

`cua_alans_way_open` takes an optional `host`. Omit it for normal work,
including errands that continue while the user is away: the router starts
on the user's computer when it is reachable and uses the VM's own Workspace
browser when it is not. Pass `host:"vm"` only when the user explicitly asks
for your own computer or the VM, or the router reports the user's computer
unreachable. Pass `host:"computer"` to force the user's computer; while it is
offline the call errors instead of silently landing on the VM.
Login, CAPTCHA, approval and uncertain-action errors are not outages and
never switch browsers. If the VM browser also fails, report the failure;
Hermes's native browser is not a third tier.

Hermes registers these MCP tools under the `workspace_browser` server, so
their exact names are `mcp__workspace_browser__cua_alans_way_status`,
`mcp__workspace_browser__cua_alans_way_tabs`,
`mcp__workspace_browser__cua_alans_way_open`,
`mcp__workspace_browser__cua_alans_way_snapshot`,
`mcp__workspace_browser__cua_alans_way_screenshot`,
`mcp__workspace_browser__cua_alans_way_action` and
`mcp__workspace_browser__cua_alans_way_close`. This skill and its references
write `cua_alans_way_*` and `workspace_computer_*` for short, without the
`mcp__workspace_browser__` prefix; a bare `cua_alans_way_snapshot` does not
exist. When they are not in your tool list, Hermes has deferred them: call
them through `tool_call` with the full name, with no `tool_search` first.
`workspace_browser` alone is not a tool.

Skip status and tabs unless a call fails or you are checking tabs for cleanup: every
`cua_alans_way_*` result already carries the serving `host`, so a working
call needs no confirmation round trip. A connection failure means that host
is unavailable; report it or continue only work already authorized on
another host. VPS status identifies the serving host, not whether the Mac
is reachable: an explicit VM request can use it while the Mac is online.
The same `cua_alans_way_*` tools are that machine's browser. Its desktop is
read with
`mcp__workspace_browser__workspace_computer_apps`,
`mcp__workspace_browser__workspace_computer_snapshot`,
`mcp__workspace_browser__workspace_computer_menu` and
`mcp__workspace_browser__workspace_computer_screenshot`, and acted on
with the `computer_use` tool. Approvals follow the user's Hermes settings;
honor that gate without adding a separate chat approval for each action.
Press a ref from the accessibility tree and do not move the human's cursor.

**Where to act.** A web page is `cua_alans_way_*` work, following the host
policy above. A native app is `computer_use` work; `workspace_computer_apps` says which
machine answers (`host`: `mac`, `windows` or `linux` is the user's computer,
`vps` is the VM desktop). When the user asks for a task in an app,
bringing that app forward is part of the task; use `focus_app` to launch a
named app if it is not running. On Mac, the target app may be read in front
and driven or raised when the user has been idle for at least 2 seconds.
For `in_front`, wait a few seconds and retry once, then tell the user briefly
if it still refuses. Do not ask for permission to use the front window.
If the app is on another Space or the screen is locked, the error or capture
note says so: ask the user instead of working around it. Other hosts keep
their own foreground restrictions.

For a Linux window the snapshot cannot name, `workspace_computer_screenshot`
is one small jpeg of that window. Read [VPS desktop operations](references/vps-desktop.md)
for that boundary. Do not use an external computer-use driver.

## The connector layer self-heals; never operate on it

`cua_alans_way_*` tools are served by a routing connector that probes the
Mac at spawn and re-routes automatically when Mac availability flips. A slow
first response can be warmup. If tools seem missing, check deferred discovery
with `tool_call` above. Retry a read-only call once after a tool error or
connector restart; if it still fails, report the failure in one line and stop.
For an uncertain action or control change, do not repeat it: use
`cua_alans_way_tabs` to inspect the controller and epoch, take a fresh snapshot,
and follow the error's recovery instructions before deciding how to continue.
Ordinary calls can continue only after a confirmed pre-dispatch missing tab;
approval-bearing calls need fresh review in the destination tab. A connector
whose script on disk is newer exits after the current call so the next call
loads it. That exit is normal and does not prove the previous action failed.

Never repair the connector layer yourself: do not kill connector/router
processes, run `hermes mcp test` loops, read or edit router scripts, ssh to
the Mac to "check the probe", or restart the gateway from a session. That
surgery spams the user with approval prompts and fixes nothing the next
respawn would not. Failover and restore are the router's decision; a
persistent outage is a deployment problem, so hand it to the user, not to
your shell.

## When the Mac goes away mid-task

Every `cua_alans_way_*` result carries the serving `host` and the Mac's
last seen state, and tool results add a `[workspace] ...` notice line while
the Mac is down or when it comes back online. When status confirms the Mac
is offline, continue the task on the VPS within the recovery conditions
below. The host change alone does not prove what happened to an earlier call.

Ordinary missing-tab continuation requires a confirmed pre-dispatch missing tab.
If the result reports a continued tab, use its returned id and take a fresh
snapshot before acting. If the continued page is still loading, read it again
before acting. If it reports only a URL, use `cua_alans_way_open` to open a new
page for inspection; that does not prove an earlier action failed. A login wall means
the VPS browser needs that site's login; tell the user rather than working past
it. Do not retry the Mac until status shows it online.

An approval-bearing call cannot continue under its old review on another tab.
Take a fresh snapshot of the intended destination and obtain fresh review of
the current target before a new action. For `review_required`, wait for human
review. For an uncertain action or control change, do not repeat it: read
`cua_alans_way_tabs` for the controller and epoch, take a fresh snapshot, and
follow the error's recovery instructions. Check any completed batch results.
If the available state cannot establish whether the earlier mutation completed,
report that uncertainty; a newly opened or restored page cannot settle it.

When the connector reports restored tabs, inspect the destination, login and
available drafts rather than assuming all source state transferred. If restore
is still running, list tabs again in a few seconds. No recovery timer or host
change authorizes replaying an in-flight action.

You do not have to wait for an error to learn a tab moved. After the move,
the first VPS result's `_meta.workspace.tabIdChanged` lists one
`[workspace] tab id changed: <old> -> <new>, reason: <handoff or host unreachable>`
line per tab. Swap any Mac tab id you saved (in a plan, a note, or a
sub-agent prompt) for its new id before you use it.

API, MCP, and connector calls that do not run on the Mac keep going. A
closed laptop does not stop them.

Stop with a "needs Mac" note only for something that exists only on that
Mac: a local file, or a Mac app that is not a website. When the Mac is back,
start the next web task in the in-app Mac browser. Finish the current VPS
task there even when the Mac returns.

## Shared links

When a link appears in your Telegram chat, the Mac app opens it as a local
browser tab assigned to your bot id, so you both see the same page. Before
opening a duplicate, list your tabs and reuse the one with that URL. If no
tab arrived, the Mac is unreachable or link sharing is off, so open it
yourself with `cua_alans_way_open` (which falls back to the VPS desktop).
Links you send follow the same rule: the app opens them for the user while
the tab stays yours to keep working.

## Operate a browser tab

1. Open a task-specific tab in the background with `cua_alans_way_open`, or
   reuse a matching tab you already own. Tabs you open belong to your bot ID;
   grants matter only for a tab another bot owns. Sign-ins are shared live
   within each host's browser profile; Mac and VPS profiles have independent
   authentication.
2. Use a successful action reply's `effect` as the current page state;
   `effect.text` is its visible text. When that reply supplies the state you
   need, skip an extra confirmation read. Recovery is an exception: after an
   uncertain result, stale state or a continued destination, take the fresh
   snapshot required by the recovery instructions before new input. Call
   `cua_alans_way_snapshot` only when you need element refs or page text
   that no reply gave you, and keep it tightly bounded with `maxChars`,
   `maxElements`, and `since`. A snapshot defaults to 2000
   characters of page text. Pass `maxChars` when you need more of the page,
   up to 20000. Do not screenshot only because the text was cut. Pass `since=` the previous
   snapshot's generation for a cheap `{unchanged:true}` re-check instead of
   a re-sent tree. A check box or radio name ends in on or off, a select name includes the chosen option, a disabled control's name ends in disabled, a section name ends in open or closed, a selected tab's name ends in selected, and the current link's name ends in current. A menu item, option, tree item, slider, or clickable div is listed by its name, so do not screenshot it to find it. A link href omits tracking parameters. A frame src omits tracking parameters too. A control inside an open shadow root is listed the same way; a closed root is not readable. A control inside a same-origin frame is listed by its name. A cross-origin frame is not readable. A control whose text lives in aria-labelledby uses that text as its name, so do not screenshot it to read the label. A pressed toggle's name ends in on or off, so do not screenshot it to see the state. Request a screenshot only when the DOM view cannot answer
   the question; `cua_alans_way_screenshot` accepts `format`
   (`jpeg`|`png`|`webp`), `quality`, and `maxWidth`; jpeg quality 50
   at 960px is the default. Use the snapshot's refs for the next action;
   after a successful current-tab reply, omit `tabId` and `epoch` from action and
   snapshot calls: they default to the tab you last used. An action or batch
   result also includes elements for up to 40 controls; use those refs. When
   a successful reply says unchanged, the controls you already have are still
   valid, so do not snapshot again. Recovery or a changed destination takes
   priority over this same-tab optimization.
3. Do ordinary multi-step work in short chunks, usually about two actions.
   `action=batch` can run up to 25 steps in order, stopping at the first error;
   that is a limit, not a target. End the chunk before any noticeable step
   (a send, a submit, or a page the user must act on). After each chunk,
   read the returned errors and side effects before continuing, report blockers
   and unexpected side effects promptly, and incorporate any new user guidance.
   The authorization policy above still requires a whole checkout batch under one `commit`; keep that
   approved batch together and give the progress text before it. Act, `wait` for the
   text or selector you expect (`{action:"wait", text:"Done", timeout:8000}`;
   `selector`, `url`, and `visible:true` conditions also work, and
   `gone:true` waits for the text or selector to disappear), then finish
   with `{action:"read"}` for the page text. The batch reply's `effect` is
   the state after the last step: it already shows the page after the
   action's own updates, so each chunk answers in one call, and you add
   `wait` or `read` steps only when you need something `effect` does not
   show. Continue into the next chunk until the task is done or blocked.
   To bring something into view, use the scroll action; scripts and reloads are refused on pages that show payment or donate buttons.
   Keep routine reads, actions and step transitions quiet. Before a noticeable step
   (email sent, form submitted, or page the user must act on), say what is
   about to happen; report side effects and mistakes right away, plainly.
   For multi-step work, send one short start line, then a one-line update only at
   a real milestone, a failed step you route around, or a noticeable wait; add
   nothing for one quick action. Interrupt for required user action, a blocker or mistake. Use
   no tool names, headings or step counters. When a new message arrives
   mid-task, acknowledge it in one line and fold it into the running task;
   do not restart. Finish with one short result message.
   Use Hermes's `clarify` buttons for real decisions the user owns; keep Other/free text possible and never use them for approvals.
   The CAPTCHA message below keeps its own handback rules. Put `wait` steps
   between actions that change the page so later steps land on a ready page
   instead of racing it. Prefer `visible:true`: an element that exists but is
   collapsed or hidden will otherwise pass the wait and fail at input. Use
   `action=eval` with `code` to run JS in the page to read DOM state or
   extract data. `eval` cannot commit: finish a purchase, booking, send,
   post, submit or delete with a click that carries `commit`, and read a
   page that shows such a control with snapshot or `read`. `eval` awaits Promises,
   so `await new Promise(r => setTimeout(r, 500))` and polling loops work
   inside it; state you store on `window` (for example `window.__h = {}`)
   persists between eval calls on that tab. Keep the return value small;
   results cap near 48KB. Both take the same epoch. If a page renders
   collapsed or mobile-narrow, set its layout size first
   (`{action:"viewport", width:1440, height:900}`); clear with
   `{action:"viewport", clear:true}`. For anything the named actions cannot
   express, `{action:"cdp", method:"...", params:{...}}` sends a raw Chrome
   DevTools Protocol command scoped to the tab, for example
   `Accessibility.getFullAXTree` or `Network.enable` interception.
   Besides `click` and `type`, a tab takes `double_click`, `right_click`,
   `drag` (from `ref`, `selector`, or `x,y` to `toRef`, `toSelector`, or
   `toX,toY`) and `select` (an option by value, label, option, text or choice). A batch's
   `results[]` carry no url, title, generation, or tab. An element omits an
   empty name and
   the default type. A failed navigation says "Navigation failed: ERR_X."
4. On `human_has_control`, the tab is the human's; ask the user before
   taking it. Say what you need from it and claim only after they agree:
   `cua_alans_way_action` with `action:"claim"` returns a fresh epoch,
   and the human can always grab the tab back just by interacting. They can
   also hand the tab over themselves with the app's Give-to-agent control.
   If claim is refused or the user wants the tab left alone, open a fresh
   owned tab instead. Use `action:"release"` to hand a tab back to the human
   when their review matters. On a stale
   epoch, inspect the current state before deciding on another action. Treat a
   timed-out submission as uncertain and check its effects before resubmitting.
5. To collaborate on another bot's tab, obtain the user's explicit grant through
   Workspace's tab access dialog. Keep normal work in your own tabs.

## When a site shows a CAPTCHA

You never solve a CAPTCHA. Do not click, type into, drag, or screenshot a
challenge widget to solve it, do not reach it with `eval` or `cdp`, and never
use a solver service. The user solves it; you wait. A challenge is never
something to approve either: do not ask the user to approve a click on one.

A snapshot or action reply on a page with a challenge carries
`challenge: {kind, blocking}`, where `kind` is `recaptcha`, `hcaptcha`,
`turnstile`, `cloudflare`, `google_sorry` or `arkose`.

- `blocking:false` is a widget inside a page that stays yours, such as a
  reCAPTCHA box in a form. Use the rest of the page. Input that would land on
  the widget is refused with `challenge_present`, and so is a click by
  position, a key or page script, which may land on it: aim at the page's
  other controls by ref or name. If you need the widget
  solved to go on, release the tab:
  `{action:"release", reason:"captcha", note:"Solve the CAPTCHA, then give the tab back."}`.
- `blocking:true` (a whole-page check such as Google's "unusual traffic"
  page or "Just a moment") is handed to the user by the app itself. The
  reply's `tab` then has `controller:"human"` and a `handback` with
  `state:"awaiting_human"`, `reason:"captcha"`, a `note` naming the site, and
  on a VM tab the `viewerUrl` to solve it in. Until it comes back, calls on
  that tab answer `awaiting_human`.

Once the tab is the user's:

1. Tell the user once, as one short text before your next tool call; Hermes
   delivers it to Telegram mid-turn. Name the site and what you were doing.
   For a tab on their computer, say it is waiting in Alan's Workspace. For a
   VM tab, include the handback's `viewerUrl`; without one, say it is in the
   VM viewer in Alan's Workspace, and ask them to say when they're through.
   Never paste a viewer link that has a password, token or key in it (a
   `password=`, `token=`, `key=` or similar query parameter, a `user:pass@`
   part, or anything after `#`): leave the link out and point them to the
   viewer in Alan's Workspace instead. For example: "Google wants a CAPTCHA
   before I can search. Can you tap through it in Alan's Workspace? I'll pick
   it back up."
2. Wait. Check `cua_alans_way_tabs` at most once every 30 seconds (a
   foreground `sleep 30` in the terminal between checks), for up to 30
   minutes. Do not snapshot, act on, or claim the tab meanwhile. The app
   hands the tab back on its own once the challenge clears. When the tab is
   back with you (`controller` is `agent` and its handback says
   `human_returned`), carry on without another message: the epoch moved on,
   and the tab list you just read gave you the fresh one. The VM tab is held too:
   ask the user to press Give back in Alan's Workspace when finished;
   the user saying they're done also ends the wait.
3. After 30 minutes, or if you cannot keep waiting in this turn, stop. Your
   message already said you will pick it back up. When the user says it's
   done, list your tabs. Keep the host, tab id and fresh epoch together from the same reply.
   If the tab is still theirs, try to claim it once.
   Continue if it succeeds; if the claim is refused with `awaiting_human`, ask them to press Give back
   in Alan's Workspace and wait for the return. Respect any other refusal.

**Back off.** When a reply's `challenge` (or the tab's `handback`) has
`backOff:true`, its `advice` says the site has challenged twice in 10 minutes:
stop using that site for this task. Do the same when the same site
challenges you twice within 10 minutes across tabs (when you cannot tell the
time, twice in this task counts). Do not wait on that tab or retry the site
in a fresh tab. Switch to another source: `web_search`, another site with
the same answer, or, when the challenges came on the VM, the user's computer
once it is online. Tell the user in one line that you moved on, so they can
ignore that CAPTCHA. This is a change of source, not a browser failure: say
in your reply which source you used. If no other source can answer, ask the
user how to go on.

## Sign-in handback

When sign-in or 2FA needs the user, including when the user only asks you to open a sign-in page,
open and inspect the tab, then call `cua_alans_way_action` with its tab id and current epoch,
`action:"release"`, `reason:"login"` (or `reason:"two_factor"`), and a short `note`
naming the site and what the user needs to do. Confirm the reply marks it
`awaiting_human` before saying it is ready; report a failed release plainly.
Opening the page alone does not complete the handback.
The existing hold shows a banner and notification in Alan's Workspace and keeps
bot input paused until Give back or the hold expires. Send one short chat message;
for a VM tab include the handback's `viewerUrl` when returned, otherwise direct
them to the VM viewer in Alan's Workspace. On `human_returned`, read current
tab state and a fresh epoch before resuming. Follow the [human-only steps](../web-errands/SKILL.md#the-walls-you-hand-back)
for other sensitive fields and the [CAPTCHA handback](#when-a-site-shows-a-captcha) for challenges.

## Hand a task between computers

Control handoff of a Mac tab keeps that same live tab, login and page state on
the Mac. The VPS agent can drive it through the private connector while the
Mac is available; the human can take over in Workspace.

A closed laptop is not this handoff. Continue that web task on the VPS
browser under the recovery conditions above. For `review_required`, wait for
human review of the destination. An approval-bearing call needs a fresh
snapshot and fresh review there; an uncertain earlier action or control change
is not a failed action to replay, so do not repeat it without establishing its
outcome and following its recovery instructions.

The person can move a Mac tab to the VM with the Move button in Alan's Workspace. That carries the page address and scroll position, and drafts when they choose; cookies come along only when the app reports a restore, and passwords, uploads and in-memory state stay behind. You have no move tool: open the page on the other computer instead, and check the destination page and login before continuing.
Keep Chromium profiles with their running browser.

The viewer is one shared desktop. **Take control** enables the human's mouse
and keyboard; **Stop control** returns to Watch. These viewer controls do not
pause browser or desktop agents. Mac **Take over / Give to agent** enforces
local tab control separately. For a VPS tab reporting `human_has_control`,
the same consent rule applies: ask the user before claiming it; the
viewer's control switch is not permission, and a release is not required
once the user agrees.

## Spend tokens on structure, not screenshots

This is the cheap path, and it is the same for every Hermes model. Do not
switch strategy because of which model you are.

Web work uses `cua_alans_way_*` only. Reuse a successful reply's current
`effect`; snapshot for element refs or page state it did not give you.
Recovery after an uncertain result, stale state or a changed destination
takes priority: acquire the fresh state required by the recovery instructions.
A screenshot is only for a canvas, a chart, or a page the snapshot says it could not read.
Never screenshot a page you can already read as text.

Desktop apps, on the Mac and on the Linux machine, are driven by the
`computer_use` tool. Hermes applies the user's configured approvals;
that approval gate is the only desktop-input path, so never look for a way
around it. `computer_use` `list_apps` names the running apps; `capture` with
`app` returns one app's numbered element list, with a small window
screenshot only when its named controls leave most of the window unexplained
(`mode="vision"` asks for one);
`click`, `double_click`, `right_click`, `drag`, `scroll`, `key`,
`set_value` and `focus_app` act on element numbers or coordinates. Each
successful action reply lists current changes or unchanged state, so use that
observation instead of capturing it again. Recovery from an uncertain action
or missing current state needs a fresh capture before deciding on more input;
on Linux (the VM desktop or a Linux computer), capture before acting by number again. `set_value` replaces a field's text; free typing with no target
element depends on the host's support; prefer a named field. A stale element
number comes back `stale_ref`, and a switch between the computer and the VM
comes back `host_changed`: `list_apps` and `capture` again. To look without
acting, `workspace_computer_apps`, `workspace_computer_snapshot`,
`workspace_computer_menu` and `workspace_computer_screenshot` read the
desktop directly. If `computer_use` is not loaded at all, this Hermes has no
approval-gated desktop path: report that and stop; do not improvise one.
These calls do not move the
human's cursor. Skip Keychain, password managers and password fields. Do not open
a browser tab to do a native app's job, and do not drive a native app to do
a website's job.

For any desktop app on the user's computer, use the `computer_use` tool
(and the read-only `workspace_computer_*` tools to look), and never run
screencapture, osascript or ssh scripts to drive the user's desktop.
If a call fails with a permission error, ask the user to turn on Accessibility and Screen Recording for the Alan's Workspace app (listed as alans-way-localapp) in System Settings, then retry.

## Promised follow-ups

When the user asks you to check in, remind them or report back later, or says yes when you offer to, create one `cronjob_manage` job right then: `action` create, a `schedule` such as `in 5m` or an exact time, a `prompt` that says what to ask or check and when to stop, `attach_to_session` true so their reply continues this chat, and no `deliver` so it comes back here. Confirm with the local time in one line. An offer they haven't answered is not a yes: save nothing. Never promise a later message without a saved job. If they answer a check-in with "not yet", offer exactly one more check-in at a named local clock time, such as "want me to check again at 10:15 PM?". Save nothing until they say yes; don't schedule repeats they didn't ask for. Remove the job when its reason goes away.

When the user wants a job, deploy or status watched inside this conversation,
suggest they send `/heartbeat every <interval> <what to check; stay silent unless something meaningful changed>`
and `/heartbeat clear` to stop. The user sends these commands; you cannot set or clear
the heartbeat yourself. Include `reply exactly [SILENT] when nothing meaningful changed`
in the suggested check. There is one heartbeat per conversation; setting another
replaces it. It fires only while the conversation is idle and the owning chat
process or gateway is running, costs a model turn per check, and needs the user's
clear command when finished. Keep cron for isolated browser watches using
[web-errands](../web-errands/SKILL.md#a-watch-is-a-cron-job).

## Preserve vanilla Hermes

Save lasting general facts and preferences to memory only when they
apply across sessions regardless of task, such as a general preference for concise replies.
How-to procedures, pitfalls and task-specific preferences belong in the relevant skill.
Project and task records, including decisions, application confirmations and status,
belong in the user's chosen place, such as a project file or tracker; ask if no place
has been chosen, and keep short-lived facts in session history.
Do not migrate or delete existing memory as part of this guidance.
Transient tab state, element refs and handback state
must never go into durable memory; reacquire live workspace state from the tools when needed.

Keep integration in supported profile configuration, optional plugins, hooks
and skills. Use Hermes' native conversation, model, approval and delegation
interfaces. Discover currently available profiles before delegating; retire
roster entries with their profiles, inventorying live work first. New bots
receive distinct connector IDs. After a Hermes code update, use the
installed CLI's gateway restart workflow (on a supervisord host,
`supervisorctl signal USR1 <program>` on the gateway's program and wait for
the new pid — `supervisorctl restart` can SIGKILL it mid-drain and corrupt
`state.db`), wait for Telegram to connect, and
verify a full model turn with a delivered reply. Keep settings and recovery
archives outside the shared repository.
