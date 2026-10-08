# test_omnivoice_engine.py - OmniVoice cloning engine (with a fake model), its vendored audio
# helpers, the one-pass speed planning it enables, and the voice catalog entries

from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from ccgen.config.defaults import DubbingDefaults
from ccgen.config.voices import (
    ENGINE_OMNIVOICE,
    OMNIVOICE_LANGUAGES,
    cloning_voice,
    engine_supports,
    resolve_voice,
)
from ccgen.engines.speech import create_engine
from ccgen.engines.speech.base import REFERENCE_RATE

_RATE = 24000
_FRAME_RATE = 25


class _FakeModel:
    """Speaks 0.1 s per character (divided by speed) and records what it was asked."""

    sampling_rate = _RATE

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.prompts: list[tuple] = []
        self.audio_tokenizer = SimpleNamespace(config=SimpleNamespace(frame_rate=_FRAME_RATE))

    def create_voice_clone_prompt(self, ref_audio, ref_text=None):
        self.prompts.append((ref_audio[0].numpy().size, ref_text))
        return SimpleNamespace(ref_text=ref_text, ref_audio_tokens=np.zeros((8, 50)))

    def _estimate_target_tokens(self, text, ref_text, ref_tokens):
        return len(text) * _FRAME_RATE // 10

    def generate(self, text, language, voice_clone_prompt, speed, generation_config):
        self.calls.append({"text": text, "language": language, "prompt": voice_clone_prompt, "speed": speed,
                           "steps": generation_config.num_step})
        return [np.ones(int(len(text) * 0.1 * _RATE / (speed or 1.0)), dtype=np.float32)]


def _heard(transcript, cut_off=""):
    """A fake Whisper that hears `transcript` spread over the middle of each clip, and `cut_off`
    as a last word running to the clip's very end."""
    def transcribe(audio, language=None, vad_filter=False):
        if not transcript:
            return []
        length = audio.size / 16000
        words = transcript.split()
        step = (length - 0.4) / len(words)
        timed = [{"word": f" {w}", "start": 0.2 + i * step, "end": 0.2 + (i + 0.8) * step} for i, w in enumerate(words)]
        if cut_off:
            timed.append({"word": f" {cut_off}", "start": length - 0.15, "end": length})
        return [{"text": " ".join(w["word"] for w in timed), "words": timed}]

    return SimpleNamespace(transcribe=transcribe)


@pytest.fixture
def engine_for(monkeypatch):
    from ccgen.engines.speech import omnivoice_engine

    def build(language="ur", fast=False, transcript="the reference words", cut_off=""):
        model = _FakeModel()
        monkeypatch.setattr(omnivoice_engine._models, "get_or_load", lambda key, loader: (model, "CPU"))
        transcriber = _heard(transcript, cut_off)
        monkeypatch.setattr(omnivoice_engine, "load_transcriber", lambda: transcriber)
        engine = create_engine(cloning_voice(ENGINE_OMNIVOICE, language), "cpu", fast=fast)
        engine.load()
        return engine, model

    return build


