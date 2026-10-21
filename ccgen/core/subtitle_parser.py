# subtitle_parser.py — parse SRT, VTT, LRC, ASS/SSA, and SBV files into Segment lists

import html
import logging
import os
import re

from ccgen.core import Segment

_log = logging.getLogger(__name__)

_SUBTITLE_EXTS = frozenset({".srt", ".vtt", ".lrc", ".ass", ".ssa", ".sbv"})
_ARROW = re.compile(r"-->")
_ARROW_SPLIT = re.compile(r"\s*-->\s*")
_SBV_TIME_LINE = re.compile(r"^\d+:\d{2}:\d{2}\.\d{3}\s*,\s*\d+:\d{2}:\d{2}\.\d{3}$")
_SBV_SPLIT = re.compile(r"\s*,\s*")
# A last LRC line has no following timestamp to derive its end from, so it gets a fixed duration.
_LRC_LAST_LINE_DURATION_S = 4.0
_LRC_LINE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\](.*)$")
_ASS_OVERRIDE_TAG = re.compile(r"\{.*?\}")
# Styling inside SRT, VTT, and SBV text: HTML-like tags (<i>, <font color=...>, VTT <v Speaker>,
# <c.class>, and <00:01.000> karaoke timestamps) and ASS-style position tags ({\an8}). They are
# formatting, not words, so they are never translated, transliterated, or spoken.
_MARKUP_TAG = re.compile(r"</?(?:[a-zA-Z][^<>]*|\d[\d:.]*)>|\{\\[^}]*\}")


def parse_subtitle(path: str) -> list[Segment]:
    """Detect file type and parse SRT, VTT, LRC, ASS/SSA, or SBV into a Segment list."""
    try:
        ext = os.path.splitext(path)[1].lower()
        _log.info("Parsing subtitle file: %s (%s)", os.path.basename(path), ext)
        if ext == ".srt":
            segments = _parse_srt(path)
        elif ext == ".vtt":
            segments = _parse_vtt(path)
        elif ext == ".sbv":
            segments = _parse_sbv(path)
        elif ext == ".lrc":
            segments = _parse_lrc(path)
        elif ext in (".ass", ".ssa"):
            segments = _parse_ass(path)
        else:
            raise ValueError(f"Unsupported subtitle extension: {ext!r}")
        _log.info("Parsed %d segments from %s", len(segments), os.path.basename(path))
        return segments
    except (OSError, ValueError):
        raise
    except Exception as e:
        _log.error("Subtitle parse failed for %s: %r", path, e, exc_info=True)
        raise OSError(f"Subtitle parse failed: {e}") from e


def is_subtitle(path: str) -> bool:
    """Return True when the path points to a recognised subtitle file."""
    return os.path.splitext(path)[1].lower() in _SUBTITLE_EXTS


def _parse_srt(path: str) -> list[Segment]:
    """Parse an SRT file into a list of Segments."""
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    segments: list[Segment] = []
    for idx, block in enumerate(_split_blocks(text)):
        seg = _build_segment(idx, block, comma_sep=True)
        if seg:
            segments.append(seg)
    return segments


def _parse_vtt(path: str) -> list[Segment]:
    """Parse a WebVTT file into a list of Segments."""
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    # strip WEBVTT header line and any leading NOTE / STYLE / REGION blocks
    lines = text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if "-->" in ln or re.match(r"^\d", ln.strip())),
        1,
    )
    segments: list[Segment] = []
    for idx, block in enumerate(_split_blocks("\n".join(lines[start:]))):
        seg = _build_segment(idx, block, comma_sep=False)
        if seg:
            segments.append(seg)
    return segments


def _parse_sbv(path: str) -> list[Segment]:
    """Parse a YouTube SBV file into a list of Segments."""
    with open(path, encoding="utf-8-sig") as fh:
        text = fh.read()
    segments: list[Segment] = []
    for idx, block in enumerate(_split_blocks(text)):
        seg = _build_segment(
            idx, block, comma_sep=False, find_pattern=_SBV_TIME_LINE, split_pattern=_SBV_SPLIT
        )
        if seg:
            segments.append(seg)
    return segments


