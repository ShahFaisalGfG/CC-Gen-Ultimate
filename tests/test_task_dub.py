# test_task_dub.py - unit tests for track assembly, muxing, and the dub task

import wave
from unittest.mock import MagicMock, patch

import av
import numpy as np
import pytest

from ccgen.core.dubbing import TRACK_RATE, attach_track, synthesize_track
from ccgen.core.tasks.configs import DubConfig
from ccgen.core.tasks.dub import DubTask
from ccgen.engines.speech.base import CloningEngine, SpeechEngine, finish_sentence, split_for_speech

_ENGINE_RATE = 24000


class FakeEngine(SpeechEngine):
    """Speaks each character as 0.1 s of tone, divided by the requested speed."""

    def __init__(self, voice=None, device="auto"):
        super().__init__(voice, device)
        self.device_label = "CPU"
        self.calls: list[tuple[str, float, int]] = []

    def load(self, status_cb=None, progress_cb=None):
        pass

    def synthesize(self, text, speed=1.0, speaker=0):
        self.calls.append((text, speed, speaker))
        return np.full(int(len(text) * 0.1 * _ENGINE_RATE / speed), 0.5, dtype=np.float32), _ENGINE_RATE


class FakeCloner(FakeEngine, CloningEngine):
    """Fake cloning engine recording the reference clips it was given."""

    def __init__(self, voice=None, device="auto"):
        super().__init__(voice, device)
        self.references = None

    def embed(self, audio):
        return np.array([1.0, 0.0])

    def set_speakers(self, references):
        self.references = references


def _cue(i, start, end, text):
    """A cue with the given timing and text."""
    return {"id": i, "start": start, "end": end, "text": text, "words": [], "language": "es"}


def _read_track(path):
    """Return the samples of a written 16-bit mono WAV."""
    with wave.open(str(path), "rb") as wav:
        assert (wav.getnchannels(), wav.getframerate()) == (1, TRACK_RATE)
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")


def _write_media(path, seconds=3, video=True, start=0):
    """Write a small media file with a stereo tone, optionally video, starting at `start` seconds."""
    with av.open(str(path), "w") as container:
        # Every stream must exist before the first packet is muxed.
        video_stream = container.add_stream("mpeg4", rate=10) if video else None
        audio = container.add_stream("aac", rate=44100, layout="stereo")
        if video_stream is not None:
            video_stream.width = video_stream.height = 32
            video_stream.pix_fmt = "yuv420p"
            for index in range(seconds * 10):
                frame = av.VideoFrame.from_ndarray(np.zeros((32, 32, 3), dtype=np.uint8), format="rgb24")
                frame.pts = start * 10 + index
                for packet in video_stream.encode(frame):
                    container.mux(packet)
        tone = (0.2 * np.sin(np.arange(44100 * seconds) * 0.03)).astype(np.float32)
        for offset in range(0, tone.size, 1024):
            frame = av.AudioFrame.from_ndarray(np.stack([tone[offset:offset + 1024]] * 2), format="fltp", layout="stereo")
            frame.sample_rate, frame.pts = 44100, start * 44100 + offset
            for packet in audio.encode(frame):
                container.mux(packet)
        for stream in container.streams:
            for packet in stream.encode():
                container.mux(packet)


