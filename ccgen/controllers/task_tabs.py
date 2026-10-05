# task_tabs.py - the Generate, Translate, Transliterate, and Dub tabs' options and job bodies
#
# Each tab's task-specific options come from step_options(), which the Workflow tab reuses for
# its step cards, so a step and its tab always start from the same saved preferences.

import os
from typing import Any, Optional

from PySide6.QtCore import Slot

from ccgen.config.capabilities import language_from_filename
from ccgen.config.defaults import (
    ComputeDefaults,
    DubbingDefaults,
    ModelDefaults,
    TranscriptionDefaults,
    TranslationDefaults,
    TransliterationDefaults,
)
from ccgen.config.translation_models import ENGINE_NLLB, NLLB_TERMS_SETTING
from ccgen.config.voices import ENGINE_XTTS, voices_for
from ccgen.controllers.task_ctrl import (
    TaskController,
    subtitle_output_body,
    subtitle_output_from_settings,
)
from ccgen.core.tasks.outputs import output_base
from ccgen.models.file_model import AUDIO_EXTS, SUBTITLE_EXTS, VIDEO_EXTS

MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
# A Kokoro or Piper voice belongs to one engine and one language, so it resets with either.
VOICE_RESETS: dict[str, dict[str, Any]] = {
    "mode": {"voice": DubbingDefaults.VOICE_AUTO},
    "language": {"voice": DubbingDefaults.VOICE_AUTO},
}


class GenerateController(TaskController):
    """Generate tab: transcribe video and audio files into subtitles."""

    task_key = "generate"
    accepted_exts = MEDIA_EXTS
    file_noun = "video or audio file"
    sample_input = "example.mp4"

    @staticmethod
    def step_options(settings: dict[str, Any]) -> dict[str, Any]:
        """Transcription options from saved preferences ("" language means auto-detect)."""
        model = settings.get("model", {})
        transcription = settings.get("transcription", {})
        return {
            "model_name": model.get("name", ModelDefaults.DEFAULT_MODEL),
            "device": model.get("device", ComputeDefaults.DEFAULT_DEVICE),
            "compute_type": model.get("compute_type", ComputeDefaults.DEFAULT_COMPUTE_TYPE),
            "language": transcription.get("language") or "",
            "beam_size": int(transcription.get("beam_size", TranscriptionDefaults.BEAM_SIZE)),
            "vad_filter": bool(transcription.get("vad_filter", TranscriptionDefaults.VAD_FILTER)),
        }

    @staticmethod
    def step_body(options: dict[str, Any]) -> dict[str, Any]:
        """Job fields for the transcription options."""
        return {
            "model_name": options["model_name"],
            "device": options["device"],
            "compute_type": options["compute_type"],
            "language": options["language"] or None,
            "beam_size": int(options["beam_size"]),
            "vad_filter": bool(options["vad_filter"]),
        }

    def initial_options(self) -> dict[str, Any]:
        return self.options_from_settings({})

    def options_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {**self.step_options(settings), **subtitle_output_from_settings(settings)}

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        return {
            "task": self.task_key,
            "input_path": item["path"],
            **subtitle_output_body(self._options, item["path"]),
            **self.step_body(self._options),
        }


