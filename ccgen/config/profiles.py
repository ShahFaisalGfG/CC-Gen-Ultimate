# profiles.py - performance profiles: which model each feature uses when its choice is Automatic
#
# A profile matches the app to the PC it runs on. "Maximum quality" assumes an NVIDIA GPU with
# room for the largest models; "Balanced" a GPU with less memory or a strong CPU; "Light" any
# other PC, where the lightest models that still meet the quality bar are used. Every model
# picker offers "Automatic", which this module resolves for the active profile; choosing a model
# by hand overrides the profile for that feature only. "Custom" is the profile for choosing every
# feature's model by hand: its Automatic choices follow the profile recommended for this PC.
#
# The choices come from the benchmark in scripts/eval (FLORES chrF for translation, FLEURS CER,
# pacing, and speaker similarity for dubbing) and are kept here, free of engine imports, so the
# UI, the API, and the tasks resolve them the same way without loading any model code.

from dataclasses import dataclass
from ccgen.config.capabilities import neural_model_key
from ccgen.config.defaults import AUTO, DubbingDefaults, TransliterationDefaults
from ccgen.config.translation_models import ENGINE_HYMT, ENGINE_OPUS_MT, OPUS_MT_LEGS, PIVOT

PROFILE_QUALITY = "quality"
PROFILE_BALANCED = "balanced"
PROFILE_LIGHT = "light"
# Used until the hardware has been detected, and for a profile value this version doesn't know:
# the light choices finish on any PC.
FALLBACK_PROFILE = PROFILE_LIGHT


@dataclass(frozen=True)
class ProfileInfo:
    """One choice in the Performance page."""

    key: str
    label: str
    hint: str


PROFILES: tuple[ProfileInfo, ...] = (
    ProfileInfo(
        PROFILE_QUALITY, "Maximum quality",
        "The largest, most accurate models, run on an NVIDIA GPU with 8 GB or more.",
    ),
    ProfileInfo(
        PROFILE_BALANCED, "Balanced",
        "Near-best accuracy at a fraction of the time; for GPUs with 4-8 GB or fast CPUs.",
    ),
    ProfileInfo(
        PROFILE_LIGHT, "Light",
        "The fastest models that still translate faithfully and clone voices; for any PC.",
    ),
)
PROFILE_KEYS = tuple(p.key for p in PROFILES)
PROFILE_CUSTOM = "custom"
CUSTOM_PROFILE = ProfileInfo(
    PROFILE_CUSTOM, "Custom",
    "Choose each feature's model and the voice cloning quality below; Automatic picks what this PC's "
    "recommended profile would.",
)
# What the Performance page offers: the three profiles, then Custom.
PROFILE_CHOICES: tuple[ProfileInfo, ...] = (*PROFILES, CUSTOM_PROFILE)

# Hardware thresholds for the recommended profile.
QUALITY_VRAM_GB = 8.0
BALANCED_VRAM_GB = 4.0
BALANCED_CORES = 8
BALANCED_RAM_GB = 16.0

# Whisper, measured on native FLEURS speech on a 4-core CPU: "small" runs at about real time and
# is the smallest model that transcribes every language ("base" fails Hindi entirely);
# large-v3-turbo halves its errors in Urdu and Hindi at 3-4 times the time; large-v3 needs a GPU.
WHISPER_MODELS = {PROFILE_QUALITY: "large-v3", PROFILE_BALANCED: "large-v3-turbo", PROFILE_LIGHT: "small"}

# Translation: OPUS-MT has no model into Japanese, Korean, or Chinese and its Korean model is
# unusable, so those directions go to Hy-MT2, which scored highest there (English to Japanese:
# chrF 42.6, against 37.8 for NLLB-200 and 29.5 for MADLAD-400). From Japanese it also beats
# OPUS-MT (into English: 57.3 against 46.7); from Chinese it doesn't keep the meaning as well
# (into English: meaning 0.752 against 0.779; into Urdu: chrF 38.2 against 39.8), so OPUS-MT,
# at a twentieth of the time, keeps Chinese sources. Automatic only picks models that are free
# for any use: a workflow learns its source language only after transcribing, too late to ask
# for a licence, so NLLB-200 (non-commercial) is used only when chosen by hand.
_NOT_OPUS = ENGINE_HYMT
_HYMT_SOURCES = frozenset({"ja", "ko"})
_HYMT_TARGETS = frozenset({"ja", "ko", "zh"})


