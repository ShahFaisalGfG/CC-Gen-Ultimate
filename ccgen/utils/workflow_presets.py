# workflow_presets.py - the Workflow tab's saved step lists, kept beside settings.json
#
# workflows.json holds the steps the tab last had (so a restart doesn't reset them) and the
# workflows the user saved by name. `ccgen workflow --preset NAME` runs a saved one. settings.json
# only keeps keys its defaults define, so free-form names live in this file of their own.
#
# Steps are stored as the Workflow tab builds them ({"kind": "translate", "input": "step:0", ...}).
# Reading one fills in options a newer version added and drops ones it no longer knows, so a file
# written by another version still loads.

import json
import logging
import os
from typing import Any, Optional

from ccgen.config.defaults import get_default_settings
from ccgen.core.jobs import STEP_OPTIONS
from ccgen.core.tasks.configs import INPUT_SOURCE
from ccgen.utils.settings import get_settings_file

_log = logging.getLogger(__name__)

FILE_NAME = "workflows.json"
MAX_NAME_LENGTH = 60
_VERSION = 1


def store_path() -> str:
    """Where the saved workflows are: workflows.json beside settings.json."""
    return os.path.join(os.path.dirname(get_settings_file()), FILE_NAME)


def load_store(path: Optional[str] = None) -> dict[str, Any]:
    """The saved workflows: {"last": [steps], "presets": {name: [steps]}}; empty when none are saved."""
    path = path or store_path()
    empty: dict[str, Any] = {"last": [], "presets": {}}
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return empty
    except (OSError, ValueError) as error:
        _log.warning("Saved workflows in %s couldn't be read: %r", path, error)
        return empty
    if not isinstance(raw, dict):
        return empty
    presets = raw.get("presets")
    if not isinstance(presets, dict):
        presets = {}
    return {
        "last": clean_steps(raw.get("last")),
        "presets": {str(name): steps for name, value in presets.items() if (steps := clean_steps(value))},
    }


def save_store(store: dict[str, Any], path: Optional[str] = None) -> None:
    """Write the saved workflows atomically. Raises OSError when the file can't be written."""
    path = path or store_path()
    tmp = f"{path}.tmp"
    data = {"version": _VERSION, "last": store.get("last", []), "presets": store.get("presets", {})}
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def preset_names(path: Optional[str] = None) -> list[str]:
    """Names of the saved workflows, in alphabetical order."""
    return sorted(load_store(path)["presets"], key=str.casefold)


def get_preset(name: str, path: Optional[str] = None) -> Optional[list[dict[str, Any]]]:
    """The steps saved under `name` (any case), or None."""
    presets = load_store(path)["presets"]
    match = next((key for key in presets if key.casefold() == name.strip().casefold()), None)
    return presets[match] if match is not None else None


def save_preset(name: str, steps: list[dict[str, Any]], path: Optional[str] = None) -> str:
    """Save `steps` under `name`, replacing a workflow of the same name; returns the name used.

    Raises ValueError for an empty or overlong name, or no steps, and OSError when it can't be written.
    """
    name = " ".join(name.split())
    if not name:
        raise ValueError("Type a name for the workflow.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"Use a name of {MAX_NAME_LENGTH} characters or fewer.")
    cleaned = clean_steps(steps)
    if not cleaned:
        raise ValueError("Add at least one step to the workflow.")
    store = load_store(path)
    store["presets"] = {key: value for key, value in store["presets"].items() if key.casefold() != name.casefold()}
    store["presets"][name] = cleaned
    save_store(store, path)
    return name


def delete_preset(name: str, path: Optional[str] = None) -> bool:
    """Remove a saved workflow; False when there was none of that name."""
    store = load_store(path)
    kept = {key: value for key, value in store["presets"].items() if key.casefold() != name.strip().casefold()}
    if len(kept) == len(store["presets"]):
        return False
    store["presets"] = kept
    save_store(store, path)
    return True


def save_last(steps: list[dict[str, Any]], path: Optional[str] = None) -> None:
    """Remember the tab's current steps for the next launch; a failed write is only logged."""
    try:
        store = load_store(path)
        store["last"] = clean_steps(steps)
        save_store(store, path)
    except OSError as error:
        _log.warning("The workflow steps couldn't be saved: %r", error)


def clean_steps(value: Any, settings: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Valid steps from saved data: known kinds, every current option (defaults where missing), and
    inputs that point at an earlier step or the queued file. Anything else is dropped."""
    if not isinstance(value, list):
        return []
    defaults = settings if settings is not None else get_default_settings()
    steps: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict) or raw.get("kind") not in STEP_OPTIONS:
            continue
        kind = raw["kind"]
        step: dict[str, Any] = {"kind": kind, **STEP_OPTIONS[kind](defaults)}
        if kind != "generate":
            step["input"] = INPUT_SOURCE
        if kind != "dub":
            step["write_output"] = True
        for key in step:
            if key != "kind" and key in raw and isinstance(raw[key], type(step[key])):
                step[key] = raw[key]
        if "alternate_target" in raw and isinstance(raw["alternate_target"], str) and kind == "transliterate":
            step["alternate_target"] = raw["alternate_target"]
        steps.append(step)
    for index, step in enumerate(steps):
        reference = step.get("input", INPUT_SOURCE)
        if reference != INPUT_SOURCE and not _earlier_text_step(reference, index, steps):
            step["input"] = INPUT_SOURCE
    return steps


def _earlier_text_step(reference: str, index: int, steps: list[dict[str, Any]]) -> bool:
    """True when "step:N" names an earlier step that produces text."""
    if not reference.startswith("step:") or not reference[5:].isdigit():
        return False
    source = int(reference[5:])
    return source < index and steps[source]["kind"] != "dub"
