---
name: workspace-operations
description: Use whenever a task needs a real browser — sites or web apps with no API, logged-in pages, forms, visual verification, or a link worth opening — plus VPS desktop control, Mac/VPS browser handoff, human takeover, or sharing a tab with another bot.
---

# Workspace operations

## Open a browser when the task needs one

Treat the workspace browser as your default surface for anything web-shaped.
If a task lives in a site or web app and no API or CLI covers it — or driving
the page is simply the most reliable path — open a tab and do the work there.
Do not ask whether you may use the browser or describe a plan first; open the
tab, work it, and report the result. There is no handoff, assignment, or grant
step for your own tabs — `cua_alans_way_open` IS the handoff, and it never
requires the human. The tab is scoped to your bot id and runs in the
background — it never moves the human's cursor or touches their tabs.

## Browser authorization policy

Ordinary actions in a bot-owned in-app browser tab are preauthorized and require
no extra browser permission prompt: navigation, typing, forms, upload/download,
research, and normal account work. Never ask merely to use the browser. Native
Hermes approval remains mandatory for sending external messages/posts,
purchases, bookings, deletions, financial actions, credential/permission
changes, destructive actions, and production changes. Ownership, control epoch,
and human takeover gates remain.

Reach for the browser when:

- the task lives in a web UI — dashboards, admin panels, account settings,
  booking or checkout flows, CMSs, internal tools — with no API to call
- driving the page beats synthesizing requests: the site enforces its own
  auth, validation, and side effects, so the UI path is the honest path
- you must see the result to trust it — read a page, confirm a change
  landed, or screenshot the final state
- a link or site comes up in chat — open it in your own tab and look

The in-app Mac browser is the only default host. When the Mac is reachable,
ALL web work goes through the `cua_alans_way_*` tools (Mac host) — never
`host:"vps"`, never another browser tool (browser_exec, computer-use
drivers), and never opening a URL in the human's personal browser via
terminal/`open`. `cua_alans_way_open` already falls back to the VPS host on
its own when the Mac is unreachable — an explicit `host:"vps"` is only for
work that must keep running after the Mac sleeps, or when the user names
the VPS as the host. If a workspace browser call fails, report the failure;
do not silently substitute another browser.

## Choose the execution host

Identify the user's intended host and task before acting. The existing VPS
Hermes gateway owns the Telegram conversation. Workspace displays that real
conversation; it supplies Mac/VPS browser tools and a viewer of the VPS desktop.

For a task in a Workspace Mac tab, call the tools by these exact names:
`cua_alans_way_status`, `cua_alans_way_tabs`, `cua_alans_way_open`,
`cua_alans_way_snapshot`, `cua_alans_way_screenshot`, `cua_alans_way_action`,
`cua_alans_way_close`. The Hermes config key is still `workspace_browser`;
that key is not a tool. Begin with status and your owned tabs. Confirm the
reported host and tab ownership. For a VPS browser task, use the same
`cua_alans_way_*` tools. Verify status reports
`host: vps`, then find a tab you own or open one. The Mac connector can
also route an explicit `host: vps` open, but the native VPS connector works
while the Mac app is offline. Desktop apps on that Linux machine use the same
`workspace_computer_apps`, `workspace_computer_snapshot`, and
`workspace_computer_action` tools: press a ref from the accessibility tree,
leave the focused window alone, and do not move the pointer. A connection failure means that
host is unavailable; report it or continue only work already authorized on
another host.

For a Linux window the snapshot cannot name, `workspace_computer_screenshot`
is one small jpeg of that window. Read [VPS desktop operations](references/vps-desktop.md)
for that boundary. Do not use an external computer-use driver.

## The connector layer self-heals — never operate on it

`cua_alans_way_*` tools are served by a routing connector that probes the
Mac at spawn and re-routes automatically when Mac availability flips. The
first call of a session pays a few seconds of warmup while the connector
probes the Mac and connects; later calls on that connection are fast, so a
slow first response is warmup, not a failure. If a browser tool call errors
or the tools seem missing, retry once: a dead connector is respawned fresh
and re-probes on its own. A connector whose script on disk is newer exits
after the current call so the next call loads it. That exit is normal. If it
still fails, report the failure in one line and stop.

