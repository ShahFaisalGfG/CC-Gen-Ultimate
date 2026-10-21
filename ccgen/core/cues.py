# cues.py - turns raw transcription segments into readable subtitle cues
#
# Whisper segments follow the model's 30 s decoding windows, not subtitle conventions: one
# segment can hold several sentences and run past 10 seconds, far more than two 42-character
# lines. This module uses the per-word timestamps to cut each segment into cues that fit the
# line limits, preferring sentence ends, then clause punctuation, then pauses in the speech.
#
# Translation needs the opposite: whole sentences translate far better than half-sentence
# fragments. sentence_units() regroups cues into sentences for translation, and
# spread_translation() maps the translated sentence back onto the original cues' timing.

import math
import re
from dataclasses import dataclass, replace
from typing import Optional

from ccgen.config.defaults import OutputDefaults
from ccgen.core import Segment, TranslatedSegment, WordToken

_SENTENCE_END = (".", "?", "!", "\u2026", "\u3002", "\uff1f", "\uff01", "\u061f", "\u06d4", "\u0964")
_CLAUSE_END = (",", ";", ":", "\u2013", "\u2014", "\u060c", "\uff0c", "\u3001")
_CLOSING_MARKS = "\"')]}\u201d\u2019\u00bb"
# A full stop after one of these words, or after a single capital letter (an initial), shortens
# a word instead of ending a sentence: "Dr. Smith" stays in one translation unit and one cue.
# "No." is left out (it is far more often an answer than "number"), as are "I." and "A.".
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "sra", "jr", "st", "vs", "e.g", "i.e", "approx", "fig",
    "nr", "bzw", "z.b", "ca", "mme", "mlle", "dra",
})
_LAST_WORD = re.compile(r"(\S+)\.$")
_OPENING_MARKS = "(\"'\u201c\u2018\u00ab"
# A sentence end closes a cue only once it holds this share of a full cue, so a short
# interjection ("Yes.") can share a cue with the next sentence instead of flashing by alone.
_SENTENCE_CLOSE_SHARE = 0.5
# A punctuation break is only used when it leaves at least this share of a full cue behind, so
# the cue before it is never a stranded fragment. Sentence ends may close shorter cues than
# commas, since a short complete sentence still reads well on its own.
_MIN_SENTENCE_BREAK_SHARE = 0.15
_MIN_CLAUSE_BREAK_SHARE = 0.3
# An unfinished tail this short is held back and joined to the next segment's words, so a
# Whisper segment boundary in mid-sentence doesn't leave a split-second fragment on screen.
_CARRY_SHARE = 0.5
# Words a line break reads naturally before, used when a sentence has to be split without
# punctuation (English plus the common Urdu/Hindi connectives).
_BREAK_BEFORE_WORDS = frozenset({
    "and", "but", "or", "so", "because", "that", "which", "who", "when", "while", "if",
    "to", "with", "for", "from", "of", "in", "on", "at", "after", "before",
    "aur", "lekin", "ke", "ki", "ko", "se", "mein", "اور", "لیکن",
})
# Comfortable reading speed used to extend short cues into the following silence.
_READING_CPS = 17.0
# Translation units stop growing at this length or at a pause this long between cues.
_UNIT_MAX_CHARS = 300
_UNIT_MAX_GAP_S = 2.0


@dataclass(frozen=True)
class CueLayout:
    """Size limits for one subtitle cue."""

    max_line_length: int = OutputDefaults.MAX_LINE_LENGTH
    max_lines: int = OutputDefaults.MAX_LINES
    max_duration: float = OutputDefaults.MAX_CUE_DURATION_S
    min_duration: float = OutputDefaults.MIN_DURATION_MS / 1000
    pause_split: float = OutputDefaults.CUE_PAUSE_SPLIT_S

    @property
    def max_chars(self) -> int:
        """Most characters a single cue may hold across all its lines."""
        return self.max_line_length * self.max_lines

    def for_language(self, language: str) -> "CueLayout":
        """Return a layout with the shorter line limit used for scripts written without spaces."""
        if is_no_space_language(language):
            return replace(self, max_line_length=min(self.max_line_length, OutputDefaults.NO_SPACE_MAX_LINE_LENGTH))
        return self


