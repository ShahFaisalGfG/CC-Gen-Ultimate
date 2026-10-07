# configs.py - one validated configuration per task, shared by the API, the CLI, and the tasks
#
# Each config is a plain dataclass whose __post_init__ rejects invalid combinations, so the API
# (which validates these same classes through pydantic) and the CLI report identical errors.

from dataclasses import dataclass, field
from typing import Annotated, Literal, Optional, Union

from pydantic import Field

from ccgen.config import profiles
from ccgen.config.capabilities import transliteration_supported
from ccgen.config.translation_models import DEFAULT_ENGINE as DEFAULT_TRANSLATION_ENGINE
from ccgen.config.translation_models import ENGINE_KEYS as TRANSLATION_ENGINE_KEYS
from ccgen.config.translation_models import route as translation_route
from ccgen.config.voices import voice_by_key
from ccgen.config.defaults import (
    AUTO,
    ComputeDefaults,
    DubbingDefaults,
    ModelDefaults,
    OutputDefaults,
    ProfileDefaults,
    TranscriptionDefaults,
    TranslationDefaults,
    TransliterationDefaults,
)
from ccgen.core.subtitle_parser import is_subtitle

SUBTITLE_FORMATS = ("srt", "vtt", "lrc", "ass", "sbv")


@dataclass(kw_only=True)
class TaskConfigBase:
    """Fields every task needs: the file to process, where to write results, and the
    performance profile that resolves every "auto" model choice (see ccgen/config/profiles.py).
    """

    input_path: str
    output_dir: Optional[str] = None
    profile: str = ProfileDefaults.DEFAULT_PROFILE

    def __post_init__(self) -> None:
        if not self.input_path.strip():
            raise ValueError("An input file is required.")
        if self.profile and self.profile not in profiles.PROFILE_KEYS:
            raise ValueError(f"Unknown performance profile: {self.profile}.")


@dataclass(kw_only=True)
class SubtitleOutputConfig(TaskConfigBase):
    """Subtitle formats and cue layout shared by every task that writes subtitle files."""

    formats: list[str] = field(default_factory=lambda: [OutputDefaults.DEFAULT_FORMAT])
    max_line_length: int = OutputDefaults.MAX_LINE_LENGTH
    max_lines: int = OutputDefaults.MAX_LINES

    def __post_init__(self) -> None:
        super().__post_init__()
        validate_subtitle_output(self.formats, self.max_line_length, self.max_lines)


@dataclass(kw_only=True)
class GenerateConfig(SubtitleOutputConfig):
    """Transcribe a video or audio file into subtitles."""

    task: Literal["generate"] = "generate"
    model_name: str = ModelDefaults.DEFAULT_MODEL
    device: str = ComputeDefaults.DEFAULT_DEVICE
    compute_type: str = ComputeDefaults.DEFAULT_COMPUTE_TYPE
    language: Optional[str] = TranscriptionDefaults.DEFAULT_LANGUAGE
    beam_size: int = TranscriptionDefaults.BEAM_SIZE
    vad_filter: bool = TranscriptionDefaults.VAD_FILTER

    def __post_init__(self) -> None:
        super().__post_init__()
        if is_subtitle(self.input_path):
            raise ValueError("Subtitle generation needs a video or audio file, not a subtitle file.")
        validate_generate(self.model_name, self.device, self.compute_type, self.beam_size)


@dataclass(kw_only=True)
class TranslateConfig(SubtitleOutputConfig):
    """Translate an existing subtitle file into another language.

    `source_lang` "auto" reads the language from a `_xx` file-name suffix (e.g. `movie_ur.srt`)
    and fails with a clear message when the name carries none.
    """

    task: Literal["translate"] = "translate"
    source_lang: str = TranslationDefaults.DEFAULT_SOURCE_LANG
    target_lang: str = TranslationDefaults.DEFAULT_TARGET_LANG
    engine: str = DEFAULT_TRANSLATION_ENGINE

    def __post_init__(self) -> None:
        super().__post_init__()
        require_subtitle_input(self.input_path, "Translation")
        validate_translate(self.source_lang, self.target_lang, self.engine, self.profile)


@dataclass(kw_only=True)
class TransliterateConfig(SubtitleOutputConfig):
    """Convert an existing subtitle file from one script to another."""

    task: Literal["transliterate"] = "transliterate"
    source_scheme: str = TransliterationDefaults.DEFAULT_SOURCE
    target_scheme: str = TransliterationDefaults.DEFAULT_TARGET
    engine: str = TransliterationDefaults.DEFAULT_ENGINE

    def __post_init__(self) -> None:
        super().__post_init__()
        require_subtitle_input(self.input_path, "Transliteration")
        validate_transliterate(self.engine, self.source_scheme, self.target_scheme, self.profile)


