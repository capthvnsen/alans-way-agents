---
name: workspace-operations
description: Use whenever a task needs a real browser: sites or web apps with no API, logged-in pages, forms, visual verification, or a link worth opening. Also covers VPS desktop control, computer/VM browser handoff, human takeover, and sharing a tab with another bot.
---

# Workspace operations

## Open a browser when the task needs one

Treat the workspace browser as your default surface for anything web-shaped.
If a task lives in a site or web app and no API or CLI covers it, or driving
the page is simply the most reliable path, open a tab and do the work there.
Do not ask whether you may use the browser or describe a plan first; open the
tab, work it, and report the result. There is no handoff, assignment, or grant
step for your own tabs: `cua_alans_way_open` IS the handoff, and it never
requires the human. The tab is scoped to your bot id and runs in the
background; it never moves the human's cursor or touches their tabs.

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
ref, by `name` or by selector, and so is opening or navigating to a same-site
address that reads like an action (`/checkout/complete`, `?step=confirm`,
`/orders/7/delete`, `/buy`), going back or forward after one, and a reload of
a page that shows such a control. So is any input the connector cannot judge by name, on
a page that shows such a control, since it can set one off: any key other than
Tab, an arrow, Escape or a plain character; any click, drag or select by
position, on an unnamed control or by a selector that names no commit; and
any `eval` or `cdp` call that can act (`Input.*`, `Runtime.evaluate`, a DOM
edit), accepting a page dialog, and any `name` that is not a commit. On a
page whose controls the connector has not seen in full (including after a
reply that listed only what changed) it is refused with `snapshot_required`,
so snapshot first; after a batch step that may change the page, send the rest
as a separate call. On a page that embeds a frame from another site (a
booking or payment widget) a snapshot cannot help: act by ref or name, or pass
`commit`. `cdp Page.addScriptToEvaluateOnNewDocument` is never allowed. A ref the connector has not seen on the current page is
refused with `snapshot_required` too. Ask the user before
any other financial, destructive or production change. Ownership, control
epoch, and human takeover gates remain.

Reach for the browser when:

- the task lives in a web UI (dashboards, admin panels, account settings,
  booking or checkout flows, CMSs, internal tools) with no API to call
- driving the page beats synthesizing requests: the site enforces its own
  auth, validation, and side effects, so the UI path is the honest path
- a link or site comes up in chat; open it in your own tab and look

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

`cua_alans_way_open` takes an optional `host`. Omit it for the default: the
user's computer when it is reachable, the VM's own browser when it is not.
Pass `host:"vm"` to use the VM's own browser even while the user's computer
is online. Pass `host:"computer"` to force the user's computer; while it is
offline the call errors instead of silently landing on the VM.

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

Skip status and tabs unless a call fails: every
`cua_alans_way_*` result already carries the serving `host`, so a working
call needs no confirmation round trip. A connection failure means that host
is unavailable; report it or continue only work already authorized on
another host. When status shows the VPS, the Mac is unreachable: the same
`cua_alans_way_*` tools are that machine's browser. Its desktop is read with
`mcp__workspace_browser__workspace_computer_apps`,
`mcp__workspace_browser__workspace_computer_snapshot`,
`mcp__workspace_browser__workspace_computer_menu` and
`mcp__workspace_browser__workspace_computer_screenshot`, and acted on
with the `computer_use` tool, which asks the user for approval on each
action. Press a ref from the accessibility
tree, leave the focused window alone, and do not move the pointer.

**Where to act.** A web page is `cua_alans_way_*` work: the user's computer
by default, the VM with `host:"vm"` or while the computer is offline. A
native app is `computer_use` work; `workspace_computer_apps` says which
machine answers (`host`: `mac`, `windows` or `linux` is the user's computer,
`vps` is the VM desktop). If the app is in front, on another Space, or the
screen is locked, the error or capture note says so: ask the user instead of
working around it.

For a Linux window the snapshot cannot name, `workspace_computer_screenshot`
is one small jpeg of that window. Read [VPS desktop operations](references/vps-desktop.md)
for that boundary. Do not use an external computer-use driver.

## The connector layer self-heals; never operate on it

`cua_alans_way_*` tools are served by a routing connector that probes the
Mac at spawn and re-routes automatically when Mac availability flips. A slow
first response is warmup, not a failure. If a browser tool call errors
or the tools seem missing (and are not merely deferred; see `tool_call`
above), retry once: a dead connector is respawned fresh
and re-probes on its own. A connector whose script on disk is newer exits
after the current call so the next call loads it. That exit is normal. If it
still fails, report the failure in one line and stop.

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
the Mac is down or when it comes back online. If the laptop closes or a Mac
browser call fails because the Mac is offline, continue the task on the VPS.
Do not stop, and do not mark the card blocked, only because the Mac left.

Web work (Google Docs, Notion, a CRM, or any other site) continues in the
VPS browser. The connector opens the last page there when the Mac drops. If
the `[workspace]` line says the page was continued, keep working in that
tab. A snapshot, screenshot, or action aimed at the Mac tab is carried onto
that VPS tab. Use the tab id in the result. The continued page may still be
loading. Snapshot that tab before acting. If an action still fails, the
error names the VPS tab. Use that tab. If that error lists controls, use one
of those refs. Open the same URL with `cua_alans_way_open` and keep acting
when that line only names a URL. If the `[workspace]` line names a page,
open that URL. The connector is already on that machine. A login wall means
the VPS browser needs that site's login once; tell the user rather than
working past it. Do not retry the Mac until status shows it online.

