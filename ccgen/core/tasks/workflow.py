# workflow.py - run a user-built chain of steps on one file, passing text between them in memory
#
# Every step names its input: the workflow's own file or an earlier step. Nothing depends on a
# step silently: a translation of a transcript takes that transcript's detected language, and a
# step whose input can't provide what it needs was rejected when the config was validated.

import logging
from typing import Optional

from ccgen.config.defaults import DubbingDefaults
from ccgen.core.audio import load_audio
from ccgen.core.cues import CueLayout
from ccgen.core.subtitle_parser import is_subtitle
from ccgen.core.tasks.base import RunContext, Task, TaskResult, Track
from ccgen.core.tasks.configs import (
    DubStep,
    GenerateStep,
    TranslateStep,
    TransliterateStep,
    WorkflowConfig,
    step_input_index,
)
from ccgen.core.tasks.dub import DUB_STAGES, Dubber, dub_settings
from ccgen.core.tasks.generate import transcribe
from ccgen.core.tasks.outputs import write_track
from ccgen.core.tasks.translate import create_translator, load_subtitle_track, translate_track
from ccgen.core.tasks.transliterate import transliterate_track, transliteration_suffix
from ccgen.engines.captions import create_engine as create_caption_engine
from ccgen.engines.captions.base import CaptionEngine
from ccgen.engines.transliteration import create_engine as create_transliteration_engine

_log = logging.getLogger(__name__)

# Speech recognition models all load in prepare(), so their "load" stages come first.
_STEP_STAGES = {
    "generate": ["transcribe"],
    "translate": ["translate"],
    "transliterate": ["transliterate"],
    "dub": DUB_STAGES,
}


class WorkflowTask(Task[WorkflowConfig]):
    """Run every step of a workflow on one file."""

    def __init__(self, config: WorkflowConfig) -> None:
        super().__init__(config)
        self._layout = CueLayout(max_line_length=config.max_line_length, max_lines=config.max_lines)
        self._captioners: dict[int, CaptionEngine] = {
            i: create_caption_engine(model_name=s.model_name, device=s.device, compute_type=s.compute_type)
            for i, s in enumerate(config.steps)
            if isinstance(s, GenerateStep)
        }

    @property
    def stages(self) -> list[str]:
        """Model loading for every generate step, then every stage of every step, in order."""
        loads = ["load"] * len(self._captioners)
        return loads + [stage for step in self.config.steps for stage in _STEP_STAGES[step.kind]]

    def _prepare(self, ctx: RunContext) -> None:
        # Speech recognition models load up front; translation, transliteration, and voice
        # models load when their step runs, once the language they need is known.
        for engine in self._captioners.values():
            ctx.begin("load", "Loading speech recognition model...")
            engine.load(ctx.status, ctx.progress)

    def _run(self, ctx: RunContext) -> TaskResult:
        cfg = self.config
        tracks: list[Optional[Track]] = []
        files: list[str] = []
        languages: dict[str, str] = {}
        source_track: Optional[Track] = None
        detected = ""
        for index, step in enumerate(cfg.steps):
            ctx.status(f"Step {index + 1} of {len(cfg.steps)}: {step.kind}")
            if isinstance(step, GenerateStep):
                track = self._generate(index, step, ctx)
                detected = detected or track.language
                if step.write_output:
                    files += self._write(track, "", languages, ctx)
                tracks.append(track)
                continue
            source = step_input_index(step.input)
            if source is None:
                source_track = source_track or load_subtitle_track(cfg.input_path)
                text = source_track
            else:
                text = tracks[source]
                assert text is not None  # validate_workflow rejects dub steps as inputs
            if isinstance(step, TranslateStep):
                track = self._translate(step, text, ctx)
                if step.write_output:
                    files += self._write(track, f"_{step.target_lang}", languages, ctx)
            elif isinstance(step, TransliterateStep):
                ctx.begin("transliterate", "Transliterating...")
                engine = create_transliteration_engine(
                    step.engine, source_scheme=step.source_scheme, target_scheme=step.target_scheme,
                )
                track = transliterate_track(text, engine, step.source_scheme, step.target_scheme, ctx)
                if step.write_output:
                    suffix = transliteration_suffix(step.source_scheme, step.target_scheme)
                    files += self._write(track, suffix, languages, ctx)
            else:
                path, language = self._dub(step, text, ctx)
                files.append(path)
                languages[path] = language
                track = None
            tracks.append(track)
        return TaskResult(
            success=True, input_path=cfg.input_path, output_files=files, detected_language=detected,
            output_languages=languages,
        )

    def _generate(self, index: int, step: GenerateStep, ctx: RunContext) -> Track:
        """Transcribe the workflow's media file."""
        ctx.begin("transcribe", "Reading audio...")
        audio = load_audio(self.config.input_path)
        ctx.status("Transcribing...")
        track = transcribe(
            self._captioners[index], audio, step.language, step.beam_size, step.vad_filter, self._layout, ctx,
        )
        if not track.cues:
            ctx.warn("No speech was found, so the transcript is empty.")
        return track

    def _translate(self, step: TranslateStep, text: Track, ctx: RunContext) -> Track:
        """Translate an earlier step's text, taking its language when the step says auto."""
        ctx.begin("translate", "Translating...")
        source = text.language if step.source_lang == "auto" else step.source_lang
        if not source:
            raise ValueError("The language of this step's input is unknown. Choose its source language.")
        engine, meaning = create_translator(step.engine, source, step.target_lang, step.meaning_check)
        return translate_track(text, engine, source, step.target_lang, ctx, meaning)

    def _dub(self, step: DubStep, text: Track, ctx: RunContext) -> tuple[str, str]:
        """Speak an earlier step's text and add it to the workflow's media; return (path, language)."""
        language = text.language if step.language == DubbingDefaults.LANGUAGE_AUTO else step.language
        if not language:
            raise ValueError("The language of this step's input is unknown. Choose the speech language.")
        media = None if is_subtitle(self.config.input_path) else self.config.input_path
        dubber = Dubber(dub_settings(step), language, media is not None, ctx)
        dubber.load(ctx)
        path = dubber.dub(
            Track(cues=text.cues, language=language), media, None, self.config.input_path, self.config.output_dir, ctx,
        )
        return path, language

    def _write(self, track: Track, suffix: str, languages: dict[str, str], ctx: RunContext) -> list[str]:
        """Write one step's subtitles in the workflow's formats, noting their language."""
        cfg = self.config
        ctx.status("Writing subtitle files...")
        files = write_track(track, cfg.input_path, suffix, cfg.formats, self._layout, cfg.output_dir)
        languages.update(dict.fromkeys(files, track.language))
        return files
