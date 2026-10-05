# translation_models.py - the translation engines and the models each one downloads
#
# Kept free of engine imports (ctranslate2, transformers, argos) like capabilities.py, so
# settings, the API, and the UI can list engines and models without loading model code. Every
# model is free to download and use; revisions are pinned so a re-uploaded checkpoint can never
# change translations between installs.

from dataclasses import dataclass
from typing import Optional

from ccgen.config.defaults import TranslationDefaults

ENGINE_OPUS_MT = "opus_mt"
ENGINE_NLLB = "nllb"
ENGINE_MADLAD = "madlad"
ENGINE_ARGOS = "argos"
DEFAULT_ENGINE = TranslationDefaults.DEFAULT_ENGINE
PIVOT = "en"
# Settings key holding the NLLB licence acceptance (its weights allow non-commercial use only).
NLLB_TERMS_SETTING = "nllb_terms_accepted"


@dataclass(frozen=True)
class EngineInfo:
    """One choice in the Translation model picker."""

    key: str
    label: str
    hint: str


ENGINES: tuple[EngineInfo, ...] = (
    EngineInfo(
        ENGINE_OPUS_MT, "OPUS-MT (recommended)",
        "Accurate and fast: the University of Helsinki's OPUS-MT models, one per direction (about "
        "300-900 MB to download, a quarter of that on disk). Free for any use.",
    ),
    EngineInfo(
        ENGINE_NLLB, "NLLB-200 1.3B",
        "Meta's model: one 1.3 GB download translating every pair directly, strongest from Urdu "
        "into English. Its licence allows non-commercial use only.",
    ),
    EngineInfo(
        ENGINE_MADLAD, "MADLAD-400 3B",
        "Google's large model: one 2.8 GB download for every pair, free for any use. Slow without "
        "an NVIDIA GPU (several seconds per sentence on a CPU).",
    ),
    EngineInfo(
        ENGINE_ARGOS, "Argos Translate (light)",
        "Small packages (about 100 MB per direction) that run quickly on any computer, with "
        "rougher translations.",
    ),
)
ENGINE_KEYS = tuple(e.key for e in ENGINES)


@dataclass(frozen=True)
class Ct2Model:
    """A CTranslate2 translation model: one Manage Models row and one folder on disk."""

    key: str
    engine: str
    repo: str
    revision: str
    label: str
    download_mb: int
    # A Transformers checkpoint that is converted to CTranslate2 (int8) once after download;
    # False for repos that already hold a CTranslate2 model.
    convert: bool


def _opus(key: str, repo: str, revision: str, label: str, download_mb: int) -> Ct2Model:
    return Ct2Model(f"opus_mt-{key}", ENGINE_OPUS_MT, f"Helsinki-NLP/{repo}", revision, label, download_mb, True)


