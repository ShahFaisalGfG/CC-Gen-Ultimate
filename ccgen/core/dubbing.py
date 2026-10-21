# dubbing.py - lay spoken cues out on a timeline and add the result to the source media
#
# Cues are spoken a sentence at a time: a sentence split over several cues (as translations are)
# is said once, with natural intonation, in the time of all its cues. Each sentence starts at its
# first cue's start time, and its slot runs until the next sentence starts, so speech may spill
# into a following silence. Speech that doesn't fit is spoken faster, up to a limit; speech still
# too long may run up to a second into the next sentence's time, which then starts later, rather
# than lose its last words. Only beyond that, or past the end of the media, is it faded out and
# reported, so one wordy line never fails a whole film. The track is written to disk as it grows,
# so a long film never has to fit in memory.
#
# The finished track is muxed in-process with PyAV: video, original audio, subtitles, fonts,
# chapters, and metadata are copied untouched, and the dub is added as one more AAC track.

import logging
import os
import tempfile
import wave
from dataclasses import dataclass, field
from typing import Callable, Optional

import av
from av.stream import Disposition
import numpy as np

from ccgen.config.defaults import DubbingDefaults
from ccgen.core import Segment
from ccgen.core.cues import join_unit_text, sentence_units
from ccgen.engines.speech.base import SpeechEngine
from ccgen.engines.speech.line_check import FAILED_CER, LineChecker
from ccgen.utils.callbacks import JobCancelled

_log = logging.getLogger(__name__)

TRACK_RATE = DubbingDefaults.TRACK_RATE
# The last cue may run this far past its own end, since no next cue bounds it.
_LAST_CUE_TAIL_S = 1.0
_FADE_S = 0.03
# A line the line check rejects is spoken again up to this many times; the best take is kept.
_RETAKES = 2
# A line that doesn't fit at the fastest allowed speed may run this far into the next line's time.
_MAX_DELAY_S = 1.0
# Encode the dub this far ahead of the source packets being copied, so the muxer can interleave.
_MUX_LEAD_S = 0.5
_AAC_FRAME = 1024
_AAC_BIT_RATE = 192_000
# Matroska tags tracks with ISO 639-2 codes.
_ISO_639_2 = {
    "ar": "ara", "de": "deu", "en": "eng", "es": "spa", "fr": "fra", "hi": "hin", "ja": "jpn",
    "ko": "kor", "pt": "por", "ru": "rus", "tr": "tur", "ur": "urd", "zh": "zho",
}
# Subtitle codecs Matroska can store as copied packets.
_MKV_SUBTITLE_CODECS = frozenset({
    "subrip", "ass", "ssa", "webvtt", "hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle",
})

Progress = Optional[Callable[[int, int], None]]
CancelCheck = Callable[[], bool]


@dataclass
class TrackReport:
    """What happened while fitting speech into the cue timeline."""

    spoken: int = 0
    sped_up: int = 0
    trimmed: list[int] = field(default_factory=list)
    # Lines where the voice kept talking past the text and the extra speech was cut.
    ran_on: list[int] = field(default_factory=list)
    # Lines the line check had to speak again, and those still unclear after every retake.
    retaken: list[int] = field(default_factory=list)
    unclear: list[int] = field(default_factory=list)

    def warnings(self) -> list[str]:
        """User-facing notes about lines that could not be spoken in full or as written."""
        notes = []
        if self.unclear:
            notes.append(
                f"{len(self.unclear)} line(s) may be hard to understand even after being spoken again "
                f"(subtitle {_numbers(self.unclear)}). Listen to them, and reword or dub again if needed."
            )
        if self.ran_on:
            notes.append(
                f"{len(self.ran_on)} line(s) kept talking past their text, so the extra speech was cut "
                f"(subtitle {_numbers(self.ran_on)}). Listen to them, and dub again if one sounds wrong."
            )
        if self.trimmed:
            notes.append(
                f"{len(self.trimmed)} line(s) were too long for their time and were cut short "
                f"(subtitle {_numbers(self.trimmed)}). Shorten them or raise the maximum speed-up."
            )
        return notes


def _numbers(lines: list[int]) -> str:
    """The first ten subtitle numbers, for a note."""
    return ", ".join(str(n) for n in lines[:10]) + (" ..." if len(lines) > 10 else "")


