# Telegram live progress and busy steering

Research on 2026-10-13 from fresh scratch clones, without inspecting or changing a live Hermes home, gateway, bot, or credentials. Hermes HEAD was `d97007c32d6340f7ba79ac1dfb5773cc00846448` (263 commits ahead of the brief's Orgo build `6e7b83a2f1c093e992a8d838ed77ea320fbd8e51`, zero behind, verified with GitHub's compare API). DirectSDK is pinned to `31b591fd04737a7807183f3d7f3d389b19f94687`. Existing aa behavior below is cited at baseline `901a42f21762ced1a31b91bde9f5e6ac35e2cf9b`; no live install was updated to these source revisions.

## Findings that determine the implementation

**DirectSDK passes interim assistant text through: YES.** Native `text_delta` becomes OpenAI-compatible `delta.content`; completed text blocks become `assistant.content` alongside converted `tool_calls`. The provider retains both rather than discarding text when a tool is requested. This establishes transport support, not that the model will produce an update at the requested cadence. [DirectSDK `directsdk.py:699-708,734-759,783-787`](https://github.com/NousResearch/hermes-plugin-claude-subscription-directsdk/blob/31b591fd04737a7807183f3d7f3d389b19f94687/directsdk.py#L699)

**Busy mode is per profile, not per platform.** The supported key is `display.busy_input_mode`; setting `display.platforms.telegram.busy_input_mode` does not configure it. The loader reads the profile's top-level display mapping and snapshots independently routed profile policies. Interim commentary does support `display.platforms.telegram.interim_assistant_messages`; precedence is platform override, global `display` value, platform default, global default. Telegram's current built-in default keeps interim messages on and tool progress off. [Hermes `gateway/run_config_loaders.py:256-267,323-359`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_config_loaders.py#L256), [Hermes `gateway/display_config.py:16-54,98-128`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/display_config.py#L98)

Hermes's effective defaults are `busy_input_mode: interrupt` and
`interim_assistant_messages: true`. `config get` includes those defaults even
when no key is stored, so guided setup asks an effective interrupt-mode user
for an explicit choice. Interim messages need no setup write; the skill only
reports an effective `false` choice and preserves it and platform overrides.
Neither setup script writes either display key.
[Hermes `hermes_cli/config_defaults.py:830,919`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/hermes_cli/config_defaults.py#L919)

## Busy input semantics and acknowledgments

- `queue`: finish the active task, then process follow-ups as new turns in arrival order. Successful steering bypasses this pending-turn queue. [Hermes messaging docs `index.md:437-454`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/website/docs/user-guide/messaging/index.md#L437), [Hermes `gateway/run_busy.py:858-880`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_busy.py#L858)
- `steer`: enqueue guidance inside the existing agent without setting its interrupt flag. Hermes consumes it after the current **tool batch**, before another model request, as a durable standalone user row carrying the out-of-band marker. Multiple steers concatenate with newlines. At the provider boundary, DirectSDK merges adjacent native user blocks, preserving the completed tool result and steer text in that native user frame. [Hermes `agent/interrupt_control.py:267-278`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/agent/interrupt_control.py#L267), [Hermes `agent/agent_runtime_helpers.py:3758-3795`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/agent/agent_runtime_helpers.py#L3758), [DirectSDK `directsdk.py:156-172`](https://github.com/NousResearch/hermes-plugin-claude-subscription-directsdk/blob/31b591fd04737a7807183f3d7f3d389b19f94687/directsdk.py#L156)
- `interrupt`: on supported active-turn agents, redirect cancels an in-flight model request and retries with the correction while retaining completed history; during tool execution redirect degrades to steering (foreground terminal tools can yield). The gateway falls back to interruption if no redirect succeeds. Active subagents and in-flight compression demote interrupt to queue. These are current HEAD semantics, not a claim that every deployed older Hermes uses the same redirect path. [Hermes `agent/interrupt_control.py:280-327`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/agent/interrupt_control.py#L280), [Hermes `gateway/run_busy.py:583-634,876-880`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_busy.py#L583)

The general busy route's English acknowledgment is “⏩ Steered into current run” followed by “Your message arrives after the next tool call.” It is debounced for 30 seconds, can be suppressed by `busy_steer_ack_enabled`, and does not itself prove model consumption. Telegram's priority fast route returns no separate acknowledgment after `_hm_busy_steer`; model acknowledgment is consequently useful. [Hermes `locales/en.yaml:723-724`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/locales/en.yaml#L723), [Hermes `gateway/run_busy.py:707-723,888-904`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_busy.py#L707), [Hermes `gateway/run_inbound.py:652-666,729-731`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_inbound.py#L652)

Caveats:

- Telegram text arriving during the default three-second post-start grace window queues/merges even with steer configured; wait beyond that window when checking the feature. Agent-startup races also use a pending follow-up. [Hermes `gateway/run_inbound.py:625-646,703-714`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_inbound.py#L625)
- The general route falls back to queue when there is no started steer-capable agent or an unsupported payload. Plain text and entirely transcribed voice attachments are supported there; the priority path checks text-only input. [Hermes `gateway/run_busy.py:602-623`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_busy.py#L602), [Hermes `gateway/run_inbound.py:648-666`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_inbound.py#L648)
- A steer cannot alter a tool call already in flight. Hermes's MCP waiter cancels only for an interrupt flag or timeout; steer sets neither. It waits for that call/batch to return before the model reads the correction. A browser batch of 25 actions is one tool call: there is no model-generated commentary inside it. [Hermes `tools/mcp_tool_loop.py:148-178`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/tools/mcp_tool_loop.py#L148), [Hermes `agent/interrupt_control.py:267-278`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/agent/interrupt_control.py#L267), [aa baseline `workspace-operations/SKILL.md:271-278`](https://github.com/capthvnsen/alans-way-agents/blob/901a42f21762ced1a31b91bde9f5e6ac35e2cf9b/alans-way/skills/workspace-operations/SKILL.md#L271)
- DirectSDK's internal CLI does **not** run real browser/MCP work: it has no native built-ins, one native turn, and inventory-only MCP whose `tools/call` always denies execution. Hermes owns actual tool execution, so steering reaches the **next Hermes/DirectSDK model invocation**, not an already-open native request. [DirectSDK `directsdk.py:595-596,629,734-746`](https://github.com/NousResearch/hermes-plugin-claude-subscription-directsdk/blob/31b591fd04737a7807183f3d7f3d389b19f94687/directsdk.py#L629), [DirectSDK `inert_mcp.py:13-18`](https://github.com/NousResearch/hermes-plugin-claude-subscription-directsdk/blob/31b591fd04737a7807183f3d7f3d389b19f94687/inert_mcp.py#L13)

## Interim commentary, progress and hooks

Hermes emits an assistant row's commentary before executing its tool calls, after the row is persisted. The delivery mixin extracts assistant text, deduplicates it, invokes the interim callback, and notifies `on_interim_message` observers. The gateway builds a commentary consumer even when final-answer token streaming is disabled; completed commentary is delivered through `adapter.send` as a separate interim message. Thus top-level `streaming.enabled: false` does not disable interim commentary. [Hermes `agent/turn_tool_round.py:155-166`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/agent/turn_tool_round.py#L155), [Hermes `agent/stream_delivery.py:176-216`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/agent/stream_delivery.py#L176), [Hermes `gateway/run_turn_runner.py:930-994`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_turn_runner.py#L930), [Hermes `gateway/stream_consumer_fallback.py:345-373`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/stream_consumer_fallback.py#L345)

`tool_progress` describes execution mechanics: `off` suppresses chat breadcrumbs; `new` reports a tool-name change; `all` reports every eligible tool start; `verbose` exposes argument JSON/full terminal blocks; `log` writes an audit log without chat progress. Grouping is `accumulate` (edit one bubble) or `separate`. Some built-in labels use a friendly verb plus argument preview, but this rail cannot explain the model's next decision, side effects, or mistake. It is not the source of the requested updates. [Hermes `gateway/run_turn_runner.py:158-180,270-301`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_turn_runner.py#L158), [Hermes `gateway/run_turn.py:3003-3010`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/gateway/run_turn.py#L3003), [Hermes messaging docs `index.md:469-486`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/website/docs/user-guide/messaging/index.md#L469)

Available plugin hooks include `pre_tool_call`, `post_tool_call`, `transform_tool_result`, `pre_llm_call`, and immutable `on_interim_message` stream observers. `pre_llm_call` adds returned context to the user message at turn setup; it is not a per-tool-loop callback. `pre_tool_call` governs veto/approval/argument modification, not arbitrary context instructions. `post_tool_call` returns are ignored by its emitter. `transform_tool_result` can return a replacement string before context sees the result, so a later optional cadence nudge could append instruction there while preserving the result. Observer callbacks cannot rewrite interim streams. [Hermes `hermes_cli/plugins.py:109-115,1971-2022`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/hermes_cli/plugins.py#L109), [Hermes `agent/turn_context.py:794-834`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/agent/turn_context.py#L794), [Hermes `model_tools.py:674-698,849-866`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/model_tools.py#L674)

`ctx.inject_message` schedules a conversation turn, with gateway injection permission and profile routing; it is not a direct send-commentary primitive. aa uses it for idle proactive turns. aa already registers per-profile voice `pre_llm_call` and final-output polishing; proactivity separately records turn activity and injects idle check-ins. The smallest change is instruction text in that existing voice/skill path, not a plugin-written progress bot. The baseline skill explicitly said to send no text between browser calls, conflicting with the complaint; the baseline voice asked only for an initial update. [Hermes `hermes_cli/plugins.py:603-620`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/hermes_cli/plugins.py#L603), [aa baseline `__init__.py:41-66`](https://github.com/capthvnsen/alans-way-agents/blob/901a42f21762ced1a31b91bde9f5e6ac35e2cf9b/alans-way/__init__.py#L41), [aa baseline `voice.py:25-32,113-125`](https://github.com/capthvnsen/alans-way-agents/blob/901a42f21762ced1a31b91bde9f5e6ac35e2cf9b/alans-way/voice.py#L25), [aa baseline `proactivity.py:248-270,355-360`](https://github.com/capthvnsen/alans-way-agents/blob/901a42f21762ced1a31b91bde9f5e6ac35e2cf9b/alans-way/proactivity.py#L248), [aa baseline `workspace-operations/SKILL.md:281-283`](https://github.com/capthvnsen/alans-way-agents/blob/901a42f21762ced1a31b91bde9f5e6ac35e2cf9b/alans-way/skills/workspace-operations/SKILL.md#L281)

No cadence hook is justified by a demonstrated missing transport mechanism. Model behavior still needs observation; if real usage stays silent across long chains after these instructions, the optional `transform_tool_result` nudge requires session/turn-scoped counting and fake-clock tests. Secure Form password cards were not investigated or implemented in this lane.

## Configuration follow-up after review of 1acf14c

A fresh checkout still resolves to Hermes `d97007c32d6340f7ba79ac1dfb5773cc00846448`,
263 commits ahead and zero behind the Orgo build. The supported commands are
`hermes -p <profile> config get display.busy_input_mode` and
`hermes -p <profile> config set display.busy_input_mode steer` (or `interrupt`).
The profile selector resolves only that profile's home.
[Hermes `hermes_cli/profiles.py:2546-2568`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/hermes_cli/profiles.py#L2546)

The CLI writer preserves comments, quoted strings and platform overrides;
its own regression suite exercises comment and quote preservation. However,
`config get` reads merged defaults; `--raw` disables secret masking, rather
than selecting raw stored YAML. A fixture with no stored interim-message key
returns `true` from `config get display.interim_assistant_messages --json`.
The CLI therefore cannot establish which stored keys are missing.
[Hermes `hermes_cli/config.py:2067-2070,3577-3708,3714-3752`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/hermes_cli/config.py#L3714),
[Hermes `tests/hermes_cli/test_config_yaml_comment_preservation.py:72-86`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/tests/hermes_cli/test_config_yaml_comment_preservation.py#L72)

The follow-up review of `2f4a544` showed that the offline defaults editor
could not find Hermes's package-manager interpreter on a fresh install, and
could write `steer` after an unanswered skill question. That editor and its
interpreter plumbing have been removed. Setup no longer writes either display
key; the skill alone applies an answered busy-mode choice through the CLI.
Hermes's interim-message default is already `true` at `d97007c` (an ancestor
check confirms this commit includes `6e7b83a2f1`), so no interim setting is
written or offered automatically.
[Hermes `hermes_cli/config_defaults.py:919`](https://github.com/NousResearch/hermes-agent/blob/d97007c32d6340f7ba79ac1dfb5773cc00846448/hermes_cli/config_defaults.py#L919)

Guided setup asks an effective `interrupt` profile with no choice marker the explicit busy-mode
question before setup/restart. Only an answered choice is applied through the
profile-scoped CLI. Already-`steer` or `queue` profiles are skipped. An explicit choice to
keep `interrupt` records `skills.config.workspace-setup.busy_input_choice:
keep-interrupt` through that CLI, after disclosure, to avoid re-asking on later
runs. Silence and non-interactive runs leave mode and marker untouched. The
marker never restores a mode over a later user change. Fixture CLI set/get
confirmed this custom skill-config key round-trips (Hermes warns it is not a
runtime config key; the setup skill is its consumer).

Historical CLI/comment-preservation evidence remains in `next-G3F-work`.
The simplification evidence is in `next-G3F2-work`: the unanswered setup
regression fails on `2f4a544`, then passes after removing the editor. Direct
workspace tests cover fresh config, reruns and existing or partial values;
skill-text tests cover effective-mode checks, answers, silence, readback and
the ask-once marker. No real Hermes configuration or gateway was used.

## Isolated scripted transport demo

The retained scratch folder `next-live-progress-research-0wTfSp` contains `demo.py`, `demo.log`, both clones, a scratch virtual environment, and empty/mock homes. No Git worktree registration was created. The script uses DirectSDK's own `tests/test_directsdk.py` fake native subprocess, then actual Hermes `StreamDeliveryMixin`, `GatewayStreamConsumer`, `GatewayInboundMixin._hm_busy_steer`, `InterruptControlMixin.steer`, `apply_pending_steer_to_tool_results`, and DirectSDK `prepare_history`. It asserts delivery before tool work, no interrupt flag, no queued new turn, normal completion of an in-flight mock tool, and preservation of the steer in the next native request frame.

Run from that scratch folder: `perl -e 'alarm 30; exec @ARGV' venv/bin/python demo.py`. Exit **0**; transcript:

```text
PROVIDER: DirectSDK returned interim content alongside tool_calls
TELEGRAM: I’m opening the login page; the password form comes next.
TOOL 1: started (mock browser/MCP operation)
USER (while tool 1 is in flight): Use the alternate account, and tell me where you are.
BUSY ROUTE: steer accepted; interrupt=False; queued_new_turns=0
TOOL 1: completed normally
NEXT MODEL CONTEXT: original task + completed tool result + user steer (same run)
DIRECTSDK NEXT REQUEST: completed tool_result + steer text preserved in native user frame
TELEGRAM: Got it—I’m using the alternate account; the password form is next.
TOOL 2: started after the second interim message
FINAL: Same task completed; no interrupted or restarted turn.
```

This is a production-method transport demonstration with fake provider output, tool work, routing bookkeeping, and Telegram delivery. It does not invoke the complete Hermes conversation loop, an actual MCP server, the Claude subscription, or Telegram networking. It cannot establish that a real model follows the requested cadence, and the printed final completion is scripted.

Remaining live Telegram check, for the lead after deployment:

1. In a designated test profile, verify `/busy status` says `steer` (choose `/busy steer` if existing interrupt was preserved); confirm interim commentary is enabled and no Telegram override disables it. Ask for a reversible multi-call task that takes more than a few seconds, such as reading two public pages and comparing them.
2. After the first update and more than three seconds after task start, send “Keep comparing those pages; tell me where you are and also include their dates.” Expect guidance to be read after the current tool batch completes, a short model acknowledgment, another update between chunks, and continued work on the original comparison. A separate Hermes steer acknowledgment may be absent or debounced.
3. Confirm the final answer covers both the original comparison and added dates, with no interrupted/restarted task or duplicated follow-up turn. Repeat with one slow read-only MCP call to check the expected wait-until-return boundary; record timestamps and the actual transcript. Model cadence, real provider replay, and real Telegram/MCP delivery remain unverified until this check.
