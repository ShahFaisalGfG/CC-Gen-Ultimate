# jobs.py - the job each task builds for one file, shared by the app's tabs and the command line
#
# A tab's options come from the saved preferences (the *_options functions), and each queued file
# becomes one job body for the task configs in ccgen/core/tasks/configs.py. The tabs and `ccgen`
# both build their jobs here, so a file runs the same way from either.
#
# Every task works from a video or audio file alone: Translate, Transliterate, and Dub send a media
# file as a workflow job that transcribes it first (with the Generate preferences) and hands the
# transcript to the task's own step in memory. Subtitle files skip the transcription.
#
# A queued file is an "item": a dict with its path, kind ("video", "audio", or "subtitle"), the
# language of its text (from its name, a detection, or a hand-off), the language chosen for it ("" for
# Auto), and for dubbing the subtitle file a media file speaks ("companion").

import logging
import os
from typing import Any, Callable, Iterable, Iterator, Optional

from ccgen.config import licences
from ccgen.config.capabilities import language_from_filename, language_name, scheme_name, script_for_language
from ccgen.config.defaults import (
    AUTO,
    ComputeDefaults,
    DubbingDefaults,
    ModelDefaults,
    OutputDefaults,
    TranscriptionDefaults,
    TranslationDefaults,
    TransliterationDefaults,
)
from ccgen.config.profiles import dub_engine, effective_profile, translation_engines, whisper_model
from ccgen.config.translation_models import engine_info
from ccgen.config.voices import ENGINE_LABELS
from ccgen.core.tasks.configs import INPUT_SOURCE, SUBTITLE_FORMATS
from ccgen.core.tasks.outputs import output_base, output_path

_log = logging.getLogger(__name__)