class TestSynthesizeTrack:
    def test_places_speech_at_cue_start(self, tmp_path):
        engine = FakeEngine()
        report = synthesize_track([_cue(0, 1.0, 2.0, "abc")], [0], engine, 1.35, str(tmp_path / "t.wav"))
        samples = _read_track(str(tmp_path / "t.wav"))
        assert samples[: TRACK_RATE - 1].max() == 0
        assert samples[TRACK_RATE] > 0
        assert samples.size == TRACK_RATE + int(0.3 * TRACK_RATE)
        assert report.spoken == 1 and not report.warnings()

    def test_speeds_up_speech_that_overruns_its_slot(self, tmp_path):
        engine = FakeEngine()
        cues = [_cue(0, 0.0, 1.0, "a" * 11 + "."), _cue(1, 1.0, 2.0, "b.")]
        report = synthesize_track(cues, [0, 0], engine, 1.35, str(tmp_path / "t.wav"))
        assert engine.calls[1] == ("a" * 11 + ".", 1.2, 0)
        assert report.sped_up == 1 and report.trimmed == []

    def test_speed_up_uses_the_engines_cheaper_retime(self, tmp_path):
        class Retimer(FakeEngine):
            def retime(self, text, speed, speaker=0):
                self.calls.append(("retime", speed, speaker))
                return super().synthesize(text, speed, speaker)

        engine = Retimer()
        cues = [_cue(0, 0.0, 1.0, "a" * 11 + "."), _cue(1, 1.0, 2.0, "b.")]
        synthesize_track(cues, [0, 0], engine, 1.35, str(tmp_path / "t.wav"))
        assert engine.calls[1] == ("retime", 1.2, 0)

    def test_trims_and_warns_when_speed_up_is_not_enough(self, tmp_path):
        cues = [_cue(0, 0.0, 1.0, "a" * 29 + "."), _cue(1, 1.0, 2.0, "b.")]
        report = synthesize_track(cues, [0, 0], FakeEngine(), 1.35, str(tmp_path / "t.wav"))
        assert report.trimmed == [1]
        assert "1 line(s) were too long" in report.warnings()[0]
        # Faded to silence a second past the slot end, where the next line then starts.
        assert _read_track(str(tmp_path / "t.wav"))[2 * TRACK_RATE - 1] == 0

    def test_overrun_within_a_second_delays_the_next_line(self, tmp_path):
        cues = [_cue(0, 0.0, 0.5, "abc."), _cue(1, 0.2, 2.0, "d.")]
        report = synthesize_track(cues, [0, 0], FakeEngine(), 1.0, str(tmp_path / "t.wav"))
        assert report.trimmed == []
        assert _read_track(str(tmp_path / "t.wav")).size == int(0.4 * TRACK_RATE) + int(0.2 * TRACK_RATE)

    def test_the_last_line_is_sped_up_to_end_with_the_media(self, tmp_path):
        engine = FakeEngine()
        cues = [_cue(0, 0.0, 1.0, "a" * 9 + ".")]
        report = synthesize_track(cues, [0], engine, 1.35, str(tmp_path / "t.wav"), end=0.8)
        assert engine.calls[-1][1] == pytest.approx(1.25)
        assert report.trimmed == []
        assert _read_track(str(tmp_path / "t.wav")).size <= int(0.8 * TRACK_RATE)

    def test_speech_past_the_media_end_is_cut_and_reported(self, tmp_path):
        cues = [_cue(0, 0.0, 1.0, "a" * 19 + ".")]
        report = synthesize_track(cues, [0], FakeEngine(), 1.35, str(tmp_path / "t.wav"), end=1.0)
        assert report.trimmed == [1]
        assert _read_track(str(tmp_path / "t.wav")).size == TRACK_RATE

    def test_a_line_starting_after_the_media_ends_is_reported_not_spoken(self, tmp_path):
        engine = FakeEngine()
        cues = [_cue(0, 0.0, 1.0, "a."), _cue(1, 3.0, 4.0, "b.")]
        report = synthesize_track(cues, [0, 0], engine, 1.35, str(tmp_path / "t.wav"), end=2.0)
        assert [c[0] for c in engine.calls] == ["a."]
        assert report.trimmed == [2] and report.spoken == 1

    def test_a_sentence_over_several_cues_is_spoken_once_in_their_time(self, tmp_path):
        engine = FakeEngine()
        cues = [_cue(0, 0.0, 1.0, "one two"), _cue(1, 1.0, 2.0, "three."), _cue(2, 2.0, 3.0, "four.")]
        report = synthesize_track(cues, [0, 0, 0], engine, 1.35, str(tmp_path / "t.wav"))
        assert [c[0] for c in engine.calls] == ["one two three.", "four."]
        assert engine.calls[0][1] == 1.0  # 1.4 s fits the two cues' 2 s, so no speed-up
        assert report.spoken == 2

    def test_a_sentence_is_split_where_the_speaker_changes(self, tmp_path):
        engine = FakeEngine()
        cues = [_cue(0, 0.0, 1.0, "hello"), _cue(1, 1.0, 2.0, "there.")]
        synthesize_track(cues, [0, 1], engine, 1.35, str(tmp_path / "t.wav"))
        assert [(c[0], c[2]) for c in engine.calls] == [("hello", 0), ("there.", 1)]

    def test_chinese_cues_are_joined_without_spaces(self, tmp_path):
        engine = FakeEngine()
        cues = [_cue(0, 0.0, 1.0, "你好"), _cue(1, 1.0, 2.0, "世界。")]
        synthesize_track(cues, [0, 0], engine, 1.35, str(tmp_path / "t.wav"), language="zh")
        assert engine.calls[0][0] == "你好世界。"

    def test_passes_each_cues_speaker(self, tmp_path):
        engine = FakeEngine()
        synthesize_track([_cue(0, 0, 1, "a"), _cue(1, 1, 2, "b")], [0, 1], engine, 1.35, str(tmp_path / "t.wav"))
        assert [c[2] for c in engine.calls] == [0, 1]

    def test_cancel_stops_between_cues(self, tmp_path):
        from ccgen.utils.callbacks import JobCancelled

        with pytest.raises(JobCancelled):
            synthesize_track([_cue(0, 0, 1, "a")], [0], FakeEngine(), 1.35, str(tmp_path / "t.wav"), cancelled=lambda: True)


