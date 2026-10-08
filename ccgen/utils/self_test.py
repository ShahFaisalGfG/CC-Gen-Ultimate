# self_test.py - checks that a build can load every engine, native library, data file, and QML module
#
# PyInstaller only follows static imports. Libraries that import by name at runtime (transformers'
# lazy modules, argostranslate's sentence splitters, uvicorn's protocol auto-detection), ship
# native DLLs, or read data files can build cleanly and still fail on a user's machine. The release
# workflow runs the frozen exe with --self-test so a missing piece fails the build instead.
# None of these checks downloads a model or touches user settings. Each check imports what it
# tests inside its own body so one missing library is reported as one failed check, not as a
# crash that hides every other result.
import os
import sys
import tempfile
import traceback
import urllib.request
import wave
from typing import Callable, Optional

import numpy as np

from ccgen.config.defaults import AudioDefaults
from ccgen.utils.helpers import resource_path

Check = tuple[str, Callable[[], None]]

_QML_DIR = "ccgen/qml"
_SERVER_TIMEOUT_S = 15.0

# The QApplication must outlive every QML engine, so it is kept for the rest of the process.
_qt_app: Optional[object] = None
def _check_engines() -> None:
    """Import the engine packages exactly as the startup splash does."""
    import ccgen.engines.captions  # noqa: F401
    import ccgen.engines.translation  # noqa: F401
    import ccgen.engines.transliteration  # noqa: F401


def _check_lazy_modules() -> None:
    """Resolve the modules third-party libraries import by name only when translating."""
    from argostranslate.apply_bpe import BPE  # noqa: F401
    from argostranslate.sbd import MiniSBDSentencizer, StanzaSentencizer  # noqa: F401
    from sacremoses.tokenize import MosesDetokenizer, MosesTokenizer  # noqa: F401
    from ctranslate2.converters import TransformersConverter  # noqa: F401 - prepares OPUS-MT models
    from llama_cpp import llama_print_system_info  # Hy-MT2 translation; loads llama.cpp's DLLs
    from tokenizers import Tokenizer  # noqa: F401 - the meaning check's tokenizer
    from transformers import MarianMTModel  # noqa: F401 - loaded by name when converting OPUS-MT
    from transformers.models.auto.tokenization_auto import tokenizer_class_from_name

    if not llama_print_system_info():
        raise RuntimeError("llama.cpp reported no system information")
    # Transliteration (M2M100), OPUS-MT (Marian), NLLB, and OmniVoice (Qwen2) tokenizers are
    # resolved by name.
    for name in ("M2M100Tokenizer", "MarianTokenizer", "NllbTokenizerFast", "Qwen2TokenizerFast"):
        if tokenizer_class_from_name(name) is None:
            raise RuntimeError(f"transformers could not resolve {name}")
    # OmniVoice builds its backbone (Qwen3) and audio codec (DAC, HuBERT) from config by name,
    # and tells speakers apart with WavLM.
    from transformers.models.auto.configuration_auto import CONFIG_MAPPING
    from transformers.models.auto.modeling_auto import MODEL_MAPPING

    for model_type in ("qwen3", "dac", "hubert", "wavlm"):
        MODEL_MAPPING[CONFIG_MAPPING[model_type]]  # raises when the model class wasn't bundled


def _check_native_libraries() -> None:
    """Load CTranslate2, ONNX Runtime (voice activity detection), SentencePiece, and torch."""
    import ctranslate2
    import sentencepiece  # noqa: F401
    import torch
    from faster_whisper.vad import get_speech_timestamps

    if not ctranslate2.get_supported_compute_types("cpu"):
        raise RuntimeError("CTranslate2 reports no CPU compute types")
    get_speech_timestamps(np.zeros(AudioDefaults.SAMPLE_RATE, dtype=np.float32))
    torch.zeros(1).add_(1)


def _check_transliteration_data() -> None:
    """Transliterate a word, which reads indic_transliteration's bundled scheme files."""
    from indic_transliteration import sanscript

    if not sanscript.transliterate("namaste", sanscript.ITRANS, sanscript.DEVANAGARI):
        raise RuntimeError("indic_transliteration returned no text")


def _check_audio_decoding() -> None:
    """Decode and resample a generated WAV file through PyAV."""
    from ccgen.core.audio import load_audio

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "tone.wav")
        rate = 44100
        tone = (8000 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)).astype("<i2")
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(tone.tobytes())
        if load_audio(path).size == 0:
            raise RuntimeError("decoded audio is empty")