VIDEO_EXTS = frozenset({".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".ts", ".m2ts"})
AUDIO_EXTS = frozenset({".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".wma"})
SUBTITLE_EXTS = frozenset({".srt", ".vtt", ".lrc", ".ass", ".ssa", ".sbv"})
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
SUPPORTED_EXTS = MEDIA_EXTS | SUBTITLE_EXTS

# What each task takes.
TASK_EXTS: dict[str, frozenset[str]] = {
    "generate": MEDIA_EXTS,
    "translate": SUPPORTED_EXTS,
    "transliterate": SUPPORTED_EXTS,
    "dub": SUPPORTED_EXTS,
    "workflow": SUPPORTED_EXTS,
}
# Who reads a task's queue, in its own words ("this tab needs a ...").
TASK_NOUNS: dict[str, str] = {
    "generate": "video or audio file",
    "translate": "video, audio, or subtitle file",
    "transliterate": "video, audio, or subtitle file",
    "dub": "video, audio, or subtitle file",
    "workflow": "video, audio, or subtitle file",
}
# A Kokoro or Piper voice belongs to one engine and one language, so it resets with either.
VOICE_RESETS: dict[str, dict[str, Any]] = {
    "mode": {"voice": DubbingDefaults.VOICE_AUTO},
    "language": {"voice": DubbingDefaults.VOICE_AUTO},
}


# ── Files ─────────────────────────────────────────────────────────────────────


def ext_of(path: str) -> str:
    """Lower-case extension of a path, with its dot."""
    return os.path.splitext(path)[1].lower()


def kind_of(path: str) -> str:
    """"video", "audio", or "subtitle" for a supported file (unknown types count as audio)."""
    ext = ext_of(path)
    return "video" if ext in VIDEO_EXTS else "subtitle" if ext in SUBTITLE_EXTS else "audio"


def make_item(path: str, chosen_language: str = "", companion: str = "") -> dict[str, Any]:
    """A queued file as the job builders read it."""
    kind = kind_of(path)
    language = language_from_filename(path) if kind == "subtitle" else ""
    if companion:
        language = language_from_filename(companion)
    return {"path": path, "kind": kind, "language": language, "chosen_language": chosen_language,
            "companion": companion}


def has_text(item: dict[str, Any]) -> bool:
    """True when a row carries subtitle text: a subtitle file, or media paired with one."""
    return item.get("kind") == "subtitle" or bool(item.get("companion"))


def effective_language(item: dict[str, Any]) -> str:
    """The language of a row's text: the one the user picked, else the one known from its name."""
    return str(item.get("chosen_language") or item.get("language") or "")


def iter_files(
    roots: Iterable[str],
    extensions: frozenset[str],
    is_cancelled: Callable[[], bool] = lambda: False,
    on_error: Optional[Callable[[str], None]] = None,
) -> Iterator[tuple[str, int]]:
    """Yield (path, size_bytes) for every file under `roots` whose extension is in `extensions`.

    Directories are walked depth-first in case-insensitive name order, so results arrive in the
    order a file browser would list them. Symlinked directories are not followed (avoids loops),
    and unreadable directories are reported through `on_error` and skipped.
    """
    stack = list(reversed([os.path.normpath(r) for r in roots]))
    while stack:
        if is_cancelled():
            return
        folder = stack.pop()
        try:
            with os.scandir(folder) as entries:
                listing = sorted(entries, key=lambda e: e.name.casefold())
        except OSError as error:
            if on_error:
                on_error(f"Skipped {folder}: {error.strerror or error}")
            continue
        subfolders: list[str] = []
        for entry in listing:
            if is_cancelled():
                return
            try:
                if entry.is_dir(follow_symlinks=False):
                    subfolders.append(entry.path)
                elif ext_of(entry.name) in extensions and entry.is_file():
                    yield entry.path, entry.stat().st_size
            except OSError as error:
                _log.debug("Skipping unreadable entry %s: %r", entry.path, error)
        stack.extend(reversed(subfolders))


def expand_inputs(
    paths: Iterable[str], extensions: frozenset[str], on_error: Optional[Callable[[str], None]] = None,
) -> tuple[list[str], list[str]]:
    """(usable files, skipped paths) for files and folders: folders are searched with their subfolders.

    Duplicates are dropped, keeping the first. A path that doesn't exist is skipped.
    """
    files: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()

    def add(path: str) -> None:
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen:
            seen.add(key)
            files.append(os.path.abspath(path))

    for path in paths:
        if os.path.isdir(path):
            for found, _size in iter_files([path], extensions, on_error=on_error):
                add(found)
        elif os.path.isfile(path) and ext_of(path) in extensions:
            add(path)
        else:
            skipped.append(path)
    return files, skipped


def _stem_key(path: str) -> str:
    """Comparable path without extension or a subtitle's language suffix."""
    return os.path.normcase(os.path.splitext(output_base(path))[0])


def same_name(subtitle: str, candidates: list[str]) -> Optional[str]:
    """The media file among `candidates` named like the subtitle (movie.mp4 for movie_es.srt)."""
    key = _stem_key(subtitle)
    return next((p for p in candidates if ext_of(p) in MEDIA_EXTS and _stem_key(p) == key), None)


def sibling_media(subtitle: str) -> Optional[str]:
    """A video or audio file next to the subtitle with the same name, if one exists."""
    stem = os.path.splitext(output_base(subtitle))[0]
    return next((stem + ext for ext in sorted(MEDIA_EXTS) if os.path.isfile(stem + ext)), None)


def pair_for_dub(paths: list[str], queued: Optional[list[str]] = None) -> tuple[list[str], dict[str, str], list[str]]:
    """Media first, then each subtitle paired with media of the same name, as the Dub tab adds files.

    Returns (media to add, {media: the subtitle it speaks}, subtitles left on their own). A subtitle
    pairs with media among `paths` or `queued`, else with a file of the same name beside it.
    """
    media = [p for p in paths if ext_of(p) in MEDIA_EXTS]
    subtitles = [p for p in paths if ext_of(p) in SUBTITLE_EXTS]
    added = list(media)
    companions: dict[str, str] = {}
    unpaired: list[str] = []
    for subtitle in subtitles:
        partner = same_name(subtitle, media + list(queued or [])) or sibling_media(subtitle)
        if partner is None:
            unpaired.append(subtitle)
            continue
        if partner not in added:
            added.append(partner)
        companions[partner] = subtitle
    return added, companions, unpaired


def missing_language(path: str) -> str:
    """The blocker for a subtitle whose language is neither in its name nor chosen."""
    return f"Choose the language of {os.path.basename(path)} in the queue."


# ── Options from saved preferences ──────────────────────────────────────────


def subtitle_output_options() -> dict[str, Any]:
    """Default subtitle format, layout, and folder options shared by subtitle-writing tasks."""
    return {
        "formats": [OutputDefaults.DEFAULT_FORMAT],
        "max_line_length": OutputDefaults.MAX_LINE_LENGTH,
        "max_lines": OutputDefaults.MAX_LINES,
        "output_dir": OutputDefaults.DIRECTORY,
    }


def subtitle_output_from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Saved subtitle format, layout, and folder preferences."""
    output = settings.get("output", {})
    defaults = subtitle_output_options()
    return {
        "formats": [fmt for fmt in SUBTITLE_FORMATS if output.get(fmt, fmt in defaults["formats"])],
        "max_line_length": int(output.get("max_line_length", defaults["max_line_length"])),
        "max_lines": int(output.get("max_lines", defaults["max_lines"])),
        "output_dir": output.get("directory") or "",
    }


def subtitle_output_body(options: dict[str, Any], input_path: str) -> dict[str, Any]:
    """Job body fields for subtitle output; files go next to their input unless a folder is set."""
    return {
        "output_dir": options["output_dir"] or os.path.dirname(input_path) or None,
        "formats": list(options["formats"]),
        "max_line_length": int(options["max_line_length"]),
        "max_lines": int(options["max_lines"]),
    }


def generate_step_options(settings: dict[str, Any]) -> dict[str, Any]:
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


def generate_step_body(options: dict[str, Any]) -> dict[str, Any]:
    """Job fields for the transcription options."""
    return {
        "model_name": options["model_name"],
        "device": options["device"],
        "compute_type": options["compute_type"],
        "language": options["language"] or None,
        "beam_size": int(options["beam_size"]),
        "vad_filter": bool(options["vad_filter"]),
    }


def translate_step_options(settings: dict[str, Any]) -> dict[str, Any]:
    """Translation options from saved preferences ("auto" source reads each file's language)."""
    translation = settings.get("translation", {})
    return {
        "source_lang": translation.get("source_lang") or TranslationDefaults.DEFAULT_SOURCE_LANG,
        "target_lang": translation.get("target_lang", TranslationDefaults.DEFAULT_TARGET_LANG),
        "engine": translation.get("engine", TranslationDefaults.DEFAULT_ENGINE),
    }


def transliterate_step_options(settings: dict[str, Any]) -> dict[str, Any]:
    """Transliteration options from saved preferences."""
    translit = settings.get("transliteration", {})
    return {
        "source_scheme": translit.get("source", TransliterationDefaults.DEFAULT_SOURCE),
        "target_scheme": translit.get("target", TransliterationDefaults.DEFAULT_TARGET),
        "engine": translit.get("engine", TransliterationDefaults.DEFAULT_ENGINE),
    }


def dub_step_options(settings: dict[str, Any]) -> dict[str, Any]:
    """Dubbing options from saved preferences ("auto" language speaks the input's language)."""
    dubbing = settings.get("dubbing", {})
    return {
        "language": DubbingDefaults.LANGUAGE_AUTO,
        "mode": dubbing.get("mode", DubbingDefaults.DEFAULT_MODE),
        "voice": DubbingDefaults.VOICE_AUTO,
        "speakers": dubbing.get("speakers", DubbingDefaults.DEFAULT_SPEAKERS),
        "max_speakers": int(dubbing.get("max_speakers", DubbingDefaults.MAX_SPEAKERS)),
        "max_speedup": float(dubbing.get("max_speedup", DubbingDefaults.MAX_SPEEDUP)),
        "output": dubbing.get("output", DubbingDefaults.DEFAULT_OUTPUT),
        "default_track": bool(dubbing.get("default_track", DubbingDefaults.DEFAULT_TRACK)),
        "device": dubbing.get("device", DubbingDefaults.DEVICE_AUTO),
        "quality": dubbing.get("quality", DubbingDefaults.DEFAULT_QUALITY),
    }


STEP_OPTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "generate": generate_step_options,
    "translate": translate_step_options,
    "transliterate": transliterate_step_options,
    "dub": dub_step_options,
}


def spoken_language(settings: dict[str, Any]) -> str:
    """The saved transcription language, the default spoken language of media ("" detects it)."""
    return str(generate_step_options(settings)["language"])


def generate_options(settings: dict[str, Any]) -> dict[str, Any]:
    """The Generate tab's options."""
    return {**generate_step_options(settings), **subtitle_output_from_settings(settings)}


def translate_options(settings: dict[str, Any]) -> dict[str, Any]:
    """The Translate tab's options; the saved source language only seeds workflow steps."""
    translation = translate_step_options(settings)
    return {
        "spoken_language": spoken_language(settings),
        "target_lang": translation["target_lang"],
        "engine": translation["engine"],
        **subtitle_output_from_settings(settings),
    }


def transliterate_options(settings: dict[str, Any]) -> dict[str, Any]:
    """The Transliterate tab's options."""
    return {
        "spoken_language": spoken_language(settings),
        **transliterate_step_options(settings),
        **subtitle_output_from_settings(settings),
    }


def dub_options(settings: dict[str, Any]) -> dict[str, Any]:
    """The Dub tab's options: it dubs into the translation target ("auto" keeps the spoken language)."""
    return {
        **dub_step_options(settings),
        "spoken_language": spoken_language(settings),
        "language": translate_step_options(settings)["target_lang"],
        "output_dir": settings.get("output", {}).get("directory") or "",
    }


TAB_OPTIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "generate": generate_options,
    "translate": translate_options,
    "transliterate": transliterate_options,
    "dub": dub_options,
    "workflow": subtitle_output_from_settings,
}


# ── Jobs ─────────────────────────────────────────────────────────────────────


def transcribe_step(settings: dict[str, Any], language: str) -> dict[str, Any]:
    """A workflow step transcribing the queued media with the saved Generate options.

    Its subtitles aren't written: the transcript only feeds the task's own step.
    """
    options = {**generate_step_options(settings), "language": language}
    return {"kind": "generate", "write_output": False, **generate_step_body(options)}


def media_job(item: dict[str, Any], options: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    """A workflow job running `steps` on a queued media file, writing subtitles as the task does."""
    return {
        "task": "workflow",
        "input_path": item["path"],
        **subtitle_output_body(options, item["path"]),
        "steps": steps,
    }


def generate_job(item: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
    """Transcribe one video or audio file."""
    return {
        "task": "generate",
        "input_path": item["path"],
        **subtitle_output_body(options, item["path"]),
        **generate_step_body(options),
    }


def translate_job(item: dict[str, Any], options: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Translate one subtitle file, or transcribe and translate one media file.

    Raises ValueError when a subtitle's language isn't known.
    """
    if not has_text(item):
        spoken = options["spoken_language"]
        return media_job(item, options, [
            transcribe_step(settings, spoken),
            {
                "kind": "translate", "input": "step:0", "write_output": True,
                "source_lang": spoken or TranslationDefaults.DEFAULT_SOURCE_LANG,
                "target_lang": options["target_lang"], "engine": options["engine"],
            },
        ])
    language = effective_language(item)
    if not language:
        raise ValueError(missing_language(item["path"]))
    return {
        "task": "translate",
        "input_path": item["path"],
        **subtitle_output_body(options, item["path"]),
        "source_lang": language,
        "target_lang": options["target_lang"],
        "engine": options["engine"],
    }


def transliterate_job(
    item: dict[str, Any], options: dict[str, Any], settings: dict[str, Any], validating: bool = False,
) -> dict[str, Any]:
    """Convert one subtitle file to another script, or transcribe one media file and convert it.

    Media is transcribed in the native script of the language spoken, so it always converts from
    that script. Raises ValueError when a subtitle's script can't be told.
    """
    if not has_text(item):
        return media_job(item, options, [
            transcribe_step(settings, options["spoken_language"]),
            {
                "kind": "transliterate", "input": "step:0", "write_output": True,
                "source_scheme": TransliterationDefaults.SOURCE_AUTO,
                "target_scheme": options["target_scheme"], "engine": options["engine"],
                "alternate_target": speech_alternate_target(options),
            },
        ])
    return {
        "task": "transliterate",
        "input_path": item["path"],
        **subtitle_output_body(options, item["path"]),
        "source_scheme": transliterate_source(item, options, validating),
        "target_scheme": options["target_scheme"],
        "engine": options["engine"],
    }


def speech_alternate_target(options: dict[str, Any]) -> str:
    """The script speech converts to when it is already in the target script: the pair's other side.

    The tab's pair reads both ways for speech, so with Roman to Urdu chosen, Urdu speech becomes
    Roman and Hindi speech becomes Urdu. "" when the source is Automatic or the same as the target.
    """
    source = options["source_scheme"]
    if source in (TransliterationDefaults.SOURCE_AUTO, options["target_scheme"]):
        return ""
    return str(source)


def transliterate_source(item: dict[str, Any], options: dict[str, Any], validating: bool = False) -> str:
    """The script a subtitle converts from; raises ValueError when it can't be told.

    `validating` against a placeholder file assumes a script that differs from the target.
    """
    scheme = options["source_scheme"]
    if scheme != TransliterationDefaults.SOURCE_AUTO:
        return scheme
    language = effective_language(item)
    if not language and validating:
        target = options["target_scheme"]
        return TransliterationDefaults.DEFAULT_TARGET if target == TransliterationDefaults.ROMAN \
            else TransliterationDefaults.ROMAN
    if not language:
        raise ValueError(missing_language(item["path"]))
    scheme = script_for_language(language)
    name = os.path.basename(item["path"])
    if not scheme:
        raise ValueError(f"Transliteration doesn't support {language_name(language)}'s script ({name}).")
    if scheme == options["target_scheme"]:
        raise ValueError(f"{name} is already written in that script. Choose another script to convert to.")
    return scheme


def dub_job(item: dict[str, Any], options: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Speak one file in the dub language as a workflow job.

    Media alone is transcribed, translated into the dub language when it is spoken in another, and
    dubbed. Media paired with a subtitle speaks that subtitle instead, and a subtitle on its own
    becomes a WAV file. Raises ValueError when the text's language isn't known.
    """
    path = item["path"]
    subtitle_only = ext_of(path) in SUBTITLE_EXTS
    target = options["language"]
    body: dict[str, Any] = {
        "task": "workflow",
        "input_path": path,
        "output_dir": options["output_dir"] or os.path.dirname(path) or None,
    }
    steps: list[dict[str, Any]] = []
    if has_text(item):
        spoken = effective_language(item)
        if not spoken:
            raise ValueError(missing_language(item.get("companion") or path))
        if not subtitle_only:
            body["text_path"] = item["companion"]
        body["text_language"] = spoken
        text = INPUT_SOURCE
    else:
        spoken = options["spoken_language"]
        steps.append(transcribe_step(settings, spoken))
        text = "step:0"
    if target != DubbingDefaults.LANGUAGE_AUTO and spoken != target:
        # A detected spoken language that turns out to be the target passes through as it is.
        steps.append({
            "kind": "translate", "input": text, "write_output": False,
            "source_lang": spoken or TranslationDefaults.DEFAULT_SOURCE_LANG,
            "target_lang": target, "engine": dub_translation_engine(settings),
        })
        text = f"step:{len(steps) - 1}"
    steps.append({
        "kind": "dub",
        "input": text,
        "language": target,
        "mode": options["mode"],
        "voice": options["voice"],
        "speakers": options["speakers"],
        "max_speakers": int(options.get("max_speakers", DubbingDefaults.MAX_SPEAKERS)),
        "max_speedup": float(options["max_speedup"]),
        # A subtitle on its own has no video to add a track to.
        "output": DubbingDefaults.OUTPUT_WAV if subtitle_only else options["output"],
        "default_track": bool(options["default_track"]),
        "device": options["device"],
        "quality": options["quality"],
    })
    return {**body, "steps": steps}


def workflow_job(item: dict[str, Any], options: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the workflow's steps on one file; steps on Automatic read a queued subtitle's language."""
    bodies = []
    for step in steps:
        body = dict(step)
        if step["kind"] == "generate":
            body.update(generate_step_body(step))
        bodies.append(body)
    return {
        "task": "workflow",
        "input_path": item["path"],
        **subtitle_output_body(options, item["path"]),
        "steps": bodies,
        "text_language": effective_language(item),
    }


def task_job(
    task: str, item: dict[str, Any], options: dict[str, Any], settings: dict[str, Any],
    steps: Optional[list[dict[str, Any]]] = None, validating: bool = False,
) -> dict[str, Any]:
    """The job body for one file of a task, with the profile that resolves every Automatic choice."""
    if task == "generate":
        body = generate_job(item, options)
    elif task == "translate":
        body = translate_job(item, options, settings)
    elif task == "transliterate":
        body = transliterate_job(item, options, settings, validating)
    elif task == "dub":
        body = dub_job(item, options, settings)
    elif task == "workflow":
        body = workflow_job(item, options, steps or [])
    else:
        raise ValueError(f"Unknown task: {task}.")
    return {**body, "profile": effective_profile(settings)}


# ── What can't run, before it starts ────────────────────────────────────────


def relies_on(task: str, options: dict[str, Any], settings: dict[str, Any]) -> str:
    """The saved choices a tab runs with besides its own options ("" for none), such as
    "Uses Whisper small for speech and OPUS-MT or Hy-MT2 for translation"."""
    if task not in ("translate", "transliterate", "dub"):
        return ""
    profile = effective_profile(settings)
    speech = f"Whisper {whisper_model(str(generate_step_options(settings)['model_name']), profile)}"
    if task != "dub" or options.get("language") == DubbingDefaults.LANGUAGE_AUTO:
        return f"Uses {speech} for speech in videos and audio."
    engine = dub_translation_engine(settings)
    translation = "OPUS-MT or Hy-MT2" if engine == AUTO else engine_info(engine).label
    return f"Uses {speech} for speech and {translation} for translation."


def dub_translation_engine(settings: dict[str, Any]) -> str:
    """The saved translation model, which translates text into the dub language."""
    return str(translate_step_options(settings)["engine"])


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


def task_models(
    task: str, options: dict[str, Any], settings: dict[str, Any], languages: tuple[str, ...] = (),
    steps: Optional[list[dict[str, Any]]] = None,
) -> list[str]:
    """The models with licence terms that a task may run for files in these languages."""
    if task == "translate":
        translate = {**options, "source_lang": TranslationDefaults.DEFAULT_SOURCE_LANG}
        return sorted(translation_models(translate, settings, languages))
    if task == "dub":
        models = [dub_model(options, settings)]
        if options["language"] != DubbingDefaults.LANGUAGE_AUTO:
            translate = {"engine": dub_translation_engine(settings), "target_lang": options["language"],
                         "source_lang": TranslationDefaults.DEFAULT_SOURCE_LANG}
            models += sorted(translation_models(translate, settings, languages))
        return models
    if task == "workflow":
        models = []
        for step in steps or []:
            if step["kind"] == "dub":
                models.append(dub_model(step, settings))
            elif step["kind"] == "translate":
                models += sorted(translation_models(step, settings))
        return models
    return []


def licence_blocker(
    task: str, options: dict[str, Any], settings: dict[str, Any], languages: tuple[str, ...] = (),
    steps: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Why a task can't start until a model's licence is accepted, or ""."""
    return licences.blocker(settings, task_models(task, options, settings, languages, steps))


def pending_licence(
    task: str, options: dict[str, Any], settings: dict[str, Any], languages: tuple[str, ...] = (),
    steps: Optional[list[dict[str, Any]]] = None,
) -> str:
    """The first model whose licence a task still needs accepted ("" when none)."""
    return licences.pending(settings, task_models(task, options, settings, languages, steps))


def _known_languages(items: list[dict[str, Any]], spoken: str) -> tuple[str, ...]:
    """Each queued file's language, or the spoken language for media, without unknowns."""
    return tuple(lang for lang in (effective_language(i) or spoken for i in items) if lang)


def queue_blocker(
    task: str, items: list[dict[str, Any]], options: dict[str, Any], settings: dict[str, Any],
    steps: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Why a queued file can't run with these options, or "" when all of them can."""
    if task == "translate":
        return _translate_blocker(items, options, settings)
    if task == "transliterate":
        return _transliterate_blocker(items, options)
    if task == "dub":
        for item in items:
            if has_text(item) and not effective_language(item):
                return missing_language(item.get("companion") or item["path"])
        return licence_blocker(task, options, settings, _known_languages(items, options["spoken_language"]))
    if task == "workflow":
        return _workflow_blocker(items, steps or [])
    return ""


def _translate_blocker(items: list[dict[str, Any]], options: dict[str, Any], settings: dict[str, Any]) -> str:
    target = options["target_lang"]
    spoken = options["spoken_language"]
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
    return licence_blocker("translate", options, settings, _known_languages(items, spoken))


def _transliterate_blocker(items: list[dict[str, Any]], options: dict[str, Any]) -> str:
    spoken = options["spoken_language"]
    target = options["target_scheme"]
    # Media is transcribed in its language's own script; with the language known, a target in that
    # same script can only convert the other way, so without one say so now, not after transcribing.
    if spoken and any(not has_text(i) for i in items):
        script = script_for_language(spoken)
        if not script:
            return f"Transliteration doesn't support {language_name(spoken)}'s script. Choose another spoken language."
        if script == target and not speech_alternate_target(options):
            return (f"{language_name(spoken)} speech is transcribed in {scheme_name(target)} already. "
                    "Choose another script to convert to.")
    if options["source_scheme"] != TransliterationDefaults.SOURCE_AUTO:
        return ""
    for item in items:
        if not has_text(item):
            continue
        try:
            transliterate_source(item, options)
        except ValueError as e:
            return str(e)
    return ""


def _workflow_blocker(items: list[dict[str, Any]], steps: list[dict[str, Any]]) -> str:
    unknown = next((i for i in items if i.get("kind") == "subtitle" and not effective_language(i)), None)
    step = step_reading_language(steps)
    if unknown is None or step is None:
        return ""
    number, title = step
    return (
        f"{os.path.basename(unknown['path'])} has no known language, which step {number} ({title}) "
        "needs. Choose its language in the queue, or set the step's language."
    )


def step_reading_language(steps: list[dict[str, Any]]) -> Optional[tuple[int, str]]:
    """(number, title) of the first step that takes the queued subtitle's language, or None."""
    for number, step in enumerate(steps, start=1):
        detects = (step["kind"] == "translate" and step["source_lang"] == "auto") \
            or (step["kind"] == "dub" and step["language"] == DubbingDefaults.LANGUAGE_AUTO) \
            or (step["kind"] == "transliterate" and step["source_scheme"] == TransliterationDefaults.SOURCE_AUTO)
        if detects and step.get("input") == INPUT_SOURCE:
            return number, step_title(step)
    return None


def needs_text_language(task: str, options: dict[str, Any], steps: Optional[list[dict[str, Any]]] = None) -> bool:
    """Whether every subtitle's language must be known to run a task with these options."""
    if task in ("translate", "dub"):
        return True
    if task == "transliterate":
        return options["source_scheme"] == TransliterationDefaults.SOURCE_AUTO
    if task == "workflow":
        return step_reading_language(steps or []) is not None
    return False


def step_title(step: dict[str, Any]) -> str:
    """Short heading for a workflow step, e.g. "Translate to Urdu"."""
    kind = step["kind"]
    if kind == "generate":
        return "Generate subtitles"
    if kind == "translate":
        return f"Translate to {language_name(step['target_lang'])}"
    if kind == "transliterate":
        return f"Transliterate to {scheme_name(step['target_scheme'])}"
    return f"Dub with {ENGINE_LABELS.get(step['mode'], step['mode'])}"


def starter_steps(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """A new workflow: subtitles, then their translation."""
    return [new_step("generate", settings, INPUT_SOURCE), new_step("translate", settings, "step:0")]


def new_step(kind: str, settings: dict[str, Any], step_input: str) -> dict[str, Any]:
    """A workflow step of `kind` with the saved options, reading `step_input`."""
    step: dict[str, Any] = {"kind": kind, **STEP_OPTIONS[kind](settings)}
    if kind != "generate":
        step["input"] = step_input
    if kind != "dub":
        step["write_output"] = True
    return step


# ── Outputs already there ───────────────────────────────────────────────────


def planned_outputs(body: dict[str, Any]) -> list[str]:
    """The files a job body will write, as far as they can be told before it runs.

    A transliteration from Automatic learns its script only while running, and a dub into
    Automatic learns its language, so their files aren't listed.
    """
    task = body.get("task")
    path = str(body.get("input_path") or "")
    out_dir = body.get("output_dir") or None
    formats = [str(f) for f in body.get("formats") or [OutputDefaults.DEFAULT_FORMAT]]

    def subtitles(suffix: str) -> list[str]:
        return [output_path(path, suffix, f".{fmt}", out_dir) for fmt in formats]

    if task == "generate":
        return subtitles("")
    if task == "translate":
        return subtitles(f"_{body.get('target_lang', '')}")
    if task == "transliterate":
        return subtitles(f"_tr_{body.get('source_scheme', '')}_{body.get('target_scheme', '')}")
    if task != "workflow":
        return []
    planned: list[str] = []
    for step in body.get("steps") or []:
        kind = step.get("kind")
        if kind == "dub":
            planned += _planned_dub(path, step, out_dir)
        elif not step.get("write_output", True):
            continue
        elif kind == "generate":
            planned += subtitles("")
        elif kind == "translate":
            planned += subtitles(f"_{step.get('target_lang', '')}")
        elif kind == "transliterate" and step.get("source_scheme") != TransliterationDefaults.SOURCE_AUTO:
            planned += subtitles(f"_tr_{step.get('source_scheme')}_{step.get('target_scheme')}")
    return planned


def _planned_dub(path: str, step: dict[str, Any], out_dir: Optional[str]) -> list[str]:
    """The dub file a step writes: movie_dub_ur.mkv (.mka for audio), or a WAV file."""
    language = step.get("language", DubbingDefaults.LANGUAGE_AUTO)
    if language == DubbingDefaults.LANGUAGE_AUTO:
        return []
    suffix = f"_dub_{language}"
    ext = ext_of(path)
    if ext in SUBTITLE_EXTS or step.get("output") == DubbingDefaults.OUTPUT_WAV:
        return [output_path(path, suffix, ".wav", out_dir)]
    return [output_path(path, suffix, ".mkv" if ext in VIDEO_EXTS else ".mka", out_dir)]


def existing_outputs(body: dict[str, Any]) -> list[str]:
    """The planned outputs of a job body that are already there."""
    return [p for p in planned_outputs(body) if os.path.exists(p)]
