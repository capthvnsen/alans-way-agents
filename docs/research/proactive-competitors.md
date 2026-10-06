# Proactive assistant competitive research

How leading proactive assistants decide **when** to reach out and **what** to surface,
plus cost-efficiency patterns for the agent loop. Written to inform the `proactive-primary`
plugin redesign (see `../proactivity.md`).

Note on naming: several sources below date from Sept–Oct 2026, when "proactive agent"
launched from xAI/SpaceXAI (Grok Bot Primary Bot), OpenAI (Dots, Pulse earlier), and Meta
(Muse) within weeks of each other. Quotes are from official docs/design posts where possible;
journalist and community reports are flagged as such.

## Competitor patterns

| Product | What triggers a proactive message | Batching / consolidation | Spam avoidance | Value categories surfaced | Asks vs. acts |
| --- | --- | --- | --- | --- | --- |
| **Grok Bot — Primary Bot** (SpaceXAI, Oct 2026) | "Routines" on a schedule **or** event triggers (e.g. Slack message matching a narrow rule); Primary Bot watches connected apps/inboxes/files and "spots work it can take off your plate," then *offers* to handle it. Canonical example: detected a flight change and flagged that the user's Uber was still tied to the old flight — mid-connection. Bots also "follow up on threads that go quiet." | One Primary Bot as the single surface over specialist bots; per-Bot conversation threads; sidebar distinguishes **needs attention** vs. **unread activity** vs. working. Routines post results into the owning conversation. | Per-Bot notification toggle; notifications suppressed while app is focused; docs warn against broad listeners ("every new message") — "they create noise, consume usage"; routines auto-pause after long user absence; **no published interrupt-frequency cap for Primary Bot yet** (open question per third-party coverage). | Anomaly/wrinkle detection (Uber-flight mismatch), meeting-prep briefs (community pattern: calendar+CRM+email+Slack → one skimmable brief), open loops ("threads that go quiet"), routine reports (account risk watchlists, org-chart upkeep), cross-bot routing/delegation. | Suggestions are free ("suggestions don't count against your usage"); accepted work bills normally. Auto Review rules: "Ask first" wins conflicts; docs recommend approval for sending/publishing/deleting/purchasing/prod changes. Guidance: "automate preparation before execution — draft, reconcile, recommend first." 50 routines/Bot max. |
| **Instinct** (Spear Street Technology, private beta) | Persistent agent reachable by iMessage/WhatsApp text or call. Connects email, messaging, screen, audio, location. "Following up on threads you've dropped, proactively calling or texting you." Reported: monitored sold-out IMAX showings → found cancellation tickets in a day; detected airline moved a flight 90 min → qualified for full refund, cancelled and rebooked (~$550 saved). | One continuous thread — which users found crowded (multiple jobs in one thread); recurring loops + a top-level agent that monitors and dispatches (per Anish Acharya's technical read). | Praised specifically because "**it doesn't text too much**" (Wired) — contrast Lindy, deleted by same reviewer after it texted every morning and joined Zoom calls uninvited. No documented quiet-hours/cap mechanism; restraint is behavioral, not a published control. | Life admin end-to-end: bookings/reservations, bill negotiation, subscription audits, spam-folder rescue, calendar-error detection, scheduling coordination on WhatsApp, monitoring watches (tickets). | Very aggressive autonomy: reset a password to finish a purchase; continued through multi-step jobs without re-confirming. Documented failures: an email sent without approval, a successful email-borne prompt injection, a Resy account banned after the agent pinged it "hundreds of times every hour." **Cautionary tale: unbounded acting destroyed trust faster than capability built it.** |
| **Meta Muse** (Sept 2026) | Works "on a schedule and in response to relevant events." When background work completes, "it evaluates whether the result is worth surfacing, and notifies you only when something is meaningfully new or needs your input." Example: caught a school-sports tryout deadline buried in email 12h before close, messaged the user pre-flight. Goals → proactive nudges; Ideas tab generated from patterns/goals. | One long main chat (bubbles, not flat transcript) + side chats for separate projects; Ideas tab as a pull-surface for suggestions; Goals tab shows tracked plans; Artifacts deliver rich output instead of text walls. | Explicit **user-tunable proactivity dial**: "you can always tell your Muse to turn it off, dial it down, or dial it up." Design bar: "a proactive message has to be genuinely helpful and worth the interruption." Third-party setup guides advise "start conservative." | Deadline catches, goal progress nudges, scheduled digests (daily scan of unread Messenger/WhatsApp/iMessage flagging follow-ups — "one daily scan replaces checking four apps"), proactive idea suggestions, approvals needed. | Deterministic approval cards for "hard to undo" actions (email send, purchase); granular scopes: allow once / for the task / for the site / always for connector / deny. Default allows standard browsing, stops on irreversible. Full activity log + editable memory files for transparency. |
| **OpenAI Dots** (DevDay Sept 2026) | "Always-on" agent on its own cloud computer; works assigned goals 24/7; when idle does "proactive research" against connected apps (restricted mode). Examples: saw on calendar the user was working through dinner → messaged two GrubHub options with prices; noticed a forgotten invoice → prepared it → sent only after approval; flagged a stale feature promise in a draft customer email before a launch meeting. | One thread per dot across ChatGPT/Slack/Teams (iMessage/RCS waitlisted). "When something needs your attention, it gets in touch." Brings "work to review and decisions that need your judgment." | User picks which apps it can access and what to focus on; **Custom Rules: allow / require approval / block per action**; pause anytime. Positioned as supervised autonomy, not volume. | Inconsistency detection (stale promise in draft), missed-obligation catches (invoice), contextual convenience (dinner order), progress updates on goals, next-step offers. | Acts within Custom Rules; approval required for user-flagged action types; demonstrated pattern is *prepare → present → send on approval*. |
| **ChatGPT Pulse** (Sept 2025, Pro mobile) | Scheduled, not event-driven: **nightly async research** synthesizing memory + chat history + thumbs feedback + optional Gmail/Calendar. Delivers a morning brief. | **5–10 topical visual cards** each morning, expandable for detail; hard stop: "**Great, that's it for today**" — deliberate anti-feed design. Cards expire after 24h unless saved or opened into chat. | Once-daily cadence only; connectors off by default; thumbs up/down + "curate" requests steer future editions; no infinite scroll; silence-by-omission — only items it judges most relevant. | Follow-ups on recurring topics, meeting agendas, gift/date reminders, travel recs, long-term goal next steps, news roundups on stated interests. | Surfaces information and drafts only (agendas, suggestions) — no external acting. Expanding a card converts it into a normal chat. |
| **LangChain ambient agents** (reference pattern) | Event-driven: agents "respond to ambient signals and demand user input only when they detect important opportunities or require feedback." Reference impl: Gmail events → triage node. | Agent Inbox collects pending human-input items; background agents run many tasks in parallel since latency tolerance is higher. | Three interrupt types, used sparingly by design: **Notify** (FYI, no action), **Question** (blocked without info), **Review** (approve a proposed action). "On-the-loop" > in-the-loop: show all intermediate steps, allow pause mid-run. | Email triage → respond/notify/ignore; anything where an event stream exists. | Acts autonomously within bounds; escalates through the three typed interrupts rather than free-text pings. Memory learns accept/edit/ignore feedback to reduce future interrupts. |
| **OpenClaw community assistants** (Rook, Lofy, Compass, Motivi) | Cron-driven briefings (morning/evening/weekly), calendar reminders, heartbeat loops ("does anything need attention? — silent if no"), event buses (on("calendar.reminder") → notify), passive chat listening (Compass extracts tasks/decisions/blockers from Telegram, posts digests to Slack). | Morning briefing + evening summary as fixed digest slots; Compass: silent unless @mentioned or scheduled; digests consolidate extracted signal. | Rook: RSS scan 4×/day with relevance scoring, **hard cap 3 notifications/day**; Motivi: `/break` mode + timezone-aware check-ins; Lofy: "stays out of your way when you're locked in"; OpenClaw `activeHours`/quiet hours. | Morning/evening digests, habit-streak nudges, deadline tracking, meeting prep, passive task extraction, RSS/web monitoring. | Mostly notify + scheduled digests; approvals handled via chat; community guidance: keep cron prompts short, let skills hold workflow logic, batch multiple checks into one heartbeat. |
| **Google Now / Assistant (historical)** | Predictive cards from search/location/calendar/email patterns: commute time, flight status, packages, appointments, weather-before-trip. Ambient Mode: glanceable proactive info on lockscreen. | Cards ranked by predicted relevance on a scroll surface; notification icons for the rest. | Relevance ranking as the filter; later Google *removed* proactive pieces (birthday reminders, commute cards) — even Google struggled to keep proactive quality high enough to keep. | Travel, commute, schedule, packages, weather. | Surfaced info + one-tap actions (navigate, call); did not act externally. |
| **Limitless / Rewind** | Meeting-scoped proactivity: pre-meeting briefs from calendar + email + prior recordings; task/commitment extraction from conversations → to-do prompts (roadmap). | Meeting prep delivered ahead of the meeting; daily summaries. | Narrow domain (meetings/conversations) keeps volume bounded. | Meeting prep, transcription, summaries, extracted commitments, "where did I leave off with Jake." | Prepares/drafts; acts only with permission (roadmap). |

## Transferable patterns

Ordered roughly by how directly they map onto `proactive-primary`.

1. **Two interrupt lanes: "needs attention" vs. "unread activity."** Grok Bot's sidebar
   separates *a question/approval/handoff* from *a finished result*. Telegram maps cleanly:
   urgent/interactive messages (approval buttons, questions) vs. quiet FYI messages the user
   can batch-read. Don't let FYI items borrow the urgency of approval items.
2. **The proactive bar is "genuinely helpful and worth the interruption" — and it's a user
   dial, not a constant.** Muse ships off/down/up. `proactive-primary` already has
   pause/resume + budgets; consider a coarse intensity setting (quiet / normal / eager)
   mapping to daily caps + low-purpose allowance rather than only on/off.
3. **A missed-obligation catch is the highest-value proactive message there is.**
   Every flagship demo is the same shape: Muse's tryout deadline, Dots' forgotten invoice,
   Grok's Uber-flight mismatch, Instinct's $550 refund. The common structure: *two sources
   disagree, or a commitment exists without a matching downstream artifact.* The plugin's
   strongest watch types are exactly these "reconciliation" checks: calendar vs. reality,
   promise vs. delivery, deadline vs. artifact.
4. **"Wrinkle detection" = deterministic diffing, not model reasoning.** The Uber example is
   a join between flight state and reservation state. Open loops ("Keith sent the pipeline
   Sep 28, financials still outstanding") are staleness arithmetic on tracked commitments.
   These are computable cheaply; the LLM only writes the message. Build watchers that emit
   structured diffs; let the model phrase, not discover.
5. **Scheduled digests + rare real-time interrupts beats uniform polling.** Fitz/Kushlev/
   Ariely (2019, n=237): notifications batched **3×/day at predictable times** beat both
   continuous trickle and hourly batching for stress/mood/control; zero notifications caused
   FoMO/anxiety. Mark et al. (CHI'08): interruptions are compensated by faster work at the
   cost of stress and frustration; 57% of work spheres get interrupted. Design: a morning
   brief + 1–2 scheduled digest slots + a small budget of immediate interrupts for
   time-critical catches (the "12 hours before tryout closes" class).
6. **Cap card/message count and declare completion.** Pulse's "Great, that's it for today"
   is a trust feature: a bounded set signals curation. A proactive brief should be a fixed
   small list (3–7 items) ranked by urgency, never a feed. Rook's "max 3 notifications/day"
   for ambient sources shows the same instinct at hobbyist scale.
7. **Expiry beats accumulation.** Pulse cards die at 24h unless saved. A proactive Telegram
   message about "your 8:30 is the real meeting" is worthless at 8:45 — staleness-aware
   retraction/collapse (edit the message, or send "no longer relevant" cleanup) keeps the
   channel high-signal.
8. **Suggestions can be cheap even when actions aren't.** Grok's "suggestions don't count
   against your usage" is pricing, but the design principle holds: *offer cheap, execute
   dear.* The plugin can surface "I could do X — want me to?" far more often than it does X.
9. **Ask vs. act needs three states, not two.** LangChain's Notify/Question/Review and
   Dots' Custom Rules (allow / require approval / block) and Muse's approval scopes
   (once / task / site / connector / deny) all converge on graded action classes:
   reversible-internal → just do it and log it; external-but-reversible → do it and report;
   external-irreversible or money/messages → propose first. `proactive-primary`'s existing
   "ask before external messages/purchases/credentials/prod" is the right floor.
10. **One long thread is where proactive messages live; structured surfaces hold the
    backlog.** Muse (Ideas/Goals tabs) and Pulse (expiring cards) keep the chat stream
    clean by parking "things you might want" in pull-surfaces. In Telegram, approximate
    this with pinned/threaded digests or a `report_signal`-style ledger the user can query —
    don't DM every idea.
11. **Negative examples are as instructive as positive ones.** Lindy was deleted for
    morning texts + uninvited Zoom joins; Instinct lost trust over an unapproved email +
    runaway polling (banned from Resy after hundreds of hits/hour); Meta's human-call-center
    fallback for Muse was rolled back after disclosure failures. The failure modes:
    *unscheduled volume*, *uninvited presence*, *unapproved external action*,
    *unbounded retry/polling*. All four are policy problems, not capability problems.
12. **Onboarding consent sets the whole relationship.** Grok's Primary Bot asks which
    existing bot to promote; Muse setup guides push "start conservative" on proactivity and
    "allow once" on approvals. For a plugin: default paused, bind explicitly, tighten watch
    scope, widen only after observed good catches — matches the existing design.
13. **Transparency surfaces kill the "what is it doing" anxiety.** Muse's tap-avatar →
    activity log + editable memory; Grok's run history (20 records/routine); LangChain's
    on-the-loop intermediate-step visibility. The plugin equivalent: `/proactivity status`,
    the watch ledger, and a readable reason attached to every wake ("I'm messaging because
    watch #7's signal changed").
14. **Proactivity needs an off-ramp that isn't deletion.** Motivi's `/break 1d`, Muse's
    dial, Grok's auto-pause-after-absence. Temporary mute ("quiet until Thursday") retains
    users who would otherwise uninstall. (Existing plugin: pause + quiet hours cover this;
    a timed "snooze N days" is a cheap addition.)
15. **Silence must be legible.** Rook's heartbeat — "does anything need attention? Silent
    if no" — only works because the user trusts the watcher ran. Emitting a low-cost
    heartbeat *state* (ledger timestamp, "last checked 14:02, all quiet") on request —
    without a model call — reassures without interrupting.

## Token- and cost-efficient proactive loops

Concrete, sourced patterns for keeping an always-watching agent affordable.

1. **Level-0 deterministic pre-filter before any model call.** VRAXIA Sense's published
   pipeline: L0 regex/length/noise-lists kills ~75% of events at $0 → L1 small-model binary
   triage (~$0.0001/event) drops another ~18% → L2 full classification (~$0.0003) on the
   ~7% remainder. Weighted ≈ **$0.000034/event**. A FleetMind case (Microsoft Foundry)
   reports a deterministic telemetry pre-filter cut LLM calls **95%**, which then allowed
   down-shifting the survivor model a tier (4.1 → 4.1-mini).
   Sources: <https://github.com/SAMIRRICARDO/vraxia-sense>,
   <https://stochasticcoder.com/2026/02/24/optimizing-ai-agents-for-scale-triage-throttle-control-and-model-right-sizing/>
2. **Event-driven spokes beat polling cursors.** Calegix's news agent: SSE/webhook "spoke"
   writes one JSON file per event to a queue dir (pure I/O, no LLM) → inotify listener →
   **cheap embedding-similarity gate** against a stored "user interests" anchor drops
   sub-threshold items → LLM only sees survivors. Result: 40× latency improvement *and*
   lower spend vs. 5-min cron polling. Rule of thumb offered: "cron does scheduled work;
   spokes do reactive work."
   Source: <https://calegix.com/posts/event-driven-spokes-vs-polling>
   (Notably, this article's queue path is `~/.hermes/` — the same ecosystem.)
3. **Snapshot-diff watchers: identical state ⇒ zero model calls.** This is already the
   plugin's own pattern (observer checks every 30 s, model-free when nothing changes) and
   it's the single biggest lever: the expensive question is "did anything *change*?", and
   it's answerable with hashes/etags/timestamps. Every watcher should persist a compact
   baseline and only admit an event on a real diff; first-write baselines, never alert on
   snapshot #1.
4. **Batch many checks into one turn.** ClawMage's OpenClaw guidance: five separate cron
   jobs (email, calendar, weather, notifications, projects) each spin a session + reload
   context; one heartbeat turn handling all five costs one context load. Keep the monitor
   scratch file small; keep cron *prompts* short and put workflow logic in the skill.
   Source: <https://clawmage.ai/blog/openclaw-cron-vs-heartbeat/>
5. **Isolated/light sessions for heartbeats.** OpenClaw docs: `isolatedSession: true`
   drops a heartbeat from ~100K context tokens to ~2–5K; `lightContext: true` skips
   workspace bootstrap files; `target: "none"` for internal-only updates. Their cost math:
   a 30-min heartbeat on a frontier model ≈ **$0.45–0.75/beat → $650–1,080/month**; the
   same on a small/local model ≈ $0–14/month. Heartbeats are "the #1 silent cost driver."
   Sources: <https://docs2.openclaw.ai/gateway/heartbeat>,
   <https://clawdocs.org/guides/cost-management>
6. **Right-size the model per job, per stage.** Clawdocs community guide: 60× price spread
   between frontier and flash-lite tiers; recommended routing — local/cheap model for
   heartbeat checks, mid-tier for scan jobs, frontier only for the actual user-facing turn.
   "The three highest-leverage changes: cheap heartbeat model, quiet hours, longer interval
   — ≈70% cost cut with no quality loss."
   Source: <https://github.com/clawdocs/clawdocs.github.io/blob/gh-pages/docs/guides/performance-tuning.md>
7. **Quiet hours are a cost feature too.** −42% heartbeat spend by not checking at 3 AM
   "for emails nobody sent." Aligns perfectly with the plugin's existing quiet window —
   suppress both the message *and* the work.
8. **Align wake cadence to the prompt-cache TTL.** OpenClaw token docs: if the provider
   cache TTL is 1h, a 55-min heartbeat keeps the cache warm and avoids re-caching the full
   prompt; cache reads bill far below fresh input. For a fixed observer prompt + small
   changing tail, structure the prompt so the stable prefix caches.
   Source: <https://cdn.jsdelivr.net/npm/openclaw-viking@2026.2.23/docs/reference/token-use.md>
9. **Dedupe before wake, not after.** Persist a hash/ID of the last-surfaced event; a
   re-armed or unchanged signal never reaches the appraiser. Both the plugin's own ledger
   design and the VRAXIA/jiraku patterns (InMemory/registry gates before classifier)
   converge here: *state machine first, model second.*
10. **Bound every autonomous loop.** Instinct's Resy-ban incident is the counterexample —
    an unthrottled watcher hit a site "hundreds of times every hour." Every collector/watch
    needs: a rate ceiling, a retry cap with backoff, a stale-data policy ("report failure
    instead of using old data" — Grok's routine template language), and an explicit
    no-data outcome.
11. **Narrow event rules over broad listeners.** Grok's docs literally prescribe this:
    "avoid broad listeners such as 'every new message' — they create noise, consume usage,
    and increase the chance of acting on irrelevant input." Match on concrete predicates
    (sender + keyword + state change), not topics.
12. **Pre-compute verdicts outside the model.** The sentinel-triage pattern: enrich events
    deterministically (pre-computed `verdict` fields, truncated payloads) so the LLM
    consumes only verified signals — never raw noise it could misread. Same move for
    proactive watches: ship the appraiser a compact diff, not the raw substrate.
    Source: <https://github.com/eabboa/sentinel-triage-agent>

## Source list

- Grok Bot docs (overview, routines, settings/notifications):
  <https://docs.x.ai/grok-bot/overview> · <https://docs.x.ai/grok-bot/skills-routines-and-automations> · <https://docs.x.ai/grok-bot/settings-and-notifications> · <https://x.ai/bot> · <https://x.ai/news/introducing-grok-bot>
- Primary Bot coverage: <https://www.progressiverobot.com/2026/10/02/primary-bot-grok-4-7-base-model-proactive-grok-bot/> · <https://www.orcarouter.ai/blog/grok-bot-launch>
- Community Grok bot patterns: <https://grokbots.ai/meeting-prep-brief> · <https://grokbot.dev/use-cases/telegram-inbox-bridge/> · <https://github.com/SSBrouhard/grokbot-telegram-bridge>
- Instinct: <https://instinct.com/> · <https://www.wired.com/story/i-finally-found-an-ai-agent-worth-the-risk/> · <https://www.usecarly.com/blog/what-is-instinct-ai/> · <https://mlq.ai/news/instinct-raises-250-million-for-private-beta-ai-assistant-at-25-billion-valuation/>
- Meta Muse: <https://introducing.muse.ai/> · <https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/> · <https://creators.instagram.com/blog/introducing-muse-personal-ai-agent/> · <https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse> · <https://museexplained.com/guide/getting-started/> · <https://www.ksl.com/article/51627159/>
- OpenAI Pulse: <https://openai.com/index/introducing-chatgpt-pulse/> · <https://techcrunch.com/2025/09/25/openai-launches-chatgpt-pulse-to-proactively-write-you-morning-briefs/> · <https://arstechnica.com/ai/2025/09/chatgpt-pulse-delivers-morning-updates-based-on-your-chat-history/>
- OpenAI Dots: <https://openai.com/index/introducing-dots/> · <https://chatgpt.com/features/dots/> · <https://www.wired.com/story/openai-dots-always-on-ai-agents-that-proactively-help/> · <https://indianexpress.com/article/technology/artificial-intelligence/openai-dots-always-on-ai-agents-explained-10900652/>
- LangChain ambient agents: <https://www.langchain.com/blog/introducing-ambient-agents> · <https://langchain-blog.ghost.io/ux-for-agents-part-2-ambient/> · <https://github.com/langchain-ai/agents-from-scratch/>
- OpenClaw ecosystem: <https://github.com/barman1985/Rook> · <https://github.com/openclaw/skills/blob/main/skills/harrey401/lofy/SKILL.md> · <https://www.npmjs.com/package/compass-ai> · <https://github.com/Timur-marii8st/Motivi-Ai> · <https://docs2.openclaw.ai/gateway/heartbeat> · <https://clawdocs.org/guides/cost-management> · <https://clawmage.ai/blog/openclaw-cron-vs-heartbeat/>
- Google (historical): <https://en.wikipedia.org/wiki/Google_Now> · <https://9to5google.com/2019/11/25/assistant-ambient-mode-details/> · <https://support.google.com/assistant/answer/13971691>
- Limitless: <https://www.theverge.com/2024/4/15/24130832/limitless-ai-pendant-wearable-meetings>
- Interruption science: Fitz, Kushlev, Jagannathan, Lewis, Paliwal, Ariely — "Batching
  smartphone notifications can improve well-being," *Computers in Human Behavior* 101 (2019)
  <https://www.kushlev.com/s/2019-Fitz-Kushlev-etal-2019.pdf> · Mark et al. — "The Cost of
  Interrupted Work: More Speed and Stress," CHI 2008 <https://ics.uci.edu/~gmark/chi08-mark.pdf> ·
  Mark et al. — "Email Duration, Batching and Self-interruption," CHI 2016
  <https://ics.uci.edu/~gmark/Home%5Fpage/Publications%5Ffiles/CHI%2016%20Email%20Duration.pdf>
- Token efficiency: <https://calegix.com/posts/event-driven-spokes-vs-polling> ·
  <https://github.com/SAMIRRICARDO/vraxia-sense> ·
  <https://stochasticcoder.com/2026/02/24/optimizing-ai-agents-for-scale-triage-throttle-control-and-model-right-sizing/> ·
  <https://github.com/eabboa/sentinel-triage-agent> ·
  <https://github.com/Perfect5th/jiraku>
