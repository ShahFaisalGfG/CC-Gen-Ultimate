# transliterate.py - convert subtitle cues from one script to another

import logging

from ccgen.config.defaults import TransliterationDefaults
from ccgen.config.profiles import transliteration_engine
from ccgen.core import Segment
from ccgen.core.cues import CueLayout
from ccgen.core.tasks.base import RunContext, Task, TaskResult, Track
from ccgen.core.tasks.configs import TransliterateConfig
from ccgen.core.tasks.outputs import write_track
from ccgen.core.tasks.translate import load_subtitle_track
from ccgen.engines.transliteration import create_engine as create_transliteration_engine
from ccgen.engines.transliteration.base import TransliterationEngine
from ccgen.utils.callbacks import JobCancelled

_log = logging.getLogger(__name__)
_SCHEME_LABELS = {code: label for label, code in TransliterationDefaults.SCHEMES}


def transliterate_track(
    track: Track, engine: TransliterationEngine, source_scheme: str, target_scheme: str, ctx: RunContext,
) -> Track:
    """Convert every cue of `track` to `target_scheme`; the spoken language stays the same.

    Text that isn't in `source_scheme` passes through as it is, so a result whose letters all
    match the input means the wrong script was chosen; that is reported as a warning.
    """
    try:
        converted = engine.transliterate_segments(track.cues, ctx.status, ctx.progress, ctx.segment)
    except JobCancelled:
        raise
    except Exception as e:
        _log.error("Transliteration failed: %r", e, exc_info=True)
        raise RuntimeError(f"Transliteration failed: {e}") from e
    if any(_letters(c["text"]) for c in track.cues) and all(
        _letters(c["transliterated"]) == _letters(cue["text"]) for c, cue in zip(converted, track.cues)
    ):
        ctx.warn(
            f"Nothing was written in {_SCHEME_LABELS.get(source_scheme, source_scheme)}, so the text is "
            "unchanged. Choose the script the subtitles are written in."
        )
    return Track(
        cues=[
            Segment(
                id=c["id"], start=c["start"], end=c["end"], text=c["transliterated"],
                words=[], language=track.language,
            )
            for c in converted
        ],
        language=track.language,
        script=target_scheme,
    )


def _letters(text: str) -> str:
    """Just the letters of `text`; engines also convert punctuation (". " to "۔ " for Urdu)."""
    return "".join(ch for ch in text if ch.isalpha())


def transliteration_suffix(source_scheme: str, target_scheme: str) -> str:
    """Output file suffix for a transliteration, e.g. `_tr_ur_roman`."""
    return f"_tr_{source_scheme}_{target_scheme}"


class TransliterateTask(Task[TransliterateConfig]):
    """Transliterate one subtitle file and write the converted subtitles."""

    def __init__(self, config: TransliterateConfig) -> None:
        super().__init__(config)
        self._layout = CueLayout(max_line_length=config.max_line_length, max_lines=config.max_lines)
        engine = transliteration_engine(config.engine, config.profile, config.source_scheme, config.target_scheme)
        self._engine = create_transliteration_engine(
            engine, source_scheme=config.source_scheme, target_scheme=config.target_scheme,
        )

    @property
    def stages(self) -> list[str]:
        """Transliteration only; a neural model loads as part of it."""
        return ["transliterate"]

    def _run(self, ctx: RunContext) -> TaskResult:
        cfg = self.config
        ctx.begin("transliterate", "Reading subtitle file...")
        track = load_subtitle_track(cfg.input_path)
        for cue in track.cues:
            ctx.segment(cue)
        ctx.status("Transliterating...")
        converted = transliterate_track(track, self._engine, cfg.source_scheme, cfg.target_scheme, ctx)
        ctx.status("Writing subtitle files...")
        suffix = transliteration_suffix(cfg.source_scheme, cfg.target_scheme)
        files = write_track(converted, cfg.input_path, suffix, cfg.formats, self._layout, cfg.output_dir)
        return TaskResult(
            success=True, input_path=cfg.input_path, output_files=files,
            detected_language=track.language, output_languages=dict.fromkeys(files, track.language),
        )