def synthesize_track(
    cues: list[Segment],
    speakers: list[int],
    engine: SpeechEngine,
    max_speedup: float,
    output_path: str,
    progress: Progress = None,
    cancelled: Optional[CancelCheck] = None,
    checker: Optional[LineChecker] = None,
    language: str = "",
    end: Optional[float] = None,
) -> TrackReport:
    """Speak every sentence at its first cue's time and write the mono 16-bit track to `output_path`.

    With a `checker`, every line is heard back and spoken again when it comes out garbled.
    `language` decides how a sentence's cues are joined (no spaces for Chinese and Japanese).
    No speech runs past `end`, the media's length in seconds, where the dub track is cut.
    Notes name each sentence by its first subtitle's number.
    """
    report = TrackReport()
    units = spoken_units(cues, speakers, language)
    end_frame = round(end * TRACK_RATE) if end is not None else None
    slot_ends = _slot_ends(cues, units, end)
    with wave.open(output_path, "wb") as track:
        track.setnchannels(1)
        track.setsampwidth(2)
        track.setframerate(TRACK_RATE)
        written = 0
        for number, (members, text) in enumerate(units):
            if cancelled is not None and cancelled():
                raise JobCancelled()
            start = max(round(cues[members[0]]["start"] * TRACK_RATE), written)
            if end_frame is not None and start >= end_frame:
                report.trimmed.append(members[0] + 1)  # it would start after the media ends
            else:
                slot = max(round(slot_ends[number] * TRACK_RATE) - start, 1)
                room = slot + round(_MAX_DELAY_S * TRACK_RATE)
                if end_frame is not None:
                    room = min(room, end_frame - start)
                    slot = min(slot, room)
                line = _Line(text, speakers[members[0]], slot, room)
                clip = _speak_checked(engine, line, max_speedup, report, members[0] + 1, checker)
                _write_silence(track, start - written)
                track.writeframes(_to_pcm(clip))
                written = start + clip.size
                report.spoken += 1
            if progress:
                progress(members[-1] + 1, len(cues))
    return report


def _slot_ends(cues: list[Segment], units: list[tuple[list[int], str]], end: Optional[float]) -> list[float]:
    """When each sentence's time ends: where the next one starts, or after the last cue."""
    ends = [cues[members[0]]["start"] for members, _ in units[1:]]
    if units:
        last = cues[units[-1][0][-1]]["end"] + _LAST_CUE_TAIL_S
        ends.append(min(last, end) if end is not None else last)
    return ends


def spoken_units(cues: list[Segment], speakers: list[int], language: str) -> list[tuple[list[int], str]]:
    """The lines to speak: each sentence's cues (only one speaker's) and their joined text."""
    units: list[tuple[list[int], str]] = []
    for sentence in sentence_units(cues):
        group: list[int] = []
        for index in sentence:
            if not cues[index]["text"].strip():
                continue
            if group and speakers[index] != speakers[group[-1]]:
                units.append((group, join_unit_text([cues[i] for i in group], language)))
                group = []
            group.append(index)
        if group:
            units.append((group, join_unit_text([cues[i] for i in group], language)))
    return units


