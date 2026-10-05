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
tab, work it, and report the result. The tab is scoped to your bot id and runs
in the background — it never moves the human's cursor or touches their tabs.

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

Prefer the local Mac browser (`workspace_browser`) as the default host: it is
the in-app browser the user can watch, and it shares the local login state.
Use `host:"vps"` (or `workspace_vps_browser`) when the work must keep running
while the Mac sleeps or when the VPS is the named host.

## Choose the execution host

Identify the user's intended host and task before acting. The existing VPS
Hermes gateway owns the Telegram conversation. Workspace displays that real
conversation; it supplies Mac/VPS browser tools and a viewer of the VPS desktop.

For a task in a Workspace Mac tab, use the `workspace_browser` MCP tools. Begin
with status and assigned tabs. Confirm the reported host and tab ownership.
For a VPS browser task, use `workspace_vps_browser`. Verify status reports
`host: vps`, then find your assigned tab or open one. The Mac connector can
also route an explicit `host: vps` open, but the native VPS connector works
while the Mac app is offline. Use configured VPS computer tools for desktop
applications outside the managed browser. A connection failure means that
host is unavailable; report it or continue only work already authorized on
another host.

For VPS window input, incomplete accessibility trees, or screenshots returned
as `MEDIA:` paths, read [VPS desktop operations](references/vps-desktop.md).

## Work around an offline Mac

Every `workspace_browser` result carries the serving `host` and the Mac's
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
off — open it yourself with `workspace_browser` (which falls back to the VPS
desktop) or `workspace_vps_browser`. Links you send follow the same rule: the
app opens them for the user while the tab stays yours to keep working.

## Operate a browser tab

1. Find the assigned tab, or open a task-specific tab in the background. Tabs
   exposed to your connector belong to your configured bot ID or an explicit
   grant. Sign-ins are shared live within each host's browser profile. Tabs,
   control, and task ownership remain separate. Mac and VPS profiles have
   independent authentication.
2. Read a fresh snapshot or screenshot. Use its refs and current control epoch
   for the next action, then inspect the result. The browser tools target that
   tab directly in the background and leave the real mouse alone. Completion requires observed
   page state, rather than the absence of a tool error.
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
4. On `human_has_control`, wait for the user to give control back. On a stale
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
For a VPS tab reporting `human_has_control`, wait for an authorized broker
controller to release it rather than treating the viewer switch as permission.
Separate desktop streams and automatic Mac/VPS login propagation remain
additional work.

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