class TestAttachTrack:
    def _dub_wav(self, path, seconds):
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(TRACK_RATE)
            wav.writeframes((np.ones(int(seconds * TRACK_RATE)) * 1000).astype("<i2").tobytes())

    def test_adds_a_tagged_track_and_keeps_the_originals(self, tmp_path):
        _write_media(tmp_path / "in.mp4")
        self._dub_wav(tmp_path / "dub.wav", 1.0)
        attach_track(str(tmp_path / "in.mp4"), str(tmp_path / "dub.wav"), str(tmp_path / "out.mkv"),
                     "Dub (es, Piper)", "es", make_default=True)
        with av.open(str(tmp_path / "out.mkv")) as out:
            kinds = [s.type for s in out.streams]
            dub = out.streams.audio[1]
            assert kinds == ["video", "audio", "audio"]
            assert dub.metadata["title"] == "Dub (es, Piper)"
            assert dub.metadata["language"] == "spa"
            assert dub.disposition & av.stream.Disposition.default
            assert not out.streams.audio[0].disposition & av.stream.Disposition.default
            samples = sum(frame.samples for frame in out.decode(dub))
        # Padded with silence to the source's length.
        assert abs(samples / TRACK_RATE - 3.0) < 0.1

    def test_dub_starts_where_the_source_timestamps_start(self, tmp_path):
        # MPEG-TS files start their timestamps well after zero; the dub must start there too.
        _write_media(tmp_path / "in.ts", start=2)
        self._dub_wav(tmp_path / "dub.wav", 1.0)
        attach_track(str(tmp_path / "in.ts"), str(tmp_path / "dub.wav"), str(tmp_path / "out.mkv"), "Dub", "es", False)
        with av.open(str(tmp_path / "in.ts")) as source:
            start = source.start_time / av.time_base
        assert start > 1.5
        with av.open(str(tmp_path / "out.mkv")) as out:
            dub = out.streams.audio[1]
            first = next(p for p in out.demux(dub) if p.pts is not None)
            original = next(p for p in out.demux(out.streams.audio[0]) if p.pts is not None)
            assert abs(float(first.pts * first.time_base) - float(original.pts * original.time_base)) < 0.1

    def test_cancel_leaves_no_output(self, tmp_path):
        from ccgen.utils.callbacks import JobCancelled

        _write_media(tmp_path / "in.mp4")
        self._dub_wav(tmp_path / "dub.wav", 1.0)
        with pytest.raises(JobCancelled):
            attach_track(str(tmp_path / "in.mp4"), str(tmp_path / "dub.wav"), str(tmp_path / "out.mkv"),
                         "Dub", "es", False, cancelled=lambda: True)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["dub.wav", "in.mp4"]