def attach_track(
    media_path: str,
    wav_path: str,
    output_path: str,
    title: str,
    language: str,
    make_default: bool,
    cancelled: Optional[CancelCheck] = None,
) -> list[str]:
    """Write `output_path` (Matroska): every stream of `media_path` plus the dub as a new track.

    Returns notes about source streams Matroska can't hold, which are left out. The output
    appears only once complete, so a cancelled or failed mux never leaves a partial file.
    """
    notes: list[str] = []
    directory = os.path.dirname(os.path.abspath(output_path))
    fd, pending = tempfile.mkstemp(prefix=".ccgen-dub-", suffix=os.path.splitext(output_path)[1], dir=directory)
    os.close(fd)
    try:
        with av.open(media_path) as source, av.open(pending, "w", format="matroska") as target, \
                wave.open(wav_path, "rb") as dub:
            target.metadata.update(source.metadata)
            copied = _copy_stream_layout(source, target, make_default, notes)
            dub_stream = target.add_stream("aac", rate=TRACK_RATE, layout="mono")
            dub_stream.bit_rate = _AAC_BIT_RATE
            dub_stream.metadata["title"] = title
            dub_stream.metadata["language"] = _ISO_639_2.get(language, "und")
            dub_flags = Disposition.dub
            if make_default:
                dub_flags |= Disposition.default
            # PyAV reads dispositions as flags but only accepts the raw integer when setting one;
            # its type stubs mark the attribute read-only although the setter exists.
            dub_stream.disposition = dub_flags.value  # type: ignore[misc]
            _copy_chapters(source, target)
            seconds = _duration_seconds(source)
            limit = int(seconds * TRACK_RATE) if seconds is not None else None
            # Copied packets keep the source's timestamps, which often don't start at zero
            # (.ts and .m2ts files usually start a second or more in), while cue times count from
            # the first sample of audio. The dub starts where the source does to stay in sync.
            start = int((source.start_time or 0) / av.time_base * TRACK_RATE)
            encoder = _DubEncoder(dub, dub_stream, target, limit, start)
            for packet in source.demux(*(source.streams[i] for i in copied)):
                if cancelled is not None and cancelled():
                    raise JobCancelled()
                if packet.dts is None:
                    continue
                if packet.time_base is not None:
                    encoder.encode_until(float(packet.dts * packet.time_base) + _MUX_LEAD_S)
                packet.stream = copied[packet.stream.index]
                target.mux(packet)
            encoder.finish()
        os.replace(pending, output_path)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    return notes


class _DubEncoder:
    """Encodes the dub WAV into AAC packets on demand, padded with silence to the source's length."""

    def __init__(self, dub: wave.Wave_read, stream, target, limit: Optional[int], start: int) -> None:
        self._dub = dub
        self._stream = stream
        self._target = target
        self._limit = limit
        self._start = start
        self._samples = 0
        self._done = False

    def encode_until(self, seconds: float) -> None:
        """Encode dub audio up to `seconds` into the track."""
        while not self._done and self._start + self._samples < seconds * TRACK_RATE:
            self._encode_chunk()

    def finish(self) -> None:
        """Encode whatever remains (up to the source's length) and flush the encoder."""
        while not self._done:
            self._encode_chunk()
        for packet in self._stream.encode(None):
            self._target.mux(packet)

    def _encode_chunk(self) -> None:
        count = _AAC_FRAME
        if self._limit is not None:
            count = min(count, self._limit - self._samples)
        pcm = self._dub.readframes(count) if count > 0 else b""
        if not pcm and count > 0 and self._limit is not None:
            # Speech ended before the media did: pad so both tracks are equally long.
            pcm = bytes(2 * count)
        if not pcm:
            self._done = True
            return
        samples = np.frombuffer(pcm, dtype="<i2").reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
        frame.sample_rate = TRACK_RATE
        frame.pts = self._start + self._samples
        self._samples += samples.shape[1]
        for packet in self._stream.encode(frame):
            self._target.mux(packet)


def _copy_stream_layout(source, target, make_default: bool, notes: list[str]) -> dict:
    """Add a copy of every source stream Matroska can hold; return {source index: copy}."""
    copied = {}
    for stream in source.streams:
        if stream.type == "subtitle" and stream.codec_context.name not in _MKV_SUBTITLE_CODECS:
            notes.append(f"Subtitle track {stream.index} ({stream.codec_context.name}) was not copied: "
                         "the MKV format can't store it.")
            continue
        if stream.type not in ("video", "audio", "subtitle", "attachment"):
            continue
        copy = target.add_stream_from_template(stream)
        copy.metadata.update(stream.metadata)
        disposition = stream.disposition
        if make_default and stream.type == "audio":
            disposition &= ~Disposition.default
        copy.disposition = disposition.value
        if stream.type != "attachment":
            copied[stream.index] = copy
    return copied


def _copy_chapters(source, target) -> None:
    """Carry chapter markers over; a container without chapters is left as is."""
    try:
        chapters = source.chapters()
        if chapters:
            target.set_chapters(chapters)
    except (AttributeError, ValueError, av.FFmpegError):
        _log.debug("Chapters were not copied", exc_info=True)


def media_seconds(path: str) -> Optional[float]:
    """How long a media file plays, in seconds, or None when its container doesn't say."""
    with av.open(path) as container:
        return _duration_seconds(container)


