# defaults.py - application defaults and supported options for CC-Gen-Ultimate

from typing import Any


class AppInfo:
    """Application metadata."""

    APP_NAME = "CC-Gen-Ultimate"
    APP_VERSION = "1.0.0"
    APP_AUTHOR = "Shah Faisal"
    APP_DESCRIPTION = "Offline subtitle generation, translation, transliteration, and dubbing"


class ModelDefaults:
    """Whisper model selection defaults."""

    DEFAULT_MODEL = "base"
    SUPPORTED_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]
    MODEL_SIZES_MB: dict[str, int] = {
        "tiny": 75,
        "base": 145,
        "small": 466,
        "medium": 1500,
        "large-v3-turbo": 1620,
        "large-v3": 3000,
    }
    MODEL_NOTES: dict[str, str] = {
        "tiny": "fastest, rough drafts",
        "base": "fast, good for clear speech",
        "small": "balanced speed and accuracy",
        "medium": "accurate, slow on CPU",
        "large-v3-turbo": "near-best accuracy, much faster than large",
        "large-v3": "best accuracy, slowest",
    }


class ModelRepos:
    """Hugging Face repo ids for every downloadable model.

    Shared by the engines that load them, the cache-status checks, and the Manage Models catalog,
    so adding a model means editing this one place.
    """

    WHISPER: dict[str, str] = {
        "tiny": "Systran/faster-whisper-tiny",
        "base": "Systran/faster-whisper-base",
        "small": "Systran/faster-whisper-small",
        "medium": "Systran/faster-whisper-medium",
        "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "large-v3": "Systran/faster-whisper-large-v3",
    }
    M2M100_TOKENIZER = "Mavkif/m2m100_rup_tokenizer_both"
    M2M100: dict[tuple[str, str], str] = {
        ("ur", "roman"): "Mavkif/m2m100_rup_ur_to_rur",
        ("roman", "ur"): "Mavkif/m2m100_rup_rur_to_ur",
    }
    REKHTA = "rekhtalabs/hi-2-ur-translit"
    PIPER_VOICES = "rhasspy/piper-voices"
    # Pinned so a re-uploaded checkpoint can never change voices between installs.
    XTTS = "coqui/XTTS-v2"
    XTTS_REVISION = "6c2b0d75eae4b7047358e3b6bd9325f857d43f77"
    XTTS_FILES = ("config.json", "model.pth", "vocab.json")
    XTTS_SIZE_BYTES = 1_868_294_705
    # Kokoro's ONNX export is published as GitHub release assets: (name, size, sha256).
    KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
    KOKORO_FILES: tuple[tuple[str, int, str], ...] = (
        ("kokoro-v1.0.onnx", 325_505_369, "beb0d1848dee9a49da392cc3df26958d46cfa35d321edf434f52949153f0df3a"),
        ("voices-v1.0.bin", 28_214_398, "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d"),
    )


class ComputeDefaults:
    """CTranslate2 device and compute type defaults.

    "auto" picks an NVIDIA GPU when CUDA is usable and falls back to the CPU otherwise; the
    "auto" compute type resolves to float16 on a GPU and int8 on a CPU.
    """

    DEVICE_AUTO = "auto"
    COMPUTE_AUTO = "auto"
    DEFAULT_DEVICE = DEVICE_AUTO
    DEFAULT_COMPUTE_TYPE = COMPUTE_AUTO
    SUPPORTED_DEVICES = [DEVICE_AUTO, "cpu", "cuda"]
    SUPPORTED_COMPUTE_TYPES = [COMPUTE_AUTO, "int8", "float16", "float32"]
    DEVICES: list[tuple[str, str]] = [
        ("Automatic (GPU when available)", DEVICE_AUTO),
        ("CPU", "cpu"),
        ("NVIDIA GPU (CUDA)", "cuda"),
    ]


class TranscriptionDefaults:
    """faster-whisper transcription defaults."""

    DEFAULT_LANGUAGE: str | None = None
    WORD_TIMESTAMPS = True
    BEAM_SIZE = 5
    VAD_FILTER = True
    VAD_MIN_SILENCE_MS = 500
    # Conditioning each window on the previous one lets a single misheard phrase repeat for
    # minutes on long files; turning it off trades a little stylistic consistency for robustness.
    CONDITION_ON_PREVIOUS_TEXT = False
    # Skips silent stretches longer than this when a window looks hallucinated (needs word timestamps).
    HALLUCINATION_SILENCE_S = 2.0
    # Language detection votes over this many 30 s windows, so a music or silent intro can't
    # decide the language for the whole file on its own.
    LANGUAGE_DETECTION_SEGMENTS = 3


