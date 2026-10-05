# test_task_translate.py - unit tests for ccgen.core.tasks.translate

from unittest.mock import MagicMock, patch

import pytest

from ccgen.core.tasks.configs import TranslateConfig
from ccgen.core.tasks.translate import TranslateTask

_SRT = "1\n00:00:00,000 --> 00:00:02,000\nHello world.\n\n2\n00:00:02,500 --> 00:00:04,000\nGood morning.\n"


def _fake_translate(units, progress_cb=None, progress_num_cb=None, segment_cb=None):
    """Stand-in for translate_segments that prefixes each unit and streams it like the engine."""
    results = []
    for unit in units:
        translated = {
            "id": unit["id"], "start": unit["start"], "end": unit["end"],
            "original": unit["text"], "translated": "ES " + unit["text"], "language": "es",
        }
        if segment_cb:
            segment_cb(translated)
        results.append(translated)
    return results


class _FaithfulMeaning:
    """Meaning check stand-in that finds every translation faithful, without loading a model."""

    score = 0.9

    def ensure(self, status_cb=None, progress_cb=None):
        pass

    def scores(self, sources, translations, target):
        return [self.score] * len(sources)


class _DriftingMeaning(_FaithfulMeaning):
    score = 0.2


@pytest.fixture
def engine():
    """Patch the translation engine factory and meaning check, and yield the fake engine."""
    with (
        patch("ccgen.core.tasks.translate.create_translation_engine") as create,
        patch("ccgen.core.tasks.translate.MeaningCheck", _FaithfulMeaning),
    ):
        fake = MagicMock(name="translator")
        fake.translate_segments.side_effect = _fake_translate
        create.return_value = fake
        yield fake


def _subtitle(tmp_path, name="movie_en.srt", body=_SRT):
    """Write a subtitle file and return its path."""
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


class TestConfig:
    def test_rejects_media_input(self, tmp_path):
        with pytest.raises(ValueError, match="needs a subtitle file"):
            TranslateConfig(input_path=str(tmp_path / "movie.mp4"))

    def test_rejects_same_languages(self, tmp_path):
        with pytest.raises(ValueError, match="different from the source"):
            TranslateConfig(input_path=str(tmp_path / "a.srt"), source_lang="es", target_lang="es")

    def test_rejects_an_unknown_model(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown translation model"):
            TranslateConfig(input_path=str(tmp_path / "a.srt"), target_lang="es", engine="babelfish")

    def test_rejects_a_pair_the_model_cannot_translate(self, tmp_path):
        with pytest.raises(ValueError, match="OPUS-MT has no model from 'en' to 'ja'"):
            TranslateConfig(input_path=str(tmp_path / "a.srt"), source_lang="en", target_lang="ja", engine="opus_mt")

    def test_opus_mt_with_the_meaning_check_is_the_default(self, tmp_path):
        cfg = TranslateConfig(input_path=str(tmp_path / "a_en.srt"), target_lang="ur")
        assert (cfg.engine, cfg.meaning_check) == ("opus_mt", True)


class TestRun:
    def test_reads_language_from_file_name_and_names_output(self, tmp_path, engine):
        cfg = TranslateConfig(input_path=_subtitle(tmp_path), target_lang="es")
        result = TranslateTask(cfg).run()
        assert result.success, result.error
        engine.set_pair.assert_called_once_with("en", "es")
        assert result.output_files == [str(tmp_path / "movie_es.srt")]
        assert result.detected_language == "en"
        assert "ES Hello world." in (tmp_path / "movie_es.srt").read_text(encoding="utf-8")

    def test_explicit_source_overrides_file_name(self, tmp_path, engine):
        cfg = TranslateConfig(input_path=_subtitle(tmp_path, "movie.srt"), source_lang="fr", target_lang="es")
        TranslateTask(cfg).run()
        engine.set_pair.assert_called_once_with("fr", "es")

    def test_unknown_source_language_fails_clearly(self, tmp_path, engine):
        cfg = TranslateConfig(input_path=_subtitle(tmp_path, "movie.srt"), target_lang="es")
        result = TranslateTask(cfg).run()
        assert not result.success
        assert "Choose the source language" in result.error
        engine.translate_segments.assert_not_called()

    def test_file_already_in_target_language_fails(self, tmp_path, engine):
        cfg = TranslateConfig(input_path=_subtitle(tmp_path, "movie_es.srt"), target_lang="es")
        result = TranslateTask(cfg).run()
        assert not result.success and "already in 'es'" in result.error

    def test_sentence_split_across_cues_is_translated_once(self, tmp_path, engine):
        body = "1\n00:00:00,000 --> 00:00:01,000\nThe quick brown\n\n2\n00:00:01,000 --> 00:00:02,000\nfox jumps.\n"
        cfg = TranslateConfig(input_path=_subtitle(tmp_path, "s_en.srt", body), target_lang="es")
        TranslateTask(cfg).run()
        units = engine.translate_segments.call_args.args[0]
        assert [u["text"] for u in units] == ["The quick brown fox jumps."]

    def test_streams_source_then_translated_cues(self, tmp_path, engine):
        segments = []
        cfg = TranslateConfig(input_path=_subtitle(tmp_path), target_lang="es")
        TranslateTask(cfg).run(segment_cb=segments.append)
        assert [("translated" in s) for s in segments] == [False, False, True, True]

    def test_engine_failure_is_reported(self, tmp_path, engine):
        engine.ensure_model.side_effect = RuntimeError("no package")
        cfg = TranslateConfig(input_path=_subtitle(tmp_path), target_lang="es")
        result = TranslateTask(cfg).run()
        assert not result.success and result.error == "Translation failed: no package"

    def test_refuses_to_overwrite_the_input(self, tmp_path, engine):
        cfg = TranslateConfig(input_path=_subtitle(tmp_path, "movie_es.srt"), source_lang="en", target_lang="es")
        result = TranslateTask(cfg).run()
        assert not result.success and "overwrite the input" in result.error

    def test_lines_that_drift_from_the_original_are_reported(self, tmp_path, engine):
        with patch("ccgen.core.tasks.translate.MeaningCheck", _DriftingMeaning):
            cfg = TranslateConfig(input_path=_subtitle(tmp_path), target_lang="es")
            result = TranslateTask(cfg).run()
        assert result.success, result.error
        assert result.warnings == [
            "2 line(s) may not say the same as the original (subtitle 1, 2). "
            "Review them, or try another translation model in Preferences."
        ]

    def test_faithful_lines_raise_no_note(self, tmp_path, engine):
        result = TranslateTask(TranslateConfig(input_path=_subtitle(tmp_path), target_lang="es")).run()
        assert result.warnings == []

    def test_meaning_check_can_be_turned_off(self, tmp_path, engine):
        with patch("ccgen.core.tasks.translate.MeaningCheck") as meaning:
            cfg = TranslateConfig(input_path=_subtitle(tmp_path), target_lang="es", meaning_check=False)
            assert TranslateTask(cfg).run().success
        meaning.assert_not_called()

    def test_the_chosen_model_is_created(self, tmp_path):
        with (
            patch("ccgen.core.tasks.translate.create_translation_engine") as create,
            patch("ccgen.core.tasks.translate.MeaningCheck", _FaithfulMeaning),
        ):
            TranslateTask(TranslateConfig(input_path=_subtitle(tmp_path), target_lang="es", engine="nllb"))
        assert create.call_args.args[0] == "nllb"
