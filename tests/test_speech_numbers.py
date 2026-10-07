# test_speech_numbers.py - digits spelled out for the XTTS-v2 languages num2words can't handle

import pytest

from ccgen.engines.speech.numbers import spell_numbers, spells_numbers


class TestHindustani:
    @pytest.mark.parametrize("number, words", [
        ("7", "सात"),
        ("19", "उन्नीस"),
        ("99", "निन्यानवे"),
        ("100", "एक सौ"),
        ("2024", "दो हज़ार चौबीस"),
        ("150000", "एक लाख पचास हज़ार"),
        ("30000000", "तीन करोड़"),
    ])
    def test_numbers(self, number, words):
        assert spell_numbers(number, "hi") == words

    def test_zero(self):
        assert spell_numbers("0", "hi") == "शून्य"

    def test_numbers_inside_text(self):
        assert spell_numbers("ML Ops 0 से हीरो, भाग 2", "hi") == "ML Ops शून्य से हीरो, भाग दो"


class TestKanji:
    @pytest.mark.parametrize("number, kanji", [
        ("0", "零"), ("10", "十"), ("15", "十五"), ("111", "百十一"), ("2024", "二千二十四"),
        ("10000", "一万"), ("123456789", "一億二千三百四十五万六千七百八十九"),
    ])
    def test_numbers(self, number, kanji):
        assert spell_numbers(number, "ja") == kanji


class TestXttsCleaners:
    def test_only_languages_xtts_cannot_expand_are_spelled_here(self):
        assert spells_numbers("hi") and spells_numbers("ja")
        assert not spells_numbers("en") and not spells_numbers("zh-cn") and not spells_numbers("ur")

    def test_spelled_hindi_passes_xtts_text_cleaning(self):
        from TTS.tts.layers.xtts.tokenizer import multilingual_cleaners

        text = "भाग 0, 12 और 2024"
        with pytest.raises(NotImplementedError):
            multilingual_cleaners(text, "hi")
        multilingual_cleaners(spell_numbers(text, "hi"), "hi")

    def test_spelled_japanese_numbers_are_read_aloud(self):
        import cutlet
        from TTS.tts.layers.xtts.tokenizer import japanese_cleaners

        katsu = cutlet.Cutlet()
        text = "第0課と12と2024"
        assert any(ch.isdigit() for ch in japanese_cleaners(text, katsu))
        assert not any(ch.isdigit() for ch in japanese_cleaners(spell_numbers(text, "ja"), katsu))
