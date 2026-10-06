"""Actual advertised schema; route bindings stay operator-only."""
ACTIONS = ["status", "pause", "resume", "configure", "review", "record_task",
           "finish_task", "report_signal", "resolve", "level"]
TEXT = {"type": "string"}
PREFERENCES = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "focus": {"type": "array", "items": TEXT, "maxItems": 20},
        "ignore": {"type": "array", "items": TEXT, "maxItems": 20},
        "max_work_minutes": {"type": "integer", "minimum": 1, "maximum": 20},
        "autonomy": {"type": "string", "enum": ["read_research_draft_continue_approved"]},
    },
}
SETTINGS = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "timezone": TEXT,
        "quiet_start": {"type": "integer", "minimum": 0, "maximum": 23},
        "quiet_end": {"type": "integer", "minimum": 0, "maximum": 23},
        "max_daily_wakes": {"type": "integer", "minimum": 0, "maximum": 6},
        "max_daily_watch_wakes": {"type": "integer", "minimum": 0, "maximum": 24},
        "max_low_purpose_wakes": {"type": "integer", "minimum": 0, "maximum": 2},
        "min_interval_seconds": {"type": "integer", "minimum": 0, "maximum": 31536000},
        "min_watch_interval_seconds": {"type": "integer", "minimum": 0, "maximum": 31536000},
        "event_ttl_seconds": {"type": "integer", "minimum": 1, "maximum": 31536000},
        "max_pending": {"type": "integer", "minimum": 1, "maximum": 1024},
        "debounce_seconds": {"type": "integer", "minimum": 0, "maximum": 31536000},
        "preferences": PREFERENCES,
    },
}
TASK = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "title", "scope", "next_action", "owner", "status"],
    "properties": {**{name: TEXT for name in ["id", "title", "scope", "next_action", "owner", "native_task_id",
                                             "native_board", "next_review_at", "due_at", "notify_when",
                                             "artifact", "verification", "consent_reference", "source"]},
                   "status": {"type": "string", "enum": ["active", "waiting", "blocked", "done", "cancelled"]},
                   "kind": {"type": "string", "enum": ["watch", "loop", "sweep"]},
                   "cadence_seconds": {"type": "integer", "minimum": 300, "maximum": 604800},
                   "execution_host": {"type": "string", "enum": ["cloud", "mac"]}},
}
SCHEMA = {
    "name": "proactive_control",
    "description": "Read live proactivity status/preferences/tasks; persist explicit user controls or watch bookkeeping. record_task only PROPOSES a watch; it never runs until the user sends /watch approve <id> themselves, so tell them that exact command. On an approved watch it may only tighten (slower, pause, finish); anything wider goes back to proposed. Binding, resume, raising the level, and any change that loosens the configured limits are operator-only through /proactivity or the CLI — this tool only tightens. Resolve only after verifying the event's real outcome.",
    "parameters": {
        "type": "object", "additionalProperties": False, "required": ["action"],
        "properties": {
            "action": {"type": "string", "enum": ACTIONS}, "settings": SETTINGS, "changes": SETTINGS,
            "task": TASK, "task_id": TEXT, "event_id": TEXT, "artifact": TEXT, "verification": TEXT,
            "signal": TEXT, "resume_at": TEXT,
            "level": {"type": "string", "enum": ["quiet", "normal", "eager"]},
            "status": {"type": "string", "enum": ["done", "cancelled", "waiting", "blocked"]},
        },
    },
}
