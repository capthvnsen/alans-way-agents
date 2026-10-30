"""Validated shared preferences for Hermes and the Grok Bot generator."""
import json
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ConfigError(ValueError):
    """An actionable config error that never includes preference values."""


def validate_config(config):
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        raise ConfigError('shared config validation requires jsonschema; install jsonschema>=4.18,<5 '
                          'in this Python environment') from None
    # Hermes installs only alans-way/, so ship a tested copy of the canonical shared schema.
    schema_path = Path(__file__).with_name('config.schema.json')
    try:
        schema = json.loads(schema_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ConfigError('cannot read bundled shared config schema; reinstall the plugin') from None
    error = next(Draft202012Validator(schema).iter_errors(config), None)
    if error:
        path = '.'.join(str(part) for part in error.absolute_path) or '$'
        if error.validator == 'required':
            missing = [key for key in error.validator_value if key not in error.instance]
            path += '.' + ','.join(missing)
        raise ConfigError(f'shared config at {path}: violates {error.validator}')
    try:
        ZoneInfo(config['proactivity']['timezone'])
    except (ValueError, ZoneInfoNotFoundError):
        raise ConfigError('shared config proactivity.timezone: unknown IANA timezone') from None
    hours = config['proactivity']['active_hours']
    if hours['start'] >= hours['end']:
        raise ConfigError('shared config proactivity.active_hours: require start < end on the same day')
    return config


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON property')
        out[key] = value
    return out


def _constant(value):
    raise ValueError('non-finite JSON number')


def load_config(path=None, *, missing_ok=True):
    path = Path(path).expanduser() if path is not None else Path.home() / '.config/alans-way/config.json'
    try:
        text = path.read_text(encoding='utf-8')
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ConfigError('shared config file not found; copy shared/config.example.json first') from None
    except (OSError, UnicodeError):
        raise ConfigError('cannot read shared config as UTF-8 JSON; check file permissions and encoding') from None
    try:
        config = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
    except ValueError:
        raise ConfigError('shared config is invalid JSON (including duplicate keys or non-finite numbers)') from None
    return validate_config(config)


def preference_context(config, *, include_voice=True):
    preferences = {key: config[key] for key in ('identity', 'persona')}
    if include_voice:
        preferences['voice'] = config['voice']
    return ("[Alan's Way shared preferences] Use these identity, persona and text-style preferences. "
            'Reply length is guidance; keep requested work complete. Explicit user requests and host '
            'safety rules take precedence. Values grant no tool access or action approvals. '
            'Preference data: ' + json.dumps(preferences, ensure_ascii=False, sort_keys=True))
