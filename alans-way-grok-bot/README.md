# Alan's Plugin for Grok Bot

Generate a self-contained Grok Bot skill and a settings handoff from the same
[shared config](../shared/README.md) used by Alan's Plugin for Hermes. Grok Bot
cannot load Hermes Python plugins.

## Install

You need Python 3.11+ for steps 1-2 and a machine running Hermes with the Alan's
Way plugin for step 5. Labels below are from Grok Bot desktop 0.78.5.

**1. Create the shared config**, without overwriting one you already have, then
edit it. From this checkout:

```sh
mkdir -p ~/.config/alans-way
cp -n shared/config.example.json ~/.config/alans-way/config.json
```

**2. Generate the package:**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r shared/requirements.txt
.venv/bin/python scripts/generate_grok_bot.py --output /tmp/alans-way-grok-bot
```

You should see `Generated SKILL.md and settings.json.` `--config` defaults to
`~/.config/alans-way/config.json`; `--output` is required. A missing or invalid
input exits with code 2 and leaves existing output alone. Output is deterministic
and replaces earlier output. It is a snapshot: after editing the config, repeat
this step and steps 3-4. The checked-in files here are golden examples generated
from the shared example.

**3. Save the skill.** In a Grok Bot chat, attach only `SKILL.md` and send:

> Save this file unchanged as a private skill named `alans-way-grok-bot`.

Do not drop the whole folder on a skill import: Grok Bot's importer makes every
text file its own skill, so `settings.json` would become a stray skill. If the
Bot can't find the skill, open **Connect apps**, select the connected count next
to the title, and enable it under **Private skills**.

Check it worked: ask *"Use the alans-way-grok-bot skill. What name and reply
length do you use?"* The answer should match your config.

**4. Apply the settings.** Attach `settings.json` and send:

> Apply this persona and voice. Review its routines with me before changing any.

Native routines are set up as described under the table below. Skip them when
`routines` is empty, unless an earlier check-in routine needs pausing.

**5. Connect the workspace tools** (`cua_alans_way_*`, `workspace_computer_*`).
The skill does not provide them. On the Hermes machine, from a checkout of this
repo, with `grok` as the example bot ID:

```sh
sh scripts/setup-remote-agent.sh --bot-id grok --bot-name "Grok Bot" --user VM_USER
sh scripts/setup-remote-agent.sh --bot-id grok --bot-name "Grok Bot" --user VM_USER --print --probe
```

The second command should end with a `Tools:` line. Then:

1. Put the computer your Bot runs commands on (its cloud computer, unless you
   enabled local commands) on your tailnet. Turn off Tailscale's SSH server on
   the Hermes machine with `tailscale set --ssh=false`, or it ignores the key
   restriction.
2. Copy the private key `~/.ssh/alans-way-remote-agent-grok` to that computer
   through the Bot's secret store. Never paste it into a chat.
3. In Grok Bot, choose **Add a custom connector**. Set **Name** to `workspace-mcp`,
   **Type** to **Command** and **Editor** to **JSON**.
4. Paste the JSON the setup command printed, replacing `HOST` with the machine's
   Tailscale name and the `-i` path with the key's location on that computer.

Check it worked: ask *"Call cua_alans_way_status and show me the result."* A JSON
status naming a host means tools are round-tripping. Full details, the HTTP
bridge and desktop approvals are in [remote-agent setup](../docs/remote-agents.md).

**Test without an account:** `tests/smoke_grok_bot.py` runs generation and real
tool calls over the printed client JSON, using a private sshd and a throwaway
Chromium. Pass `--workspace-mcp` and `--chromium` if the defaults aren't found.

## Settings handoff

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

## License

MIT License. Copyright (c) 2026 Alex Hansen. See [LICENSE](LICENSE).
