# Shared agent config (draft v1)

Alan's Plugin for Hermes and Alan's Plugin for Grok Bot target one JSON config
contract for persona, voice, proactivity and identity. This directory owns that
contract; plugin packages reference it rather than maintaining their own schemas
or preference copies.

**Status:** documentation and structure only. Hermes has no reader for this
format yet, and the Grok Bot package is a skill/settings scaffold. Adding these
files changes no running agent. The example values are proposed preferences,
not a change to Hermes defaults.

## Files and location

- [`config.schema.json`](config.schema.json): JSON Schema Draft 2020-12, with
  `schema_version: 1` and unknown fields rejected at every object level.
- [`config.example.json`](config.example.json): a complete, non-secret example.
- Proposed user config: `~/.config/alans-way/config.json`. Both future plugin
  readers on the same host use this one file. Expand `~` to the running user's
  home; this path is independent of the current directory and Hermes profiles.

To prepare a config for review, copy the example to that location without
overwriting an existing file, then edit it. Creating the file does not activate
it in Hermes. The schema stays in this repo; the user config contains values,
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

These requirements describe future adapters and the Grok Bot skill's use of the
config; they do not install a loader or scheduler.

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

## Consumer status

| Consumer | Current state |
|---|---|
| [Alan's Plugin for Hermes](../alans-way/README.md) | References this contract only. Existing persona settings, `/tone`, `/proactivity` and per-profile state remain authoritative. A future adapter needs a separate runtime change and tests. |
| [Alan's Plugin for Grok Bot](../alans-way-grok-bot/README.md) | `settings.json` points to this schema and user config; `SKILL.md` describes reading the values. Native settings loading, packaging and scheduling are pending. |

## Decisions for Alex

- TODO: approve the draft field names, example preferences and shared user path,
  including whether a later version needs separate identities per bot/profile.
- TODO: decide how a future Hermes adapter resolves shared preferences against
  existing persona, tone and proactivity settings. This draft performs no migration.

## License

MIT License. Copyright (c) 2026 Alex Hansen. See [LICENSE](../LICENSE).
