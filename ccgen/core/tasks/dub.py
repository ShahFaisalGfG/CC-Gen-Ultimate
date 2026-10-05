# dub.py - speak subtitles in a chosen or cloned voice and add the speech to the media

import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Optional, Union

import av
from av.stream import Disposition

from ccgen.config.defaults import DubbingDefaults
from ccgen.config.voices import ENGINE_LABELS, resolve_voice
from ccgen.core.audio import load_audio
from ccgen.core.dubbing import attach_track, synthesize_track
from ccgen.core.speakers import assign_speakers, reference_clips
from ccgen.core.subtitle_parser import is_subtitle
from ccgen.core.tasks.base import RunContext, Task, TaskResult, Track
from ccgen.core.tasks.configs import DubConfig, DubStep
from ccgen.core.tasks.outputs import output_path
from ccgen.core.tasks.translate import load_subtitle_track
from ccgen.engines.speech import CloningEngine, create_engine
from ccgen.engines.speech.base import REFERENCE_RATE

_log = logging.getLogger(__name__)

DUB_STAGES = ["load", "speakers", "speak", "write"]
# A separate reference recording is trimmed to this length; XTTS only conditions on the start.
_REFERENCE_MAX_S = 30


@dataclass
class DubSettings:
    """How to speak a track; shared by the dub task and the workflow's dub step."""

    mode: str
    voice: str
    speakers: str
    max_speakers: int
    max_speedup: float
    output: str
    default_track: bool
    device: str
    script_bridge: bool = DubbingDefaults.SCRIPT_BRIDGE


class Dubber:
    """Loads one speech engine and turns a track into dubbed media."""

    def __init__(self, settings: DubSettings, language: str, can_clone: bool, ctx: RunContext) -> None:
        self.settings = settings
        self.language = language
        self.voice, warning = resolve_voice(language, settings.mode, settings.voice, can_clone, settings.script_bridge)
        if warning:
            ctx.warn(warning)
        self.engine = create_engine(self.voice, settings.device)

    def load(self, ctx: RunContext) -> None:
        """Download (first use) and load the speech model."""
        ctx.begin("load", f"Loading {ENGINE_LABELS[self.voice.engine]}...")
        self.engine.load(ctx.status, ctx.progress)

    def dub(
        self,
        track: Track,
        media_path: Optional[str],
        reference_audio: Optional[str],
        out_base: str,
        output_dir: Optional[str],
        ctx: RunContext,
    ) -> str:
        """Speak `track` and write the dubbed media (or a WAV file); return the written path.

        `media_path` is the video or audio the cue times refer to and the dub is added to (None
        when only a subtitle file was given). `reference_audio` is a separate recording to clone
        instead of the media's own speakers.
        """
        speakers = self._prepare_speakers(track, media_path, reference_audio, ctx)
        directory = output_dir or os.path.dirname(os.path.abspath(out_base))
        os.makedirs(directory, exist_ok=True)
        fd, wav_path = tempfile.mkstemp(prefix=".ccgen-dub-", suffix=".wav", dir=directory)
        os.close(fd)
        try:
            ctx.begin("speak", f"Speaking {len(track.cues)} lines on {self.engine.device_label}...")
            report = synthesize_track(
                track.cues, speakers, self.engine, self.settings.max_speedup, wav_path,
                progress=ctx.progress, cancelled=ctx.is_cancelled,
            )
            for warning in report.warnings():
                ctx.warn(warning)
            ctx.begin("write", "Writing the dubbed file...")
            return self._publish(wav_path, media_path, out_base, output_dir, ctx)
        finally:
            if os.path.exists(wav_path):
                os.unlink(wav_path)

    def _prepare_speakers(
        self, track: Track, media_path: Optional[str], reference_audio: Optional[str], ctx: RunContext,
    ) -> list[int]:
        """Find each cue's speaker and register their voices with a cloning engine."""
        ctx.begin("speakers", "Listening to the original voices...")
        single = [0] * len(track.cues)
        if not isinstance(self.engine, CloningEngine):
            return single
        if reference_audio:
            audio = load_audio(reference_audio, REFERENCE_RATE)[: _REFERENCE_MAX_S * REFERENCE_RATE]
            self.engine.set_speakers({0: [audio]})
            return single
        if media_path is None:
            raise RuntimeError("Voice cloning needs the original recording.")
        audio = load_audio(media_path, REFERENCE_RATE)
        speakers = single
        if self.settings.speakers != DubbingDefaults.SPEAKERS_SINGLE:
            speakers = assign_speakers(
                track.cues, audio, REFERENCE_RATE, self.engine.embed, self.settings.max_speakers, ctx.progress,
            )
        references = reference_clips(track.cues, audio, REFERENCE_RATE, speakers)
        ctx.status(f"Cloning {len(references)} voice{'s' if len(references) != 1 else ''}...")
        self.engine.set_speakers(references)
        return speakers

    def _publish(
        self, wav_path: str, media_path: Optional[str], out_base: str, output_dir: Optional[str], ctx: RunContext,
    ) -> str:
        """Move the WAV into place, or mux it into a copy of the media."""
        suffix = f"_dub_{self.language}"
        if self.settings.output == DubbingDefaults.OUTPUT_WAV or media_path is None:
            final = output_path(out_base, suffix, ".wav", output_dir)
            os.replace(wav_path, final)
            return final
        final = output_path(media_path, suffix, _container_ext(media_path), output_dir)
        title = f"Dub ({self.language}, {ENGINE_LABELS[self.voice.engine]})"
        notes = attach_track(
            media_path, wav_path, final, title, self.language, self.settings.default_track, ctx.is_cancelled,
        )
        for note in notes:
            ctx.warn(note)
        return final


