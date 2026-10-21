# speech - text-to-speech engines used for dubbing
#
# Engines are imported only when created: each pulls in a heavy runtime (PyTorch for OmniVoice
# and XTTS, ONNX Runtime and eSpeak for Piper and Kokoro), and most runs need just one of them.

from ccgen.config.voices import ENGINE_KOKORO, ENGINE_OMNIVOICE, ENGINE_PIPER, ENGINE_XTTS, VoiceOption
from ccgen.engines.speech.base import CloningEngine, SpeechEngine


def create_engine(voice: VoiceOption, device: str, fast: bool = False) -> SpeechEngine:
    """Instantiate the speech engine that speaks with `voice` on the preferred `device`.

    `fast` trades a little quality for speed where an engine offers that (OmniVoice runs fewer
    denoising steps).
    """
    if voice.engine == ENGINE_OMNIVOICE:
        from ccgen.engines.speech.omnivoice_engine import FAST_STEPS, QUALITY_STEPS, OmniVoiceEngine

        return OmniVoiceEngine(voice, device, FAST_STEPS if fast else QUALITY_STEPS)
    if voice.engine == ENGINE_XTTS:
        from ccgen.engines.speech.xtts_engine import XttsEngine

        return XttsEngine(voice, device)
    if voice.engine == ENGINE_KOKORO:
        from ccgen.engines.speech.kokoro_engine import KokoroEngine

        return KokoroEngine(voice, device)
    if voice.engine == ENGINE_PIPER:
        from ccgen.engines.speech.piper_engine import PiperEngine

        return PiperEngine(voice, device)
    raise ValueError(f"Unknown speech engine: '{voice.engine}'.")


__all__ = ["CloningEngine", "SpeechEngine", "create_engine"]
