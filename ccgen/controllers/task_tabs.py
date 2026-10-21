# task_tabs.py - the Generate, Translate, Transliterate, and Dub tabs' options and job bodies
#
# Each tab's task-specific options come from step_options(), which the Workflow tab reuses for
# its step cards, so a step and its tab always start from the same saved preferences.
#
# Every tab works from a video or audio file alone: Translate, Transliterate, and Dub send a
# media file as a workflow job that transcribes it first (with the Generate preferences) and
# hands the transcript to the tab's own step in memory. Subtitle files skip the transcription.

import os
from typing import Any, Optional

from PySide6.QtCore import Slot

from ccgen.config import licences
from ccgen.config.capabilities import language_from_filename, language_name, script_for_language
from ccgen.config.defaults import (
    AUTO,
    ComputeDefaults,
    DubbingDefaults,
    ModelDefaults,
    TranscriptionDefaults,
    TranslationDefaults,
    TransliterationDefaults,
)
from ccgen.config.profiles import dub_engine, effective_profile, translation_engines
from ccgen.config.voices import CLONING_ENGINES, voices_for
from ccgen.controllers.task_ctrl import (
    TaskController,
    missing_language,
    subtitle_output_body,
    subtitle_output_from_settings,
)
from ccgen.core.tasks.outputs import output_base
from ccgen.models.file_model import AUDIO_EXTS, SUBTITLE_EXTS, VIDEO_EXTS, effective_language, has_text

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


def spoken_language(settings: dict[str, Any]) -> str:
    """The saved transcription language, the default spoken language of media ("" detects it)."""
    return str(GenerateController.step_options(settings)["language"])


def transcribe_step(settings: dict[str, Any], language: str) -> dict[str, Any]:
    """A workflow step transcribing the queued media with the saved Generate options.

    Its subtitles aren't written: the transcript only feeds the tab's own step.
    """
    options = {**GenerateController.step_options(settings), "language": language}
    return {"kind": "generate", "write_output": False, **GenerateController.step_body(options)}


