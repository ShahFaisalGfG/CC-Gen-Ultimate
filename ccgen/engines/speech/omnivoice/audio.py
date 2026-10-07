#!/usr/bin/env python3
# Copyright    2026  Xiaomi Corp.        (authors:  Han Zhu)
#
# See ../../LICENSE for clarification regarding multiple authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Audio I/O and processing utilities.

Provides functions for loading, resampling, silence removal,
chunking, cross-fading, and format conversion.

All public functions in this module operate on **numpy float32 arrays**
with shape ``(C, T)`` (channels-first).
"""

import io
import logging

import numpy as np
import soundfile as sf
import torch
import torchaudio

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_waveform(audio_path: str):
    """Load audio from a file path, returning (data, sample_rate).

    Tries two backends in order:
    1. soundfile — covers WAV/FLAC/OGG etc., no ffmpeg needed.
    2. librosa — covers MP3/M4A etc. via audioread + ffmpeg.

    Returns:
        (data, sample_rate) where data is a numpy float32 array of
        shape (C, T).
    """
    try:
        data, sr = sf.read(audio_path, dtype="float32", always_2d=True)
        return data.T, sr  # (T, C) → (C, T)
    except Exception:
        # soundfile cannot handle MP3/M4A etc., fall back to librosa.
        import librosa

        data, sr = librosa.load(audio_path, sr=None, mono=False)
        if data.ndim == 1:
            data = data[np.newaxis, :]
        return data, sr


def load_audio(audio_path: str, sampling_rate: int) -> np.ndarray:
    """Load a waveform from file and resample to the target rate.

    Parameters:
        audio_path: path of the audio.
        sampling_rate: target sampling rate.

    Returns:
        Numpy float32 array of shape (1, T).
    """
    data, sr = load_waveform(audio_path)

    if data.shape[0] > 1:
        data = np.mean(data, axis=0, keepdims=True)
    if sr != sampling_rate:
        data = torchaudio.functional.resample(
            torch.from_numpy(data), orig_freq=sr, new_freq=sampling_rate
        ).numpy()

    return data


def load_audio_bytes(raw: bytes, sampling_rate: int) -> np.ndarray:
    """Load audio from in-memory bytes and resample.

    Parameters:
        raw: raw audio file bytes (e.g. from WebDataset).
        sampling_rate: target sampling rate.

    Returns:
        Numpy float32 array of shape (1, T).
    """
    buf = io.BytesIO(raw)

    try:
        data, sr = sf.read(buf, dtype="float32", always_2d=True)
        data = data.T  # (T, C) → (C, T)
    except Exception:
        import librosa

        buf.seek(0)
        data, sr = librosa.load(buf, sr=None, mono=False)
        if data.ndim == 1:
            data = data[np.newaxis, :]

    if data.shape[0] > 1:
        data = np.mean(data, axis=0, keepdims=True)
    if sr != sampling_rate:
        data = torchaudio.functional.resample(
            torch.from_numpy(data), orig_freq=sr, new_freq=sampling_rate
        ).numpy()

    return data


# ---------------------------------------------------------------------------
# Audio processing (all numpy in / numpy out)
# ---------------------------------------------------------------------------


# CC-Gen: the silence helpers below replace pydub's AudioSegment, split_on_silence,
# detect_nonsilent, and detect_leading_silence with numpy versions of the same algorithms
# (millisecond units, dBFS relative to 16-bit full scale), so the app needs no pydub or audioop.

_FULL_SCALE = 32768.0


def _to_ms_frames(audio: np.ndarray, sample_rate: int) -> tuple[np.ndarray, float]:
    """Sum of squares per millisecond (all channels together), in 16-bit sample units."""
    samples = np.clip(audio * _FULL_SCALE, -32768, 32767).astype(np.float64)
    per_ms = sample_rate / 1000.0
    length_ms = int(audio.shape[-1] / per_ms)
    bounds = (np.arange(length_ms + 1) * per_ms).astype(np.int64)
    cumulative = np.concatenate([[0.0], np.cumsum((samples ** 2).sum(axis=0))])
    return np.diff(cumulative[bounds]), per_ms * audio.shape[0]


def _window_rms(energy: tuple[np.ndarray, float], start: int, length: int) -> float:
    """RMS of `length` milliseconds starting at `start` ms."""
    per_ms, samples_per_ms = energy
    window = per_ms[start:start + length]
    count = window.size * samples_per_ms
    return float(np.sqrt(window.sum() / count)) if count else 0.0


def _detect_silence(energy, min_silence_len: int, silence_thresh: float, seek_step: int) -> list[list[int]]:
    """Silent ranges in ms, as pydub.silence.detect_silence."""
    length = energy[0].size
    if length < min_silence_len:
        return []
    threshold = (10 ** (silence_thresh / 20)) * _FULL_SCALE
    last_start = length - min_silence_len
    starts = list(range(0, last_start + 1, seek_step))
    if last_start % seek_step:
        starts.append(last_start)
    silent = [i for i in starts if _window_rms(energy, i, min_silence_len) <= threshold]
    if not silent:
        return []
    ranges = []
    previous = current = silent.pop(0)
    for start in silent:
        if start != previous + seek_step and start > previous + min_silence_len:
            ranges.append([current, previous + min_silence_len])
            current = start
        previous = start
    ranges.append([current, previous + min_silence_len])
    return ranges


def _detect_nonsilent(energy, min_silence_len: int, silence_thresh: float, seek_step: int) -> list[list[int]]:
    """Non-silent ranges in ms, as pydub.silence.detect_nonsilent."""
    length = energy[0].size
    silent = _detect_silence(energy, min_silence_len, silence_thresh, seek_step)
    if not silent:
        return [[0, length]]
    if silent[0] == [0, length]:
        return []
    ranges, previous_end = [], 0
    for start, end in silent:
        ranges.append([previous_end, start])
        previous_end = end
    if silent[-1][1] != length:
        ranges.append([previous_end, length])
    if ranges and ranges[0] == [0, 0]:
        ranges.pop(0)
    return ranges


def _leading_silence_ms(energy, silence_threshold: float, chunk_size: int = 10) -> int:
    """Milliseconds of leading silence, as pydub.silence.detect_leading_silence."""
    length = energy[0].size
    threshold = (10 ** (silence_threshold / 20)) * _FULL_SCALE
    trim = 0
    while trim < length and _window_rms(energy, trim, chunk_size) < threshold:
        trim += chunk_size
    return min(trim, length)


def _ms_slice(audio: np.ndarray, sample_rate: int, start_ms: int, end_ms: int) -> np.ndarray:
    return audio[..., int(start_ms * sample_rate / 1000):int(end_ms * sample_rate / 1000)]


def remove_silence(
    audio: np.ndarray,
    sampling_rate: int,
    mid_sil: int = 300,
    lead_sil: int = 100,
    trail_sil: int = 300,
) -> np.ndarray:
    """Remove middle silences longer than *mid_sil* ms and trim edge silences.

    Parameters:
        audio: numpy array with shape (C, T).
        sampling_rate: sampling rate of the audio.
        mid_sil: middle-silence threshold in ms (0 to skip).
        lead_sil: kept leading silence in ms.
        trail_sil: kept trailing silence in ms.

    Returns:
        Numpy array with shape (C, T').
    """
    if mid_sil > 0:
        energy = _to_ms_frames(audio, sampling_rate)
        ranges = [[start - mid_sil, end + mid_sil]
                  for start, end in _detect_nonsilent(energy, mid_sil, -50, 10)]
        for current, following in zip(ranges, ranges[1:]):
            if following[0] < current[1]:
                current[1] = following[0] = (current[1] + following[0]) // 2
        length = energy[0].size
        pieces = [_ms_slice(audio, sampling_rate, max(start, 0), min(end, length)) for start, end in ranges]
        audio = np.concatenate(pieces, axis=-1) if pieces else audio[..., :0]

    return remove_silence_edges(audio, sampling_rate, lead_sil, trail_sil, -50)


def remove_silence_edges(
    audio: np.ndarray,
    sampling_rate: int,
    lead_sil: int = 100,
    trail_sil: int = 300,
    silence_threshold: float = -50,
) -> np.ndarray:
    """Remove edge silences, keeping *lead_sil* / *trail_sil* ms."""
    lead = _leading_silence_ms(_to_ms_frames(audio, sampling_rate), silence_threshold)
    audio = _ms_slice(audio, sampling_rate, max(0, lead - lead_sil), 10 ** 12)
    reversed_audio = audio[..., ::-1]
    trail = _leading_silence_ms(_to_ms_frames(reversed_audio, sampling_rate), silence_threshold)
    reversed_audio = _ms_slice(reversed_audio, sampling_rate, max(0, trail - trail_sil), 10 ** 12)
    return np.ascontiguousarray(reversed_audio[..., ::-1])


def fade_and_pad_audio(
    audio: np.ndarray,
    pad_duration: float = 0.1,
    fade_duration: float = 0.1,
    sample_rate: int = 24000,
) -> np.ndarray:
    """Apply fade-in/out and pad with silence to prevent clicks.

    Args:
        audio: numpy array of shape (C, T).
        pad_duration: silence padding duration per side (seconds).
        fade_duration: fade curve duration (seconds).
        sample_rate: audio sampling rate.

    Returns:
        Processed numpy array of shape (C, T_new).
    """
    if audio.shape[-1] == 0:
        return audio

    fade_samples = int(fade_duration * sample_rate)
    pad_samples = int(pad_duration * sample_rate)

    processed = audio.copy()

    if fade_samples > 0:
        k = min(fade_samples, processed.shape[-1] // 2)
        if k > 0:
            fade_in = np.linspace(0, 1, k, dtype=np.float32)[np.newaxis, :]
            processed[..., :k] *= fade_in

            fade_out = np.linspace(1, 0, k, dtype=np.float32)[np.newaxis, :]
            processed[..., -k:] *= fade_out

    if pad_samples > 0:
        silence = np.zeros(
            (processed.shape[0], pad_samples),
            dtype=processed.dtype,
        )
        processed = np.concatenate([silence, processed, silence], axis=-1)

    return processed


def trim_long_audio(
    audio: np.ndarray,
    sampling_rate: int,
    max_duration: float = 15.0,
    min_duration: float = 3.0,
    trim_threshold: float = 20.0,
) -> np.ndarray:
    """Trim audio to <= *max_duration* by splitting at the largest silence gap.

    Only trims when the audio exceeds *trim_threshold* seconds.

    Args:
        audio: numpy array of shape (C, T).
        sampling_rate: audio sampling rate.
        max_duration: maximum duration in seconds.
        min_duration: minimum duration in seconds.
        trim_threshold: only trim if audio is longer than this (seconds).

    Returns:
        Trimmed numpy array.
    """
    duration = audio.shape[-1] / sampling_rate
    if duration <= trim_threshold:
        return audio

    energy = _to_ms_frames(audio, sampling_rate)
    nonsilent = _detect_nonsilent(energy, 100, -40, 10)
    if not nonsilent:
        return audio

    max_ms = int(max_duration * 1000)
    min_ms = int(min_duration * 1000)

    best_split = 0
    for start, end in nonsilent:
        if start > best_split and start <= max_ms:
            best_split = start
        if end > max_ms:
            break

    if best_split < min_ms:
        best_split = min(max_ms, energy[0].size)

    return _ms_slice(audio, sampling_rate, 0, best_split)


def cross_fade_chunks(
    chunks: list[np.ndarray],
    sample_rate: int,
    silence_duration: float = 0.3,
) -> np.ndarray:
    """Concatenate audio chunks with silence gaps and cross-fade at boundaries.

    Args:
        chunks: list of numpy arrays, each (C, T).
        sample_rate: audio sample rate.
        silence_duration: total silence gap duration in seconds.

    Returns:
        Merged numpy array (C, T_total).
    """
    if len(chunks) == 1:
        return chunks[0]

    total_n = int(silence_duration * sample_rate)
    fade_n = total_n // 3
    silence_n = fade_n
    merged = chunks[0].copy()

    for chunk in chunks[1:]:
        parts = [merged]

        fout_n = min(fade_n, merged.shape[-1])
        if fout_n > 0:
            w_out = np.linspace(1, 0, fout_n, dtype=np.float32)[np.newaxis, :]
            parts[-1][..., -fout_n:] *= w_out

        parts.append(np.zeros((chunks[0].shape[0], silence_n), dtype=np.float32))

        fade_in = chunk.copy()
        fin_n = min(fade_n, fade_in.shape[-1])
        if fin_n > 0:
            w_in = np.linspace(0, 1, fin_n, dtype=np.float32)[np.newaxis, :]
            fade_in[..., :fin_n] *= w_in

        parts.append(fade_in)
        merged = np.concatenate(parts, axis=-1)

    return merged