def _duration_seconds(container) -> Optional[float]:
    """Source length in seconds, or None when unknown."""
    if container.duration is not None and container.duration > 0:
        return container.duration / av.time_base
    lengths = [
        float(s.duration * s.time_base) for s in container.streams
        if s.duration is not None and s.time_base is not None
    ]
    return max(lengths) if lengths else None


@dataclass
class _Line:
    """One sentence to speak: its text and speaker, the samples until the next sentence starts
    (`slot`), and the most it may take, running into the next sentence's time (`room`)."""

    text: str
    speaker: int
    slot: int
    room: int


@dataclass
class _Take:
    """One spoken version of a line, fitted to its slot."""

    clip: np.ndarray
    sped_up: bool
    trimmed: bool
    ran_on: bool
    error: float = 0.0


def _speak_checked(
    engine: SpeechEngine,
    line: _Line,
    max_speedup: float,
    report: TrackReport,
    number: int,
    checker: Optional[LineChecker],
) -> np.ndarray:
    """Speak a line to fit its slot; with a checker, retake a garbled line and keep the best take."""
    best: Optional[_Take] = None
    for attempt in range(1 + (_RETAKES if checker is not None else 0)):
        take = _speak_to_fit(engine, line, max_speedup)
        if checker is not None:
            take.error = checker.score(take.clip, TRACK_RATE, line.text)
        if best is None or take.error < best.error:
            best = take
        if take.error < FAILED_CER:
            break
        if attempt == 0:
            report.retaken.append(number)
    assert best is not None
    if best.error >= FAILED_CER:
        report.unclear.append(number)
    report.sped_up += int(best.sped_up)
    if best.trimmed:
        report.trimmed.append(number)
    if best.ran_on:
        report.ran_on.append(number)
    return best.clip


def _speak_to_fit(engine: SpeechEngine, line: _Line, max_speedup: float) -> _Take:
    """Synthesize a line at TRACK_RATE to fit its slot, speeding up, or trimming beyond its room."""
    text, speaker, slot = line.text, line.speaker, line.slot
    speed = 1.0
    planned = engine.natural_seconds(text, speaker)
    if planned is not None and max_speedup > 1.0:
        speed = min(max(planned * TRACK_RATE / slot, 1.0), max_speedup)
    clip = _resample(*engine.synthesize(text, speed, speaker))
    ran_on = engine.last_line_capped
    if clip.size > slot and max_speedup > speed:
        speed = min(speed * clip.size / slot, max_speedup)
        clip = _resample(*engine.retime(text, speed, speaker))
    trimmed = clip.size > line.room
    if trimmed:
        clip = _fade_out(clip[:line.room])
    return _Take(clip, speed > 1.0, trimmed, ran_on)


def _resample(samples: np.ndarray, rate: int) -> np.ndarray:
    """Linear-resample mono float samples to TRACK_RATE."""
    samples = np.asarray(samples, dtype=np.float32).ravel()
    if rate == TRACK_RATE or samples.size == 0:
        return samples
    length = max(1, round(samples.size * TRACK_RATE / rate))
    positions = np.linspace(0, samples.size - 1, length)
    return np.interp(positions, np.arange(samples.size), samples).astype(np.float32)


def _fade_out(clip: np.ndarray) -> np.ndarray:
    """Fade the last few milliseconds so a trimmed line doesn't end in a click."""
    fade = min(clip.size, int(_FADE_S * TRACK_RATE))
    if fade:
        clip = clip.copy()
        clip[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return clip


def _to_pcm(clip: np.ndarray) -> bytes:
    """Convert float samples to 16-bit PCM, scaling down any clip that would distort."""
    peak = float(np.max(np.abs(clip))) if clip.size else 0.0
    if peak > 0.99:
        clip = clip * (0.99 / peak)
    return (clip * 32767).astype("<i2").tobytes()


def _write_silence(track: wave.Wave_write, frames: int) -> None:
    """Write a gap without allocating it all at once."""
    chunk = bytes(2 * TRACK_RATE)
    remaining = frames * 2
    while remaining > 0:
        size = min(len(chunk), remaining)
        track.writeframesraw(chunk[:size])
        remaining -= size
