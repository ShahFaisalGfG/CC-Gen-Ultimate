# launch.py - what one start of the app asks for, and which tab each of its files joins
#
# Explorer's menu, "Open with", a shortcut, or a drop on the exe start CC-Gen-Ultimate with file
# paths, and the menu names the tab first (`--tab translate`). A later start hands its request to
# the open window (single_instance.py), which routes it the same way as the first start's own.
#
# Standard library only: the routing is a pure function of the request and the extensions each
# tab takes, which the tab controllers supply.

from __future__ import annotations

import json
import logging
import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

TAB_KEYS = ("generate", "translate", "transliterate", "dub", "workflow")
# Where a file goes when the launch names no tab, or a tab that can't take it: the first of these
# that takes it (video and audio make subtitles, subtitle files get translated).
DEFAULT_TABS = ("generate", "translate")
_TAB_FLAG = "--tab"

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LaunchRequest:
    """One start of the app: the tab it names ("" for none) and the paths it was given."""

    tab: str = ""
    paths: tuple[str, ...] = ()

    def encode(self) -> bytes:
        """The request as one line of JSON (json.dumps escapes any newline inside a path)."""
        return json.dumps({"tab": self.tab, "paths": list(self.paths)}).encode("utf-8") + b"\n"

    @classmethod
    def decode(cls, line: bytes) -> LaunchRequest:
        """Parse a line written by encode(); raises ValueError for anything else.

        A tab this copy doesn't know becomes "", so the files still join the queue.
        """
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise ValueError("the message is not a JSON object")
        tab, paths = payload.get("tab", ""), payload.get("paths", [])
        if not (isinstance(tab, str) and isinstance(paths, list) and all(isinstance(p, str) for p in paths)):
            raise ValueError("the message has fields of the wrong type")
        return cls(tab if tab in TAB_KEYS else "", tuple(paths))


@dataclass(frozen=True)
class LaunchPlan:
    """Where a launch's files go: each tab's share in launch order, and the tab to show ("" for none)."""

    tab: str
    files: dict[str, tuple[str, ...]]


def parse_arguments(arguments: Sequence[str]) -> LaunchRequest:
    """The request in a command line (without the program): `--tab KEY` and the paths that exist.

    Paths become absolute, since the open window that may take them runs in another folder.
    """
    tab = ""
    paths: list[str] = []
    values = iter(arguments)
    for argument in values:
        if argument == _TAB_FLAG or argument.startswith(_TAB_FLAG + "="):
            name = argument.partition("=")[2] if "=" in argument else next(values, "")
            tab = _known_tab(name) or tab
        elif os.path.exists(argument):
            paths.append(os.path.abspath(argument))
        else:
            _log.info("Ignored a command-line argument that isn't an existing file or folder: %s", argument)
    return LaunchRequest(tab, tuple(paths))


def plan_launch(request: LaunchRequest, accepted: Mapping[str, Collection[str]]) -> LaunchPlan:
    """Route each path to the named tab when it takes the file type, else to its default tab.

    `accepted` maps tab keys to the extensions (".mp4") each takes. Folders and file types no tab
    takes go to the named tab, or Generate, whose queue scans folders and says what it skipped.
    The tab shown is the named one when it got files or there were none, else the first file's.
    """
    order = ((request.tab,) if request.tab else ()) + DEFAULT_TABS
    fallback = request.tab or DEFAULT_TABS[0]
    routes: dict[str, list[str]] = {}
    for path in request.paths:
        extension = os.path.splitext(path)[1].lower()
        key = next((tab for tab in order if extension in accepted.get(tab, ())), fallback)
        routes.setdefault(key, []).append(path)
    if request.tab and (request.tab in routes or not routes):
        tab = request.tab
    else:
        tab = next(iter(routes), "")
    return LaunchPlan(tab, {key: tuple(paths) for key, paths in routes.items()})


def _known_tab(name: str) -> str:
    """The tab key `name` names (any case), or "" (logged) when no tab has that name."""
    key = name.strip().lower()
    if key in TAB_KEYS:
        return key
    _log.warning("Ignored --tab %r; the tabs are %s", name, ", ".join(TAB_KEYS))
    return ""