@dataclass(kw_only=True)
class DubConfig(TaskConfigBase):
    """Speak a subtitle file and add the speech to its video or audio as a new track.

    `input_path` is the media to dub, or a subtitle file alone (which can only produce a WAV
    file and needs `reference_audio` to clone a voice). `language` "auto" reads the language
    from the subtitle file name.
    """

    task: Literal["dub"] = "dub"
    subtitle_path: Optional[str] = None
    language: str = DubbingDefaults.LANGUAGE_AUTO
    mode: str = DubbingDefaults.DEFAULT_MODE
    voice: str = DubbingDefaults.VOICE_AUTO
    speakers: str = DubbingDefaults.DEFAULT_SPEAKERS
    max_speakers: int = DubbingDefaults.MAX_SPEAKERS
    max_speedup: float = DubbingDefaults.MAX_SPEEDUP
    output: str = DubbingDefaults.DEFAULT_OUTPUT
    default_track: bool = DubbingDefaults.DEFAULT_TRACK
    device: str = DubbingDefaults.DEVICE_AUTO
    quality: str = DubbingDefaults.DEFAULT_QUALITY
    reference_audio: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if is_subtitle(self.input_path):
            if self.output == DubbingDefaults.OUTPUT_TRACK:
                raise ValueError("A subtitle file has no video to add a track to. Choose a separate WAV file.")
        elif not self.subtitle_path:
            raise ValueError("Choose the subtitle file to speak.")
        elif not is_subtitle(self.subtitle_path):
            raise ValueError("The text to speak must be a subtitle file.")
        if self.reference_audio and is_subtitle(self.reference_audio):
            raise ValueError("The voice to clone must be a video or audio file.")
        validate_dub(
            self.language, self.mode, self.speakers, self.max_speakers, self.max_speedup, self.output, self.device,
            self.voice, self.quality,
        )

    @property
    def text_path(self) -> str:
        """The subtitle file whose text is spoken."""
        return self.subtitle_path or self.input_path

    @property
    def voice_source(self) -> Optional[str]:
        """The recording whose speakers are cloned: the media itself or a separate reference."""
        return self.reference_audio or (None if is_subtitle(self.input_path) else self.input_path)


INPUT_SOURCE = "source"
_STEP_PREFIX = "step:"


@dataclass(kw_only=True)
class GenerateStep:
    """Workflow step: transcribe the workflow's video or audio file."""

    kind: Literal["generate"] = "generate"
    write_output: bool = True
    model_name: str = ModelDefaults.DEFAULT_MODEL
    device: str = ComputeDefaults.DEFAULT_DEVICE
    compute_type: str = ComputeDefaults.DEFAULT_COMPUTE_TYPE
    language: Optional[str] = TranscriptionDefaults.DEFAULT_LANGUAGE
    beam_size: int = TranscriptionDefaults.BEAM_SIZE
    vad_filter: bool = TranscriptionDefaults.VAD_FILTER

    def __post_init__(self) -> None:
        validate_generate(self.model_name, self.device, self.compute_type, self.beam_size)


@dataclass(kw_only=True)
class TranslateStep:
    """Workflow step: translate the text of an earlier step (or of a subtitle source).

    `source_lang` "auto" uses the language the input step produced (for example the language
    a generate step detected).
    """

    kind: Literal["translate"] = "translate"
    input: str = INPUT_SOURCE
    write_output: bool = True
    source_lang: str = TranslationDefaults.DEFAULT_SOURCE_LANG
    target_lang: str = TranslationDefaults.DEFAULT_TARGET_LANG
    engine: str = DEFAULT_TRANSLATION_ENGINE

    def __post_init__(self) -> None:
        validate_translate(self.source_lang, self.target_lang, self.engine)


@dataclass(kw_only=True)
class TransliterateStep:
    """Workflow step: convert the text of an earlier step to another script."""

    kind: Literal["transliterate"] = "transliterate"
    input: str = INPUT_SOURCE
    write_output: bool = True
    source_scheme: str = TransliterationDefaults.DEFAULT_SOURCE
    target_scheme: str = TransliterationDefaults.DEFAULT_TARGET
    engine: str = TransliterationDefaults.DEFAULT_ENGINE

    def __post_init__(self) -> None:
        validate_transliterate(self.engine, self.source_scheme, self.target_scheme)