The Mac can also drop in the middle of a call. The connector then moves the
session to the VPS within about ten seconds, and the `[workspace]` notice
says so. When it lists restored tabs, those tabs have the Mac tabs' cookies
(where the Mac had any), scroll, and drafts: keep working in them by the VPS
tab ids it names, and look at any it flags before acting. If it says the
restore is still running, list tabs again in a few seconds. An action that
was in flight when the Mac dropped is never retried for you and comes back
as an error. It may have happened, so snapshot the VPS tab and check before
repeating it.

You do not have to wait for an error to learn a tab moved. After the move,
every VPS result's `_meta.workspace.tabIdChanged` lists one
`[workspace] tab id changed: <old> -> <new>, reason: <handoff or host unreachable>`
line per tab. Swap any Mac tab id you saved (in a plan, a note, or a
sub-agent prompt) for its new id before you use it.

API, MCP, and connector calls that do not run on the Mac keep going. A
closed laptop does not stop them.

Stop with a "needs Mac" note only for something that exists only on that
Mac: a local file, or a Mac app that is not a website. When the Mac is back,
start the next web task in the in-app Mac browser. Finish the current VPS
step first.

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
2. Act straight from the replies. Every action reply carries `effect`, the
   page's new state: `effect.text` is its new visible text. Do not snapshot
   or re-read the page after acting, and do not ask for one more
   confirmation round trip; `effect` already is the observation. Call
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
   after a tab's first reply, omit `tabId` and `epoch` from action and
   snapshot calls: they default to the tab you last used. An action or batch
   result also includes elements for up to 40 controls; use those refs. When
   it says unchanged, the controls you already have are still valid, so do
   not snapshot again.
3. Do multi-step work as one batch: `action=batch` runs up to 25 steps in
   order in a single call, stopping at the first error. Act, `wait` for the
   text or selector you expect (`{action:"wait", text:"Done", timeout:8000}`;
   `selector`, `url`, and `visible:true` conditions also work, and
   `gone:true` waits for the text or selector to disappear), then finish
   with `{action:"read"}` for the page text. The batch reply's `effect` is
   the state after the last step: it already shows the page after the
   action's own updates, so the whole run answers in one call, and you add
   `wait` or `read` steps only when you need something `effect` does not
   show. For
   a multi-step browser run, write no chat text between tool calls and send
   one short message when it is done. Put `wait` steps
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

## Hand a task between computers

Control handoff of a Mac tab keeps that same live tab, login and page state on
the Mac. The VPS agent can drive it through the private connector while the
Mac is available; the human can take over in Workspace.

A closed laptop is not this handoff. Continue that web task on the VPS
browser as described above. Do not wait for a human review of the page.

The app supplies local Mac tabs and a single VPS desktop viewer; cross-host
handoff controls are not exposed in its UI. Use an installed Companion
handoff capability only when it advertises support; read its checkpoint
context, wait for authorized agent control, and verify the destination page
and login before continuing. `review_required` means the page needs human
review. Cookies for agent tabs carry over to the VM over Tailscale;
passwords, uploads and in-memory state stay on the source host. Keep
Chromium profiles with their running browser.

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

Web work uses `cua_alans_way_*` only. Action replies carry `effect`, so a
snapshot is for element refs a reply did not give you, and a screenshot is
only for a canvas, a chart, or a page the snapshot says it could not read.
Never screenshot a page you can already read as text.

Desktop apps, on the Mac and on the Linux machine, are driven by the
`computer_use` tool. Hermes asks the user for approval before each action;
that approval gate is the only desktop-input path, so never look for a way
around it. `computer_use` `list_apps` names the running apps; `capture` with
`app` returns one app's numbered element list, with a small window
screenshot only when its named controls leave most of the window unexplained
(`mode="vision"` asks for one);
`click`, `double_click`, `right_click`, `drag`, `scroll`, `key`,
`set_value` and `focus_app` act on element numbers or coordinates. Each
action's reply lists what changed, so do not capture again just to read
the result; on Linux (the VM desktop or a Linux computer), capture before acting by number again. `set_value` replaces a field's text; free typing with no target
element is not available because nothing takes focus. A stale element
number comes back `stale_ref`, and a switch between the computer and the VM
comes back `host_changed`: `list_apps` and `capture` again. To look without
acting, `workspace_computer_apps`, `workspace_computer_snapshot`,
`workspace_computer_menu` and `workspace_computer_screenshot` read the
desktop directly. If `computer_use` is not loaded at all, this Hermes has no
approval-gated desktop path: report that and stop; do not improvise one.
These calls do not move the
human's cursor. Skip the focused window, Keychain, and password fields. Do not open
a browser tab to do a native app's job, and do not drive a native app to do
a website's job.

For any desktop app on the user's computer, use the `computer_use` tool
(and the read-only `workspace_computer_*` tools to look), and never run
screencapture, osascript or ssh scripts to drive the user's desktop.
If a call fails with a permission error, ask the user to turn on Accessibility and Screen Recording for the Alan's Workspace app (listed as alans-way-localapp) in System Settings, then retry.

## Preserve vanilla Hermes

Save durable user facts, decisions and preferences to memory as they come up during work,
so nothing important lives only in chat history. Transient tab state, element refs and handback state
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
