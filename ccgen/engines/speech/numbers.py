# numbers.py - spell out digits for the XTTS-v2 languages that can't read them
#
# XTTS-v2 expands digits with num2words, which has no Hindi: a Hindi line like "भाग 2" raised
# NotImplementedError and stopped the whole dub. Its Japanese reader leaves digits unread
# ("2024" stays "2024" in the romanized text). Numbers in these languages are written out here
# first: Hindustani words in Devanagari for Hindi and for Urdu read in Hindi script, and kanji
# numerals for Japanese, which the Japanese reader pronounces ("二千二十四" -> "nisen nijuu yon").

import re

_DIGITS_RE = re.compile(r"\d+")

# 1-99 have their own Hindustani words; Hindi and Urdu share them.
_HINDUSTANI_1_99 = (
    "एक दो तीन चार पाँच छह सात आठ नौ दस "
    "ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
    "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस "
    "इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस सैंतीस अड़तीस उनतालीस चालीस "
    "इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास "
    "इक्यावन बावन तिरेपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ "
    "इकसठ बासठ तिरेसठ चौंसठ पैंसठ छियासठ सड़सठ अड़सठ उनहत्तर सत्तर "
    "इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी "
    "इक्यासी बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे "
    "इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे सत्तानवे अट्ठानवे निन्यानवे"
).split()
_HINDUSTANI_ZERO = {"hi": "शून्य", "ur": "सिफ़र"}
# Indian numbering: crore (10^7), lakh (10^5), thousand, hundred.
_HINDUSTANI_SCALES = ((10_000_000, "करोड़"), (100_000, "लाख"), (1000, "हज़ार"), (100, "सौ"))

_KANJI_DIGITS = "零一二三四五六七八九"
_KANJI_SMALL = ((1000, "千"), (100, "百"), (10, "十"))
_KANJI_LARGE = ((10**12, "兆"), (10**8, "億"), (10**4, "万"))


def spells_numbers(language: str) -> bool:
    """True when digits in `language` are spelled out here instead of by XTTS-v2."""
    return language in _HINDUSTANI_ZERO or language == "ja"


def spell_numbers(text: str, language: str) -> str:
    """Replace each run of digits in `text` with its words in `language` (hi, ur, or ja)."""
    if language == "ja":
        return _DIGITS_RE.sub(lambda m: _kanji(int(m.group(0))), text)
    zero = _HINDUSTANI_ZERO[language]
    return _DIGITS_RE.sub(lambda m: _hindustani(int(m.group(0)), zero), text)


def _hindustani(number: int, zero: str) -> str:
    """Hindustani words for a whole number, e.g. 2024 -> "दो हज़ार चौबीस"."""
    if number == 0:
        return zero
    words: list[str] = []
    for scale, name in _HINDUSTANI_SCALES:
        count, number = divmod(number, scale)
        if count:
            words += [_hindustani(count, zero), name]
    if number:
        words.append(_HINDUSTANI_1_99[number - 1])
    return " ".join(words)


def _kanji(number: int) -> str:
    """Kanji numerals for a whole number, e.g. 2024 -> "二千二十四"."""
    if number == 0:
        return _KANJI_DIGITS[0]
    out = ""
    for scale, name in _KANJI_LARGE:
        count, number = divmod(number, scale)
        if count:
            out += _kanji_below_10000(count) + name
    return out + _kanji_below_10000(number)


def _kanji_below_10000(number: int) -> str:
    """Kanji for 0-9999, leaving out the "one" before ten, hundred, and thousand (十, not 一十)."""
    out = ""
    for scale, name in _KANJI_SMALL:
        count, number = divmod(number, scale)
        if count:
            out += ("" if count == 1 else _KANJI_DIGITS[count]) + name
    return out + (_KANJI_DIGITS[number] if number else "")