class TranslationDefaults:
    """Translation defaults (the models themselves are listed in translation_models.py)."""

    DEFAULT_SOURCE_LANG = "auto"
    DEFAULT_TARGET_LANG = "en"
    # OPUS-MT; kept as a literal here so this module needn't import the model catalog.
    DEFAULT_ENGINE = "opus_mt"
    MEANING_CHECK = True


class OutputDefaults:
    """Subtitle output format and cue layout defaults."""

    FORMAT_SRT = True
    FORMAT_VTT = False
    FORMAT_LRC = False
    FORMAT_ASS = False
    FORMAT_SBV = False
    # Written when a request names no format at all.
    DEFAULT_FORMAT = "srt"
    # Empty means "next to each input file".
    DIRECTORY = ""
    MAX_LINE_LENGTH = 42
    MAX_LINE_LENGTH_RANGE = (20, 80)
    MAX_LINES = 2
    MAX_LINES_RANGE = (1, 3)
    MIN_DURATION_MS = 500
    # A cue is closed early once it runs this long, even when it still has room for more text.
    MAX_CUE_DURATION_S = 7.0
    # A pause between two words at least this long starts a new cue.
    CUE_PAUSE_SPLIT_S = 0.8
    # Scripts written without spaces between words get a shorter line limit (Netflix guidance).
    NO_SPACE_LANGUAGES = frozenset({"zh", "ja", "th", "my", "lo", "km"})
    NO_SPACE_MAX_LINE_LENGTH = 16


class AudioDefaults:
    """Audio decoding defaults (Whisper models expect 16 kHz mono)."""

    SAMPLE_RATE = 16000


class LoggingDefaults:
    """Logging preferences: "critical" keeps errors only, "all" records everything."""

    ENABLE_LOGS = True
    DEFAULT_LOG_LEVEL = "critical"
    SUPPORTED_LOG_LEVELS = ["critical", "all"]
    LOG_FILE_NAME = "ccgen.log"
    MAX_LOG_BYTES = 1_000_000
    LOG_BACKUP_COUNT = 3


class LanguageOptions:
    """Language lists for transcription and translation UI dropdowns."""

    TRANSCRIPTION: list[tuple[str, str | None]] = [
        ("Auto-detect", None),
        ("Arabic", "ar"),
        ("Chinese", "zh"),
        ("English", "en"),
        ("French", "fr"),
        ("German", "de"),
        ("Hindi", "hi"),
        ("Japanese", "ja"),
        ("Korean", "ko"),
        ("Portuguese", "pt"),
        ("Russian", "ru"),
        ("Spanish", "es"),
        ("Turkish", "tr"),
        ("Urdu", "ur"),
    ]

    TRANSLATION_TARGETS: list[tuple[str, str]] = [
        ("Arabic", "ar"),
        ("English", "en"),
        ("French", "fr"),
        ("German", "de"),
        ("Hindi", "hi"),
        ("Portuguese", "pt"),
        ("Russian", "ru"),
        ("Spanish", "es"),
        ("Turkish", "tr"),
        ("Urdu", "ur"),
    ]


class TransliterationDefaults:
    """Transliteration scheme and engine defaults."""

    DEFAULT_SOURCE = "roman"
    DEFAULT_TARGET = "ur"

    ENGINE_RULE = "rule"
    ENGINE_NEURAL = "neural"
    DEFAULT_ENGINE = ENGINE_RULE

    ENGINES: list[tuple[str, str]] = [
        ("Rule-based (fast, offline)", ENGINE_RULE),
        ("Neural (higher quality)", ENGINE_NEURAL),
    ]

    SCHEMES: list[tuple[str, str]] = [
        ("Roman / Latin",      "roman"),
        ("Urdu (Nastaliq)",    "ur"),
        ("Hindi (Devanagari)", "hi"),
        ("Bengali",            "bn"),
        ("Gujarati",           "gu"),
        ("Punjabi (Gurmukhi)", "pa"),
        ("Tamil",              "ta"),
        ("Telugu",             "te"),
        ("Kannada",            "kn"),
        ("Malayalam",          "ml"),
        ("Odia",               "or"),
        ("Sinhala",            "si"),
        ("Thai",               "th"),
        ("Burmese",            "my"),
    ]


