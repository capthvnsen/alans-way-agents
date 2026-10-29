# Shared agent config (draft v1)

Alan's Plugin for Hermes and Alan's Plugin for Grok Bot target one JSON config
contract for persona, voice, proactivity and identity. This directory owns that
contract; plugin packages share its validation and never keep separate preference
files.

Both consumers now validate this contract. Hermes reads it when the plugin
loads; the Grok Bot generator renders a portable snapshot. No config means
Hermes retains its existing behavior. Invalid config fails plugin registration
before applying any preferences, with an error naming the field and rule rather
than echoing its value.

## Files and location

- [`config.schema.json`](config.schema.json): JSON Schema Draft 2020-12, with
  `schema_version: 1` and unknown fields rejected at every object level.
- [`config.example.json`](config.example.json): a complete, non-secret example.
- User config: `~/.config/alans-way/config.json`. Both consumers on the same host use this one file. Expand `~` to the running user's
  home; this path is independent of the current directory and Hermes profiles.

Copy the example to that location without overwriting an existing file, then
edit it. Reload the Hermes plugin (normally by restarting its gateway through
its owner) to apply edits. The schema stays in this repo; the user config contains values,
not a second schema. Separate hosts require an explicitly managed copy; this
contract supplies no synchronization service.

## Fields

Every field below is required. There is no implicit default filling or merge
with a plugin-specific JSON preference copy.

| Field | Meaning |
|---|---|
| `schema_version` | Contract version; only integer `1` is defined |
| `persona.description` | Character and working approach, distinct from a display name |
| `voice.tone` | Text reply style; speech synthesis is outside this draft |
| `voice.reply_length` | `short`, `balanced` or `detailed`; guidance that keeps requested work complete |
| `proactivity.enabled` | Preference for unsolicited check-ins; the example opts out |
| `proactivity.timezone` | A real IANA timezone name, such as `Etc/UTC` |
| `proactivity.idle_minutes` | Positive integer minimum quiet time; native backoff can delay a check-in further |
| `proactivity.active_hours.start`, `.end` | Local `HH:MM`, start inclusive, end exclusive; start must be earlier than end on the same day |
| `identity.name`, `.role` | Assistant display name and role; neither identifies a user, account, chat or bot route |

## Reader contract

Both adapters follow this contract; generation alone does not install a scheduler.

1. Read the same user config path and validate the complete document against
   this schema before applying preferences. Verify the IANA timezone and the
   same-day hours ordering separately: JSON Schema checks the time syntax, not
   those semantics. Overnight and all-day windows are outside draft v1.
2. A missing file means no shared override. Report malformed JSON, validation
   errors and unsupported versions without applying a partial config, rewriting
   the file or resetting existing host settings. Read the file as data, never
   execute its values as commands.
3. Use persona, voice and identity as preferences within the host's instruction
   hierarchy. Explicit user requests and host safety rules still govern the
   task. This config grants no tool access, credentials or action approvals.
4. Apply proactivity only through supported native scheduling and operator
   controls. `enabled: true` alone cannot start a worker, bind a conversation,
   widen permissions or override a pause. If scheduling is unavailable, report
   it; do not promise background check-ins.

## Use with Hermes and Grok Bot

Install `jsonschema>=4.18,<5` in each consumer's Python environment:

```sh
python -m pip install -r shared/requirements.txt
mkdir -p ~/.config/alans-way
cp -n shared/config.example.json ~/.config/alans-way/config.json
```

Hermes declares this dependency in `alans-way/plugin.yaml`; installations that
only warn about dependencies need the pip command above using Hermes's Python.
A missing config needs no validator and preserves all previous plugin defaults.
All fields are required when a file exists; partial or unknown fields are errors.
JSON must be UTF-8, with unique keys and finite numbers. The reader also checks
that the timezone exists and `start < end`. Error messages never echo input values.

**Hermes precedence:** shared identity/persona are injected as preferences on
every profile and surface. With `/tone texting`, shared tone and reply length
replace the built-in texting prompt and formatting cleanup on chat surfaces.
`/tone default` disables that voice override; identity/persona remain. Existing
pacing stays local. Shared reply length is guidance, not a character limit.
Shared timezone, idle time and exact active hours control the native scheduler;
edit the shared file and reload to change them. Conflicting `/proactivity` or CLI
schedule edits return a clear error. Profile route bindings, pauses, backoff,
morning-brief and weekly-report choices remain local. A shared `enabled: false`
blocks all unsolicited plugin check-ins, briefs and reports; local resume cannot
bypass it. `enabled: true` preserves local pauses and never creates a route.
An explicitly requested `/proactivity now` remains a manual action.
Shared values are never written into profile state, SOUL.md or config.yaml.
Deleting the shared file and reloading restores the existing local preferences.

**Grok Bot:** run the [generator](../alans-way-grok-bot/README.md#generate-and-use)
and give its two outputs to your Bot. The settings JSON contains persona, voice
and schedule+prompt routine definitions, with its own output schema. It is a
handoff format, not a native importer. Generation and skill loading make no
changes to running Bots; native routine setup remains operator-requested.

`shared/config.schema.json` is canonical. Hermes installs only the `alans-way/`
subdirectory, so `alans-way/config.schema.json` is a bundled copy, checked byte
for byte in tests. When updating the contract, copy the canonical schema there
and run the config tests. Both readers use the same implementation in
`alans-way/shared_config.py`; no second preference file is maintained.

## License

MIT License. Copyright (c) 2026 Alex Hansen. See [LICENSE](../LICENSE).
