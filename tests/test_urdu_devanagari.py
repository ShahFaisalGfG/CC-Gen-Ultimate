# test_urdu_devanagari.py - Urdu -> Devanagari conversion for the Transliterate tab

import pytest

from ccgen.engines.transliteration.rule_engine import RuleEngine
from ccgen.engines.transliteration.urdu_devanagari import urdu_to_devanagari


def _has_arabic_letters(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


class TestUrduToDevanagari:
    @pytest.mark.parametrize("urdu, devanagari", [
        ("یہ ایک مکمل دوستانہ کورس ہے۔", "ये एक मुकम्मल दोसताना कोर्स है।"),
        ("میرا نام", "मेरा नाम"),
        ("کھانا", "खाना"),
        ("بھائی", "भाई"),
        ("اِس", "इस"),
        ("لیں", "लें"),
        ("آپ", "आप"),
        ("کریں گے۔", "करेंगे।"),
    ])
    def test_words(self, urdu, devanagari):
        assert urdu_to_devanagari(urdu) == devanagari

    def test_silent_final_he_reads_as_a(self):
        assert urdu_to_devanagari("زندہ").endswith("दा")

    def test_latin_text_digits_and_punctuation_pass_through(self):
        assert urdu_to_devanagari("ML Ops ۰ سے ہیرو، ٹھیک؟") == "ML Ops 0 से हीरो, ठीक?"

    def test_no_urdu_letters_are_left(self):
        text = ("اگر آپ نہیں سمجھ پاتے کہ مشین سیکھنے کیا ہے، تو کیا ماڈل ہے۔ "
                "جہاں بھی مطلوب ہے، میں نے مضامین میں مفید تعلقات شامل کیے ہیں۔ "
                "لہٰذا اِس بات کا یقین کریں کہ آپ ژالہ، غزل، ظلم، ثواب، ضرور، عزت، ؤ، ئ پڑھیں۔")
        assert not _has_arabic_letters(urdu_to_devanagari(text))


class TestRuleEngineUrdu:
    def _convert(self, target: str, text: str) -> str:
        segment = {"id": 0, "start": 0.0, "end": 1.0, "text": text}
        return RuleEngine("ur", target).transliterate_segments([segment])[0]["transliterated"]

    def test_urdu_to_hindi_uses_the_dedicated_converter(self):
        assert self._convert("hi", "میرا نام") == "मेरा नाम"

    def test_other_indic_scripts_go_through_devanagari(self):
        bengali = self._convert("bn", "میرا نام")
        assert bengali and not _has_arabic_letters(bengali)
        assert all("ঀ" <= ch <= "৿" or ch == " " for ch in bengali)