@dataclass(kw_only=True)
class DubStep:
    """Workflow step: speak the text of an earlier step and add it to the workflow's media."""

    kind: Literal["dub"] = "dub"
    input: str = INPUT_SOURCE
    language: str = DubbingDefaults.LANGUAGE_AUTO
    mode: str = DubbingDefaults.DEFAULT_MODE
    voice: str = DubbingDefaults.VOICE_AUTO
    speakers: str = DubbingDefaults.DEFAULT_SPEAKERS
    max_speakers: int = DubbingDefaults.MAX_SPEAKERS
    max_speedup: float = DubbingDefaults.MAX_SPEEDUP
    output: str = DubbingDefaults.DEFAULT_OUTPUT
    default_track: bool = DubbingDefaults.DEFAULT_TRACK
    device: str = DubbingDefaults.DEVICE_AUTO
    quality: str = DubbingDefaults.DEFAULT_QUALITY

    def __post_init__(self) -> None:
        validate_dub(
            self.language, self.mode, self.speakers, self.max_speakers, self.max_speedup, self.output, self.device,
            self.voice, self.quality,
        )


WorkflowStep = Annotated[
    Union[GenerateStep, TranslateStep, TransliterateStep, DubStep],
    Field(discriminator="kind"),
]


@dataclass(kw_only=True)
class WorkflowConfig(SubtitleOutputConfig):
    """Run several steps on one file, each taking the workflow's file or an earlier step's text.

    The subtitle formats and layout apply to every step that writes subtitles.
    """

    task: Literal["workflow"] = "workflow"
    steps: list[WorkflowStep] = field(default_factory=list)

    def __post_init__(self) -> None:
        super().__post_init__()
        validate_workflow(self.input_path, self.steps)


def step_input_index(value: str) -> Optional[int]:
    """Return the step index an input names ("step:2" -> 2), or None for the workflow's file."""
    if value == INPUT_SOURCE:
        return None
    if value.startswith(_STEP_PREFIX) and value[len(_STEP_PREFIX):].isdigit():
        return int(value[len(_STEP_PREFIX):])
    raise ValueError(f"Unknown step input: {value}.")


def validate_workflow(input_path: str, steps: list) -> None:
    """Check that every step's input exists, comes earlier, and carries text it can use."""
    if not steps:
        raise ValueError("Add at least one step to the workflow.")
    source_is_subtitle = is_subtitle(input_path)
    writers: dict[str, int] = {}
    for number, step in enumerate(steps, 1):
        suffix = _written_suffix(step)
        if suffix is not None:
            if suffix in writers:
                raise ValueError(
                    f"Steps {writers[suffix]} and {number} would write the same files. "
                    "Change one of them, or turn off saving its subtitles."
                )
            writers[suffix] = number
        name = f"Step {number} ({step.kind})"
        if isinstance(step, GenerateStep):
            if source_is_subtitle:
                raise ValueError(f"{name} needs a video or audio file, but the workflow's file is a subtitle.")
            continue
        index = step_input_index(step.input)
        if index is None:
            if not source_is_subtitle:
                raise ValueError(f"{name} needs text: use a subtitle file or an earlier step as its input.")
        elif index >= number - 1:
            raise ValueError(f"{name} can only use a step that comes before it.")
        elif isinstance(steps[index], DubStep):
            raise ValueError(f"{name} can't use step {index + 1}: a dub produces no text.")
        if isinstance(step, DubStep) and source_is_subtitle and step.output == DubbingDefaults.OUTPUT_TRACK:
            raise ValueError(f"{name}: a subtitle file has no video to add a track to. Choose a separate WAV file.")


def _written_suffix(step) -> Optional[str]:
    """File-name suffix of the subtitles a step writes, or None when it writes none."""
    if isinstance(step, DubStep) or not step.write_output:
        return None
    if isinstance(step, GenerateStep):
        return ""
    if isinstance(step, TranslateStep):
        return f"_{step.target_lang}"
    return f"_tr_{step.source_scheme}_{step.target_scheme}"


