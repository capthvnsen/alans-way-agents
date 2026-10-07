"""Parsers for the operator's plain-language knobs: quiet hours and snooze."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import re

QUIET_USAGE = "Use /proactivity quiet 22-8 (start and end hour, 0 to 23) or /proactivity quiet off."
SNOOZE_USAGE = ("Use /proactivity snooze 3d (or 2h, 30m), /proactivity snooze until 2026-12-01 08:00 "
                "(or until 08:00), or /proactivity snooze off.")


def parse_quiet(value):
    """(start, end) hours; equal endpoints switch the quiet window off."""
    text = (value or "").strip().lower()
    if text == "off":
        return 0, 0
    match = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", text)
    if not match or any(int(group) > 23 for group in match.groups()):
        raise ValueError(QUIET_USAGE)
    return int(match[1]), int(match[2])


def parse_snooze(value, tz, now=None):
    """Aware ISO timestamp for '3d', '2h', '30m', 'until <time>'; ValueError with usage otherwise."""
    now = now or datetime.now(timezone.utc)
    zone = ZoneInfo(tz)
    text = (value or "").strip()
    match = re.fullmatch(r"(\d{1,4})\s*([mhd])", text.lower())
    if match and int(match[1]) > 0:
        unit = {"m": "minutes", "h": "hours", "d": "days"}[match[2]]
        return (now + timedelta(**{unit: int(match[1])})).isoformat()
    if text.lower().startswith("until "):
        raw = text[6:].strip()
        try:
            if re.fullmatch(r"\d{1,2}:\d{2}", raw):
                hour, minute = map(int, raw.split(":"))
                local = now.astimezone(zone).replace(hour=hour, minute=minute, second=0, microsecond=0)
                moment = local if local > now else local + timedelta(days=1)
            else:
                moment = datetime.fromisoformat(raw.replace(" ", "T", 1))
                if moment.tzinfo is None:
                    moment = moment.replace(tzinfo=zone)
        except ValueError:
            raise ValueError(SNOOZE_USAGE) from None
        if moment > now:
            return moment.isoformat()
    raise ValueError(SNOOZE_USAGE)
