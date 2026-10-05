# translate.py - translate subtitle cues into another language
#
# Cues are often half-sentence fragments; translating them one by one loses the context a
# sentence-level model needs, especially between languages with different word order (e.g.
# English to Urdu). Whole sentences are translated, then spread back over their cues.

import logging
import os
from typing import Optional

from ccgen.config.capabilities import language_from_filename
from ccgen.core import Segment, TranslatedSegment
from ccgen.core.cues import CueLayout, join_unit_text, sentence_units, spread_translation
from ccgen.core.subtitle_parser import parse_subtitle
from ccgen.core.tasks.base import RunContext, Task, TaskResult, Track
from ccgen.core.tasks.configs import TranslateConfig
from ccgen.core.tasks.outputs import write_track
from ccgen.engines.translation import create_engine as create_translation_engine
from ccgen.engines.translation.base import TranslationEngine
from ccgen.engines.translation.fidelity import DOUBT_THRESHOLD, MeaningCheck
from ccgen.utils.callbacks import JobCancelled

_log = logging.getLogger(__name__)


def load_subtitle_track(path: str, language: str = "") -> Track:
    """Parse a subtitle file into a track, taking its language from `language` or the file name."""
    language = language or language_from_filename(path)
    cues = parse_subtitle(path)
    for cue in cues:
        cue["language"] = language
    return Track(cues=cues, language=language)


def resolve_source(requested: str, track: Track, input_path: str) -> str:
    """Return the explicit source language, or the track's own language for "auto"."""
    if requested != "auto":
        return requested
    if track.language:
        return track.language
    raise ValueError(
        f"Can't tell which language {os.path.basename(input_path)} is in. Choose the source language, "
        "or name the file with a language suffix such as movie_en.srt."
    )


def translate_track(
    track: Track,
    engine: TranslationEngine,
    source: str,
    target: str,
    ctx: RunContext,
    meaning: Optional[MeaningCheck] = None,
) -> Track:
    """Translate whole sentences of `track`, then spread each translation back over its cues.

    With `meaning`, sentences whose translation drifts from the original are reported by their
    subtitle numbers so they can be reviewed.
    """
    if source == target:
        raise ValueError(f"The subtitles are already in '{target}'. Choose a different target language.")
    cues = track.cues
    if not cues:
        return Track(cues=[], language=target)
    units = sentence_units(cues)
    unit_segments = [
        Segment(
            id=idx,
            start=cues[members[0]]["start"],
            end=cues[members[-1]]["end"],
            text=join_unit_text([cues[i] for i in members], source),
            words=[],
            language=source,
        )
        for idx, members in enumerate(units)
    ]

    def spread(unit: TranslatedSegment) -> list[TranslatedSegment]:
        return spread_translation([cues[i] for i in units[unit["id"]]], unit["translated"], target)

    def on_unit(unit: TranslatedSegment) -> None:
        for part in spread(unit):
            ctx.segment(part)

    _log.debug("Translating %d sentences (%d cues): %s → %s", len(units), len(cues), source, target)
    try:
        engine.set_pair(source, target)
        engine.ensure_model(ctx.status, ctx.progress)
        translated_units = engine.translate_segments(unit_segments, ctx.status, ctx.progress, on_unit)
        if meaning is not None:
            _report_doubtful(translated_units, units, meaning, target, ctx)
    except JobCancelled:
        raise
    except Exception as e:
        _log.error("Translation failed: %r", e, exc_info=True)
        raise RuntimeError(f"Translation failed: {e}") from e
    parts = [part for unit in translated_units for part in spread(unit)]
    return Track(
        cues=[
            Segment(id=p["id"], start=p["start"], end=p["end"], text=p["translated"], words=[], language=target)
            for p in parts
        ],
        language=target,
    )


def _report_doubtful(
    translated: list[TranslatedSegment], units: list[list[int]], meaning: MeaningCheck, target: str, ctx: RunContext,
) -> None:
    """Warn about sentences whose translation may not say the same as the original."""
    filled = [unit for unit in translated if unit["original"] and unit["translated"]]
    if not filled:
        return
    ctx.status("Checking the translation against the original...")
    meaning.ensure(ctx.status, ctx.progress)
    scores = meaning.scores([u["original"] for u in filled], [u["translated"] for u in filled], target)
    numbers = [units[u["id"]][0] + 1 for u, score in zip(filled, scores) if score < DOUBT_THRESHOLD]
    if numbers:
        listed = ", ".join(str(n) for n in numbers[:10]) + (" ..." if len(numbers) > 10 else "")
        ctx.warn(
            f"{len(numbers)} line(s) may not say the same as the original (subtitle {listed}). "
            "Review them, or try another translation model in Preferences."
        )


def create_translator(engine: str, source: str, target: str, meaning_check: bool) -> tuple[TranslationEngine, Optional[MeaningCheck]]:
    """The engine a translate task or step uses, and its meaning check when that is on."""
    meaning = MeaningCheck() if meaning_check else None
    return create_translation_engine(engine, source_lang=source, target_lang=target, meaning=meaning), meaning


class TranslateTask(Task[TranslateConfig]):
    """Translate one subtitle file and write the translated subtitles."""

    def __init__(self, config: TranslateConfig) -> None:
        super().__init__(config)
        self._layout = CueLayout(max_line_length=config.max_line_length, max_lines=config.max_lines)
        self._engine, self._meaning = create_translator(
            config.engine, config.source_lang, config.target_lang, config.meaning_check,
        )

    @property
    def stages(self) -> list[str]:
        """Translation only; the language model is installed as part of it."""
        return ["translate"]

    def _run(self, ctx: RunContext) -> TaskResult:
        cfg = self.config
        ctx.begin("translate", "Reading subtitle file...")
        track = load_subtitle_track(cfg.input_path)
        for cue in track.cues:
            ctx.segment(cue)
        source = resolve_source(cfg.source_lang, track, cfg.input_path)
        ctx.status("Translating...")
        translated = translate_track(track, self._engine, source, cfg.target_lang, ctx, self._meaning)
        ctx.status("Writing subtitle files...")
        files = write_track(
            translated, cfg.input_path, f"_{cfg.target_lang}", cfg.formats, self._layout, cfg.output_dir,
        )
        return TaskResult(
            success=True, input_path=cfg.input_path, output_files=files,
            detected_language=source, output_languages=dict.fromkeys(files, cfg.target_lang),
        )
