# generate.py - transcribe a video or audio file into subtitle cues

import logging
from typing import Optional

import numpy as np

from ccgen.config.profiles import whisper_model
from ccgen.core import Segment
from ccgen.core.audio import load_audio
from ccgen.core.cues import CueBuilder, CueLayout, finalize_timing
from ccgen.core.tasks.base import RunContext, Task, TaskResult, Track
from ccgen.core.tasks.configs import GenerateConfig
from ccgen.core.tasks.outputs import write_track
from ccgen.engines.captions import create_engine as create_caption_engine
from ccgen.engines.captions.base import CaptionEngine

_log = logging.getLogger(__name__)


def transcribe(
    engine: CaptionEngine,
    audio: np.ndarray,
    language: Optional[str],
    beam_size: int,
    vad_filter: bool,
    layout: CueLayout,
    ctx: RunContext,
) -> Track:
    """Transcribe audio into readable cues, streaming each cue as it forms.

    Cues are streamed with their provisional timing; once timing is finalized, cues whose start
    or end moved are streamed again under the same id so the caller's view matches the files.
    """
    builder = CueBuilder(layout)
    live: dict[int, tuple[float, float]] = {}

    def stream(cues: list[Segment]) -> None:
        for cue in cues:
            live[cue["id"]] = (cue["start"], cue["end"])
            ctx.segment(cue)

    raw = engine.transcribe(
        audio,
        language=language,
        beam_size=beam_size,
        vad_filter=vad_filter,
        progress_cb=ctx.status,
        segment_cb=lambda segment: stream(builder.add(segment)),
        progress_num_cb=ctx.progress,
    )
    # Engines are expected to stream every segment, but anything they returned without
    # streaming still has to become cues.
    for segment in raw[builder.source_count:]:
        stream(builder.add(segment))
    stream(builder.flush())
    cues = finalize_timing(builder.cues, layout)
    for cue in cues:
        if live.get(cue["id"]) != (cue["start"], cue["end"]):
            ctx.segment(cue)
    detected = raw[0]["language"] if raw else (language or "")
    return Track(cues=cues, language=detected)


class GenerateTask(Task[GenerateConfig]):
    """Transcribe one media file and write its subtitles."""

    def __init__(self, config: GenerateConfig) -> None:
        super().__init__(config)
        self._layout = CueLayout(max_line_length=config.max_line_length, max_lines=config.max_lines)
        self._engine = create_caption_engine(
            model_name=whisper_model(config.model_name, config.profile), device=config.device,
            compute_type=config.compute_type,
        )

    @property
    def stages(self) -> list[str]:
        """Model loading, then transcription."""
        return ["load", "transcribe"]

    def _prepare(self, ctx: RunContext) -> None:
        ctx.begin("load", "Loading speech recognition model...")
        self._engine.load(ctx.status, ctx.progress)

    def _run(self, ctx: RunContext) -> TaskResult:
        cfg = self.config
        ctx.begin("transcribe", "Reading audio...")
        audio = load_audio(cfg.input_path)
        ctx.status("Transcribing...")
        track = transcribe(self._engine, audio, cfg.language, cfg.beam_size, cfg.vad_filter, self._layout, ctx)
        if not track.cues:
            ctx.warn("No speech was found, so the subtitle files are empty.")
        ctx.status("Writing subtitle files...")
        files = write_track(track, cfg.input_path, "", cfg.formats, self._layout, cfg.output_dir)
        return TaskResult(
            success=True, input_path=cfg.input_path, output_files=files,
            detected_language=track.language, output_languages=dict.fromkeys(files, track.language),
        )
