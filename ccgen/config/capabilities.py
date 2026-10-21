# capabilities.py - which language and script pairs each engine can handle
#
# Kept free of engine imports (torch, transformers, argos) so config validation, the API, and
# the UI controllers can answer "is this supported?" without loading any model code.

import os
import re
from typing import Optional

from ccgen.config.defaults import LanguageOptions, ModelRepos, TransliterationDefaults
from ccgen.config.translation_models import ENGINE_ARGOS, ENGINE_HYMT, HYMT_MODEL, models_for

_SCHEME_CODES = frozenset(code for _, code in TransliterationDefaults.SCHEMES)
# Punjabi has no direct neural model; the neural engine pivots it through Devanagari to reach
# the Hindi -> Urdu model.
_REKHTA_SOURCES = frozenset({"hi", "pa"})
_KNOWN_LANGUAGES = frozenset(
    code for _, code in LanguageOptions.TRANSCRIPTION + LanguageOptions.TRANSLATION_TARGETS if code
)
# Argos publishes most pairs only to and from English, which the translator pivots through.
PIVOT_LANGUAGE = "en"
# A language tag ends a subtitle's name after a separator: movie_en, movie.en, movie-en, movie en,
# movie [en], movie (English). Brackets may close it.
_TRAILING_WORD = re.compile(r"(?P<sep>[\s._\-\[(]+)(?P<word>[A-Za-z]+)[\])]?\s*$")
_NAME_SEPARATORS = " ._-[("
# Media players' subtitle tags that may follow the language: movie.en.forced.srt
_SUBTITLE_TAGS = frozenset({"forced", "sdh", "cc"})
_LANGUAGE_WORDS = {
    # ISO 639-2 codes, bibliographic and terminology forms
    "ara": "ar", "chi": "zh", "zho": "zh", "eng": "en", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de",
    "hin": "hi", "jpn": "ja", "kor": "ko", "por": "pt", "rus": "ru", "spa": "es", "tur": "tr", "urd": "ur",
    # English names
    "arabic": "ar", "chinese": "zh", "mandarin": "zh", "english": "en", "french": "fr", "german": "de",
    "hindi": "hi", "japanese": "ja", "korean": "ko", "portuguese": "pt", "russian": "ru", "spanish": "es",
    "turkish": "tr", "urdu": "ur",
}
# A region or script after a hyphen (pt-BR, en-US, zh-Hans) is at most this long.
_MAX_REGION_LENGTH = 4
# Languages written in Latin script, whose subtitles transliterate as "roman".
_LATIN_SCRIPT_LANGUAGES = frozenset({
    "af", "az", "ca", "cs", "cy", "da", "de", "en", "es", "et", "eu", "fi", "fr", "ga", "gl", "hr", "ht", "hu",
    "id", "is", "it", "jw", "la", "lb", "lt", "lv", "mi", "ms", "mt", "nl", "nn", "no", "pl", "pt", "ro", "sk",
    "sl", "sn", "so", "sq", "sv", "sw", "tk", "tl", "tr", "uz", "vi", "yo",
})


def transliteration_supported(engine: str, source: str, target: str) -> bool:
    """Return True when `engine` can convert text written in `source` script to `target`."""
    if source == target:
        return False
    if engine == TransliterationDefaults.ENGINE_RULE:
        return source in _SCHEME_CODES and target in _SCHEME_CODES
    if engine == TransliterationDefaults.ENGINE_NEURAL:
        return neural_model_key(source, target) is not None
    return False


def neural_model_key(source: str, target: str) -> Optional[str]:
    """Return the asset key of the neural model serving a script pair, or None."""
    if (source, target) in ModelRepos.M2M100:
        return f"{source}-{target}"
    if source in _REKHTA_SOURCES and target == "ur":
        return "hi-ur"
    return None


def translation_asset_ids(source: str, target: str, engine: str = ENGINE_ARGOS) -> list[str]:
    """Manage Models ids of what `engine` needs to translate source→target ("" source: not known yet).

    Argos needs a package per direction (via English when needed). NLLB, MADLAD, and Hy-MT2 need
    their one model whatever the pair; OPUS-MT needs the models on its route, and with the source
    not known yet, the model from English into the target.
    """
    if source == target or not target:
        return []
    if engine == ENGINE_HYMT:
        return [f"translation:{HYMT_MODEL.key}"]
    if engine == ENGINE_ARGOS:
        if not source:
            return []
        if PIVOT_LANGUAGE in (source, target):
            return [f"translation:{source}-{target}"]
        return [f"translation:{source}-{PIVOT_LANGUAGE}", f"translation:{PIVOT_LANGUAGE}-{target}"]
    source = source or PIVOT_LANGUAGE
    if source == target:
        return []
    try:
        return [f"translation:{model.key}" for model in models_for(engine, source, target)]
    except ValueError:
        return []


def language_from_filename(path: str) -> str:
    """Return the language code a subtitle's name ends with (`movie.en.srt` -> "en"), or ""."""
    return split_language(path)[1]


def split_language(path: str) -> tuple[str, str]:
    """Split a language tag off the end of a file name: (path without the tag, language code).

    Reads 2-letter codes with an optional region (`movie_pt-BR.srt`), ISO 639-2 codes
    (`movie.eng.srt`), and English names (`movie (Urdu).srt`), followed by tags such as
    `forced`. Only supported languages count, and a name must remain before the tag, so
    `my_movie.srt`, `en.srt`, and `movie_tr_ur_roman.srt` carry no language and come back whole.
    """
    folder, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    base = stem
    while (match := _TRAILING_WORD.search(base)) and match.group("word").lower() in _SUBTITLE_TAGS:
        base = base[: match.start()]
    code, start = _language_at_end(base)
    if not code:
        return path, ""
    return os.path.join(folder, base[:start] + ext) if folder else base[:start] + ext, code


def _language_at_end(stem: str) -> tuple[str, int]:
    """The language tag ending `stem` and where its separator starts, or ("", -1)."""
    match = _named_word(stem)
    if match is None:
        return "", -1
    code = _language_code(match.group("word"))
    if code:
        return code, match.start()
    word = match.group("word")
    if match.group("sep") == "-" and len(word) <= _MAX_REGION_LENGTH:
        inner = _named_word(stem[: match.start()])
        if inner is not None and len(inner.group("word")) == 2:
            code = _language_code(inner.group("word"))
            if code:
                return code, inner.start()
    return "", -1


def _named_word(stem: str) -> Optional[re.Match[str]]:
    """The last separated word of `stem` when a name comes before it."""
    match = _TRAILING_WORD.search(stem)
    if match is None or not stem[: match.start()].strip(_NAME_SEPARATORS):
        return None
    return match


def _language_code(word: str) -> str:
    """The supported language a code or name stands for, or ""."""
    word = word.lower()
    if len(word) == 2:
        return word if word in _KNOWN_LANGUAGES else ""
    return _LANGUAGE_WORDS.get(word, "")


def language_name(code: str) -> str:
    """The display name of a supported language code, or the code itself."""
    return next((label for label, value in LanguageOptions.TRANSLATION_TARGETS if value == code), code)


def script_for_language(language: str) -> str:
    """The transliteration script a language's text is written in, or "" when no script fits."""
    if language in _LATIN_SCRIPT_LANGUAGES:
        return TransliterationDefaults.ROMAN
    return language if language in _SCHEME_CODES else ""