def normalize(profile: str) -> str:
    """A known profile key: the given one, or the fallback for "" and unknown values."""
    return profile if profile in PROFILE_KEYS else FALLBACK_PROFILE


def profile_info(key: str) -> ProfileInfo:
    """The catalog entry for a profile key, Custom included (the fallback profile's for unknown keys)."""
    if key == PROFILE_CUSTOM:
        return CUSTOM_PROFILE
    key = normalize(key)
    return next(p for p in PROFILES if p.key == key)


def saved_profile(settings: dict) -> str:
    """The profile chosen in saved settings, Custom included ("" until the hardware has been detected)."""
    return str(settings.get("performance", {}).get("profile") or "")


def effective_profile(settings: dict) -> str:
    """The profile that resolves Automatic choices: the chosen one, or for Custom the one
    recommended for this PC ("" until the hardware has been detected)."""
    profile = saved_profile(settings)
    if profile == PROFILE_CUSTOM:
        return str(settings.get("performance", {}).get("recommended") or "")
    return profile


def recommend(vram_gb: float, ram_gb: float, physical_cores: int) -> str:
    """The profile for a PC with this GPU memory (0 without a usable GPU), RAM, and CPU."""
    if vram_gb >= QUALITY_VRAM_GB:
        return PROFILE_QUALITY
    if vram_gb >= BALANCED_VRAM_GB or (physical_cores >= BALANCED_CORES and ram_gb >= BALANCED_RAM_GB):
        return PROFILE_BALANCED
    return PROFILE_LIGHT


def whisper_model(choice: str, profile: str) -> str:
    """The Whisper model for a model setting ("auto" or a model name)."""
    return WHISPER_MODELS[normalize(profile)] if choice == AUTO else choice


def translation_engine(choice: str, profile: str, source: str, target: str) -> str:
    """The translation engine for an engine setting ("auto" or an engine key) and a direction."""
    if choice != AUTO:
        return choice
    del profile  # every profile currently makes the same per-direction choice
    if source in _HYMT_SOURCES or target in _HYMT_TARGETS:
        return _NOT_OPUS
    legs = [(source, target)] if PIVOT in (source, target) else [(source, PIVOT), (PIVOT, target)]
    return ENGINE_OPUS_MT if all(leg in OPUS_MT_LEGS for leg in legs) else _NOT_OPUS


def transliteration_engine(choice: str, profile: str, source: str, target: str) -> str:
    """The transliteration engine: neural where a model exists, except on the Light profile."""
    if choice != AUTO:
        return choice
    if normalize(profile) != PROFILE_LIGHT and neural_model_key(source, target) is not None:
        return TransliterationDefaults.ENGINE_NEURAL
    return TransliterationDefaults.ENGINE_RULE


@dataclass(frozen=True)
class DubChoice:
    """The dubbing engine and whether it runs in its faster mode."""

    mode: str
    fast: bool


def translation_engines(choice: str, profile: str, source: str, target: str, sources: tuple[str, ...] = ()) -> set[str]:
    """Every engine a translation may run: one per possible source when `source` is "auto".

    `sources` are the languages known for the queued files; without any, English is assumed.
    """
    if choice != AUTO:
        return {choice}  # a model chosen by hand runs whatever the pair
    candidates = (source,) if source != AUTO else (sources or (PIVOT,))
    return {translation_engine(choice, profile, s, target) for s in candidates if s and s != target}


def dub_engine(choice: str, profile: str, quality: str = AUTO) -> DubChoice:
    """The dubbing mode for a mode setting, and whether it runs fast: as `quality` says, or with
    "auto" fast except on Maximum quality."""
    if quality == AUTO:
        fast = normalize(profile) != PROFILE_QUALITY
    else:
        fast = quality == DubbingDefaults.QUALITY_FAST
    mode = DubbingDefaults.MODE_OMNIVOICE if choice == AUTO else choice
    return DubChoice(mode, fast)


def describe(profile: str) -> list[tuple[str, str]]:
    """What Automatic means on each feature for a profile, for the Performance page."""
    profile = normalize(profile)
    translit = "neural where available" if profile != PROFILE_LIGHT else "rule-based"
    speed = "full quality" if profile == PROFILE_QUALITY else "fast mode"
    return [
        ("Subtitle generation", f"Whisper {WHISPER_MODELS[profile]}"),
        ("Translation", "OPUS-MT, with Hy-MT2 into Japanese, Korean, and Chinese and from Japanese and Korean"),
        ("Transliteration", translit.capitalize()),
        ("Dubbing", f"OmniVoice voice cloning, {speed}"),
    ]