class TranslateController(TaskController):
    """Translate tab: translate subtitle files into another language."""

    task_key = "translate"
    accepted_exts = SUBTITLE_EXTS
    file_noun = "subtitle file"
    sample_input = "example.srt"

    @staticmethod
    def step_options(settings: dict[str, Any]) -> dict[str, Any]:
        """Translation options from saved preferences ("auto" source reads each file's language)."""
        translation = settings.get("translation", {})
        return {
            "source_lang": translation.get("source_lang") or TranslationDefaults.DEFAULT_SOURCE_LANG,
            "target_lang": translation.get("target_lang", TranslationDefaults.DEFAULT_TARGET_LANG),
            "engine": translation.get("engine", TranslationDefaults.DEFAULT_ENGINE),
            "meaning_check": bool(translation.get("meaning_check", TranslationDefaults.MEANING_CHECK)),
        }

    def initial_options(self) -> dict[str, Any]:
        return self.options_from_settings({})

    def options_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {**self.step_options(settings), **subtitle_output_from_settings(settings)}

    def extra_blocker(self) -> str:
        if self._options["engine"] == ENGINE_NLLB and not nllb_terms_accepted(self._saved_settings):
            return NLLB_TERMS_BLOCKER
        return ""

    def queue_blocker(self, items: list[dict[str, Any]]) -> str:
        unknown = next((i for i in items if not i.get("language")), None)
        if self._options["source_lang"] == "auto" and unknown is not None:
            return (
                f"{os.path.basename(unknown['path'])} has no language in its name. Choose the language "
                "to translate from, or rename it with a suffix such as movie_en.srt."
            )
        return ""

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        opts = self._options
        # "Detect" uses the language each file is known to be in: from its name or from the tab
        # that produced it (queue_blocker stops a run while any file has neither).
        source = opts["source_lang"]
        if source == "auto" and item.get("language"):
            source = item["language"]
        return {
            "task": self.task_key,
            "input_path": item["path"],
            **subtitle_output_body(opts, item["path"]),
            "source_lang": source,
            "target_lang": opts["target_lang"],
            "engine": opts["engine"],
            "meaning_check": bool(opts["meaning_check"]),
        }


class TransliterateController(TaskController):
    """Transliterate tab: rewrite subtitle files in another script."""

    task_key = "transliterate"
    accepted_exts = SUBTITLE_EXTS
    file_noun = "subtitle file"
    sample_input = "example.srt"

    @staticmethod
    def step_options(settings: dict[str, Any]) -> dict[str, Any]:
        """Transliteration options from saved preferences."""
        translit = settings.get("transliteration", {})
        return {
            "source_scheme": translit.get("source", TransliterationDefaults.DEFAULT_SOURCE),
            "target_scheme": translit.get("target", TransliterationDefaults.DEFAULT_TARGET),
            "engine": translit.get("engine", TransliterationDefaults.DEFAULT_ENGINE),
        }

    def initial_options(self) -> dict[str, Any]:
        return self.options_from_settings({})

    def options_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {**self.step_options(settings), **subtitle_output_from_settings(settings)}

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        opts = self._options
        return {
            "task": self.task_key,
            "input_path": item["path"],
            **subtitle_output_body(opts, item["path"]),
            "source_scheme": opts["source_scheme"],
            "target_scheme": opts["target_scheme"],
            "engine": opts["engine"],
        }