Never repair the connector layer yourself: do not kill connector/router
processes, run `hermes mcp test` loops, read or edit router scripts, ssh to
the Mac to "check the probe", or restart the gateway from a session. That
surgery spams the user with approval prompts and fixes nothing the next
respawn would not. Host selection is the router's decision — there is no
`host:` value you can pass to steer it, and none is needed. A persistent
outage is a deployment problem; hand it to the user, not to your shell.

## Work around an offline Mac

Every `cua_alans_way_*` result carries the serving `host` and the Mac's
last seen state, and tool results add a `[workspace] ...` notice line while
the Mac is down or when it comes back online. When a task needs Mac-only
resources — local files, Mac logins, a tab handoff waiting on the Mac — and
`mac.state` is `offline`, do not improvise on the VPS: mark the kanban card
`blocked` with a "needs Mac" note, tell the user, and stop. The Mac
availability watcher turns the next offline→online flip into a context event
for the lead bot's review, which can unblock the card and resume the task.

## Shared links

When a link appears in your Telegram chat — sent by you or the user — the Mac
app opens it as a local browser tab assigned to your bot id, so you both see
the same page. Before opening a duplicate, list your tabs and reuse the one
with that URL. If no tab arrived — the Mac is unreachable or link sharing is
off — open it yourself with `cua_alans_way_open` (which falls back to the VPS
desktop). Links you send follow the same rule: the
app opens them for the user while the tab stays yours to keep working.

## Operate a browser tab

1. List your tabs and reuse a matching one, or open a task-specific tab in
   the background. Tabs you open belong to your bot ID — no human assignment
   or grant is involved; grants matter only for a tab another bot owns.
   Sign-ins are shared live within each host's browser profile. Tabs,
   control, and task ownership remain separate. Mac and VPS profiles have
   independent authentication.
2. Read a fresh snapshot, tightly bounded. `cua_alans_way_snapshot`
   accepts `maxChars`, `maxElements`, and `since` — keep the bounds small
   enough that the payload stays readable, and pass `since=` the previous
   snapshot's generation for a cheap `{unchanged:true}` re-check instead of
   a re-sent tree. A check box or radio name ends in on or off, a select name includes the chosen option, a disabled control's name ends in disabled, a section name ends in open or closed, a selected tab's name ends in selected, and the current link's name ends in current. Request a screenshot only when the DOM view cannot answer
   the question; `cua_alans_way_screenshot` accepts `format`
   (`jpeg`|`png`|`webp`), `quality`, and `maxWidth` — jpeg around 70 quality
   at 1280px is the fast default. Use the snapshot's refs and current
   control epoch for the next action, then inspect the result. A click, type, press, scroll, navigate, or batch result includes elements for up to 40 controls and no page text. Use those refs. When it says unchanged, the controls you already have are still valid, so do not snapshot again. The browser
   tools target that tab directly in the background and leave the real
   mouse alone. Completion requires observed page state, rather than the
   absence of a tool error.
3. Prefer `action=batch` for multi-step work — up to 25 actions in one call,
   run in order, stopping at the first error; each step reports its own result.
   Every round-trip is a separate tool call otherwise, so batching is the fast,
   cheap path. Put `wait` steps between actions that change the page
   (`{action:"wait", selector:".results", timeout:8000}` — `text`, `url`, and
   `visible:true` conditions also work) so later steps land on a ready page
   instead of racing it. Prefer `visible:true`: an element that exists but is
   collapsed or hidden will otherwise pass the wait and fail at input. Click
   failures name what covers the element; if a click still cannot land, drive
   that step with eval or a different selector rather than retrying. Use
   `action=eval` with `code` to run JS in the page: read DOM state, extract
   data, or complete a whole interaction in one call. `eval` awaits Promises,
   so `await new Promise(r => setTimeout(r, 500))` and polling loops work
   inside it; state you store on `window` (for example `window.__h = {}`)
   persists between eval calls on that tab. Keep the return value small;
   results cap near 48KB. Both take the same epoch. If a page renders
   collapsed or mobile-narrow, set its layout size first
   (`{action:"viewport", width:1440, height:900}`); clear with
   `{action:"viewport", clear:true}`. For anything the named actions cannot
   express, `{action:"cdp", method:"...", params:{...}}` sends a raw Chrome
   DevTools Protocol command scoped to the tab — for example
   `Accessibility.getFullAXTree` or `Network.enable` interception.
