# xtts_urdu_worker.py - XTTS-v2 fine-tuned on Urdu (suhaibrashid17/XTTS-v2-Urdu-FT) on the CPU
#
# Runs in the app's environment (coqui-tts). The fine-tune's README replaces coqui's tokenizer
# file to add Urdu; here the same changes (a [ur] language token, a 150-character limit, and
# text cleaning that leaves Urdu letters alone) are applied in this process only.

import os
import re
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import run_jobs  # noqa: E402

REPO = "suhaibrashid17/XTTS-v2-Urdu-FT"
REVISION = "ff5a7a88a99f44d0203a4b9e13707092e787a0d0"
REFERENCE_RATE = 22050


def _patch_tokenizer() -> None:
    """Let coqui's XTTS tokenizer accept Urdu text."""
    from TTS.tts.layers.xtts import tokenizer

    original = tokenizer.VoiceBpeTokenizer.preprocess_text

    def preprocess_text(self, txt: str, lang: str) -> str:
        if lang != "ur":
            return original(self, txt, lang)
        return re.sub(r"\s+", " ", txt.replace('"', "")).strip().lower()

    tokenizer.VoiceBpeTokenizer.preprocess_text = preprocess_text


def main() -> None:
    from huggingface_hub import hf_hub_download
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import Xtts
    import librosa

    paths = {name: hf_hub_download(REPO, name, revision=REVISION) for name in ("config.json", "vocab.json", "model.pth")}
    _patch_tokenizer()
    config = XttsConfig()
    config.load_json(paths["config.json"])
    model = Xtts.init_from_config(config)
    model.load_checkpoint(config, checkpoint_path=paths["model.pth"], vocab_path=paths["vocab.json"], use_deepspeed=False)
    model.tokenizer.char_limits["ur"] = 150
    model.eval()

    @torch.inference_mode()
    def speak(job: dict) -> tuple:
        reference, _ = librosa.load(job["ref_audio"], sr=REFERENCE_RATE)
        clip = torch.from_numpy(reference.astype(np.float32)).unsqueeze(0)
        latent = model.get_gpt_cond_latents(clip, REFERENCE_RATE, length=config.gpt_cond_len,
                                            chunk_length=config.gpt_cond_chunk_len)
        embedding = model.get_speaker_embedding(clip, REFERENCE_RATE)
        # The fine-tune's published sampling settings.
        out = model.inference(job["text"], "ur", latent, embedding, temperature=0.1, length_penalty=0.1,
                              repetition_penalty=10.0, top_k=10, top_p=0.3)
        return np.asarray(out["wav"], dtype=np.float32), int(config.audio.output_sample_rate)

    run_jobs(speak)


if __name__ == "__main__":
    main()