OPUS_MT_MODELS: dict[str, Ct2Model] = {m.key: m for m in (
    _opus("en-ar", "opus-mt-tc-big-en-ar", "ae9f1b2fd512000ca9440eb3b8ec9aa9acb298ac", "English → Arabic", 456),
    _opus("en-de", "opus-mt-en-de", "6183067f769a302e3861815543b9f312c71b0ca4", "English → German", 284),
    _opus("en-es", "opus-mt-tc-big-en-es", "8f4d4924189681076e9c642b2fd85278d793fd4d", "English → Spanish", 443),
    _opus("en-fr", "opus-mt-tc-big-en-fr", "6e062862ced6f5622a589ab2aadc2a1d4978db78", "English → French", 440),
    _opus("en-iir", "opus-mt-tc-bible-big-deu_eng_fra_por_spa-iir", "63f6d1fe0c0a9a259de39ab5be23de4b654af49e",
          "English → Hindi, Urdu", 915),
    _opus("en-pt", "opus-mt-tc-big-en-pt", "9f2863d807ecf91a374bdbecb8d01e402e90622e", "English → Portuguese", 443),
    _opus("en-ru", "opus-mt-en-ru", "bb09c99d180016eac6819df3dae68edb1690fdee", "English → Russian", 292),
    _opus("en-tr", "opus-mt-tc-big-en-tr", "e539fc16a8a1a0ea5950eb339b595bfcce990e90", "English → Turkish", 448),
    _opus("ar-en", "opus-mt-tc-big-ar-en", "bcb4acd39ee8e3552e171653a8e31a10729b4330", "Arabic → English", 575),
    _opus("de-en", "opus-mt-de-en", "1a922f3b32a8e809e17a47d4b32142d8105924e5", "German → English", 284),
    _opus("es-en", "opus-mt-es-en", "c96e2c5399ebfae4fc43d9669556b9afa74bb69d", "Spanish → English", 297),
    _opus("fr-en", "opus-mt-tc-big-fr-en", "5fa3b3c9fa3bcd65fbf31206c3ec7419c9d9cd7d", "French → English", 440),
    _opus("iir-en", "opus-mt-tc-bible-big-iir-deu_eng_fra_por_spa", "843954fb57af8f83e81a4e3230147ab83caafe1a",
          "Hindi, Urdu → English", 914),
    _opus("ja-en", "opus-mt-ja-en", "0770961a39ba6bd66305b149c3f4110bcafca2e6", "Japanese → English", 289),
    _opus("ko-en", "opus-mt-tc-big-ko-en", "fa26583a41d95346933f26b4cb8f9b700da0d445", "Korean → English", 398),
    _opus("roa-en", "opus-mt-tc-bible-big-roa-en", "4d4757865ab116b39daa3b4ca3cfe1e7daf43cbe",
          "Portuguese → English", 889),
    _opus("ru-en", "opus-mt-ru-en", "fbd6dc73284f95536648512cc21d57f19191961a", "Russian → English", 292),
    _opus("tr-en", "opus-mt-tc-big-tr-en", "2261c8fc7b1af59caee87f8ff0ecf3fbccfe8391", "Turkish → English", 447),
    _opus("zh-en", "opus-mt-zh-en", "cf109095479db38d6df799875e34039d4938aaa6", "Chinese → English", 297),
)}


@dataclass(frozen=True)
class OpusLeg:
    """The OPUS-MT model serving one direction, and the target token multi-target models need."""

    model: str
    prefix: str = ""


# Every direction goes to or from English; other pairs are translated through English.
OPUS_MT_LEGS: dict[tuple[str, str], OpusLeg] = {
    ("en", "ar"): OpusLeg("opus_mt-en-ar", ">>ara<<"),
    ("en", "de"): OpusLeg("opus_mt-en-de"),
    ("en", "es"): OpusLeg("opus_mt-en-es"),
    ("en", "fr"): OpusLeg("opus_mt-en-fr"),
    ("en", "hi"): OpusLeg("opus_mt-en-iir", ">>hin<<"),
    ("en", "pt"): OpusLeg("opus_mt-en-pt", ">>por<<"),
    ("en", "ru"): OpusLeg("opus_mt-en-ru"),
    ("en", "tr"): OpusLeg("opus_mt-en-tr"),
    ("en", "ur"): OpusLeg("opus_mt-en-iir", ">>urd<<"),
    ("ar", "en"): OpusLeg("opus_mt-ar-en"),
    ("de", "en"): OpusLeg("opus_mt-de-en"),
    ("es", "en"): OpusLeg("opus_mt-es-en"),
    ("fr", "en"): OpusLeg("opus_mt-fr-en"),
    ("hi", "en"): OpusLeg("opus_mt-iir-en", ">>eng<<"),
    ("ja", "en"): OpusLeg("opus_mt-ja-en"),
    ("ko", "en"): OpusLeg("opus_mt-ko-en"),
    ("pt", "en"): OpusLeg("opus_mt-roa-en"),
    ("ru", "en"): OpusLeg("opus_mt-ru-en"),
    ("tr", "en"): OpusLeg("opus_mt-tr-en"),
    ("ur", "en"): OpusLeg("opus_mt-iir-en", ">>eng<<"),
    ("zh", "en"): OpusLeg("opus_mt-zh-en"),
}