class DubController(TaskController):
    """Dub tab: speak subtitles and add the speech to their video or audio as a new track.

    Each media row speaks one subtitle file (its "companion"). Subtitles added alongside their
    media are paired automatically by name (movie.mp4 + movie_es.srt); a media row without one
    looks for a matching subtitle next to it when its turn comes. A subtitle on its own becomes
    a separate WAV file.
    """

    task_key = "dub"
    accepted_exts = MEDIA_EXTS | SUBTITLE_EXTS
    file_noun = "video, audio, or subtitle file"
    sample_input = "example.mp4"
    # A chosen voice belongs to one engine and one language.
    option_resets = VOICE_RESETS

    @staticmethod
    def step_options(settings: dict[str, Any]) -> dict[str, Any]:
        """Dubbing options from saved preferences."""
        dubbing = settings.get("dubbing", {})
        return {
            "language": DubbingDefaults.LANGUAGE_AUTO,
            "mode": dubbing.get("mode", DubbingDefaults.DEFAULT_MODE),
            "voice": DubbingDefaults.VOICE_AUTO,
            "speakers": dubbing.get("speakers", DubbingDefaults.DEFAULT_SPEAKERS),
            "max_speedup": float(dubbing.get("max_speedup", DubbingDefaults.MAX_SPEEDUP)),
            "output": dubbing.get("output", DubbingDefaults.DEFAULT_OUTPUT),
            "default_track": bool(dubbing.get("default_track", DubbingDefaults.DEFAULT_TRACK)),
            "device": dubbing.get("device", DubbingDefaults.DEVICE_AUTO),
            "script_bridge": bool(dubbing.get("script_bridge", DubbingDefaults.SCRIPT_BRIDGE)),
        }

    def initial_options(self) -> dict[str, Any]:
        return self.options_from_settings({})

    def options_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {**self.step_options(settings), "output_dir": settings.get("output", {}).get("directory") or ""}

    def add_paths(self, paths: list[str]) -> None:
        """Add media first, then pair each subtitle with media of the same name when possible."""
        media = [p for p in paths if _ext(p) in MEDIA_EXTS]
        subtitles = [p for p in paths if _ext(p) in SUBTITLE_EXTS]
        self._file_model.addFiles(media)
        unpaired = []
        for subtitle in subtitles:
            partner = _same_name(subtitle, media + self._file_model.getPaths()) or _sibling_media(subtitle)
            if partner is None:
                unpaired.append(subtitle)
                continue
            self._file_model.addFiles([partner])
            self._file_model.set_companion(partner, subtitle, language_from_filename(subtitle))
        self._file_model.addFiles(unpaired)

    def _on_scan_batch(self, entries: list) -> None:
        """Pair scanned subtitles with their media, as for dropped files."""
        self.add_paths([path for path, _size in entries])

    @Slot(list, str, list)
    def receiveFiles(self, paths: list, source: str, languages: list) -> None:
        """Take subtitles from another tab and pair them with the media they were made from."""
        known = dict(zip(paths, languages))
        subtitles = [p for p in paths if _ext(p) in SUBTITLE_EXTS]
        if not subtitles:
            self.notice.emit("Only subtitle files can be dubbed.")
            return
        if source and _ext(source) in MEDIA_EXTS:
            self._file_model.addFiles([source])
            self._file_model.set_companion(source, subtitles[0], str(known.get(subtitles[0]) or ""))
            self.notice.emit(f"{os.path.basename(source)} will speak {os.path.basename(subtitles[0])}.")
            return
        super().receiveFiles(subtitles, source, [known.get(p, "") for p in subtitles])

    def extra_blocker(self) -> str:
        if self._options["mode"] == ENGINE_XTTS and not xtts_terms_accepted(self._saved_settings):
            return XTTS_TERMS_BLOCKER
        return ""

    @Slot(str, str, result=list)
    def voiceOptions(self, mode: str, language: str) -> list:
        """Voices the mode offers for a language, after the automatic choice."""
        items = [{"label": "Best voice for the language", "code": DubbingDefaults.VOICE_AUTO}]
        if mode != ENGINE_XTTS and language != DubbingDefaults.LANGUAGE_AUTO:
            items += [{"label": v.label, "code": v.key} for v in voices_for(mode, language)]
        return items

    def queue_blocker(self, items: list[dict[str, Any]]) -> str:
        language = self._options["language"]
        listings: dict[str, dict[str, list[str]]] = {}  # each folder is listed once per check
        for item in items:
            path = item["path"]
            text = path if _ext(path) in SUBTITLE_EXTS else item.get("companion")
            if not text:
                folder = os.path.dirname(path)
                if folder not in listings:
                    listings[folder] = subtitles_by_stem(folder)
                try:
                    text = find_companion(path, language, listings[folder])
                except ValueError as e:
                    return str(e)
            if language == DubbingDefaults.LANGUAGE_AUTO and not (item.get("language") or language_from_filename(text)):
                return (
                    f"{os.path.basename(text)} has no language in its name. Choose the speech language, "
                    "or rename it with a suffix such as movie_es.srt."
                )
        return ""

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        opts = self._options
        path = item["path"]
        subtitle_only = _ext(path) in SUBTITLE_EXTS
        companion = None
        if not subtitle_only:
            companion = item.get("companion") or (
                os.path.splitext(path)[0] + "_example.srt" if validating else find_companion(path, opts["language"])
            )
        language = opts["language"]
        if language == DubbingDefaults.LANGUAGE_AUTO and item.get("language"):
            language = item["language"]
        return {
            "task": self.task_key,
            "input_path": path,
            "subtitle_path": companion,
            "output_dir": opts["output_dir"] or os.path.dirname(path) or None,
            "language": language,
            "mode": opts["mode"],
            "voice": opts["voice"],
            "speakers": opts["speakers"],
            "max_speedup": float(opts["max_speedup"]),
            # A subtitle on its own has no video to add a track to.
            "output": DubbingDefaults.OUTPUT_WAV if subtitle_only else opts["output"],
            "default_track": bool(opts["default_track"]),
            "device": opts["device"],
            "script_bridge": bool(opts["script_bridge"]),
        }