class TestDubConfig:
    def test_media_needs_a_subtitle(self, tmp_path):
        with pytest.raises(ValueError, match="Choose the subtitle file"):
            DubConfig(input_path=str(tmp_path / "a.mp4"))

    def test_subtitle_alone_cannot_add_a_track(self, tmp_path):
        with pytest.raises(ValueError, match="separate WAV"):
            DubConfig(input_path=str(tmp_path / "a_es.srt"))

    def test_unknown_quality_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="voice cloning quality"):
            DubConfig(input_path=str(tmp_path / "a.mp4"), subtitle_path=str(tmp_path / "a.srt"), quality="slow")

    def test_speed_up_range(self, tmp_path):
        with pytest.raises(ValueError, match="speed-up"):
            DubConfig(input_path=str(tmp_path / "a.mp4"), subtitle_path=str(tmp_path / "a.srt"), max_speedup=5)


class TestDubTask:
    @pytest.fixture
    def files(self, tmp_path):
        _write_media(tmp_path / "movie.mp4")
        (tmp_path / "movie_es.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhola\n\n2\n00:00:01,500 --> 00:00:02,500\nadios\n",
            encoding="utf-8",
        )
        return tmp_path

    def _run(self, config, engine):
        heard = MagicMock()
        heard.transcribe.side_effect = lambda audio, language=None, vad_filter=False: [{"text": "hola adios"}]
        with (
            patch("ccgen.core.tasks.dub.create_engine", return_value=engine),
            patch("ccgen.core.tasks.dub.load_transcriber", return_value=heard),
        ):
            task = DubTask(config)
            task.prepare()
            return task.run()

    def test_dubs_video_into_mkv_named_after_the_language(self, files):
        cfg = DubConfig(input_path=str(files / "movie.mp4"), subtitle_path=str(files / "movie_es.srt"), mode="kokoro")
        result = self._run(cfg, FakeEngine())
        assert result.success, result.error
        assert result.output_files == [str(files / "movie_dub_es.mkv")]
        assert result.detected_language == "es"

    def test_cloning_registers_the_original_voices(self, files):
        cloner = FakeCloner()
        cfg = DubConfig(input_path=str(files / "movie.mp4"), subtitle_path=str(files / "movie_es.srt"))
        result = self._run(cfg, cloner)
        assert result.success, result.error
        assert sorted(cloner.references) == [0]

    def test_wav_output_for_subtitle_only_input(self, files):
        cfg = DubConfig(input_path=str(files / "movie_es.srt"), output="wav", mode="piper")
        result = self._run(cfg, FakeEngine())
        assert result.output_files == [str(files / "movie_dub_es.wav")]

    def test_subtitle_only_input_cannot_clone_and_says_so(self, files):
        cfg = DubConfig(input_path=str(files / "movie_es.srt"), output="wav")
        result = self._run(cfg, FakeEngine())
        assert "has no original voice to clone, so Kokoro was used instead." in result.warnings[0]

    def test_unknown_language_fails_in_prepare(self, files):
        (files / "movie.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhola\n", encoding="utf-8")
        cfg = DubConfig(input_path=str(files / "movie.mp4"), subtitle_path=str(files / "movie.srt"))
        with pytest.raises(ValueError, match="Choose the speech language"):
            DubTask(cfg).prepare()


class _Checker:
    """Line check stand-in that fails the first `bad` takes of every line."""

    def __init__(self, bad: int) -> None:
        self.bad = bad
        self.seen: dict[str, int] = {}

    def score(self, audio, rate, text):
        self.seen[text] = self.seen.get(text, 0) + 1
        return 0.9 if self.seen[text] <= self.bad else 0.1