4. On `human_has_control`, do not wait, ask, or describe a handoff — call
   `cua_alans_way_action` with `action:"claim"` on that tab to take
   control yourself. You have priority in the in-app browser; claim needs no
   human involvement, returns a fresh epoch, and the human can always grab
   the tab back just by interacting. Claim is also how you reach a tab whose
   login or page state only exists there (e.g. a site logged in on a human
   tab). If claim is refused because another bot owns the tab, open a fresh
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

The app supplies local Mac tabs and a single VPS desktop viewer. Cross-host
handoff controls are not exposed in its UI. Use an installed Companion handoff
capability only when it advertises support. Backend checkpoints may contain a
task note, source/destination IDs, verification and draft counts. Read that
context, wait for authorized agent control, and verify the destination page
and login before continuing. `review_required` means the page needs human
review. Passwords, cookies, uploads and in-memory state stay on the source
host. Keep Chromium profiles with their running browser.

The viewer is one shared desktop. **Take control** enables the human's mouse
and keyboard; **Stop control** returns to Watch. These viewer controls do not
pause browser or desktop agents. Coordinate work in the same window with the
human. Mac **Take over / Give to agent** enforces local tab control separately.
For a VPS tab reporting `human_has_control`, claim it with
`action:"claim"` the same way rather than treating the viewer switch as
permission or waiting on a release.
Separate desktop streams and automatic Mac/VPS login propagation remain
additional work.

## Spend tokens on structure, not screenshots

This is the cheap path, and it is the same for every Hermes model. Do not
switch strategy because of which model you are.

Web work uses `cua_alans_way_*` only. One `cua_alans_way_snapshot`
returns text and element refs. Act with those refs, and batch up to 25 steps
in one call. A screenshot is only for a canvas, a chart, or a page the
snapshot says it could not read. Never screenshot a page you can already
read as text.

Desktop apps, on the Mac and on the Linux machine, use `workspace_computer_apps`,
then `workspace_computer_snapshot`, then `workspace_computer_action`. Press a
`ref` from that snapshot. `type` replaces the text of a ref and does not send
keystrokes. Pass `since=` the previous snapshot's generation
for a cheap `{unchanged:true}` when that desktop tree is the same. The action
result includes `generation`. When it says `unchanged`, do not snapshot again.
When it includes `elements`, that is the fresh tree. On a Mac,
use `click` or `drag` with the snapshot's x,y only when the control has no name. A drag on a slider sets its value from the end point. On the Linux desktop, press a ref, click its snapshot x,y, or drag a slider or scroll bar to the end point. `workspace_computer_screenshot` captures that one window as a small
jpeg, and only when the snapshot has no named control for what you need. On a
Mac, scale image pixels by `window.width / imageWidth`. Do not screenshot a
window you can already read as names and refs. A check box or radio name ends in on or off. A disabled control's name ends in disabled, so do not press it. These calls do not move the
human's cursor. Skip the focused window, Keychain, and password fields. Do not open
a browser tab to do a native app's job, and do not drive a native app to do
a website's job.

## Preserve vanilla Hermes

Keep integration in supported profile configuration, optional plugins, hooks
and skills. Use Hermes' native conversation, model, approval and delegation
interfaces. Discover currently available profiles before delegating; retire
roster entries with their profiles. New bots receive distinct connector IDs.
After a Hermes code update, use the installed CLI's gateway restart workflow,
wait for Telegram to connect, and verify a full model turn with a delivered
reply. For profile retirement, inventory live work, preserve a private full
snapshot, then use native lifecycle commands. Keep settings and recovery
archives outside the shared repository.