def is_no_space_language(language: Optional[str]) -> bool:
    """Return True for languages whose script does not separate words with spaces."""
    return (language or "") in OutputDefaults.NO_SPACE_LANGUAGES


def ends_sentence(text: str) -> bool:
    """Return True when text ends with sentence-final punctuation (ignoring closing quotes).

    A full stop closing a common abbreviation or an initial ("Dr.", "e.g.", "J.") doesn't count.
    """
    text = text.rstrip().rstrip(_CLOSING_MARKS)
    if not text.endswith(_SENTENCE_END):
        return False
    last = _LAST_WORD.search(text)
    if last is None or text.endswith(".."):
        return True
    word = last.group(1).lstrip(_OPENING_MARKS)
    return not (word.lower() in _ABBREVIATIONS or (len(word) == 1 and word.isupper() and word not in "IA"))


class CueBuilder:
    """Splits transcription segments into cues one segment at a time, so cues can stream live.

    Call flush() after the last segment to release a held-back unfinished tail.
    """

    def __init__(self, layout: CueLayout) -> None:
        self._layout = layout
        self._cues: list[Segment] = []
        self._source_count = 0
        self._pending: list[WordToken] = []
        self._pending_segment: Optional[Segment] = None

    @property
    def cues(self) -> list[Segment]:
        """Every cue built so far, in order."""
        return self._cues

    @property
    def source_count(self) -> int:
        """How many source segments have been added."""
        return self._source_count

    def add(self, segment: Segment) -> list[Segment]:
        """Split one segment into cues, append them, and return only the new cues."""
        self._source_count += 1
        words = segment.get("words") or []
        if not words:
            return self.flush() + self._append([self._make_cue(segment, [])])
        layout = self._layout.for_language(segment.get("language", ""))
        groups = _split_words(self._pending + list(words), layout)
        self._pending, self._pending_segment = [], None
        if groups and _is_unfinished(groups[-1], layout):
            self._pending, self._pending_segment = groups.pop(), segment
        return self._append([self._make_cue(segment, group) for group in groups])

    def flush(self) -> list[Segment]:
        """Emit the held-back tail, if any, as a final cue."""
        if not self._pending or self._pending_segment is None:
            return []
        cue = self._make_cue(self._pending_segment, self._pending)
        self._pending, self._pending_segment = [], None
        return self._append([cue])

    def _append(self, cues: list[Segment]) -> list[Segment]:
        """Number and store non-empty cues; return the ones added."""
        added = [cue for cue in cues if cue["text"]]
        for cue in added:
            cue["id"] = len(self._cues)
            self._cues.append(cue)
        return added

    def _make_cue(self, segment: Segment, words: list[WordToken]) -> Segment:
        """Build a cue from a run of words, or from the whole segment when it has no words."""
        if words:
            text = "".join(w["word"] for w in words).strip()
            start, end = words[0]["start"], max(words[-1]["end"], words[0]["start"])
        else:
            text = segment["text"].strip()
            start, end = segment["start"], segment["end"]
        return Segment(
            id=-1,
            start=start,
            end=end,
            text=" ".join(text.split()) if not is_no_space_language(segment.get("language")) else text,
            words=list(words),
            language=segment.get("language", ""),
        )


def build_cues(segments: list[Segment], layout: CueLayout) -> list[Segment]:
    """Split every segment into cues and return them with sequential ids and final timing."""
    builder = CueBuilder(layout)
    for segment in segments:
        builder.add(segment)
    builder.flush()
    return finalize_timing(builder.cues, layout)


