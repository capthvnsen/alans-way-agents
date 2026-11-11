# Browser handoff: known gaps in the app

Reliability gaps in the handoff between Alan's Workspace on the user's computer and the
VM browser. These belong to the app repo
([capthvnsen/alans-way](https://github.com/capthvnsen/alans-way)), so they are listed here
rather than fixed from this repo. Pointers are to `origin/main` at `7672fdd` (2026-11-10).
Paths are under `desktop/`. Open PR #247 (one pending Move per source, no Move from a retired
source, persist before focus) is assumed and is not repeated here.

How it fits together: on lid close or an unreachable host, this repo's router asks the VM
browser host to rebuild the bot's tabs from the app's mirror (`POST /v1/restore`). On wake the
app asks the VM which tabs it continued (`GET /v1/mirror/continued`) and retires the local
copies, so only one copy runs.

| # | Gap | Failure | Where | Severity |
|---|---|---|---|---|
| 1 | Manual Move ignores the pending wake check | The VM resumed tab T during sleep. On wake the user presses Move to VM before the continued-tabs check succeeds: a second VM copy is opened and T is marked moved. The later check then skips T, so the resumed copy stays agent-controlled next to the new one. | `handoffTab` never reads `continuedCheckDue` (`src/main.cjs:2662-2711`). `resume` only sets the flag (`src/main.cjs:3386-3387`), and the status stays `connected`, so Move stays enabled. | med |
| 2 | Failed wake check still reports "connected" | `/v1/tabs` answers but `/v1/mirror/continued` fails (timeout, Tailscale flap). The status is set to `connected` anyway, and the Mac copy stays `controller: agent` while the VM copy also runs, until a retry succeeds (backoff up to 60s). Mirror pushes pause correctly. | `src/main.cjs:293-294` (status set after the failed retire), `src/main.cjs:337` | med-high |
| 3 | The lid-close mirror push can be skipped | `suspend` fires `pushVpsMirror()` without waiting. The pusher returns at once if a push is in flight, and `collect` returns null while the wake check is pending. Sleep may not wait for tab reads (up to 2s each, plus cookies), so the VM restores a mirror up to 10s old, or none, and recent drafts are lost. There is no `lock-screen` or `shutdown` handler. | `src/main.cjs:3385`, `src/main.cjs:337`, `src/vps-browser.cjs:101` | med |
| 4 | Auto-retire does not wait for the tab's action queue | `retireContinuedTabs` hands the tab to the human without awaiting `tab.queue`, which a manual Move does. A step already running on the Mac copy can finish after retirement while the VM copy runs. | `src/main.cjs:328` vs `src/main.cjs:2670` | low |
| 5 | Move back is lost after an app restart | Bot-owned tabs are not persisted, `tab.handoff` and `continuedNotice` live only in memory, and nothing reads the saved `prefs.handoffs` back. The VM tab view has no Move button of its own. After a restart, a task that moved to the VM cannot be brought back in one click. | `src/main.cjs:207`, `src/main.cjs:321-330`, `src/renderer.js:472-476` | med |
| 6 | Failed Move back leaves the VM source held by the human | VM to Mac: if the destination is still loading, the Mac tab is closed but the VM source is never given back to the agent. If the restore script throws, a half-made Mac tab is left with no record. Mac to VM: the `restore` call after the VM tab is created sits outside the try/catch (PR #247 lists this as a remaining limitation). | `src/main.cjs:2696-2701` | med |
| 7 | Move back never closes the retired copy | Move back always creates a new Mac tab, leaving a stale "Handed off" tab next to it. This may be intended. | `src/main.cjs:2698` | low |
| 8 | "Disconnected" never says why | Any refresh failure clears the error text unless it starts with "Invalid VPS browser", so the user cannot tell an SSH, Tailscale or broker failure apart. | `src/main.cjs:296` | low |

Not verified: the physical lid close, live VM SSH, and whether the router actually sends
actions to both copies in gaps 2 and 4. Gaps 5 and 8 come from reading the code, not from a
reproduction.

## Fixed in this repo

- A VPS session whose own host probe failed no longer tells the agent that the host is "back
  online" because a dead or lagging mac-watch still reads `online`. The agent is told it was
  routed to the VPS browser (`alans-way/scripts/workspace-router.cjs`, `makeAnnotator`).
