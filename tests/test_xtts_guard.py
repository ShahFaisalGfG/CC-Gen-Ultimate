# test_xtts_guard.py - XTTS-v2 runaway takes are retried cooler, then cut to a plausible length

from types import SimpleNamespace

import numpy as np
import pytest
import torch

from ccgen.config.voices import xtts_voice
from ccgen.core.dubbing import TrackReport

_RATE = 1000  # samples per second, small enough for fast tests
_FRAMES_PER_S = 20


class _FakeModel:
    """Returns takes of the given lengths in seconds, one per inference call."""

    def __init__(self, seconds: list[float]) -> None:
        self.seconds = list(seconds)
        self.temperatures: list[object] = []
        self.tokenizer = SimpleNamespace(char_limits={"en": 250})
        self.config = SimpleNamespace(audio=SimpleNamespace(output_sample_rate=_RATE))
        self.device = "cpu"

    def inference(self, text, language, latent, embedding, speed=1.0, **options):
        self.temperatures.append(options.get("temperature"))
        length = self.seconds.pop(0)
        frames = int(length * _FRAMES_PER_S)
        return {
            "wav": np.ones(int(length * _RATE), np.float32),
            "gpt_latents": np.arange(frames * 2, dtype=np.float32).reshape(1, frames, 2),
        }

    def hifigan_decoder(self, latents, g=None):
        return torch.ones(latents.shape[1] * _RATE // _FRAMES_PER_S)


@pytest.fixture
def engine_for(monkeypatch):
    from ccgen.engines.speech import xtts_engine

    def build(seconds):
        model = _FakeModel(seconds)
        monkeypatch.setattr(xtts_engine._models, "get_or_load", lambda key, loader: (model, "CPU"))
        engine = xtts_engine.XttsEngine(xtts_voice("en"), "cpu")
        engine.load()
        engine._speakers = {0: (None, None)}
        return engine, model

    return build


class TestRunawayGuard:
    TEXT = "A short line."  # 13 characters: about 1.2 s expected, 2.6 s allowed

    def test_a_take_of_normal_length_is_kept(self, engine_for):
        engine, model = engine_for([1.2])
        wav, _ = engine.synthesize(self.TEXT)
        assert wav.size == int(1.2 * _RATE)
        assert model.temperatures == [None]
        assert not engine.last_line_capped

    def test_a_runaway_take_is_spoken_again_cooler(self, engine_for):
        engine, model = engine_for([6.0, 1.3])
        wav, _ = engine.synthesize(self.TEXT)
        assert wav.size == int(1.3 * _RATE)
        assert model.temperatures == [None, 0.5]
        assert not engine.last_line_capped

    def test_when_every_take_runs_on_the_shortest_is_cut(self, engine_for):
        engine, model = engine_for([7.0, 5.0, 6.0])
        wav, _ = engine.synthesize(self.TEXT)
        assert model.temperatures == [None, 0.5, 0.3]
        assert engine.last_line_capped
        # Capped to 1.3x the expected length, far below the 5 s shortest take.
        assert 1.0 * _RATE <= wav.size <= 1.8 * _RATE

    def test_a_capped_line_can_still_be_retimed(self, engine_for):
        engine, _ = engine_for([7.0, 5.0, 6.0])
        engine.synthesize(self.TEXT)
        latents = engine._last_line[2][0]
        assert latents.shape[1] < 5 * _FRAMES_PER_S


class TestRanOnNote:
    def test_lines_that_ran_on_are_named(self):
        report = TrackReport(ran_on=[3, 12])
        assert report.warnings() == [
            "2 line(s) kept talking past their text, so the extra speech was cut (subtitle 3, 12). "
            "Listen to them, and dub again if one sounds wrong."
        ]
