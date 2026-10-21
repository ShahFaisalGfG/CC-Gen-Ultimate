# qwen3tts_worker.py - Qwen3-TTS 0.6B Base (Apache-2.0) voice cloning on the CPU
#
# Runs with the app's environment plus qwen-tts, einops, and sox on PYTHONPATH (qwen-tts pins
# transformers 4.57, the version the app ships). Languages: zh, en, ja, ko, de, fr, ru, pt, es.

import os
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import LANGUAGE_NAMES, run_jobs  # noqa: E402

MODEL = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"


def main() -> None:
    from qwen_tts import Qwen3TTSModel

    model = Qwen3TTSModel.from_pretrained(MODEL, device_map="cpu", dtype=torch.float32)
    supported = {name.lower() for name in (model.model.get_supported_languages() or [])}

    def speak(job: dict) -> tuple:
        name = LANGUAGE_NAMES[job["language"]]
        if supported and name.lower() not in supported:
            raise SystemExit(f"Qwen3-TTS doesn't speak {name}; supported: {sorted(supported)}")
        wavs, rate = model.generate_voice_clone(
            text=job["text"], language=name, ref_audio=job["ref_audio"], ref_text=job["ref_text"],
        )
        return wavs[0], rate

    run_jobs(speak)


if __name__ == "__main__":
    main()
