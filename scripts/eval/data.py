# data.py - benchmark test data: FLORES-200 sentences and FLEURS read speech
#
# FLORES-200 (CC-BY-SA-4.0) has the same 1012 devtest sentences professionally translated into
# every language CC-Gen supports, so it scores translation in any direction. FLEURS (CC-BY-4.0)
# has native speakers reading FLORES sentences aloud; it is the known-good speech every dub is
# compared against, and its speakers are the voices the cloning engines imitate. Both are
# downloaded once into the benchmark cache and never committed.

import csv
import os
import tarfile
import urllib.request
from dataclasses import dataclass

import numpy as np
import soundfile

FLORES_URL = "https://dl.fbaipublicfiles.com/nllb/flores200_dataset.tar.gz"
FLEURS_REPO = "google/fleurs"
FLEURS_REVISION = "70bb2e84b976b7e960aa89f1c648e09c59f894dd"
# FLORES file names and FLEURS folders for every language CC-Gen translates and dubs.
FLORES_CODES = {
    "ar": "arb_Arab", "de": "deu_Latn", "en": "eng_Latn", "es": "spa_Latn", "fr": "fra_Latn",
    "hi": "hin_Deva", "ja": "jpn_Jpan", "ko": "kor_Hang", "pt": "por_Latn", "ru": "rus_Cyrl",
    "tr": "tur_Latn", "ur": "urd_Arab", "zh": "zho_Hans",
}
FLEURS_CODES = {
    "ar": "ar_eg", "de": "de_de", "en": "en_us", "es": "es_419", "fr": "fr_fr", "hi": "hi_in",
    "ja": "ja_jp", "ko": "ko_kr", "pt": "pt_br", "ru": "ru_ru", "tr": "tr_tr", "ur": "ur_pk",
    "zh": "cmn_hans_cn",
}
LANGUAGES = tuple(FLORES_CODES)
# Seconds a download may wait for data before failing (a stalled connection would hang forever).
_TIMEOUT_S = 120


def cache_root() -> str:
    """Folder holding downloaded benchmark data and results (outside the repository)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "CC-Gen-Ultimate", "eval")


def flores(language: str, count: int) -> list[str]:
    """The first `count` FLORES-200 devtest sentences in `language`."""
    folder = os.path.join(cache_root(), "flores200")
    path = os.path.join(folder, f"{FLORES_CODES[language]}.devtest")
    if not os.path.exists(path):
        _extract_flores(folder)
    with open(path, encoding="utf-8") as fh:
        return [line.rstrip("\n") for line in fh][:count]


def _extract_flores(folder: str) -> None:
    """Download the FLORES-200 archive once and keep the devtest files of our languages."""
    os.makedirs(folder, exist_ok=True)
    wanted = {f"{code}.devtest" for code in FLORES_CODES.values()}
    with urllib.request.urlopen(FLORES_URL, timeout=_TIMEOUT_S) as response, tarfile.open(fileobj=response, mode="r|gz") as archive:
        for member in archive:
            name = os.path.basename(member.name)
            if "/devtest/" in member.name and name in wanted:
                data = archive.extractfile(member)
                assert data is not None
                with open(os.path.join(folder, name), "wb") as out:
                    out.write(data.read())


@dataclass(frozen=True)
class Utterance:
    """One FLEURS recording: a native speaker reading a sentence."""

    language: str
    key: str
    text: str
    gender: str
    audio: np.ndarray
    rate: int

    @property
    def seconds(self) -> float:
        return self.audio.size / self.rate


def fleurs(language: str, count: int) -> list[Utterance]:
    """`count` FLEURS test recordings in `language`, alternating speaker gender where possible."""
    folder = os.path.join(cache_root(), "fleurs", FLEURS_CODES[language])
    rows = _fleurs_rows(language, folder)
    by_gender: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_gender.setdefault(row["gender"], []).append(row)
    # Interleave genders so a small sample still has both kinds of voice.
    picked: list[dict[str, str]] = []
    queues = list(by_gender.values())
    while len(picked) < count and any(queues):
        for queue in queues:
            if queue and len(picked) < count:
                picked.append(queue.pop(0))
    _fetch_audio(language, folder, {row["file"] for row in picked})
    utterances = []
    for row in picked:
        audio, rate = soundfile.read(os.path.join(folder, row["file"]), dtype="float32")
        utterances.append(Utterance(language, row["file"], row["text"], row["gender"], audio, rate))
    return utterances


def _fleurs_rows(language: str, folder: str) -> list[dict[str, str]]:
    """The test split's rows, one per distinct file, in file order."""
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(FLEURS_REPO, f"data/{FLEURS_CODES[language]}/test.tsv", repo_type="dataset",
                           revision=FLEURS_REVISION)
    os.makedirs(folder, exist_ok=True)
    rows: dict[str, dict[str, str]] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        for record in csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            # id, file name, raw transcription, normalized transcription, letters, samples, gender
            rows.setdefault(record[1], {"file": record[1], "text": record[2], "gender": record[6]})
    return list(rows.values())


def _fetch_audio(language: str, folder: str, files: set[str]) -> None:
    """Stream the test audio archive until every wanted file is on disk."""
    missing = {name for name in files if not os.path.exists(os.path.join(folder, name))}
    if not missing:
        return
    from huggingface_hub import hf_hub_url

    url = hf_hub_url(FLEURS_REPO, f"data/{FLEURS_CODES[language]}/audio/test.tar.gz", repo_type="dataset",
                     revision=FLEURS_REVISION)
    with urllib.request.urlopen(url, timeout=_TIMEOUT_S) as response, tarfile.open(fileobj=response, mode="r|gz") as archive:
        for member in archive:
            name = os.path.basename(member.name)
            if name in missing:
                data = archive.extractfile(member)
                assert data is not None
                with open(os.path.join(folder, name), "wb") as out:
                    out.write(data.read())
                missing.discard(name)
                if not missing:
                    break


def read_audio(path: str, track: int = 0) -> tuple[np.ndarray, int]:
    """Mono float32 samples of one audio track of any media file (decoded with PyAV, as the app does)."""
    import av

    with av.open(path) as container:
        stream = container.streams.audio[track]
        rate = stream.codec_context.sample_rate
        resampler = av.AudioResampler(format="flt", layout="mono", rate=rate)
        chunks = [
            frame.to_ndarray().ravel()
            for packet in container.demux(stream)
            for decoded in packet.decode()
            for frame in resampler.resample(decoded)
        ]
    return (np.concatenate(chunks) if chunks else np.zeros(0, np.float32)), rate


def write_wav(path: str, audio: np.ndarray, rate: int) -> None:
    """Save a clip for listening."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    soundfile.write(path, audio, rate, subtype="PCM_16")


__all__ = ["LANGUAGES", "Utterance", "cache_root", "flores", "fleurs", "read_audio", "write_wav"]
