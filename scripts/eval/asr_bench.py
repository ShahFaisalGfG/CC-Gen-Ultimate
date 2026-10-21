# asr_bench.py - score the Whisper models on native FLEURS speech in every supported language
#
#   python scripts/eval/asr_bench.py --models small,large-v3-turbo --count 10
#
# Each model transcribes the same recordings exactly as the Generate tab does (the app's own
# Whisper engine on the CPU, int8, with the language given), so the report shows what each
# performance profile's model delivers: mean CER per language and the real-time factor (seconds
# of work per second of audio). Results are cached per model and language.

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import data  # noqa: E402
from metrics import cer, resample  # noqa: E402

from ccgen.config.defaults import ModelDefaults  # noqa: E402
from ccgen.engines.captions.whisper_engine import WhisperEngine  # noqa: E402


def run(model: str, language: str, count: int) -> dict:
    """Transcribe `count` FLEURS recordings in `language` with one Whisper model."""
    engine = WhisperEngine(model_name=model, device="cpu")
    engine.load()
    errors, audio_seconds, work_seconds = [], 0.0, 0.0
    for utterance in data.fleurs(language, count):
        clip = resample(utterance.audio, utterance.rate)
        started = time.perf_counter()
        segments = engine.transcribe(clip, language=language, vad_filter=False)
        work_seconds += time.perf_counter() - started
        audio_seconds += utterance.seconds
        errors.append(cer(" ".join(s["text"] for s in segments), utterance.text, language))
    return {"model": model, "language": language, "count": len(errors), "mean_cer": float(np.mean(errors)),
            "failed_rate": float(np.mean([e > 0.5 for e in errors])), "real_time_factor": work_seconds / audio_seconds}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default="small,large-v3-turbo,large-v3")
    parser.add_argument("--languages", default=",".join(data.LANGUAGES))
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    folder = os.path.join(data.cache_root(), "results", "asr")
    os.makedirs(folder, exist_ok=True)
    for model in args.models.split(","):
        if model not in ModelDefaults.SUPPORTED_MODELS:
            raise SystemExit(f"Unknown Whisper model: {model}")
        for language in args.languages.split(","):
            path = os.path.join(folder, f"{model}-{language}-{args.count}.json")
            if os.path.exists(path):
                continue
            result = run(model, language, args.count)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(result, fh, indent=1)
            print(f"{model:>15} {language}: mean CER {result['mean_cer']:.3f}  failed {result['failed_rate']:.0%}  "
                  f"RTF {result['real_time_factor']:.2f}", flush=True)


if __name__ == "__main__":
    main()