def validate_dub(
    language: str, mode: str, speakers: str, max_speakers: int, max_speedup: float, output: str, device: str,
    voice: str = DubbingDefaults.VOICE_AUTO,
    quality: str = DubbingDefaults.DEFAULT_QUALITY,
) -> None:
    """Reject unknown dubbing options and out-of-range limits."""
    languages = {code for _, code in DubbingDefaults.LANGUAGES} | {DubbingDefaults.LANGUAGE_AUTO}
    if language not in languages:
        raise ValueError(f"Dubbing doesn't support the language '{language}'.")
    if mode not in {code for _, code, _ in DubbingDefaults.MODES}:
        raise ValueError(f"Unknown dubbing mode: {mode}.")
    if speakers not in {code for _, code in DubbingDefaults.SPEAKERS}:
        raise ValueError(f"Unknown speaker setting: {speakers}.")
    if not 1 <= max_speakers <= DubbingDefaults.MAX_SPEAKERS:
        raise ValueError(f"Detect between 1 and {DubbingDefaults.MAX_SPEAKERS} speakers.")
    low, high = DubbingDefaults.MAX_SPEEDUP_RANGE
    if not low <= max_speedup <= high:
        raise ValueError(f"Maximum speed-up must be between {low:g}x and {high:g}x.")
    if output not in {code for _, code in DubbingDefaults.OUTPUTS}:
        raise ValueError(f"Unknown dubbing output: {output}.")
    if device not in {code for _, code in DubbingDefaults.DEVICES}:
        raise ValueError(f"Unknown device: {device}.")
    if quality not in {code for _, code, _ in DubbingDefaults.QUALITIES}:
        raise ValueError(f"Unknown voice cloning quality: {quality}.")
    validate_voice(voice, mode, language)


def validate_voice(voice: str, mode: str, language: str) -> None:
    """Reject a named voice that belongs to other voices or speaks another language."""
    if voice == DubbingDefaults.VOICE_AUTO:
        return
    option = voice_by_key(voice)
    if option is None or option.engine != mode:
        raise ValueError(f"The voice {voice} isn't one of the chosen voices. Pick another voice.")
    if language != DubbingDefaults.LANGUAGE_AUTO and option.language != language:
        raise ValueError(f"The voice {option.label} doesn't speak '{language}'. Pick another voice.")


def validate_subtitle_output(formats: list[str], max_line_length: int, max_lines: int) -> None:
    """Reject unknown or missing subtitle formats and out-of-range line limits."""
    unknown = sorted(set(formats) - set(SUBTITLE_FORMATS))
    if unknown:
        raise ValueError(f"Unknown subtitle format: {', '.join(unknown)}.")
    if not formats:
        raise ValueError("Select at least one subtitle format.")
    low, high = OutputDefaults.MAX_LINE_LENGTH_RANGE
    if not low <= max_line_length <= high:
        raise ValueError(f"Line length must be between {low} and {high} characters.")
    low, high = OutputDefaults.MAX_LINES_RANGE
    if not low <= max_lines <= high:
        raise ValueError(f"Lines per cue must be between {low} and {high}.")


def validate_generate(model_name: str, device: str, compute_type: str, beam_size: int) -> None:
    """Reject unknown Whisper models, devices, compute types, and beam sizes."""
    if model_name != AUTO and model_name not in ModelDefaults.SUPPORTED_MODELS:
        raise ValueError(f"Unknown Whisper model: {model_name}.")
    if device not in ComputeDefaults.SUPPORTED_DEVICES:
        raise ValueError(f"Unknown device: {device}.")
    if compute_type not in ComputeDefaults.SUPPORTED_COMPUTE_TYPES:
        raise ValueError(f"Unknown compute type: {compute_type}.")
    if beam_size < 1:
        raise ValueError("Beam size must be at least 1.")


def validate_translate(
    source_lang: str, target_lang: str, engine: str = DEFAULT_TRANSLATION_ENGINE, profile: str = "",
) -> None:
    """Reject identical languages, unknown models, and pairs the model can't reach.

    An "auto" source is resolved at run time, so its pair is only checked then.
    """
    if source_lang == target_lang:
        raise ValueError("Choose a target language different from the source language.")
    if engine not in TRANSLATION_ENGINE_KEYS:
        raise ValueError(f"Unknown translation model: '{engine}'.")
    if source_lang != TranslationDefaults.DEFAULT_SOURCE_LANG:
        resolved = profiles.translation_engine(engine, profile, source_lang, target_lang)
        translation_route(resolved, source_lang, target_lang)


def validate_transliterate(engine: str, source_scheme: str, target_scheme: str, profile: str = "") -> None:
    """Reject identical scripts and script pairs the chosen engine cannot convert."""
    if engine not in (AUTO, TransliterationDefaults.ENGINE_RULE, TransliterationDefaults.ENGINE_NEURAL):
        raise ValueError(f"Unknown transliteration engine: {engine}.")
    if source_scheme == target_scheme:
        raise ValueError("Choose two different transliteration scripts.")
    engine = profiles.transliteration_engine(engine, profile, source_scheme, target_scheme)
    if not transliteration_supported(engine, source_scheme, target_scheme):
        raise ValueError(f"The {engine} engine can't convert {source_scheme} to {target_scheme}.")


def require_subtitle_input(path: str, action: str) -> None:
    """Raise when a subtitle-only task receives a video or audio file."""
    if not is_subtitle(path):
        raise ValueError(f"{action} needs a subtitle file. Generate subtitles for this file first.")
