# test_task_generate.py - unit tests for ccgen.core.tasks.generate

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ccgen.core.tasks.configs import GenerateConfig
from ccgen.core.tasks.generate import GenerateTask


def _config(tmp_path, **overrides) -> GenerateConfig:
    """Build a GenerateConfig for a media file that exists on disk."""
    media = tmp_path / "movie.mp4"
    media.write_bytes(b"")
    overrides.setdefault("input_path", str(media))
    return GenerateConfig(**overrides)


def _streaming_transcribe(segments):
    """Stand-in for CaptionEngine.transcribe that streams each segment like the real engine."""
    def transcribe(audio, language=None, beam_size=5, vad_filter=True, progress_cb=None,
                   segment_cb=None, progress_num_cb=None):
        for idx, segment in enumerate(segments, 1):
            if segment_cb:
                segment_cb(segment)
            if progress_num_cb:
                progress_num_cb(idx, len(segments))
        return segments
    return transcribe


@pytest.fixture
def engine():
    """Patch the caption engine factory and audio decoding; yield the fake engine."""
    with (
        patch("ccgen.core.tasks.generate.create_caption_engine") as create,
        patch("ccgen.core.tasks.generate.load_audio", return_value=np.zeros(16000, dtype=np.float32)),
    ):
        fake = MagicMock(name="transcriber")
        create.return_value = fake
        yield fake


class TestConfig:
    def test_rejects_subtitle_input(self, tmp_path):
        with pytest.raises(ValueError, match="needs a video or audio file"):
            GenerateConfig(input_path=str(tmp_path / "movie.srt"))

    def test_rejects_missing_formats(self, tmp_path):
        with pytest.raises(ValueError, match="at least one subtitle format"):
            _config(tmp_path, formats=[])

    def test_rejects_unknown_model(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown Whisper model"):
            _config(tmp_path, model_name="huge")

    def test_rejects_line_length_out_of_range(self, tmp_path):
        with pytest.raises(ValueError, match="Line length"):
            _config(tmp_path, max_line_length=5)


class TestPrepare:
    def test_engine_created_from_config(self, tmp_path):
        with patch("ccgen.core.tasks.generate.create_caption_engine") as create:
            GenerateTask(_config(tmp_path, model_name="small", device="cpu", compute_type="int8"))
        create.assert_called_once_with(model_name="small", device="cpu", compute_type="int8")

    def test_loads_model_in_load_stage(self, tmp_path, engine):
        task = GenerateTask(_config(tmp_path))
        task.prepare()
        engine.load.assert_called_once()
        assert task.stage == "load" and task.step == 0

    def test_load_failure_propagates(self, tmp_path, engine):
        engine.load.side_effect = RuntimeError("model download failed")
        with pytest.raises(RuntimeError, match="model download failed"):
            GenerateTask(_config(tmp_path)).prepare()


class TestRun:
    def test_writes_srt_and_reports_language(self, tmp_path, engine, sample_segments):
        engine.transcribe.side_effect = _streaming_transcribe(sample_segments)
        result = GenerateTask(_config(tmp_path)).run()
        assert result.success, result.error
        assert result.output_files == [str(tmp_path / "movie.srt")]
        assert result.detected_language == "en"
        assert "Hello world" in (tmp_path / "movie.srt").read_text(encoding="utf-8")

    def test_writes_every_requested_format(self, tmp_path, engine, sample_segments):
        engine.transcribe.side_effect = _streaming_transcribe(sample_segments)
        result = GenerateTask(_config(tmp_path, formats=["srt", "vtt", "lrc", "ass", "sbv"])).run()
        assert sorted(p.rsplit(".", 1)[1] for p in result.output_files) == ["ass", "lrc", "sbv", "srt", "vtt"]

    def test_transcribe_receives_config(self, tmp_path, engine, sample_segments):
        engine.transcribe.side_effect = _streaming_transcribe(sample_segments)
        GenerateTask(_config(tmp_path, language="en", beam_size=3, vad_filter=False)).run()
        kwargs = engine.transcribe.call_args.kwargs
        assert (kwargs["language"], kwargs["beam_size"], kwargs["vad_filter"]) == ("en", 3, False)

    def test_streams_cues_and_progress(self, tmp_path, engine, sample_segments):
        engine.transcribe.side_effect = _streaming_transcribe(sample_segments)
        segments, progress = [], []
        task = GenerateTask(_config(tmp_path))
        task.run(segment_cb=segments.append, progress_cb=lambda d, t: progress.append((task.stage, d, t)))
        assert segments and all("text" in s for s in segments)
        assert progress[-1] == ("transcribe", 2, 2)

    def test_restreams_cues_whose_timing_was_finalized(self, tmp_path, engine):
        short = [{
            "id": 0, "start": 0.0, "end": 0.1, "text": "Hi.", "language": "en",
            "words": [{"word": " Hi.", "start": 0.0, "end": 0.1}],
        }]
        engine.transcribe.side_effect = _streaming_transcribe(short)
        segments = []
        # Copies: finalize_timing adjusts the streamed cue dicts in place.
        GenerateTask(_config(tmp_path)).run(segment_cb=lambda s: segments.append(dict(s)))
        assert len(segments) == 2
        assert segments[0]["id"] == segments[1]["id"]
        assert segments[1]["end"] > segments[0]["end"]

    def test_empty_transcript_warns(self, tmp_path, engine):
        engine.transcribe.side_effect = _streaming_transcribe([])
        result = GenerateTask(_config(tmp_path)).run()
        assert result.success
        assert result.warnings == ["No speech was found, so the subtitle files are empty."]

    def test_output_dir_is_created_and_used(self, tmp_path, engine, sample_segments):
        engine.transcribe.side_effect = _streaming_transcribe(sample_segments)
        out = tmp_path / "subs" / "nested"
        result = GenerateTask(_config(tmp_path, output_dir=str(out))).run()
        assert result.output_files == [str(out / "movie.srt")]

    def test_missing_input_fails_without_raising(self, tmp_path, engine):
        task = GenerateTask(GenerateConfig(input_path=str(tmp_path / "gone.mp4")))
        result = task.run()
        assert not result.success and "gone.mp4 isn't there any more" in result.error

    def test_engine_error_becomes_failed_result(self, tmp_path, engine):
        engine.transcribe.side_effect = RuntimeError("decoder crashed")
        result = GenerateTask(_config(tmp_path)).run()
        assert not result.success and "Something went wrong" in result.error
        assert result.error_detail == "RuntimeError: decoder crashed"

    def test_out_of_gpu_memory_says_what_to_do(self, tmp_path, engine):
        engine.transcribe.side_effect = RuntimeError("CUDA failed with error out of memory")
        result = GenerateTask(_config(tmp_path)).run()
        assert result.error.startswith("The graphics card ran out of memory.")

    def test_cancel_during_transcription(self, tmp_path, engine, sample_segments):
        task = GenerateTask(_config(tmp_path))

        def cancel_midway(audio, segment_cb=None, **kwargs):
            segment_cb(sample_segments[0])
            task.cancel()
            segment_cb(sample_segments[1])
            return sample_segments

        engine.transcribe.side_effect = cancel_midway
        result = task.run(segment_cb=lambda s: None)
        assert result.cancelled and result.error == "Cancelled by user."
        assert not (tmp_path / "movie.srt").exists()