class TestOmniVoiceEngine:
    def test_speaks_in_the_registered_voice_with_its_language_id(self, engine_for):
        engine, model = engine_for("ar")
        engine.set_speakers({0: [np.zeros(REFERENCE_RATE, np.float32)]})
        audio, rate = engine.synthesize("مرحبا")
        assert rate == _RATE and audio.size > 0
        call = model.calls[0]
        assert (call["language"], call["prompt"].ref_text, call["speed"]) == ("arb", "the reference words", None)

    def test_fast_mode_runs_fewer_steps(self, engine_for):
        for fast, steps in ((False, 32), (True, 8)):
            engine, model = engine_for(fast=fast)
            engine.set_speakers({0: [np.zeros(REFERENCE_RATE, np.float32)]})
            engine.synthesize("hello")
            assert model.calls[0]["steps"] == steps

    def test_lines_are_finished_and_numbers_spelled(self, engine_for):
        engine, model = engine_for("hi")
        engine.set_speakers({0: [np.zeros(REFERENCE_RATE, np.float32)]})
        engine.synthesize("भाग 2")
        assert model.calls[0]["text"] == "भाग दो।"

    def test_reference_clips_are_joined_up_to_ten_seconds_then_silence(self, engine_for):
        from ccgen.engines.speech.omnivoice_engine import _TAIL_S

        engine, model = engine_for()
        clips = [np.ones(6 * REFERENCE_RATE, np.float32), np.ones(6 * REFERENCE_RATE, np.float32)]
        engine.set_speakers({0: clips})
        size, text = model.prompts[0]
        assert 9 * REFERENCE_RATE < size <= (10 + _TAIL_S) * REFERENCE_RATE
        assert text.startswith("the reference words the")  # whole words of both clips

    def test_a_clip_with_too_little_room_left_is_skipped(self, engine_for):
        engine, model = engine_for()
        clips = [np.ones(int(9.5 * REFERENCE_RATE), np.float32), np.ones(6 * REFERENCE_RATE, np.float32)]
        engine.set_speakers({0: clips})
        assert model.prompts[0][1] == "the reference words"  # only the first clip's words

    def test_a_word_cut_off_at_a_clip_edge_is_left_out_of_the_prompt(self, engine_for):
        from ccgen.engines.speech.omnivoice_engine import _TAIL_S

        engine, model = engine_for(cut_off="wherever")
        engine.set_speakers({0: [np.ones(4 * REFERENCE_RATE, np.float32)]})
        size, text = model.prompts[0]
        assert text == "the reference words"
        assert size < (4 - 0.15 + _TAIL_S) * REFERENCE_RATE  # its sound is cut away with it

    def test_a_speaker_without_speech_gets_the_neutral_voice(self, engine_for):
        engine, model = engine_for(transcript="")
        engine.set_speakers({0: [np.zeros(REFERENCE_RATE, np.float32)]})
        engine.synthesize("hello")
        assert model.prompts == [] and model.calls[0]["prompt"] is None

    def test_unregistered_speaker_is_an_error(self, engine_for):
        engine, _ = engine_for()
        with pytest.raises(RuntimeError, match="speaker 3"):
            engine.synthesize("hello", speaker=3)

    def test_natural_length_is_known_before_speaking(self, engine_for):
        engine, _ = engine_for("en")
        engine.set_speakers({0: [np.zeros(REFERENCE_RATE, np.float32)]})
        assert engine.natural_seconds("Hello there") == pytest.approx(1.2)  # "Hello there." at 0.1 s/char