def finalize_timing(cues: list[Segment], layout: CueLayout) -> list[Segment]:
    """Fix cue timing in place: no inverted or overlapping cues, and readable minimum durations.

    Word timestamps end the instant speech stops, which leaves short cues on screen too briefly
    to read. Each cue is extended toward a comfortable reading time, but never past the start of
    the next cue.
    """
    for idx, cue in enumerate(cues):
        next_start = cues[idx + 1]["start"] if idx + 1 < len(cues) else math.inf
        cue["end"] = max(cue["end"], cue["start"])
        if cue["end"] > next_start > cue["start"]:
            cue["end"] = next_start
        reading_time = max(layout.min_duration, len(cue["text"]) / _READING_CPS)
        wanted_end = cue["start"] + min(reading_time, layout.max_duration)
        if cue["end"] < wanted_end:
            cue["end"] = max(cue["end"], min(wanted_end, next_start))
    return cues


def sentence_units(cues: list[Segment]) -> list[list[int]]:
    """Group consecutive cue indexes into sentence-sized units for translation."""
    units: list[list[int]] = []
    current: list[int] = []
    current_len = 0
    for idx, cue in enumerate(cues):
        text = cue["text"]
        if current:
            gap = cue["start"] - cues[current[-1]]["end"]
            if gap > _UNIT_MAX_GAP_S or current_len + len(text) > _UNIT_MAX_CHARS:
                units.append(current)
                current, current_len = [], 0
        current.append(idx)
        current_len += len(text) + 1
        if ends_sentence(text):
            units.append(current)
            current, current_len = [], 0
    if current:
        units.append(current)
    return units


def join_unit_text(cues: list[Segment], language: Optional[str]) -> str:
    """Join a unit's cue texts into one string, without spaces for no-space scripts."""
    joiner = "" if is_no_space_language(language) else " "
    return joiner.join(cue["text"].strip() for cue in cues).strip()


def spread_translation(
    cues: list[Segment],
    translated: str,
    target_lang: str,
) -> list[TranslatedSegment]:
    """Distribute one translated sentence across the cues it came from.

    Each cue receives a share of the translated words proportional to its share of the source
    text, with breaks nudged onto nearby punctuation. When the translation has fewer words than
    there are cues, the leftover cues merge into their neighbours so no empty cue is written.
    """
    parts = distribute_text(translated, [len(c["text"]) or 1 for c in cues], is_no_space_language(target_lang))
    results: list[TranslatedSegment] = []
    for cue, part in zip(cues, parts):
        if not part:
            if results:
                results[-1]["end"] = cue["end"]
            continue
        start = cue["start"]
        if not results and cue is not cues[0]:
            start = cues[0]["start"]
        results.append(TranslatedSegment(
            id=cue["id"],
            start=start,
            end=cue["end"],
            original=cue["text"],
            translated=part,
            language=target_lang,
        ))
    return results


def distribute_text(text: str, weights: list[int], no_space: bool = False) -> list[str]:
    """Split text into len(weights) consecutive parts sized proportionally to weights."""
    count = len(weights)
    if count <= 1:
        return [text.strip()]
    tokens = [ch for ch in text.strip()] if no_space else text.split()
    joiner = "" if no_space else " "
    total_weight = sum(weights) or count
    bounds: list[int] = []
    running = 0
    for k in range(1, count):
        running += weights[k - 1]
        ideal = round(len(tokens) * running / total_weight)
        lower = bounds[-1] + 1 if bounds else 1
        upper = len(tokens) - (count - k)
        if lower > upper:
            bounds.append(min(max(ideal, bounds[-1] if bounds else 0), len(tokens)))
            continue
        bounds.append(_snap_to_punctuation(tokens, min(max(ideal, lower), upper), lower, upper))
    edges = [0] + bounds + [len(tokens)]
    return [joiner.join(tokens[edges[i]:edges[i + 1]]).strip() for i in range(count)]


def _snap_to_punctuation(tokens: list[str], ideal: int, lower: int, upper: int) -> int:
    """Move a split point up to two tokens so it lands right after punctuation, if possible."""
    for offset in (0, -1, 1, -2, 2):
        candidate = ideal + offset
        if lower <= candidate <= upper and tokens[candidate - 1].endswith(_SENTENCE_END + _CLAUSE_END):
            return candidate
    return ideal