class TestLineCheck:
    def test_a_garbled_line_is_spoken_again(self, tmp_path):
        engine = FakeEngine()
        report = synthesize_track([_cue(0, 0.0, 2.0, "abc")], [0], engine, 1.35, str(tmp_path / "t.wav"),
                                  checker=_Checker(bad=1))
        assert len(engine.calls) == 2
        assert (report.retaken, report.unclear, report.warnings()) == ([1], [], [])

    def test_a_line_still_unclear_after_every_retake_is_reported(self, tmp_path):
        engine = FakeEngine()
        report = synthesize_track([_cue(0, 0.0, 2.0, "abc")], [0], engine, 1.35, str(tmp_path / "t.wav"),
                                  checker=_Checker(bad=5))
        assert len(engine.calls) == 3
        assert report.unclear == [1]
        assert "may be hard to understand" in report.warnings()[0]

    def test_clear_lines_are_spoken_once(self, tmp_path):
        engine = FakeEngine()
        synthesize_track([_cue(0, 0.0, 2.0, "abc")], [0], engine, 1.35, str(tmp_path / "t.wav"), checker=_Checker(bad=0))
        assert len(engine.calls) == 1


class TestCharacterErrorRate:
    def test_case_punctuation_and_spacing_are_ignored(self):
        from ccgen.engines.speech.line_check import character_error_rate

        assert character_error_rate("hello world", "Hello, World!", "en") == 0.0
        assert character_error_rate("يہ ايک", "یہ ایک", "ur") == 0.0
        assert character_error_rate("", "abc", "en") == 1.0

    def test_run_on_speech_counts(self):
        from ccgen.engines.speech.line_check import run_on

        assert run_on("one two three four", "one two", "en") > 0.3
        assert run_on("one", "one two", "en") == 0.0


class TestLineChecker:
    def _score(self, heard, text, language):
        from ccgen.engines.speech.line_check import LineChecker

        transcriber = MagicMock()
        transcriber.transcribe.return_value = [{"text": heard}]
        return LineChecker(transcriber, language).score(np.zeros(16000, np.float32), 16000, text)

    def test_names_in_latin_letters_are_not_held_against_a_native_script_line(self):
        assert self._score("میرا نام ابھیشیک ہے", "میرا نام Abhishek ہے", "ur") == 0.0

    def test_a_garbled_line_with_a_name_still_fails(self):
        from ccgen.engines.speech.line_check import FAILED_CER

        assert self._score("یہاں تر نتا مدس", "میرا نام Abhishek ہے اور خوش آمدید", "ur") >= FAILED_CER

    def test_a_line_of_only_latin_words_cannot_fail(self):
        assert self._score("ایم ایل آپس", "ML Ops", "ur") == 0.0

    def test_garbled_and_run_on_speech_fails(self):
        from ccgen.engines.speech.line_check import FAILED_CER

        assert self._score("یہاں تر نتا", "بھی جوڑے ہیں", "ur") >= FAILED_CER
        assert self._score("hello there and then some more words", "hello there", "en") >= FAILED_CER


class TestFinishSentence:
    @pytest.mark.parametrize("text, language, spoken", [
        ("my name is", "en", "my name is."),
        ("मेरा नाम", "hi", "मेरा नाम।"),
        ("میرا نام", "ur", "میرا نام۔"),
        ("私の名前は", "ja", "私の名前は。"),
        ("Hello, world!", "en", "Hello, world!"),
        ("and then,", "en", "and then,"),
        ('He said "stop"', "en", 'He said "stop"'),
        ("  ", "en", ""),
    ])
    def test_lines_end_with_the_languages_full_stop(self, text, language, spoken):
        assert finish_sentence(text, language) == spoken


class TestSplitForSpeech:
    def test_short_text_is_one_piece(self):
        assert split_for_speech("  Hello.  ", 20) == ["Hello."]

    def test_splits_at_sentence_ends_then_spaces(self):
        text = "Hello there. This is a long sentence that keeps going on and on."
        pieces = split_for_speech(text, 30)
        assert pieces == ["Hello there.", "This is a long sentence that", "keeps going on and on."]
        assert all(len(p) <= 30 for p in pieces)

    def test_unspaced_scripts_split_at_their_punctuation(self):
        # No spaces to break at, so a sentence longer than the limit is cut at the limit.
        assert split_for_speech("短い。これは長い文章です。", 8) == ["短い。", "これは長い文章で", "す。"]

    def test_empty_text_has_no_pieces(self):
        assert split_for_speech("   ", 10) == []
