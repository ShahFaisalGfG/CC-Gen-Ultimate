# speakers.py - tell speakers apart and pick each one's reference audio for voice cloning
#
# Each cue long enough to carry a voice gets a speaker embedding from the cloning model itself,
# so no separate diarization model or account is needed. Embeddings are grouped by
# average-linkage clustering on cosine similarity. Cues too short to embed reliably take the
# speaker of the nearest embedded cue in time. Each speaker's longest, clearest cues become the
# reference recording the model imitates.

import logging
from typing import Callable, Optional

import numpy as np

from ccgen.core import Segment

_log = logging.getLogger(__name__)

# Shorter cues carry too little voice for a stable embedding.
MIN_EMBED_SECONDS = 1.0
# Cosine similarity above which two groups of cues count as the same voice. XTTS embeddings of
# one voice score about 0.6-0.8 against each other and different voices about 0.0-0.2.
SAME_SPEAKER_SIMILARITY = 0.5
# A detected speaker with less speech than this can't be cloned well, so it joins the closest one.
MIN_SPEAKER_SECONDS = 4.0
# Reference audio collected per speaker; XTTS conditions on up to about this much.
REFERENCE_SECONDS = 12.0
# Reference clips reach this far past their cue on each side, so the cue's first and last words
# are whole: cue times end where the last word does, and a word cut short there is one a cloning
# engine would try to finish before every line.
REFERENCE_PAD_S = 0.25
# Embedding every cue of a long film adds little; the longest ones decide the speakers.
MAX_EMBEDDED_CUES = 300

Embed = Callable[[np.ndarray], np.ndarray]


def assign_speakers(
    cues: list[Segment],
    audio: np.ndarray,
    rate: int,
    embed: Embed,
    max_speakers: int,
    progress: Optional[Callable[[int, int], None]] = None,
) -> list[int]:
    """Return a speaker number (0, 1, ...) for every cue, ordered by first appearance."""
    if not cues:
        return []
    durations = [cue["end"] - cue["start"] for cue in cues]
    eligible = sorted(
        (i for i, d in enumerate(durations) if d >= MIN_EMBED_SECONDS),
        key=lambda i: durations[i], reverse=True,
    )[:MAX_EMBEDDED_CUES]
    if len(eligible) < 2 or max_speakers < 2:
        return [0] * len(cues)
    eligible.sort()
    vectors = []
    for done, index in enumerate(eligible, 1):
        vectors.append(_normalize(embed(_cut(audio, rate, cues[index]))))
        if progress:
            progress(done, len(eligible))
    matrix = np.stack(vectors)
    labels = _absorb_small(_cluster(matrix, max_speakers), matrix, [durations[i] for i in eligible])
    by_cue = dict(zip(eligible, labels))
    assigned = [by_cue.get(i, _nearest_label(i, cues, by_cue)) for i in range(len(cues))]
    return _renumber(assigned)


def reference_clips(
    cues: list[Segment],
    audio: np.ndarray,
    rate: int,
    speakers: list[int],
) -> dict[int, list[np.ndarray]]:
    """Collect up to REFERENCE_SECONDS of each speaker's longest, loudest cues."""
    references: dict[int, list[np.ndarray]] = {}
    for speaker in sorted(set(speakers)):
        members = [cue for cue, s in zip(cues, speakers) if s == speaker]
        clips = sorted((_cut(audio, rate, cue, REFERENCE_PAD_S) for cue in members), key=_clip_score, reverse=True)
        chosen: list[np.ndarray] = []
        total = 0.0
        for clip in clips:
            if total >= REFERENCE_SECONDS or not clip.size:
                break
            chosen.append(clip)
            total += clip.size / rate
        references[speaker] = chosen or [audio[: int(REFERENCE_SECONDS * rate)]]
    return references


def _cut(audio: np.ndarray, rate: int, cue: Segment, pad: float = 0.0) -> np.ndarray:
    """The samples a cue spans, `pad` seconds wider on each side."""
    return audio[max(0, int((cue["start"] - pad) * rate)): max(0, int((cue["end"] + pad) * rate))]


def _clip_score(clip: np.ndarray) -> float:
    """Prefer long clips with a healthy level: duration weighted by loudness (RMS)."""
    if not clip.size:
        return 0.0
    return clip.size * float(np.sqrt(np.mean(np.square(clip, dtype=np.float64))))


def _normalize(vector: np.ndarray) -> np.ndarray:
    """Scale a vector to unit length so dot products are cosine similarities."""
    vector = np.asarray(vector, dtype=np.float64).ravel()
    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def _cluster(vectors: np.ndarray, max_speakers: int) -> list[int]:
    """Average-linkage agglomerative clustering on cosine similarity.

    Merges the two most similar groups until no pair reaches SAME_SPEAKER_SIMILARITY and at
    most `max_speakers` groups remain.
    """
    groups: list[list[int]] = [[i] for i in range(len(vectors))]
    similarity = vectors @ vectors.T
    np.fill_diagonal(similarity, -np.inf)
    while len(groups) > 1:
        a, b = np.unravel_index(np.argmax(similarity), similarity.shape)
        if similarity[a, b] < SAME_SPEAKER_SIMILARITY and len(groups) <= max_speakers:
            break
        a, b = min(a, b), max(a, b)
        size_a, size_b = len(groups[a]), len(groups[b])
        # Average linkage: the merged group's similarity to every other group is the
        # size-weighted mean of its two parts' similarities.
        merged = (similarity[a] * size_a + similarity[b] * size_b) / (size_a + size_b)
        similarity[a, :] = merged
        similarity[:, a] = merged
        similarity[a, a] = -np.inf
        similarity = np.delete(np.delete(similarity, b, axis=0), b, axis=1)
        groups[a].extend(groups.pop(b))
    labels = [0] * len(vectors)
    for label, members in enumerate(groups):
        for index in members:
            labels[index] = label
    return labels


def _absorb_small(labels: list[int], vectors: np.ndarray, durations: list[float]) -> list[int]:
    """Fold speakers with too little speech to clone into the speaker whose voice is closest."""
    totals: dict[int, float] = {}
    for label, duration in zip(labels, durations):
        totals[label] = totals.get(label, 0.0) + duration
    keep = sorted(label for label, total in totals.items() if total >= MIN_SPEAKER_SECONDS)
    if not keep:
        return [0] * len(labels)
    centroids = np.stack([
        _normalize(vectors[[i for i, label in enumerate(labels) if label == kept]].mean(axis=0)) for kept in keep
    ])
    return [label if label in keep else keep[int(np.argmax(centroids @ vectors[i]))] for i, label in enumerate(labels)]


def _nearest_label(index: int, cues: list[Segment], by_cue: dict[int, int]) -> int:
    """Speaker of the embedded cue closest in time to an unembedded one."""
    midpoint = (cues[index]["start"] + cues[index]["end"]) / 2
    nearest = min(by_cue, key=lambda j: abs((cues[j]["start"] + cues[j]["end"]) / 2 - midpoint))
    return by_cue[nearest]


def _renumber(labels: list[int]) -> list[int]:
    """Renumber speakers 0, 1, ... in order of first appearance."""
    order: dict[int, int] = {}
    for label in labels:
        order.setdefault(label, len(order))
    return [order[label] for label in labels]