NLLB_MODEL = Ct2Model(
    "nllb-1.3b", ENGINE_NLLB, "OpenNMT/nllb-200-distilled-1.3B-ct2-int8",
    "70f572adafa4794890ce7826156a4209717855af", "Every language pair", 1336, False,
)
MADLAD_MODEL = Ct2Model(
    "madlad-3b", ENGINE_MADLAD, "santhosh/madlad400-3b-ct2",
    "c32ad0cf118807ea6258d14be137547155842723", "Every language pair", 2822, False,
)
# NLLB-200 names languages with script tags; MADLAD-400 uses the plain codes (<2ur>).
NLLB_CODES: dict[str, str] = {
    "ar": "arb_Arab", "de": "deu_Latn", "en": "eng_Latn", "es": "spa_Latn", "fr": "fra_Latn",
    "hi": "hin_Deva", "ja": "jpn_Jpan", "ko": "kor_Hang", "pt": "por_Latn", "ru": "rus_Cyrl",
    "tr": "tur_Latn", "ur": "urd_Arab", "zh": "zho_Hans",
}
MADLAD_CODES: dict[str, str] = {code: code for code in NLLB_CODES}

CT2_MODELS: dict[str, Ct2Model] = {**OPUS_MT_MODELS, NLLB_MODEL.key: NLLB_MODEL, MADLAD_MODEL.key: MADLAD_MODEL}


@dataclass(frozen=True)
class MeaningModel:
    """The multilingual sentence-embedding model behind the meaning check."""

    key: str = "meaning-check"
    repo: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    revision: str = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
    # The 8-bit ONNX export runs on the onnxruntime the app already ships.
    files: tuple[str, ...] = ("tokenizer.json", "onnx/model_quint8_avx2.onnx")
    download_mb: int = 120


MEANING_MODEL = MeaningModel()


def engine_info(key: str) -> EngineInfo:
    """The catalog entry for an engine key; raises ValueError for an unknown one."""
    for info in ENGINES:
        if info.key == key:
            return info
    raise ValueError(f"Unknown translation model: '{key}'.")


def route(engine: str, source: str, target: str) -> list[tuple[str, str]]:
    """The directions `engine` translates through to get from `source` to `target`.

    OPUS-MT and Argos go through English when there is no direct model; NLLB and MADLAD
    translate every pair directly. Raises ValueError when the engine can't reach the target.
    """
    if engine in (ENGINE_NLLB, ENGINE_MADLAD):
        codes = NLLB_CODES if engine == ENGINE_NLLB else MADLAD_CODES
        missing = [lang for lang in (source, target) if lang not in codes]
        if missing:
            raise ValueError(f"{engine_info(engine).label} can't translate '{missing[0]}'.")
        return [(source, target)]
    if engine == ENGINE_OPUS_MT:
        legs = [(source, target)] if (source, target) in OPUS_MT_LEGS or PIVOT in (source, target) \
            else [(source, PIVOT), (PIVOT, target)]
        missing_leg = next((leg for leg in legs if leg not in OPUS_MT_LEGS), None)
        if missing_leg:
            raise ValueError(f"OPUS-MT has no model from '{missing_leg[0]}' to '{missing_leg[1]}'.")
        return legs
    if engine == ENGINE_ARGOS:
        return [(source, target)]
    raise ValueError(f"Unknown translation model: '{engine}'.")


def models_for(engine: str, source: str, target: str) -> list[Ct2Model]:
    """The CTranslate2 models a translation needs, in route order (none for Argos)."""
    if engine == ENGINE_NLLB:
        return [NLLB_MODEL]
    if engine == ENGINE_MADLAD:
        return [MADLAD_MODEL]
    if engine == ENGINE_OPUS_MT:
        keys: list[str] = []
        for leg in route(engine, source, target):
            if OPUS_MT_LEGS[leg].model not in keys:
                keys.append(OPUS_MT_LEGS[leg].model)
        return [OPUS_MT_MODELS[key] for key in keys]
    return []


def opus_leg(source: str, target: str) -> Optional[OpusLeg]:
    """The OPUS-MT model and target token for one direction, or None."""
    return OPUS_MT_LEGS.get((source, target))
