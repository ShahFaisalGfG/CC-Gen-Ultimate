# test_task_outputs.py - unit tests for output naming and engine capability checks

import os

import pytest

from ccgen.config.capabilities import (
    language_from_filename,
    neural_model_key,
    script_for_language,
    split_language,
    transliteration_supported,
)
from ccgen.core.tasks.outputs import output_base, output_path


class TestLanguageFromFilename:
    @pytest.mark.parametrize("name, expected", [
        ("movie_ur.srt", "ur"),
        ("Movie_EN.vtt", "en"),
        ("movie.srt", ""),
        ("movie_xx.srt", ""),
        ("my_movie.srt", ""),
        ("movie_tr_ur_roman.srt", ""),
        ("movie.en.srt", "en"),
        ("movie-ja.vtt", "ja"),
        ("movie ko.ass", "ko"),
        ("movie [es].srt", "es"),
        ("Movie (Urdu).srt", "ur"),
        ("movie_english.srt", "en"),
        ("movie.eng.srt", "en"),
        ("movie.fre.srt", "fr"),
        ("movie_pt-BR.srt", "pt"),
        ("movie.zh-Hans.srt", "zh"),
        ("movie-en-US.srt", "en"),
        ("movie.en.forced.srt", "en"),
        ("movie.en.sdh.srt", "en"),
        ("movie.forced.srt", ""),
        ("en.srt", ""),
        ("english.srt", ""),
        ("the-boy.srt", ""),
        ("movie 2020.srt", ""),
    ])
    def test_reads_known_language_tags_only(self, name, expected):
        assert language_from_filename(os.path.join("dir", name)) == expected

    def test_split_keeps_the_folder_and_extension(self):
        path = os.path.join("dir", "movie.en.forced.srt")
        assert split_language(path) == (os.path.join("dir", "movie.srt"), "en")

    def test_split_returns_a_name_without_language_whole(self):
        assert split_language("my_movie.srt") == ("my_movie.srt", "")


class TestScriptForLanguage:
    @pytest.mark.parametrize("language, script", [
        ("ur", "ur"), ("hi", "hi"), ("en", "roman"), ("tr", "roman"), ("ta", "ta"), ("ja", ""), ("", ""),
    ])
    def test_maps_languages_to_their_script(self, language, script):
        assert script_for_language(language) == script


class TestOutputNaming:
    def test_subtitle_language_suffix_is_replaced(self):
        assert output_base(os.path.join("d", "movie_en.srt")) == os.path.join("d", "movie.srt")
        assert output_base(os.path.join("d", "movie.en.srt")) == os.path.join("d", "movie.srt")

    def test_media_names_are_kept_whole(self):
        assert output_base(os.path.join("d", "talk_en.mp4")) == os.path.join("d", "talk_en.mp4")

    def test_output_dir_relocates_file(self):
        path = output_path(os.path.join("src", "movie_en.srt"), "_ur", ".srt", os.path.join("out"))
        assert path == os.path.join("out", "movie_ur.srt")


class TestTransliterationSupport:
    def test_rule_engine_handles_any_two_known_scripts(self):
        assert transliteration_supported("rule", "ta", "ur")
        assert not transliteration_supported("rule", "ur", "ur")
        assert not transliteration_supported("rule", "klingon", "ur")

    def test_neural_engine_handles_its_model_pairs(self):
        assert neural_model_key("ur", "roman") == "ur-roman"
        assert neural_model_key("pa", "ur") == "hi-ur"
        assert transliteration_supported("neural", "roman", "ur")
        assert not transliteration_supported("neural", "ur", "hi")

    def test_unknown_engine_supports_nothing(self):
        assert not transliteration_supported("magic", "ur", "roman")
