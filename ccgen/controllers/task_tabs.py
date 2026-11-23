# task_tabs.py - the Generate, Translate, Transliterate, and Dub tabs
#
# Each tab's options and the job it builds for a queued file come from ccgen/core/jobs.py, which
# the command line uses too, so a file runs the same way from either. The Workflow tab reuses each
# tab's step_options() for its step cards, so a step and its tab start from the same preferences.

import os
from typing import Any

from PySide6.QtCore import Slot

from ccgen.config.capabilities import language_from_filename
from ccgen.config.defaults import AUTO, DubbingDefaults
from ccgen.config.voices import CLONING_ENGINES, voices_for
from ccgen.controllers.task_ctrl import TaskController
from ccgen.core import jobs
from ccgen.core.jobs import MEDIA_EXTS, SUBTITLE_EXTS, VOICE_RESETS

__all__ = [
    "DubController", "GenerateController", "MEDIA_EXTS", "TranslateController", "TransliterateController",
    "VOICE_RESETS",
]


class GenerateController(TaskController):
    """Generate tab: transcribe video and audio files into subtitles."""

    task_key = "generate"
    accepted_exts = jobs.TASK_EXTS["generate"]
    file_noun = jobs.TASK_NOUNS["generate"]
    sample_input = "example.mp4"
    step_options = staticmethod(jobs.generate_step_options)
    step_body = staticmethod(jobs.generate_step_body)


class TranslateController(TaskController):
    """Translate tab: translate subtitles, or the speech of videos and audio, into another language.

    A subtitle's language comes from its name or from the queue row's language picker; a media
    file's spoken language is the tab's Spoken language option ("" detects it).
    """

    task_key = "translate"
    accepted_exts = jobs.TASK_EXTS["translate"]
    file_noun = jobs.TASK_NOUNS["translate"]
    sample_input = "example.mp4"
    step_options = staticmethod(jobs.translate_step_options)


class TransliterateController(TaskController):
    """Transliterate tab: rewrite subtitles, or the speech of videos and audio, in another script.

    Media is transcribed first, and its transcript is in the native script of the language
    spoken, so it always converts from that script (and the other way when it is already in the
    target script). With the source script on Automatic, a subtitle converts from the script of its
    language (from its name or the row's picker).
    """

    task_key = "transliterate"
    accepted_exts = jobs.TASK_EXTS["transliterate"]
    file_noun = jobs.TASK_NOUNS["transliterate"]
    sample_input = "example.srt"
    step_options = staticmethod(jobs.transliterate_step_options)


class DubController(TaskController):
    """Dub tab: speak videos, audio, or subtitles in a chosen language.

    A video or audio file alone is transcribed, translated into the Dub into language when it
    is spoken in another, and dubbed. Subtitles added alongside their media are paired by name
    (movie.mp4 + movie_es.srt) and spoken instead of a transcript, translated when needed. A
    subtitle on its own becomes a separate WAV file.
    """

    task_key = "dub"
    accepted_exts = jobs.TASK_EXTS["dub"]
    file_noun = jobs.TASK_NOUNS["dub"]
    sample_input = "example.mp4"
    # A chosen voice belongs to one engine and one language.
    option_resets = VOICE_RESETS
    step_options = staticmethod(jobs.dub_step_options)

    def add_paths(self, paths: list[str]) -> None:
        """Add media first, then pair each subtitle with media of the same name when possible."""
        media, companions, unpaired = jobs.pair_for_dub(paths, self._file_model.getPaths())
        self._file_model.addFiles(media)
        for partner, subtitle in companions.items():
            self._file_model.set_companion(partner, subtitle, language_from_filename(subtitle))
        self._file_model.addFiles(unpaired)

    def _on_scan_batch(self, entries: list) -> None:
        """Pair scanned subtitles with their media, as for dropped files."""
        self.add_paths([path for path, _size in entries])

    @Slot(list, str, list)
    def receiveFiles(self, paths: list, source: str, languages: list) -> None:
        """Take files from another tab, pairing a subtitle with the media it was made from."""
        known = dict(zip(paths, languages))
        subtitles = [p for p in paths if jobs.ext_of(p) in SUBTITLE_EXTS]
        if subtitles and source and jobs.ext_of(source) in MEDIA_EXTS:
            self._file_model.addFiles([source])
            self._file_model.set_companion(source, subtitles[0], str(known.get(subtitles[0]) or ""))
            self.notice.emit(f"{os.path.basename(source)} will speak {os.path.basename(subtitles[0])}.")
            return
        super().receiveFiles(paths, source, languages)

    @Slot(str, str, result=list)
    def voiceOptions(self, mode: str, language: str) -> list:
        """Voices the mode offers for a language, after the automatic choice."""
        items: list[dict[str, Any]] = [{"label": "Best voice for the language", "code": DubbingDefaults.VOICE_AUTO}]
        if mode != AUTO and mode not in CLONING_ENGINES and language != DubbingDefaults.LANGUAGE_AUTO:
            items += [{"label": v.label, "code": v.key} for v in voices_for(mode, language)]
        return items