def media_job(item: dict[str, Any], options: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    """A workflow job running `steps` on a queued media file, writing subtitles as the tab does."""
    return {
        "task": "workflow",
        "input_path": item["path"],
        **subtitle_output_body(options, item["path"]),
        "steps": steps,
    }


class TranslateController(TaskController):
    """Translate tab: translate subtitles, or the speech of videos and audio, into another language.

    A subtitle's language comes from its name or from the queue row's language picker; a media
    file's spoken language is the tab's Spoken language option ("" detects it).
    """

    task_key = "translate"
    accepted_exts = MEDIA_EXTS | SUBTITLE_EXTS
    file_noun = "video, audio, or subtitle file"
    sample_input = "example.mp4"

    @staticmethod
    def step_options(settings: dict[str, Any]) -> dict[str, Any]:
        """Translation options from saved preferences ("auto" source reads each file's language)."""
        translation = settings.get("translation", {})
        return {
            "source_lang": translation.get("source_lang") or TranslationDefaults.DEFAULT_SOURCE_LANG,
            "target_lang": translation.get("target_lang", TranslationDefaults.DEFAULT_TARGET_LANG),
            "engine": translation.get("engine", TranslationDefaults.DEFAULT_ENGINE),
        }

    def initial_options(self) -> dict[str, Any]:
        return self.options_from_settings({})

    def options_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        # The tab reads each subtitle's language from its row, so the saved source language
        # only seeds the Workflow tab's translate steps.
        translation = self.step_options(settings)
        return {
            "spoken_language": spoken_language(settings),
            "target_lang": translation["target_lang"],
            "engine": translation["engine"],
            **subtitle_output_from_settings(settings),
        }

    def needs_text_language(self) -> bool:
        return True

    def extra_blocker(self) -> str:
        return licences.blocker(self._saved_settings, self._models())

    def queue_blocker(self, items: list[dict[str, Any]]) -> str:
        target = self._options["target_lang"]
        spoken = self._options["spoken_language"]
        if spoken == target and any(not has_text(i) for i in items):
            return f"The spoken language is {language_name(target)}, the language to translate to. Choose another."
        for item in items:
            if not has_text(item):
                continue
            language = effective_language(item)
            if not language:
                return missing_language(item["path"])
            if language == target:
                return (
                    f"{os.path.basename(item['path'])} is already in {language_name(target)}. "
                    "Choose another language to translate to, or remove it from the queue."
                )
        languages = tuple(effective_language(i) or spoken for i in items)
        return licences.blocker(self._saved_settings, self._models(tuple(lang for lang in languages if lang)))

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        opts = self._options
        if not has_text(item):
            spoken = opts["spoken_language"]
            return media_job(item, opts, [
                transcribe_step(self._saved_settings, spoken),
                {
                    "kind": "translate", "input": "step:0", "write_output": True,
                    "source_lang": spoken or TranslationDefaults.DEFAULT_SOURCE_LANG,
                    "target_lang": opts["target_lang"], "engine": opts["engine"],
                },
            ])
        language = effective_language(item)
        if not language:
            raise ValueError(missing_language(item["path"]))
        return {
            "task": self.task_key,
            "input_path": item["path"],
            **subtitle_output_body(opts, item["path"]),
            "source_lang": language,
            "target_lang": opts["target_lang"],
            "engine": opts["engine"],
        }

    def _models(self, languages: tuple[str, ...] = ()) -> set[str]:
        """The translation engines this tab will run for files in these languages."""
        options = {**self._options, "source_lang": TranslationDefaults.DEFAULT_SOURCE_LANG}
        return translation_models(options, self._saved_settings, languages)


class TransliterateController(TaskController):
    """Transliterate tab: rewrite subtitles, or the speech of videos and audio, in another script.

    Media is transcribed first, and its transcript is in the native script of the language
    spoken, so it always converts from that script. With the source script on Automatic, a
    subtitle converts from the script of its language (from its name or the row's picker).
    """

    task_key = "transliterate"
    accepted_exts = MEDIA_EXTS | SUBTITLE_EXTS
    file_noun = "video, audio, or subtitle file"
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
        return {
            "spoken_language": spoken_language(settings),
            **self.step_options(settings),
            **subtitle_output_from_settings(settings),
        }

    def needs_text_language(self) -> bool:
        return self._options["source_scheme"] == TransliterationDefaults.SOURCE_AUTO

    def queue_blocker(self, items: list[dict[str, Any]]) -> str:
        if not self.needs_text_language():
            return ""
        for item in items:
            if not has_text(item):
                continue
            try:
                self._source_scheme(item)
            except ValueError as e:
                return str(e)
        return ""

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        opts = self._options
        if not has_text(item):
            return media_job(item, opts, [
                transcribe_step(self._saved_settings, opts["spoken_language"]),
                {
                    "kind": "transliterate", "input": "step:0", "write_output": True,
                    "source_scheme": TransliterationDefaults.SOURCE_AUTO,
                    "target_scheme": opts["target_scheme"], "engine": opts["engine"],
                },
            ])
        return {
            "task": self.task_key,
            "input_path": item["path"],
            **subtitle_output_body(opts, item["path"]),
            "source_scheme": self._source_scheme(item, validating),
            "target_scheme": opts["target_scheme"],
            "engine": opts["engine"],
        }

    def _source_scheme(self, item: dict[str, Any], validating: bool = False) -> str:
        """The script a subtitle row converts from; raises ValueError when it can't be told.

        `validating` against the placeholder file assumes a script that differs from the target.
        """
        scheme = self._options["source_scheme"]
        if scheme != TransliterationDefaults.SOURCE_AUTO:
            return scheme
        language = effective_language(item)
        if not language and validating:
            target = self._options["target_scheme"]
            return TransliterationDefaults.DEFAULT_TARGET if target == TransliterationDefaults.ROMAN \
                else TransliterationDefaults.ROMAN
        if not language:
            raise ValueError(missing_language(item["path"]))
        scheme = script_for_language(language)
        name = os.path.basename(item["path"])
        if not scheme:
            raise ValueError(f"Transliteration doesn't support {language_name(language)}'s script ({name}).")
        if scheme == self._options["target_scheme"]:
            raise ValueError(f"{name} is already written in that script. Choose another script to convert to.")
        return scheme


class DubController(TaskController):
    """Dub tab: speak videos, audio, or subtitles in a chosen language.

    A video or audio file alone is transcribed, translated into the Dub into language when it
    is spoken in another, and dubbed. Subtitles added alongside their media are paired by name
    (movie.mp4 + movie_es.srt) and spoken instead of a transcript, translated when needed. A
    subtitle on its own becomes a separate WAV file.
    """

    task_key = "dub"
    accepted_exts = MEDIA_EXTS | SUBTITLE_EXTS
    file_noun = "video, audio, or subtitle file"
    sample_input = "example.mp4"
    # A chosen voice belongs to one engine and one language.
    option_resets = VOICE_RESETS

    @staticmethod
    def step_options(settings: dict[str, Any]) -> dict[str, Any]:
        """Dubbing options from saved preferences ("auto" language speaks the input's language)."""
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
            "quality": dubbing.get("quality", DubbingDefaults.DEFAULT_QUALITY),
        }

    def initial_options(self) -> dict[str, Any]:
        return self.options_from_settings({})

    def options_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        # The tab dubs into a language ("auto" keeps the spoken one), starting from the
        # translation target; the translation itself uses the saved translation model.
        return {
            **self.step_options(settings),
            "spoken_language": spoken_language(settings),
            "language": TranslateController.step_options(settings)["target_lang"],
            "output_dir": settings.get("output", {}).get("directory") or "",
        }

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
        """Take files from another tab, pairing a subtitle with the media it was made from."""
        known = dict(zip(paths, languages))
        subtitles = [p for p in paths if _ext(p) in SUBTITLE_EXTS]
        if subtitles and source and _ext(source) in MEDIA_EXTS:
            self._file_model.addFiles([source])
            self._file_model.set_companion(source, subtitles[0], str(known.get(subtitles[0]) or ""))
            self.notice.emit(f"{os.path.basename(source)} will speak {os.path.basename(subtitles[0])}.")
            return
        super().receiveFiles(paths, source, languages)

    def needs_text_language(self) -> bool:
        return True

    def extra_blocker(self) -> str:
        return licences.blocker(self._saved_settings, self._models())

    @Slot(str, str, result=list)
    def voiceOptions(self, mode: str, language: str) -> list:
        """Voices the mode offers for a language, after the automatic choice."""
        items = [{"label": "Best voice for the language", "code": DubbingDefaults.VOICE_AUTO}]
        if mode != AUTO and mode not in CLONING_ENGINES and language != DubbingDefaults.LANGUAGE_AUTO:
            items += [{"label": v.label, "code": v.key} for v in voices_for(mode, language)]
        return items

    def queue_blocker(self, items: list[dict[str, Any]]) -> str:
        for item in items:
            if has_text(item) and not effective_language(item):
                return missing_language(item.get("companion") or item["path"])
        languages = tuple(effective_language(i) or self._options["spoken_language"] for i in items)
        return licences.blocker(self._saved_settings, self._models(tuple(lang for lang in languages if lang)))

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        opts = self._options
        path = item["path"]
        subtitle_only = _ext(path) in SUBTITLE_EXTS
        target = opts["language"]
        body: dict[str, Any] = {
            "task": "workflow",
            "input_path": path,
            "output_dir": opts["output_dir"] or os.path.dirname(path) or None,
        }
        steps: list[dict[str, Any]] = []
        if has_text(item):
            # The subtitle's text is spoken; its language must be known (see queue_blocker).
            spoken = effective_language(item)
            if not spoken:
                raise ValueError(missing_language(item.get("companion") or path))
            if not subtitle_only:
                body["text_path"] = item["companion"]
            body["text_language"] = spoken
            text = "source"
        else:
            spoken = opts["spoken_language"]
            steps.append(transcribe_step(self._saved_settings, spoken))
            text = "step:0"
        if target != DubbingDefaults.LANGUAGE_AUTO and spoken != target:
            # A detected spoken language that turns out to be the target passes through as it is.
            steps.append({
                "kind": "translate", "input": text, "write_output": False,
                "source_lang": spoken or TranslationDefaults.DEFAULT_SOURCE_LANG,
                "target_lang": target, "engine": self._translation_engine(),
            })
            text = f"step:{len(steps) - 1}"
        steps.append({
            "kind": "dub",
            "input": text,
            "language": target,
            "mode": opts["mode"],
            "voice": opts["voice"],
            "speakers": opts["speakers"],
            "max_speedup": float(opts["max_speedup"]),
            # A subtitle on its own has no video to add a track to.
            "output": DubbingDefaults.OUTPUT_WAV if subtitle_only else opts["output"],
            "default_track": bool(opts["default_track"]),
            "device": opts["device"],
            "quality": opts["quality"],
        })
        return {**body, "steps": steps}

    def _translation_engine(self) -> str:
        """The saved translation model, which translates text into the dub language."""
        return str(TranslateController.step_options(self._saved_settings)["engine"])

    def _models(self, languages: tuple[str, ...] = ()) -> list[str]:
        """The dubbing engine and the translation engines this tab will run."""
        models = [dub_model(self._options, self._saved_settings)]
        target = self._options["language"]
        if target != DubbingDefaults.LANGUAGE_AUTO:
            options = {
                "engine": self._translation_engine(),
                "source_lang": TranslationDefaults.DEFAULT_SOURCE_LANG,
                "target_lang": target,
            }
            models += sorted(translation_models(options, self._saved_settings, languages))
        return models


def translation_models(options: dict[str, Any], settings: dict[str, Any], languages: tuple[str, ...] = ()) -> set[str]:
    """The translation engines a translate tab or step will run with these options.

    `languages` are the queued files' known languages, used when the source is "auto".
    """
    return translation_engines(
        options["engine"], effective_profile(settings), options["source_lang"], options["target_lang"], languages,
    )


def dub_model(options: dict[str, Any], settings: dict[str, Any]) -> str:
    """The dubbing engine a dub tab or step will run with these options."""
    return dub_engine(options["mode"], effective_profile(settings)).mode


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
