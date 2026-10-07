# test_speakers.py - unit tests for speaker detection and reference selection

import numpy as np

from ccgen.core.speakers import assign_speakers, reference_clips

_RATE = 100


def _cue(start, end):
    """A minimal cue spanning start..end seconds."""
    return {"id": 0, "start": start, "end": end, "text": "x", "words": [], "language": "en"}


def _voices_audio(spans, seconds):
    """Audio whose samples carry a per-speaker constant, so a fake embedder can tell them apart."""
    audio = np.zeros(seconds * _RATE, dtype=np.float32)
    for (start, end), voice in spans:
        audio[int(start * _RATE):int(end * _RATE)] = voice
    return audio


def _embed(clip):
    """Fake speaker embedding: one axis per voice value found in the clip."""
    vector = np.zeros(4)
    vector[int(round(float(np.median(clip))))] = 1.0
    return vector


class TestAssignSpeakers:
    def test_two_speakers_alternating(self):
        spans = [((0, 2), 1), ((2, 4), 2), ((4, 6), 1), ((6, 8), 2), ((8, 10), 1), ((10, 12), 2)]
        cues = [_cue(s, e) for (s, e), _ in spans]
        speakers = assign_speakers(cues, _voices_audio(spans, 12), _RATE, _embed, max_speakers=6)
        assert speakers == [0, 1, 0, 1, 0, 1]

    def test_single_voice_is_one_speaker(self):
        spans = [((0, 3), 1), ((3, 6), 1), ((6, 9), 1)]
        cues = [_cue(s, e) for (s, e), _ in spans]
        assert assign_speakers(cues, _voices_audio(spans, 9), _RATE, _embed, max_speakers=6) == [0, 0, 0]

    def test_speaker_limit_merges_the_closest_voices(self):
        spans = [((0, 5), 1), ((5, 10), 2), ((10, 15), 3)]
        cues = [_cue(s, e) for (s, e), _ in spans]
        speakers = assign_speakers(cues, _voices_audio(spans, 15), _RATE, _embed, max_speakers=2)
        assert len(set(speakers)) == 2

    def test_short_cues_take_the_nearest_speaker(self):
        spans = [((0, 3), 1), ((3, 3.5), 2), ((10, 13), 2), ((13, 16), 2)]
        cues = [_cue(s, e) for (s, e), _ in spans]
        speakers = assign_speakers(cues, _voices_audio(spans, 16), _RATE, _embed, max_speakers=6)
        assert speakers[1] == speakers[0]

    def test_brief_speaker_folds_into_a_main_one(self):
        spans = [((0, 3), 1), ((3, 6), 1), ((6, 7.5), 2), ((7.5, 11), 1)]
        cues = [_cue(s, e) for (s, e), _ in spans]
        assert set(assign_speakers(cues, _voices_audio(spans, 11), _RATE, _embed, max_speakers=6)) == {0}

    def test_brief_speaker_joins_the_most_similar_voice_not_the_nearest(self):
        # Voice 3 sounds like voice 1 (similarity 0.45, below the same-speaker cut-off) but is
        # spoken right next to voice 2; with too little speech of its own it must join voice 1.
        def embed(clip):
            value = int(round(float(np.median(clip))))
            return {1: np.array([1.0, 0.0, 0.0]), 2: np.array([0.0, 1.0, 0.0]),
                    3: np.array([0.45, 0.0, 0.89])}[value]

        spans = [((0, 5), 1), ((5, 10), 2), ((10, 12), 3), ((12, 17), 2)]
        cues = [_cue(s, e) for (s, e), _ in spans]
        speakers = assign_speakers(cues, _voices_audio(spans, 17), _RATE, embed, max_speakers=6)
        assert speakers == [0, 1, 0, 1]

    def test_no_cues(self):
        assert assign_speakers([], np.zeros(10), _RATE, _embed, 6) == []


class TestReferenceClips:
    def test_longest_clips_first_up_to_the_limit(self):
        cues = [_cue(0, 2), _cue(2, 10), _cue(10, 20)]
        audio = np.full(20 * _RATE, 0.5, dtype=np.float32)
        refs = reference_clips(cues, audio, _RATE, [0, 0, 0])
        assert [clip.size / _RATE for clip in refs[0]] == [10.25, 8.5]  # each widened by REFERENCE_PAD_S

    def test_one_entry_per_speaker(self):
        cues = [_cue(0, 2), _cue(2, 4)]
        refs = reference_clips(cues, np.ones(4 * _RATE, dtype=np.float32), _RATE, [0, 1])
        assert sorted(refs) == [0, 1]
