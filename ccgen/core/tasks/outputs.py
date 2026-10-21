# outputs.py - output file naming and subtitle writing shared by every task
#
# Names follow the input file: movie.mp4 -> movie.srt (transcript), movie_ur.srt (translation),
# movie_tr_ur_roman.srt (transliteration), movie_dub_ur.mkv (dub). A trailing language suffix on
# a subtitle input (movie_en.srt, movie.en.srt) is dropped first, so translating it to Urdu gives
# movie_ur.srt.

import os
from typing import Callable, Optional

from ccgen.config.capabilities import split_language
from ccgen.core.cues import CueLayout
from ccgen.core.subtitle import derive_output_path, write_ass, write_lrc, write_sbv, write_srt, write_vtt
from ccgen.core.subtitle_parser import is_subtitle
from ccgen.core.tasks.base import Track

_WRITERS: dict[str, Callable[..., str]] = {
    "srt": write_srt,
    "vtt": write_vtt,
    "lrc": write_lrc,
    "ass": write_ass,
    "sbv": write_sbv,
}


def output_base(input_path: str) -> str:
    """Return a subtitle input's path without the language tag its name ends with.

    `movie_en.srt` and `movie.en.srt` both give `movie.srt`. Media names are kept whole, so
    `talk_en.mp4` and `talk_ur.mp4` never share an output name.
    """
    return split_language(input_path)[0] if is_subtitle(input_path) else input_path


def output_path(input_path: str, suffix: str, ext: str, output_dir: Optional[str]) -> str:
    """Build an output path next to the input, or inside `output_dir` when one is set."""
    candidate = derive_output_path(output_base(input_path), suffix, ext)
    if output_dir:
        return os.path.join(output_dir, os.path.basename(candidate))
    return candidate


def write_track(
    track: Track,
    input_path: str,
    suffix: str,
    formats: list[str],
    layout: CueLayout,
    output_dir: Optional[str],
) -> list[str]:
    """Write `track` in every requested subtitle format and return the written paths."""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    lang_layout = layout.for_language(track.script or track.language)
    written: list[str] = []
    for fmt in formats:
        path = output_path(input_path, suffix, f".{fmt}", output_dir)
        if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(input_path)):
            raise ValueError(f"Writing {os.path.basename(path)} would overwrite the input file.")
        _WRITERS[fmt](
            track.cues, path,
            max_line_length=lang_layout.max_line_length, max_lines=lang_layout.max_lines,
        )
        written.append(path)
    return written
