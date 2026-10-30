#!/usr/bin/env python3
"""Render a validated shared config into a standalone Grok Bot skill and settings."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'alans-way'))
from shared_config import ConfigError, load_config, preference_context, validate_config


DESCRIPTION = "Apply Alan's Way persona and voice preferences in conversation, or run an approved proactive check-in routine."


def render(config):
    validate_config(config)
    proactivity = config['proactivity']
    hours = proactivity['active_hours']
    prompt = (
        "Use the alans-way-grok-bot skill. Check this routine's owning conversation only. "
        f"Run only between {hours['start']} (inclusive) and {hours['end']} (exclusive) "
        f"in {proactivity['timezone']}, after at least {proactivity['idle_minutes']} minutes of quiet "
        'since the most recent user message, assistant reply, or earlier check-in. '
        'Skip while another task or reply is in progress. Preserve operator pauses. '
        'If recent activity, local time, or the owning conversation cannot be verified, skip this run. '
        'Otherwise offer one useful next step grounded in a current open thread, in 1-3 short sentences. '
        'If nothing is worth attention, produce no check-in. '
        'Ask before sending external messages, spending money, deleting, publishing or changing production.'
    )
    routines = []
    if proactivity['enabled']:
        routines.append({
            'name': "Alan's Way idle check-in",
            'schedule': {
                # shortcut: Grok routines have a five-minute minimum; shorter idle preferences wait for the next run.
                'every_minutes': max(5, proactivity['idle_minutes']),
                'timezone': proactivity['timezone'],
                'active_hours': hours,
            },
            'prompt': prompt,
        })
    settings = {
        'persona': {
            'name': config['identity']['name'],
            'description': config['persona']['description'],
            'role': config['identity']['role'],
        },
        'voice': config['voice'],
        'routines': routines,
    }
    behavior = ("On a scheduled routine, follow its schedule and prompt in the adjacent settings.json. "
                "The routine must belong to an operator-approved conversation; preserve any pause."
                if routines else
                "Proactivity is disabled: initiate no unsolicited check-ins through this skill.")
    skill = f"""---
name: alans-way-grok-bot
description: {DESCRIPTION}
---

# Alan's Plugin for Grok Bot

Use this skill for Alan's Way conversation preferences and approved check-in routines.

{preference_context(config)}

{behavior}

Apply the adjacent settings.json persona and voice as preferences in Grok Bot.
Its JSON is a documented handoff format, not a native settings importer.
Create or update a native routine only when the operator requests it, after confirming
its owning Bot, conversation, schedule and timezone. Match an existing routine by name
before creating another, preserve pauses, and verify its saved schedule and prompt.
When settings.json has no routines, pause any existing Alan's Way idle check-in routine
as part of an operator-requested settings update. Leave unrelated routines alone.
If native scheduling or recent conversation activity is unavailable, report the limitation
and skip check-ins. Loading this skill never creates a routine or grants permissions.
For an interactive reply, finish the user's requested work and report the verified result.
"""
    return skill, json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', help='Shared JSON (default: ~/.config/alans-way/config.json)')
    parser.add_argument('--output', required=True, type=Path, help='Directory for SKILL.md and settings.json')
    args = parser.parse_args(argv)
    try:
        skill, settings = render(load_config(args.config, missing_ok=False))
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / 'SKILL.md').write_text(skill, encoding='utf-8', newline='\n')
        (args.output / 'settings.json').write_text(settings, encoding='utf-8', newline='\n')
    except ConfigError as error:
        print(error, file=sys.stderr)
        return 2
    except OSError:
        print('cannot write Grok Bot output; check the output directory and permissions', file=sys.stderr)
        return 2
    print('Generated SKILL.md and settings.json.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