XTTS_TERMS_BLOCKER = "Accept the XTTS-v2 licence to use voice cloning (see the notice under Voices)."


def xtts_terms_accepted(settings: dict[str, Any]) -> bool:
    """True once the user agreed to the XTTS-v2 licence."""
    return bool(settings.get("dubbing", {}).get("xtts_terms_accepted"))


NLLB_TERMS_BLOCKER = "Accept the NLLB-200 licence to translate with it (see the notice under Translation)."


def nllb_terms_accepted(settings: dict[str, Any]) -> bool:
    """True once the user agreed to the NLLB-200 licence (non-commercial use)."""
    return bool(settings.get("translation", {}).get(NLLB_TERMS_SETTING))


def subtitles_by_stem(folder: str) -> dict[str, list[str]]:
    """The subtitle files in `folder`, grouped by the name they share with their media."""
    try:
        entries = os.listdir(folder or ".")
    except OSError:
        entries = []
    grouped: dict[str, list[str]] = {}
    suffixes = tuple(SUBTITLE_EXTS)  # a suffix test is far cheaper than splitext on big folders
    for entry in sorted(entries):
        if entry.lower().endswith(suffixes):
            path = os.path.join(folder, entry)
            grouped.setdefault(_stem_key(path), []).append(path)
    return grouped


def find_companion(media: str, language: str, subtitles: Optional[dict[str, list[str]]] = None) -> str:
    """Find the subtitle to speak next to `media`: movie_<lang>.srt, or the only candidate.

    `subtitles` is the folder's subtitles_by_stem() listing, passed in when checking many files.
    Raises ValueError naming the problem when there is none or the choice is ambiguous.
    """
    folder, name = os.path.split(media)
    stem = os.path.splitext(name)[0]
    listing = subtitles if subtitles is not None else subtitles_by_stem(folder)
    candidates = listing.get(_stem_key(media), [])
    if language != DubbingDefaults.LANGUAGE_AUTO:
        preferred = [c for c in candidates if language_from_filename(c) == language]
        if preferred:
            return preferred[0]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(f"No subtitle found for {name}. Add one named like {stem}_es.srt, or choose one.")
    raise ValueError(
        f"{name} has several subtitles ({', '.join(os.path.basename(c) for c in candidates)}). "
        "Choose the speech language, or pick the subtitle to speak."
    )


def _ext(path: str) -> str:
    """Lower-case extension of a path, with its dot."""
    return os.path.splitext(path)[1].lower()


def _stem_key(path: str) -> str:
    """Comparable path without extension or a subtitle's language suffix."""
    return os.path.normcase(os.path.splitext(output_base(path))[0])


def _same_name(subtitle: str, candidates: list[str]) -> Optional[str]:
    """The media file among `candidates` named like the subtitle (movie.mp4 for movie_es.srt)."""
    key = _stem_key(subtitle)
    return next((p for p in candidates if _ext(p) in MEDIA_EXTS and _stem_key(p) == key), None)


def _sibling_media(subtitle: str) -> Optional[str]:
    """A video or audio file next to the subtitle with the same name, if one exists."""
    stem = os.path.splitext(output_base(subtitle))[0]
    return next((stem + ext for ext in sorted(MEDIA_EXTS) if os.path.isfile(stem + ext)), None)
