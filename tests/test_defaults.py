# test_defaults.py - sanity checks for ccgen.config.defaults

from ccgen.config.defaults import (
    LanguageOptions,
    ModelDefaults,
    TranslationDefaults,
    TransliterationDefaults,
    get_default_settings,
)


class TestGetDefaultSettings:
    def test_returns_dict_with_expected_top_level_sections(self):
        settings = get_default_settings()
        expected = {
            "model", "transcription", "translation",
            "output", "logging", "transliteration", "ui",
        }
        assert expected.issubset(settings.keys())

    def test_model_section_matches_settings_service_usage(self):
        settings = get_default_settings()
        assert settings["model"]["name"] == ModelDefaults.DEFAULT_MODEL
        assert settings["model"]["name"] in ModelDefaults.SUPPORTED_MODELS

    def test_transliteration_section_keys_used_by_settings_service(self):
        settings = get_default_settings()
        transliteration = settings["transliteration"]
        assert set(transliteration.keys()) == {"source", "target", "engine"}

    def test_translation_section_has_no_stage_switch(self):
        translation = get_default_settings()["translation"]
        assert set(translation.keys()) == {
            "source_lang", "target_lang", "engine", "meaning_check", "nllb_terms_accepted",
        }
        assert (translation["engine"], translation["meaning_check"]) == ("opus_mt", True)

    def test_output_section_keys_used_by_settings_service(self):
        settings = get_default_settings()
        output = settings["output"]
        assert set(output.keys()) == {
            "directory", "srt", "vtt", "lrc", "ass", "sbv", "max_line_length", "max_lines",
        }


class TestModelDefaults:
    def test_supported_models_non_empty(self):
        assert len(ModelDefaults.SUPPORTED_MODELS) > 0

    def test_default_model_in_supported_list(self):
        assert ModelDefaults.DEFAULT_MODEL in ModelDefaults.SUPPORTED_MODELS

    def test_every_supported_model_has_a_size(self):
        for model in ModelDefaults.SUPPORTED_MODELS:
            assert model in ModelDefaults.MODEL_SIZES_MB


class TestLanguageOptions:
    def test_transcription_options_non_empty(self):
        assert len(LanguageOptions.TRANSCRIPTION) > 0

    def test_translation_targets_non_empty(self):
        assert len(LanguageOptions.TRANSLATION_TARGETS) > 0

    def test_translation_default_target_in_targets(self):
        codes = [code for _, code in LanguageOptions.TRANSLATION_TARGETS]
        assert TranslationDefaults.DEFAULT_TARGET_LANG in codes


class TestTransliterationDefaults:
    def test_engines_non_empty(self):
        assert len(TransliterationDefaults.ENGINES) > 0

    def test_schemes_non_empty(self):
        assert len(TransliterationDefaults.SCHEMES) > 0

    def test_default_engine_is_a_known_engine_code(self):
        codes = [code for _, code in TransliterationDefaults.ENGINES]
        assert TransliterationDefaults.DEFAULT_ENGINE in codes

    def test_default_target_is_a_known_scheme_code(self):
        codes = [code for _, code in TransliterationDefaults.SCHEMES]
        assert TransliterationDefaults.DEFAULT_TARGET in codes

    def test_default_source_is_a_known_scheme_code(self):
        codes = [code for _, code in TransliterationDefaults.SCHEMES]
        assert TransliterationDefaults.DEFAULT_SOURCE in codes
