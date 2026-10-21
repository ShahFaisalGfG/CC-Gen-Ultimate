# test_voices.py - unit tests for dubbing voice catalogs and mode resolution

import pytest

from ccgen.config.voices import VOICES, engine_supports, resolve_voice, voice_by_key, voices_for


class TestCatalog:
    def test_only_dubbing_languages_are_loaded(self):
        assert VOICES
        assert {v.language for v in VOICES} <= {
            "ar", "zh", "en", "fr", "de", "hi", "ja", "ko", "pt", "ru", "es", "tr", "ur",
        }

    def test_kokoro_voices_sort_best_grade_first(self):
        assert voices_for("kokoro", "en")[0].voice_id == "af_heart"

    def test_preferred_piper_voice_comes_first(self):
        assert voices_for("piper", "ur")[0].voice_id == "ur_PK-aegis_female-medium"

    def test_engine_support(self):
        assert engine_supports("xtts", "zh")
        assert engine_supports("piper", "ur")
        assert not engine_supports("kokoro", "ar")

    def test_japanese_and_chinese_have_no_stock_voices(self):
        # Their stock voices need phonemizers the app doesn't ship; voice cloning speaks them.
        for engine in ("kokoro", "piper"):
            assert not engine_supports(engine, "ja")
            assert not engine_supports(engine, "zh")
        assert engine_supports("kokoro", "hi")
        assert engine_supports("omnivoice", "ja") and engine_supports("omnivoice", "zh")

    def test_xtts_has_no_urdu(self):
        assert not engine_supports("xtts", "ur")
        assert voices_for("xtts", "ur") == []


class TestResolveVoice:
    def test_requested_mode_is_used_when_it_speaks_the_language(self):
        voice, warning = resolve_voice("en", "xtts")
        assert (voice.engine, voice.model_path, warning) == ("xtts", "en", None)

    def test_chinese_uses_xtts_tokenizer_code(self):
        assert resolve_voice("zh", "xtts")[0].model_path == "zh-cn"

    def test_falls_back_with_a_warning(self):
        voice, warning = resolve_voice("ur", "xtts")
        assert voice.engine == "piper"
        assert warning == "XTTS-v2 can't speak 'ur', so Piper was used instead."

    def test_supported_languages_have_no_warning(self):
        voice, warning = resolve_voice("hi", "xtts")
        assert (voice.engine, voice.model_path, warning) == ("xtts", "hi", None)

    def test_xtts_without_reference_audio_falls_back(self):
        voice, warning = resolve_voice("en", "xtts", can_clone=False)
        assert voice.engine == "kokoro"
        assert warning == "XTTS-v2 has no original voice to clone, so Kokoro was used instead."

    def test_explicit_voice_is_honoured(self):
        voice, _ = resolve_voice("ur", "piper", "piper:ur_PK-fasih-medium")
        assert voice == voice_by_key("piper:ur_PK-fasih-medium")

    def test_explicit_voice_for_another_language_is_rejected(self):
        with pytest.raises(ValueError, match="speaks 'ur', not 'en'"):
            resolve_voice("en", "piper", "piper:ur_PK-fasih-medium")

    def test_cloning_without_a_recording_explains_why_nothing_speaks(self):
        with pytest.raises(ValueError, match="OmniVoice needs the original recording"):
            resolve_voice("ja", "omnivoice", can_clone=False)

    def test_a_stock_mode_for_japanese_points_to_voice_cloning(self):
        with pytest.raises(ValueError, match=r"Kokoro can't speak 'ja'; choose voice cloning \(OmniVoice\)"):
            resolve_voice("ja", "kokoro")

    def test_unknown_language_is_rejected(self):
        with pytest.raises(ValueError, match="No dubbing voice speaks 'xx'"):
            resolve_voice("xx", "kokoro")


class TestValidateVoice:
    def test_auto_and_matching_voices_pass(self):
        from ccgen.core.tasks.configs import validate_voice

        validate_voice("auto", "kokoro", "en")
        validate_voice("piper:ur_PK-fasih-medium", "piper", "ur")
        validate_voice("piper:ur_PK-fasih-medium", "piper", "auto")

    def test_voice_from_other_engine_or_language_fails(self):
        from ccgen.core.tasks.configs import validate_voice

        with pytest.raises(ValueError, match="isn't one of the chosen voices"):
            validate_voice("piper:ur_PK-fasih-medium", "kokoro", "ur")
        with pytest.raises(ValueError, match="doesn't speak 'es'"):
            validate_voice("piper:ur_PK-fasih-medium", "piper", "es")


class TestKokoroLocales:
    def test_every_kokoro_voice_uses_a_language_espeak_accepts(self):
        from kokoro_onnx.tokenizer import Tokenizer

        tokenizer = Tokenizer()
        for locale in sorted({v.locale for v in VOICES if v.engine == "kokoro"}):
            assert tokenizer.phonemize("hello", locale), locale