def _parse_lrc(path: str) -> list[Segment]:
    """Parse an LRC lyrics file into a list of Segments (fixed duration for the final line)."""
    with open(path, encoding="utf-8-sig") as fh:
        raw_lines = fh.read().splitlines()
    entries: list[tuple[float, str]] = []
    for line in raw_lines:
        match = _LRC_LINE.match(line.strip())
        if not match:
            continue
        minutes, seconds, body = match.groups()
        body = body.strip()
        if body:
            entries.append((int(minutes) * 60 + float(seconds), body))
    segments: list[Segment] = []
    for idx, (start, body) in enumerate(entries):
        end = entries[idx + 1][0] if idx + 1 < len(entries) else start + _LRC_LAST_LINE_DURATION_S
        segments.append(Segment(id=idx, start=start, end=end, text=body, words=[], language=""))
    return segments


def _parse_ass(path: str) -> list[Segment]:
    """Parse an ASS/SSA subtitle file's [Events] Dialogue lines into a list of Segments."""
    with open(path, encoding="utf-8-sig") as fh:
        raw_lines = fh.read().splitlines()
    segments: list[Segment] = []
    idx = 0
    for line in raw_lines:
        stripped = line.strip()
        if not stripped.lower().startswith("dialogue:"):
            continue
        fields = stripped[len("dialogue:"):].split(",", 9)
        if len(fields) < 10:
            continue
        start = _to_seconds(fields[1].strip(), comma_sep=False)
        end = _to_seconds(fields[2].strip(), comma_sep=False)
        body = _strip_ass_tags(fields[9])
        if not body:
            continue
        segments.append(Segment(id=idx, start=start, end=end, text=body, words=[], language=""))
        idx += 1
    return segments


def _strip_ass_tags(text: str) -> str:
    """Strip ASS override tags ('{...}') and convert forced line breaks to spaces."""
    text = _ASS_OVERRIDE_TAG.sub("", text)
    return text.replace("\\N", " ").replace("\\n", " ").replace("\\h", " ").strip()


def _strip_markup(text: str) -> str:
    """Remove styling tags and decode HTML entities (&amp;) from a cue's text."""
    return " ".join(html.unescape(_MARKUP_TAG.sub("", text)).split())


def _split_blocks(text: str) -> list[list[str]]:
    """Split raw subtitle text into non-empty line groups."""
    blocks: list[list[str]] = []
    for raw in re.split(r"\n{2,}", text.strip()):
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if lines:
            blocks.append(lines)
    return blocks


def _build_segment(
    idx: int,
    lines: list[str],
    comma_sep: bool,
    find_pattern: re.Pattern = _ARROW,
    split_pattern: re.Pattern = _ARROW_SPLIT,
) -> Segment | None:
    """Build a Segment from a subtitle block; return None when timestamp is missing."""
    time_line = _find_timestamp_line(lines, find_pattern)
    if time_line is None:
        return None
    parts = split_pattern.split(lines[time_line], maxsplit=1)
    if len(parts) != 2:
        return None
    start = _to_seconds(parts[0], comma_sep)
    end   = _to_seconds(parts[1].split()[0], comma_sep)  # drop optional cue settings
    body  = _strip_markup(" ".join(lines[time_line + 1:]))
    if not body:
        return None
    return Segment(id=idx, start=start, end=end, text=body, words=[], language="")


def _find_timestamp_line(lines: list[str], pattern: re.Pattern) -> int | None:
    """Return the index of the first line matching the given timestamp pattern."""
    for i, ln in enumerate(lines):
        if pattern.search(ln):
            return i
    return None


def _to_seconds(ts: str, comma_sep: bool) -> float:
    """Convert 'HH:MM:SS,mmm' or 'HH:MM:SS.mmm' or 'MM:SS.mmm' to float seconds."""
    try:
        ts = ts.strip().replace(",", ".")
        parts = ts.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(ts)
    except Exception:
        return 0.0