def _check_speech_engines() -> None:
    """Phonemize through both bundled eSpeak builds, load XTTS's Japanese, Chinese, and Korean
    text tools (dictionaries included), and report the devices speech can run on."""
    import cutlet
    import pypinyin
    from ko_speech_tools import hangul_romanize  # noqa: F401
    from kokoro_onnx.tokenizer import Tokenizer
    from piper.phonemize_espeak import EspeakPhonemizer
    from TTS.tts.models.xtts import Xtts  # noqa: F401

    from ccgen.engines.devices import EDITION_LABELS, built_architectures, describe_accelerators, torch_edition
    from ccgen.engines.hardware import detect
    from ccgen.engines.speech.omnivoice.audio import remove_silence
    from ccgen.engines.speech.omnivoice.model import OmniVoice  # noqa: F401

    if not EspeakPhonemizer().phonemize("en-us", "hello"):
        raise RuntimeError("Piper's eSpeak returned no phonemes")
    if not Tokenizer().phonemize("hello", "en-us"):
        raise RuntimeError("Kokoro's eSpeak returned no phonemes")
    if not cutlet.Cutlet().romaji("こんにちは"):
        raise RuntimeError("Japanese romanization returned nothing")
    if not pypinyin.lazy_pinyin("你好"):
        raise RuntimeError("Chinese pinyin returned nothing")
    tone = (0.3 * np.sin(np.arange(16000) * 0.05)).astype(np.float32)[None, :]
    if remove_silence(tone, 16000).shape[-1] == 0:
        raise RuntimeError("OmniVoice's silence trimming removed speech")
    architectures = " ".join(built_architectures()) or "none"
    print(f"    edition: {EDITION_LABELS[torch_edition()]} (GPU architectures: {architectures})")
    for runtime, devices in describe_accelerators().items():
        print(f"    {runtime}: {', '.join(devices)}")
    hardware = detect()
    print(f"    hardware: {hardware.summary} ({hardware.recommended} profile)")


def _check_api_server() -> None:
    """Start the embedded API server and request /options from it."""
    from ccgen.api.embedded import EmbeddedServer

    server = EmbeddedServer()
    server.start()
    try:
        if not server.wait_ready(_SERVER_TIMEOUT_S):
            raise RuntimeError("embedded API server did not start")
        with urllib.request.urlopen(f"{server.base_url}/options", timeout=_SERVER_TIMEOUT_S) as response:
            if response.status != 200:
                raise RuntimeError(f"/options returned HTTP {response.status}")
    finally:
        server.stop()


def _qml_files() -> list[str]:
    """Return every bundled .qml file."""
    root = resource_path(_QML_DIR)
    files = [
        os.path.join(folder, name)
        for folder, _dirs, names in os.walk(root)
        for name in names
        if name.endswith(".qml")
    ]
    if not files:
        raise RuntimeError(f"no QML files found in {root}")
    return sorted(files)


def _check_qml() -> None:
    """Compile every bundled QML file, which resolves each Qt module and component it imports."""
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    from PySide6.QtWidgets import QApplication

    global _qt_app
    QQuickStyle.setStyle("Material")
    _qt_app = QApplication.instance() or QApplication([sys.argv[0]])
    engine = QQmlEngine()
    errors: list[str] = []
    for path in _qml_files():
        component = QQmlComponent(engine, QUrl.fromLocalFile(path))
        if component.isError():
            errors.extend(error.toString() for error in component.errors())
    if errors:
        raise RuntimeError("; ".join(errors))
CHECKS: list[Check] = [
    ("Engines", _check_engines),
    ("Lazily imported modules", _check_lazy_modules),
    ("Native libraries", _check_native_libraries),
    ("Transliteration data", _check_transliteration_data),
    ("Audio decoding", _check_audio_decoding),
    ("Speech engines", _check_speech_engines),
    ("Embedded API server", _check_api_server),
    ("QML", _check_qml),
]


def run_self_test(report_path: Optional[str] = None, checks: Optional[list[Check]] = None) -> int:
    """Run every check, write a PASS/FAIL report, and return 0 when all checks pass, else 1.

    The report goes to report_path when given and to stdout when one exists; a --windowed
    build has no console, so the release workflow reads the report file.
    """
    selected = CHECKS if checks is None else checks
    lines: list[str] = []
    failed = 0
    for name, check in selected:
        try:
            check()
            lines.append(f"PASS  {name}")
        except Exception as e:
            failed += 1
            lines.append(f"FAIL  {name}: {e!r}")
            lines.extend("      " + line for line in traceback.format_exc().rstrip().splitlines())
    lines.append(f"{failed} of {len(selected)} checks failed" if failed else f"All {len(selected)} checks passed")
    report = "\n".join(lines) + "\n"
    if report_path:
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(report)
    if sys.stdout is not None:
        sys.stdout.write(report)
    return 1 if failed else 0
