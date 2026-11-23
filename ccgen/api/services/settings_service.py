# settings_service.py - serialized read-modify-write access to persisted settings, for the API and
# the command line (`ccgen settings`)

import threading
from typing import Any

from ccgen.config.defaults import get_default_settings
from ccgen.config.options import setting_choices, setting_ranges
from ccgen.utils.logging import configure_from_settings
from ccgen.utils.settings import load_settings, save_settings

# FastAPI runs sync route handlers on a thread pool, so two saves arriving together would
# otherwise both load the old file and the later write would silently drop the earlier change.
_lock = threading.Lock()


def get_all() -> dict[str, Any]:
    """Return the full persisted settings dictionary."""
    with _lock:
        return load_settings()


def reset_defaults() -> dict[str, Any]:
    """Overwrite persisted settings with factory defaults and return them."""
    with _lock:
        defaults = get_default_settings()
        _persist(defaults)
        configure_from_settings(defaults)
        return defaults


def set_one(key: str, value: Any) -> dict[str, Any]:
    """Set a dot-separated settings key, persist it, and return the updated dictionary."""
    return set_many({key: value})


def set_many(values: dict[str, Any]) -> dict[str, Any]:
    """Set several dot-separated keys in one atomic save and return the updated dictionary."""
    with _lock:
        settings = load_settings()
        for key, value in values.items():
            _assign(settings, key, value)
        _persist(settings)
        if any(key.startswith("logging.") for key in values):
            configure_from_settings(settings)
        return settings


def _assign(settings: dict[str, Any], key: str, value: Any) -> None:
    """Write `value` at a dot-separated path the defaults define.

    Raises ValueError for any other key: loading drops keys the defaults don't define, so
    accepting one here would report a save that silently disappears on the next read.
    """
    parts = key.split(".")
    node, defaults = settings, get_default_settings()
    for part in parts[:-1]:
        defaults = defaults.get(part) if isinstance(defaults, dict) else None
        if not isinstance(defaults, dict):
            raise ValueError(f"Unknown setting: {key}")
        child = node.get(part)
        if not isinstance(child, dict):
            child = node[part] = {}
        node = child
    if parts[-1] not in defaults or isinstance(defaults[parts[-1]], dict):
        raise ValueError(f"Unknown setting: {key}")
    node[parts[-1]] = value


def _persist(settings: dict[str, Any]) -> None:
    """Save settings, raising so the route reports a failed write instead of a silent success."""
    if not save_settings(settings):
        raise OSError("Could not write the settings file.")


def flatten(settings: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Every setting by its dot-separated key ({"model.name": "auto", ...}), "version" left out."""
    flat: dict[str, Any] = {}
    for key, value in settings.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(flatten(value, f"{name}."))
        elif name != "version":
            flat[name] = value
    return flat


def parse_value(key: str, text: str) -> Any:
    """Turn the text typed for a setting into its value, checked against what the setting accepts.

    Raises ValueError in plain words for an unknown key, a value of the wrong kind, or one the
    setting doesn't offer. A setting whose default is empty (the spoken language) takes "auto" or ""
    for "detect it".
    """
    defaults = flatten(get_default_settings())
    if key not in defaults:
        raise ValueError(f"Unknown setting: {key}. `ccgen settings list` shows every setting.")
    default = defaults[key]
    text = text.strip()
    if isinstance(default, bool):
        value: Any = _parse_bool(key, text)
    elif isinstance(default, int):
        value = _parse_number(key, text, int)
    elif isinstance(default, float):
        value = _parse_number(key, text, float)
    elif default is None:
        value = None if text.lower() in ("", "auto", "none") else text
    else:
        value = text
    choices = setting_choices().get(key)
    if choices is not None and value not in choices and not (value is None and None in choices):
        shown = ", ".join("auto" if c is None else str(c) if c else '""' for c in choices)
        raise ValueError(f"{key} can't be {text!s}. Choose one of: {shown}.")
    limits = setting_ranges().get(key)
    if limits is not None and isinstance(value, (int, float)) and not limits[0] <= value <= limits[1]:
        raise ValueError(f"{key} must be between {limits[0]:g} and {limits[1]:g}.")
    return value


def _parse_bool(key: str, text: str) -> bool:
    lowered = text.lower()
    if lowered in ("true", "yes", "on", "1"):
        return True
    if lowered in ("false", "no", "off", "0"):
        return False
    raise ValueError(f"{key} is true or false.")


def _parse_number(key: str, text: str, kind: type) -> Any:
    try:
        return kind(text)
    except ValueError:
        raise ValueError(f"{key} is a {'whole ' if kind is int else ''}number.") from None
