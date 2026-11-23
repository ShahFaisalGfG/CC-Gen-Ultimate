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
from ccgen.core.tasks.configs import EXISTING_KEEP_BOTH, EXISTING_REPLACE, EXISTING_SKIP

__all__ = ["EXISTING_KEEP_BOTH", "EXISTING_REPLACE", "EXISTING_SKIP", "kept_message", "output_base",
           "output_path", "place", "write_track"]

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


def place(path: str, existing: str) -> Optional[str]:
    """Where to write `path` under the `existing` choice: the path itself, a free "name (2)" beside
    it, or None to keep the file that is there (skip)."""
    if not os.path.exists(path) or existing == EXISTING_REPLACE:
        return path
    if existing == EXISTING_SKIP:
        return None
    base, ext = os.path.splitext(path)
    number = 2
    while os.path.exists(f"{base} ({number}){ext}"):
        number += 1
    return f"{base} ({number}){ext}"


def kept_message(path: str) -> str:
    """The note for an output that was already there and kept."""
    return f"Kept the existing {os.path.basename(path)}; the new one wasn't saved."


def write_track(
    track: Track,
    input_path: str,
    suffix: str,
    formats: list[str],
    layout: CueLayout,
    output_dir: Optional[str],
    existing: str = EXISTING_REPLACE,
    warn: Optional[Callable[[str], None]] = None,
) -> list[str]:
    """Write `track` in every requested subtitle format and return the written paths.

    A file already there is handled as `existing` says; a kept one is reported through `warn`.
    """
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    lang_layout = layout.for_language(track.script or track.language)
    written: list[str] = []
    for fmt in formats:
        planned = output_path(input_path, suffix, f".{fmt}", output_dir)
        if os.path.normcase(os.path.abspath(planned)) == os.path.normcase(os.path.abspath(input_path)):
            raise ValueError(f"Writing {os.path.basename(planned)} would overwrite the input file.")
        path = place(planned, existing)
        if path is None:
            if warn is not None:
                warn(kept_message(planned))
            continue
        _WRITERS[fmt](
            track.cues, path,
            max_line_length=lang_layout.max_line_length, max_lines=lang_layout.max_lines,
        )
        written.append(path)
    return written
