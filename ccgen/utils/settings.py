# settings.py - settings persistence: load, save, and merge

import json
import logging
import os
import sys
from typing import Any

from ccgen.config.defaults import AUTO, SETTINGS_VERSION, get_default_settings

_log = logging.getLogger(__name__)

# Settings files before version 2 saved every value, defaults included, so a model choice still
# at its old default there was never picked by hand; it becomes Automatic, which follows the
# performance profile. (section, key) -> the old default.
_OLD_MODEL_DEFAULTS = {
    ("model", "name"): "base",
    ("translation", "engine"): "opus_mt",
    ("transliteration", "engine"): "rule",
    ("dubbing", "mode"): "xtts",
}


def get_settings_file() -> str:
    """Return path to settings.json, creating the app data dir if needed."""
    try:
        if getattr(sys, "frozen", False):
            appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
            data_dir = os.path.join(appdata, "CC-Gen-Ultimate")
            os.makedirs(data_dir, exist_ok=True)
            return os.path.join(data_dir, "settings.json")
    except Exception:
        pass
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "settings.json")


def load_settings() -> dict[str, Any]:
    """Load settings from disk, merging with defaults for any missing keys."""
    path = get_settings_file()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                user = migrate_settings(json.load(fh))
            defaults = get_default_settings()
            return merge_settings(defaults, drop_unknown_keys(user, defaults))
        except Exception:
            _log.warning("Settings file %s is unreadable; using defaults", path, exc_info=True)
    return get_default_settings()


def save_settings(settings: dict[str, Any]) -> bool:
    """Persist a settings dictionary to disk atomically. Returns True on success.

    Writes to a temporary file in the same folder and swaps it in, so a crash or a full disk
    mid-write can never leave a truncated settings.json behind.
    """
    path = get_settings_file()
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
        os.replace(tmp_path, path)
        return True
    except Exception:
        _log.error("Failed to save settings to %s", path, exc_info=True)
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


def migrate_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Bring a settings file written by an older version up to the current layout."""
    version = settings.get("version")
    if not isinstance(version, int) or version < 2:
        for (section, key), old_default in _OLD_MODEL_DEFAULTS.items():
            values = settings.get(section)
            if isinstance(values, dict) and values.get(key) == old_default:
                values[key] = AUTO
    settings["version"] = SETTINGS_VERSION
    return settings


def merge_settings(
    defaults: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Deep-merge overrides onto defaults, preserving all nested default keys.

    Rebuilds every nested dict fresh (even branches `overrides` never touches), so the
    result never aliases a mutable nested dict from either `defaults` or `overrides`.
    """
    result = {
        key: (merge_settings(value, {}) if isinstance(value, dict) else value)
        for key, value in defaults.items()
    }
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_settings(result[key], value)
        else:
            result[key] = value
    return result


def drop_unknown_keys(settings: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Return `settings` without the keys the defaults no longer define.

    Settings files written by older versions keep options that were since removed (such as the
    old per-stage "enabled" switches); dropping them keeps stale values out of the UI and API.
    """
    result: dict[str, Any] = {}
    for key, value in settings.items():
        if key not in defaults:
            continue
        if isinstance(defaults[key], dict):
            if isinstance(value, dict):
                result[key] = drop_unknown_keys(value, defaults[key])
        else:
            result[key] = value
    return result