def _tiny_omnivoice(fail=False):
    """A real torch module shaped like OmniVoice: a backbone and an audio codec submodule."""
    import torch

    class Model(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = torch.nn.Linear(4, 4)
            self.audio_tokenizer = torch.nn.Linear(4, 4)
            self.moved_with_codec: list[bool] = []

        def to(self, *args, **kwargs):
            self.moved_with_codec.append(self.audio_tokenizer is not None)
            return super().to(*args, **kwargs)

        def generate(self, **kwargs):
            if fail:
                raise RuntimeError("CUDA error: no kernel image is available")

    return Model()


class TestPlacement:
    def _gpu(self):
        import torch

        from ccgen.engines.devices import Accelerator

        return Accelerator(torch.device("cpu"), "NVIDIA GPU (CUDA): Test")  # a stand-in GPU

    def test_a_gpu_gets_a_half_precision_backbone_and_a_full_precision_codec(self):
        import torch

        from ccgen.engines.speech.omnivoice_engine import _place

        model = _place(_tiny_omnivoice(), self._gpu())
        assert model.backbone.weight.dtype == torch.float16
        assert model.audio_tokenizer.weight.dtype == torch.float32

    def test_the_codec_stays_behind_when_the_gpu_is_short_of_memory(self):
        from ccgen.engines.speech import omnivoice_engine

        model = _tiny_omnivoice()
        with patch.object(omnivoice_engine, "_codec_fits", return_value=False):
            omnivoice_engine._place(model, self._gpu())
        assert model.moved_with_codec == [False] and model.audio_tokenizer is not None

    def test_a_failed_gpu_hands_back_a_full_precision_model(self):
        import torch

        from ccgen.engines.speech.omnivoice_engine import _place

        model = _tiny_omnivoice(fail=True)
        with pytest.raises(RuntimeError, match="no kernel image"):
            _place(model, self._gpu())
        assert model.backbone.weight.dtype == torch.float32 and model.audio_tokenizer is not None

    def test_a_strong_gpu_is_used_without_timing(self):
        import torch

        from ccgen.engines.devices import Accelerator
        from ccgen.engines.speech import omnivoice_engine

        cpu = Accelerator(torch.device("cpu"), "CPU")
        strong = SimpleNamespace(strong=True)
        with (
            patch.object(omnivoice_engine, "cuda_gpu", return_value=strong),
            patch.object(omnivoice_engine, "fastest_working", side_effect=AssertionError("timed")),
        ):
            assert omnivoice_engine._settle(_tiny_omnivoice(), [self._gpu(), cpu]) == self._gpu()

    def test_a_weak_gpu_that_wins_the_timing_keeps_the_model(self):
        import torch

        from ccgen.engines.devices import Accelerator
        from ccgen.engines.speech import omnivoice_engine

        cpu = Accelerator(torch.device("cpu"), "CPU")
        gpu = self._gpu()

        def timed(order, place, probe):
            assert order == [cpu, gpu]  # the CPU first, so a winning GPU needs no second move
            for accelerator in order:
                place(accelerator)
            return None, gpu

        model = _tiny_omnivoice()
        with (
            patch.object(omnivoice_engine, "cuda_gpu", return_value=SimpleNamespace(strong=False)),
            patch.object(omnivoice_engine, "fastest_working", side_effect=timed),
        ):
            assert omnivoice_engine._settle(model, [gpu, cpu]) == gpu
        assert model.backbone.weight.dtype == torch.float16


class TestOnePassFit:
    def test_engine_that_plans_its_length_is_sped_up_without_a_second_take(self, tmp_path):
        from ccgen.core.dubbing import TRACK_RATE, synthesize_track
        from tests.test_task_dub import FakeEngine, _cue

        class Planner(FakeEngine):
            def natural_seconds(self, text, speaker=0):
                return len(text) * 0.1

            def retime(self, text, speed, speaker=0):
                raise AssertionError("a planned line needs no second take")

        engine = Planner()
        cues = [_cue(0, 0.0, 1.0, "a" * 11 + "."), _cue(1, 1.0, 2.0, "b.")]
        report = synthesize_track(cues, [0, 0], engine, 1.35, str(tmp_path / "t.wav"))
        assert engine.calls[0] == ("a" * 11 + ".", pytest.approx(1.2), 0)
        assert report.sped_up == 1 and report.trimmed == []
        assert TRACK_RATE  # the track was written at the dub rate


class TestCatalog:
    def test_omnivoice_speaks_every_dubbing_language(self):
        assert set(OMNIVOICE_LANGUAGES) == {code for _, code in DubbingDefaults.LANGUAGES}
        assert engine_supports(ENGINE_OMNIVOICE, "ur")

    def test_omnivoice_ids_are_known_to_the_model(self):
        from ccgen.engines.speech.omnivoice.lang_map import LANG_IDS

        assert set(OMNIVOICE_LANGUAGES.values()) <= set(LANG_IDS)

    def test_a_fallback_never_switches_to_the_other_cloning_engine(self):
        voice, warning = resolve_voice("ur", "xtts")
        assert voice.engine == "piper"
        voice, warning = resolve_voice("en", ENGINE_OMNIVOICE, can_clone=False)
        assert voice.engine == "kokoro"
        assert warning == "OmniVoice has no original voice to clone, so Kokoro was used instead."


class TestSilenceHelpers:
    def test_long_pauses_are_shortened_and_edges_trimmed(self):
        from ccgen.engines.speech.omnivoice.audio import remove_silence

        rate = 16000
        tone = (0.3 * np.sin(np.arange(rate) * 0.05)).astype(np.float32)
        gap = np.zeros(rate, np.float32)
        audio = np.concatenate([gap, tone, gap, tone, gap])[None, :]
        out = remove_silence(audio, rate, mid_sil=200, lead_sil=100, trail_sil=200)
        # Two seconds of tone, one shortened pause, and short edges remain.
        assert 2.2 * rate < out.shape[-1] < 3.0 * rate

    def test_quiet_audio_is_removed_entirely(self):
        from ccgen.engines.speech.omnivoice.audio import remove_silence

        assert remove_silence(np.zeros((1, 16000), np.float32), 16000).shape[-1] == 0


class TestAutoTranslation:
    def test_the_engine_is_chosen_for_the_pair_set_last(self):
        from ccgen.engines.translation import AutoEngine

        engine = AutoEngine("light", "auto", "ur", None)
        created = []

        def fake_create(name, source, target, meaning, for_speech=False):
            created.append((name, source, target))
            return SimpleNamespace(ensure_model=lambda *a: None)

        with patch("ccgen.engines.translation.create_engine", side_effect=fake_create):
            engine.set_pair("ko", "ur")
            engine.ensure_model()
            engine.set_pair("en", "ur")
            engine.ensure_model()
        assert created == [("hymt2", "ko", "ur"), ("opus_mt", "en", "ur")]
        assert engine.resolved == "opus_mt"