def _split_words(words: list[WordToken], layout: CueLayout) -> list[list[WordToken]]:
    """Greedily group words into cues that respect the layout's length, duration, and pauses."""
    groups: list[list[WordToken]] = []
    current: list[WordToken] = []
    for idx, word in enumerate(words):
        if current and _starts_new_cue(current, word, layout):
            keep, carry = _best_break(current, word, layout)
            if not carry and word["start"] - current[-1]["end"] < layout.pause_split:
                keep, carry = _balanced_break(current, words[idx:], layout)
            groups.append(keep)
            current = carry
        current.append(word)
        if ends_sentence(word["word"]) and _text_len(current) >= layout.max_chars * _SENTENCE_CLOSE_SHARE:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _starts_new_cue(current: list[WordToken], word: WordToken, layout: CueLayout) -> bool:
    """Return True when `word` can't join the current cue."""
    if word["start"] - current[-1]["end"] >= layout.pause_split:
        return True
    if _text_len(current + [word]) > layout.max_chars:
        return True
    return word["end"] - current[0]["start"] > layout.max_duration


def _best_break(
    current: list[WordToken],
    word: WordToken,
    layout: CueLayout,
) -> tuple[list[WordToken], list[WordToken]]:
    """Choose where to close the current cue: after the latest sentence end, else clause end.

    Words after the chosen break carry over into the next cue. A pause-triggered break always
    closes at the pause, since the speaker already marked the boundary.
    """
    if word["start"] - current[-1]["end"] >= layout.pause_split:
        return current, []
    for marks, share in ((_SENTENCE_END, _MIN_SENTENCE_BREAK_SHARE), (_CLAUSE_END, _MIN_CLAUSE_BREAK_SHARE)):
        for idx in range(len(current) - 1, 0, -1):
            if current[idx - 1]["word"].rstrip().rstrip(_CLOSING_MARKS).endswith(marks):
                if _text_len(current[:idx]) >= layout.max_chars * share:
                    return current[:idx], current[idx:]
                break
    return current, []


def _balanced_break(
    current: list[WordToken],
    upcoming: list[WordToken],
    layout: CueLayout,
) -> tuple[list[WordToken], list[WordToken]]:
    """Split an overlong sentence into two even cues instead of filling the first one greedily.

    Greedy filling leaves the end of the sentence as a tiny cue that flashes by. When the rest of
    the sentence is short and spoken without a pause, the break moves back so both cues are
    about the same length, preferring a spot just before a connective such as "and" or "with".
    """
    tail: list[WordToken] = []
    for word in upcoming:
        if tail and word["start"] - tail[-1]["end"] >= layout.pause_split:
            return current, []
        tail.append(word)
        if ends_sentence(word["word"]):
            break
    else:
        return current, []
    if _text_len(tail) >= layout.max_chars * _CARRY_SHARE:
        return current, []
    best: Optional[tuple[float, int]] = None
    for k in range(1, len(current)):
        first, second = current[:k], current[k:] + tail
        if _text_len(first) > layout.max_chars or _text_len(second) > layout.max_chars:
            continue
        if second[-1]["end"] - second[0]["start"] > layout.max_duration:
            continue
        score = float(abs(_text_len(first) - _text_len(second)))
        if current[k]["word"].strip().lower() in _BREAK_BEFORE_WORDS:
            score -= layout.max_line_length * 0.25
        if best is None or score < best[0]:
            best = (score, k)
    if best is None:
        return current, []
    return current[:best[1]], current[best[1]:]


def _is_unfinished(words: list[WordToken], layout: CueLayout) -> bool:
    """True for a short trailing word run that doesn't end a sentence (worth carrying over)."""
    text = "".join(w["word"] for w in words)
    return not ends_sentence(text) and _text_len(words) < layout.max_chars * _CARRY_SHARE


def _text_len(words: list[WordToken]) -> int:
    """Length of the text a run of words renders to."""
    return len("".join(w["word"] for w in words).strip())
