# base.py - abstract contract for speech engines used by dubbing

import logging
import re
from abc import ABC, abstractmethod
from typing import Callable, Optional

import numpy as np

from ccgen.config.defaults import DubbingDefaults
from ccgen.config.voices import VoiceOption

_log = logging.getLogger(__name__)

StatusCb = Optional[Callable[[str], None]]
ProgressCb = Optional[Callable[[int, int], None]]

# Reference audio handed to cloning engines is mono float32 at this rate (XTTS's input rate).
REFERENCE_RATE = 22050
# Sentence ends in Latin, CJK, Arabic, and Devanagari punctuation, keeping the mark with its sentence.
_SENTENCE_END = re.compile(r"(?<=[.!?。！？؟।])\s*")


class SpeechEngine(ABC):
    """Turns one line of text into speech with a fixed voice."""

    def __init__(self, voice: VoiceOption, device: str) -> None:
        self.voice = voice
        self._device_preference = device
        self.device_label = ""
        # True when the last synthesize() call had to cut speech that ran on past its text
        # (XTTS-v2's runaway sampling); the dub reports those lines.
        self.last_line_capped = False

    @abstractmethod
    def load(self, status_cb: StatusCb = None, progress_cb: ProgressCb = None) -> None:
        """Download (first use) and load the model on a working device, preferring a GPU."""

    @abstractmethod
    def synthesize(self, text: str, speed: float = 1.0, speaker: int = 0) -> tuple[np.ndarray, int]:
        """Speak `text` and return mono float32 samples and their sample rate.

        `speed` above 1.0 speaks faster. `speaker` picks a cloned voice registered with
        set_speakers(); fixed-voice engines ignore it.
        """

    def _fall_back_to_cpu(self, error: Exception) -> None:
        """Reload on the CPU after the GPU failed mid-run; re-raise when already on the CPU.

        Some GPU drivers only fail on particular inputs, which a short probe at load time can't
        catch, so one failing line moves the rest of the job to the CPU instead of failing it.
        """
        if self._device_preference == DubbingDefaults.DEVICE_CPU or self.device_label in ("", "CPU"):
            raise error
        _log.warning("%s failed on %s, continuing on the CPU: %r", self.voice.key, self.device_label, error)
        self._device_preference = DubbingDefaults.DEVICE_CPU
        self.load()

    def retime(self, text: str, speed: float, speaker: int = 0) -> tuple[np.ndarray, int]:
        """Speak the line just synthesized again at another speed.

        Fixed-voice engines are fast enough to synthesize again; engines that can reuse the
        first pass's work (XTTS) override this to skip the expensive part.
        """
        return self.synthesize(text, speed, speaker)


class CloningEngine(SpeechEngine):
    """A speech engine that imitates speakers from short reference recordings."""

    @abstractmethod
    def embed(self, audio: np.ndarray) -> np.ndarray:
        """Return a speaker embedding (1-D) for `audio` at REFERENCE_RATE, for telling voices apart."""

    @abstractmethod
    def set_speakers(self, references: dict[int, list[np.ndarray]]) -> None:
        """Register each speaker's reference clips (at REFERENCE_RATE) under its speaker id."""


def split_for_speech(text: str, limit: int) -> list[str]:
    """Split text into pieces of at most `limit` characters, preferring sentence ends, then spaces."""
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else []
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    pieces: list[str] = []
    for sentence in sentences:
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit + 1)
            cut = cut if cut > 0 else limit
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if pieces and len(pieces[-1]) + 1 + len(sentence) <= limit:
            pieces[-1] = f"{pieces[-1]} {sentence}"
        elif sentence:
            pieces.append(sentence)
    return pieces