def _container_ext(media_path: str) -> str:
    """Matroska video for anything with real video, Matroska audio otherwise (cover art isn't video)."""
    with av.open(media_path) as container:
        has_video = any(
            not stream.disposition & Disposition.attached_pic for stream in container.streams.video
        )
    return ".mkv" if has_video else ".mka"


class DubTask(Task[DubConfig]):
    """Dub one media file (or speak one subtitle file) with the configured voice."""

    def __init__(self, config: DubConfig) -> None:
        super().__init__(config)
        self._track: Optional[Track] = None
        self._dubber: Optional[Dubber] = None

    @property
    def stages(self) -> list[str]:
        """Loading the voice, finding speakers, speaking, and writing the file."""
        return DUB_STAGES

    @property
    def media_path(self) -> Optional[str]:
        """The video or audio being dubbed; None when only a subtitle file was given."""
        return None if is_subtitle(self.config.input_path) else self.config.input_path

    def _prepare(self, ctx: RunContext) -> None:
        cfg = self.config
        track = load_subtitle_track(cfg.text_path)
        language = track.language if cfg.language == DubbingDefaults.LANGUAGE_AUTO else cfg.language
        if not language:
            raise ValueError(
                f"Can't tell which language {os.path.basename(cfg.text_path)} is in. "
                "Choose the speech language, or name the file with a suffix such as movie_ur.srt."
            )
        self._track = Track(cues=track.cues, language=language)
        can_clone = bool(cfg.reference_audio or self.media_path)
        self._dubber = Dubber(dub_settings(cfg), language, can_clone, ctx)
        self._dubber.load(ctx)

    def _run(self, ctx: RunContext) -> TaskResult:
        cfg = self.config
        if self._track is None or self._dubber is None:
            raise RuntimeError("prepare() must run before run().")
        if not self._track.cues:
            raise ValueError(f"{os.path.basename(cfg.text_path)} has no lines to speak.")
        for cue in self._track.cues:
            ctx.segment(cue)
        path = self._dubber.dub(self._track, self.media_path, cfg.reference_audio, cfg.text_path, cfg.output_dir, ctx)
        language = self._dubber.language
        return TaskResult(
            success=True, input_path=cfg.input_path, output_files=[path], detected_language=language,
            output_languages={path: language},
        )


def dub_settings(cfg: Union[DubConfig, DubStep]) -> DubSettings:
    """Pick the speech settings out of a dub config or a workflow's dub step."""
    return DubSettings(
        mode=cfg.mode, voice=cfg.voice, speakers=cfg.speakers, max_speakers=cfg.max_speakers,
        max_speedup=cfg.max_speedup, output=cfg.output, default_track=cfg.default_track, device=cfg.device,
        script_bridge=cfg.script_bridge,
    )
