# Alan's Plugin for Grok Bot

Generate a self-contained Grok Bot skill and a settings handoff from the same
[shared config](../shared/README.md) used by Alan's Plugin for Hermes. Grok Bot
cannot load Hermes Python plugins.

## Generate and use

From this checkout, with Python 3.11+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r shared/requirements.txt
.venv/bin/python scripts/generate_grok_bot.py \
  --config ~/.config/alans-way/config.json --output /tmp/alans-way-grok-bot
```

Prepare the config using [the shared example](../shared/config.example.json).
`--config` defaults to `~/.config/alans-way/config.json`; `--output` is required.
The command validates everything before writing `SKILL.md` and `settings.json`.
A missing or invalid input exits with code 2 and leaves existing output alone.
Re-running with identical values produces identical UTF-8 files, independent of
working directory or input key order. Existing generated output is replaced.
The checked-in files here are golden examples generated from the shared example.
Regenerate your package after editing the shared config; it is a snapshot.

Give both generated files to your Grok Bot and ask it to save the skill as
`alans-way-grok-bot`, apply the persona and text voice, and review the routine
settings with you. Ask for the skill by name in conversation. Enable the private
skill for the owning Bot through Connect apps if it cannot find it.

There is **no native settings JSON importer**. [`settings.schema.json`](settings.schema.json)
defines this project's handoff format:

| Key | Meaning |
|---|---|
| `persona.name`, `.description`, `.role` | Display name, character and role from shared preferences |
| `voice.tone`, `.reply_length` | Text style and requested detail; no TTS provider selection |
| `routines` | Empty when proactivity is off; otherwise one idle check-in definition |
| `routines[].schedule` | `every_minutes`, IANA `timezone`, same-day `active_hours` (`start` inclusive, `end` exclusive) |
| `routines[].prompt` | Instructions to verify recent activity, enforce idle time and active hours, preserve pauses, and skip when evidence is unavailable |

When you request routine setup, confirm its owning Bot and conversation, then
have the Bot create or update the named native routine and verify its saved
schedule and prompt. Match by name rather than duplicating an existing routine.
When applying an off config, pause the existing Alan's Way idle check-in routine.
Loading a skill or generating files does not install, activate or pause routines.
Schedules repeat at `max(5, idle_minutes)` minutes; Grok's native minimum is five
minutes. A shorter idle preference can therefore check in later. Quiet-hours and
idle checks also run inside the prompt; if recent activity cannot be verified,
the run must skip. These are model instructions, not a Hermes scheduler or an
enforced activity observer. Keep consequential actions behind native approvals.

Grok's official [skills and routines guide](https://docs.x.ai/grok-bot/skills-routines-and-automations)
describes skill discovery, routine creation, minimum intervals and verification.
Its [settings guide](https://docs.x.ai/grok-bot/settings-and-notifications) explains
the Bot timezone. Native account behavior has not been exercised by these tests.

## Workspace connection

An existing Alan's CU MCP connection supplies workspace tools independently of
this skill. See [remote-agent setup](../docs/remote-agents.md). Generating
preferences creates no MCP connection, credentials, permissions or services.

## License

MIT License. Copyright (c) 2026 Alex Hansen. See [LICENSE](LICENSE).
