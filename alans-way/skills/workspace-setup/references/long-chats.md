# Long-chat setup procedure

Run before setup's gateway restart. Use `hermes profile list` and identify only
profiles using Alan's Way (the installed plugin or its managed `workspace_browser`
block); include `default` when applicable. Repeat the check and consent step for
each target, always passing `-p`, including `-p default`, so the active profile
cannot redirect a command. This is an agent-guided step; `setup.sh` does not run it.

## Read and report first

Set `profile` to the target's name. Check `hermes config get --help` and
`hermes config set --help` on the installed version. If the pruning keys or CLI
are unsupported, report that and skip this option; never hand-edit YAML.

```sh
: "${profile:?Select the target profile first}"
for key in compression model auxiliary.compression.provider auxiliary.compression.model auxiliary.compression.base_url; do
    printf '%s: ' "$key"
    hermes -p "$profile" config get "$key" --json || break
done
```

Report whether compression is enabled, its configured `threshold`,
`threshold_tokens` cap and `model_thresholds` overrides. Report the **effective**
token trigger for the running model, using the current profile's runtime
`Context compressor initialized` log entry (matching model/provider), or the
running session's context diagnostics if available. Keep unrelated logs and
credentials out of chat. The configured default `0.50` alone is not the effective
threshold: below 512,000 tokens Hermes raises the ratio to at least 75%, applies
it after the output reservation, and uses a 64,000-token floor bounded near 85%
of the input budget when that floor binds. The absolute cap and summary-model
capacity can lower it further. Account for model overrides and runtime model
changes. If the runtime trigger or model capacity cannot be established, report
it as **unknown**, list the configured inputs and explain the floor; do not claim
a guessed token count or that compression always starts at 50%. If disabled,
report that automatic summary compression is off and leave it off.

Report `auxiliary.compression.provider`, `.model` and `.base_url`. With provider
`auto` and an empty model, the summary normally inherits the main model/provider
before Hermes' fallbacks; report that main route if resolved, otherwise say it is
unknown. An explicit summary route should be reported as configured, with any
known runtime fallback identified separately. `auto` is not inherently cheap.
Suggest a dedicated fast summary model only as an option, after checking its
input capacity and continuity; never switch routes automatically or make a test
model call as part of this check.

## Offer pruning, then apply only with consent

Explain: "Hermes can prune large old tool results once the context reaches
48,000 tokens, considering results over 8,000 characters and committing only
when at least 4,096 tokens can be reclaimed."

Show the current three values and proposed changes for this profile. Record
them outside the repository for undo. Values differing from Hermes' stock
defaults (`0`, `8000`, `4096`) are customized and must stay untouched, including
a trigger already set to `48000`. If the user deliberately chose a stock value,
preserve that too and skip the option for this profile. `config get` returns
the merged value, so a trigger that reads `0` cannot be told apart from one the
user deliberately set to `0`: ask whether pruning was turned off on purpose
before proposing to enable it. Ask for explicit consent to the remaining
changes; approval of general installation, `--non-interactive`
or proactivity does not count. Without consent, finish the read-only report.

After consent, set `PRUNING_CONSENT=yes` for this block and keep `profile` set
to the approved target. Do not default consent to yes or carry it to another
profile without approval covering that profile. The block rechecks values
before writing and treats unreadable keys as unknown, never as defaults.

<!-- pruning-commands -->
```sh
if [ "${PRUNING_CONSENT:-}" = yes ]; then
    : "${profile:?Select the approved target profile first}"
    for setting in proactive_prune_tokens:0:48000 proactive_prune_min_result_chars:8000:8000 proactive_prune_min_reclaim_tokens:4096:4096; do
        key=${setting%%:*}
        values=${setting#*:}
        stock=${values%%:*}
        proposed=${values#*:}
        current=$(hermes -p "$profile" config get "compression.$key" --json) || {
            printf 'Skipped %s: value unknown\n' "$key"
            continue
        }
        if [ "$current" = "$stock" ] && [ "$current" != "$proposed" ]; then
            hermes -p "$profile" config set "compression.$key" "$proposed" || break
        else
            printf 'Kept %s unchanged\n' "$key"
        fi
    done
fi
```

Read the three keys again with `hermes -p "$profile" config get` and report the
actual values and any failures before the planned restart. If already running,
apply changes via the existing gateway restart workflow only when authorized.
Leave compression thresholds, the summary route and `compression.micro_compact`
unchanged. This option uses the built-in compressor; a custom context engine
may not implement it. Pruning protects recent context but rewrites the sent
history and breaks the prompt-cache prefix when it commits; the reclaim minimum
keeps this episodic. It cannot guarantee faster chats or lossless recovery.

## Undo

To disable the stock-default opt-in for an approved profile:

```sh
hermes -p "$profile" config set compression.proactive_prune_tokens 0
```

Restore any other values this step actually changed from the recorded values
using `hermes -p "$profile" config set <key> <old-value>`. If a changed key was
originally absent, `hermes -p "$profile" config unset <key>` restores inherited
defaults. Leave preexisting custom values alone. Undo applies to future pruning;
it does not reconstruct tool bodies already pruned from active context. Use
Hermes' session search to recover archived details when available.