class DubbingDefaults:
    """Speech synthesis defaults for dubbing."""

    MODE_XTTS = "xtts"
    MODE_KOKORO = "kokoro"
    MODE_PIPER = "piper"
    DEFAULT_MODE = MODE_XTTS
    # (label, code, trade-offs shown under the mode picker)
    MODES: list[tuple[str, str, str]] = [
        ("Voice cloning (XTTS-v2)", MODE_XTTS,
         "Clones each original speaker for the most natural dub. Slow without a GPU, a 1.9 GB "
         "download, speaks every language here (Urdu by reading it in Hindi script), and allows "
         "non-commercial use only."),
        ("Natural voices (Kokoro)", MODE_KOKORO,
         "Very natural stock voices that run fast on any computer. 350 MB; English, Spanish, French, "
         "Hindi, Japanese, Portuguese, and Chinese."),
        ("Light voices (Piper)", MODE_PIPER,
         "Small, fast stock voices with the widest language coverage, including Urdu. "
         "About 60 MB per voice; sounds more synthetic."),
    ]
    VOICE_AUTO = "auto"
    # Voice cloning has no Urdu model; on, it reads Urdu lines in Hindi script with the cloned
    # voices, off, Urdu falls back to a Piper voice.
    SCRIPT_BRIDGE = True
    LANGUAGE_AUTO = "auto"
    SPEAKERS_AUTO = "auto"
    SPEAKERS_SINGLE = "single"
    DEFAULT_SPEAKERS = SPEAKERS_AUTO
    SPEAKERS: list[tuple[str, str]] = [
        ("Detect each speaker", SPEAKERS_AUTO),
        ("One voice for everyone", SPEAKERS_SINGLE),
    ]
    MAX_SPEAKERS = 6
    # Speech may be sped up this much to fit a cue's time before it is trimmed.
    MAX_SPEEDUP = 1.35
    MAX_SPEEDUP_RANGE = (1.0, 2.0)
    OUTPUT_TRACK = "track"
    OUTPUT_WAV = "wav"
    DEFAULT_OUTPUT = OUTPUT_TRACK
    OUTPUTS: list[tuple[str, str]] = [
        ("Add as a new audio track", OUTPUT_TRACK),
        ("Separate WAV file", OUTPUT_WAV),
    ]
    DEFAULT_TRACK = False
    DEVICE_AUTO = "auto"
    DEVICE_CPU = "cpu"
    DEVICES: list[tuple[str, str]] = [
        ("Automatic (best device)", DEVICE_AUTO),
        ("CPU", DEVICE_CPU),
    ]
    # Sample rate of the assembled dub track.
    TRACK_RATE = 48000
    # Languages offered for dubbing: every spoken language the app transcribes.
    LANGUAGES: list[tuple[str, str]] = [(label, code) for label, code in LanguageOptions.TRANSCRIPTION if code]


def get_default_settings() -> dict[str, Any]:
    """Return the complete default settings dictionary."""
    return {
        "model": {
            "name": ModelDefaults.DEFAULT_MODEL,
            "device": ComputeDefaults.DEFAULT_DEVICE,
            "compute_type": ComputeDefaults.DEFAULT_COMPUTE_TYPE,
        },
        "transcription": {
            "language": TranscriptionDefaults.DEFAULT_LANGUAGE,
            "word_timestamps": TranscriptionDefaults.WORD_TIMESTAMPS,
            "beam_size": TranscriptionDefaults.BEAM_SIZE,
            "vad_filter": TranscriptionDefaults.VAD_FILTER,
        },
        "translation": {
            "source_lang": TranslationDefaults.DEFAULT_SOURCE_LANG,
            "target_lang": TranslationDefaults.DEFAULT_TARGET_LANG,
            "engine": TranslationDefaults.DEFAULT_ENGINE,
            "meaning_check": TranslationDefaults.MEANING_CHECK,
            "nllb_terms_accepted": False,
        },
        "output": {
            "directory": OutputDefaults.DIRECTORY,
            "srt": OutputDefaults.FORMAT_SRT,
            "vtt": OutputDefaults.FORMAT_VTT,
            "lrc": OutputDefaults.FORMAT_LRC,
            "ass": OutputDefaults.FORMAT_ASS,
            "sbv": OutputDefaults.FORMAT_SBV,
            "max_line_length": OutputDefaults.MAX_LINE_LENGTH,
            "max_lines": OutputDefaults.MAX_LINES,
        },
        "logging": {
            "enable_logs": LoggingDefaults.ENABLE_LOGS,
            "log_level": LoggingDefaults.DEFAULT_LOG_LEVEL,
        },
        "transliteration": {
            "source": TransliterationDefaults.DEFAULT_SOURCE,
            "target": TransliterationDefaults.DEFAULT_TARGET,
            "engine": TransliterationDefaults.DEFAULT_ENGINE,
        },
        "dubbing": {
            "mode": DubbingDefaults.DEFAULT_MODE,
            "speakers": DubbingDefaults.DEFAULT_SPEAKERS,
            "max_speedup": DubbingDefaults.MAX_SPEEDUP,
            "output": DubbingDefaults.DEFAULT_OUTPUT,
            "default_track": DubbingDefaults.DEFAULT_TRACK,
            "device": DubbingDefaults.DEVICE_AUTO,
            "script_bridge": DubbingDefaults.SCRIPT_BRIDGE,
            "xtts_terms_accepted": False,
        },
        "ui": {
            "theme": "system",
        },
    }
