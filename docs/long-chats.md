# Long chats

Hermes automatically compacts long conversations when compression is enabled:
it prunes/deduplicates old tool output and summarizes older context while keeping
recent anchors. Original messages remain in session archives for session search,
but summaries are lossy and a boundary can cause a pause. The effective trigger
depends on the model window, output reservation and overrides; the configured
default `0.50` does not mean every chat compacts at 50%.

The workspace-setup skill offers **opt-in** early pruning for each Alan's Way
profile: a 48,000-token trigger, eligibility above 8,000 characters and a
4,096-token minimum reclaim. It reports compression settings and the summary
route first, requires explicit consent, and preserves customized values. This
is an agent-guided option; running `setup.sh` alone does not enable it. It adds
no compactor, changes no summary model and does not enable `micro_compact`.
Each committed prune breaks the prompt-cache prefix, so savings vary.

The workspace-operations skill saves lasting general facts and preferences
to memory when they apply across sessions regardless of task, such as a preference
for concise replies. How-to procedures, pitfalls and task-specific preferences
belong in the relevant skill. Project and task records belong in the user's chosen
place, such as a project file or tracker; the bot asks if no place has been chosen.
Short-lived facts stay in session history. This guidance does not migrate or delete existing memory.
Transient tabs, element refs and handback state stay out of durable memory.

To undo the opt-in, run
`hermes -p <profile> config set compression.proactive_prune_tokens 0` for each
profile you enabled (`default` names the main profile). Restore any other values
actually changed from the setup record with `config set`, or use `config unset`
for keys originally absent. Existing custom settings stay intact. Restart via
the normal gateway workflow when authorized; undo does not restore already
pruned active output.

See the [profile check, consent and undo procedure](../alans-way/skills/workspace-setup/references/long-chats.md).
