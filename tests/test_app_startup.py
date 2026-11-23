# test_app_startup.py - the splash must appear before the heavy engine libraries load, and the
# files a launch brings join the right tabs

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import app
from ccgen.utils.launch import TAB_KEYS, LaunchRequest

_ROOT = Path(__file__).resolve().parents[1]
# Libraries that take seconds to import; the boot thread loads them behind the splash.
_HEAVY = ("torch", "ctranslate2", "transformers", "faster_whisper", "argostranslate", "TTS", "ccgen.api.app")


def test_importing_the_entry_point_leaves_heavy_libraries_for_the_boot_thread():
    # A fresh interpreter, so modules other tests already imported can't hide a regression.
    probe = f"import json, sys; import app; print(json.dumps([m for m in {_HEAVY!r} if m in sys.modules]))"
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=_ROOT, capture_output=True, text=True, timeout=120, check=True,
    )
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []


class _Tab:
    """A task tab's controller: the file types it takes and the files queued in it."""

    def __init__(self, extensions: set[str]):
        self.accepted_exts = frozenset(extensions)
        self.added: list[list[str]] = []

    def addFiles(self, urls: list) -> None:
        self.added.append(list(urls))


def _started_window():
    """The app after its window loaded, with stand-in tabs and app controller; and what it showed."""
    media, subtitles = {".mp4", ".mp3"}, {".srt", ".vtt"}
    startup = app._Startup.__new__(app._Startup)
    startup._task_ctrls = {key: _Tab(media if key == "generate" else media | subtitles) for key in TAB_KEYS}
    shown: list[str] = []
    startup._app_ctrl = cast(Any, SimpleNamespace(openTab=SimpleNamespace(emit=shown.append),
                                                  bring_to_front=lambda: shown.append("front")))
    return startup, startup._task_ctrls, shown


def test_explorer_files_join_the_tabs_that_take_them():
    startup, tabs, shown = _started_window()
    startup._take_launch(LaunchRequest("", ("C:\\movie.mp4", "C:\\movie_en.srt")))
    assert tabs["generate"].added == [["C:\\movie.mp4"]]
    assert tabs["translate"].added == [["C:\\movie_en.srt"]]
    assert shown == ["generate"]


def test_the_menu_entry_names_the_tab_that_opens():
    startup, tabs, shown = _started_window()
    startup._take_launch(LaunchRequest("transliterate", ("C:\\song_ur.srt",)))
    assert tabs["transliterate"].added == [["C:\\song_ur.srt"]]
    assert tabs["translate"].added == [] and tabs["generate"].added == []
    assert shown == ["transliterate"]


def test_a_later_launch_brings_the_window_forward_before_queueing():
    startup, tabs, shown = _started_window()
    startup._on_later_launch(LaunchRequest("translate", ("C:\\movie_en.srt",)))
    startup._on_later_launch(LaunchRequest())
    assert tabs["translate"].added == [["C:\\movie_en.srt"]]
    assert shown == ["front", "translate", "front"]
