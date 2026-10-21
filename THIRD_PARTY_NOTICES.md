# Third-Party Notices

CC-Gen-Ultimate's own source code is released under the [MIT License](LICENSE). The installers and
the portable app bundle the open-source libraries below, and download models on first use.

## Licence of the distributed app

The dubbing feature bundles **piper-tts**, **phonemizer**, and the **eSpeak NG** library, which are
licensed under the GNU General Public License v3.0 or later. Because they are distributed inside the
same app, the installers and portable app as a whole are conveyed under the terms of the
**GPL-3.0-or-later**. CC-Gen-Ultimate's source stays available under MIT, which is compatible with
the GPL, and the complete source for every bundled component is available from the projects listed
below.

## Bundled libraries

| Component | Licence | Used for |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | Speech recognition |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT | Whisper and translation inference |
| [llama-cpp-python](https://github.com/abetlen/llama-cpp-python) and [llama.cpp](https://github.com/ggml-org/llama.cpp) | MIT | Hy-MT2 translation |
| [Argos Translate](https://github.com/argosopentech/argos-translate) | MIT | Translation |
| [Transformers](https://github.com/huggingface/transformers) | Apache-2.0 | Neural transliteration, OmniVoice voice cloning, speaker detection |
| [Hugging Face Hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 | Model downloads |
| [PyTorch](https://github.com/pytorch/pytorch) | BSD-3-Clause | Neural transliteration, voice cloning |
| [torchaudio](https://github.com/pytorch/audio) | BSD-2-Clause | Voice cloning audio processing |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) (CPU and DirectML builds) | MIT | Piper and Kokoro voices, voice activity detection |
| [OmniVoice](https://github.com/k2-fsa/OmniVoice) inference code (Xiaomi Corp.), version 0.2.1, adapted in `ccgen/engines/speech/omnivoice` | Apache-2.0 | OmniVoice voice cloning |
| Higgs Audio V2 tokenizer model code (Boson AI and The HuggingFace Team), ported from Transformers in `ccgen/engines/speech/omnivoice/higgs_codec.py` | Apache-2.0 | OmniVoice's audio codec |
| [coqui-tts](https://github.com/idiap/coqui-ai-TTS) | MPL-2.0 | XTTS-v2 voice cloning |
| [piper-tts](https://github.com/OHF-Voice/piper1-gpl) | GPL-3.0-or-later | Piper voices |
| [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | MIT | Kokoro voices |
| [phonemizer](https://github.com/bootphon/phonemizer) | GPL-3.0-or-later | Kokoro pronunciation |
| [eSpeak NG](https://github.com/espeak-ng/espeak-ng) (via piper-tts and espeakng-loader) | GPL-3.0-or-later | Pronunciation for Piper and Kokoro |
| [cutlet](https://github.com/polm/cutlet), [fugashi](https://github.com/polm/fugashi), [unidic-lite](https://github.com/polm/unidic-lite) | MIT; fugashi MIT and BSD-3-Clause | Japanese text for voice cloning |
| [pypinyin](https://github.com/mozillazg/python-pinyin), [spacy-pkuseg](https://github.com/explosion/spacy-pkuseg) | MIT | Chinese text for voice cloning |
| [ko-speech-tools](https://github.com/eginhard/ko-speech-tools), [mecab-ko](https://github.com/NoUnique/pymecab-ko) | Apache-2.0; BSD | Korean text for voice cloning |
| [num2words](https://github.com/savoirfairelinux/num2words) | LGPL | Spelling out numbers for voice cloning |
| [PyAV](https://github.com/PyAV-Org/PyAV) and its FFmpeg libraries | BSD-3-Clause (FFmpeg: LGPL-2.1-or-later) | Audio decoding, adding the dub track |
| [indic-transliteration](https://github.com/indic-transliteration/indic_transliteration_py) | MIT | Rule-based transliteration |
| [PySide6 / Qt](https://www.qt.io/qt-for-python) | LGPL-3.0 | User interface |
| [FastAPI](https://github.com/fastapi/fastapi), [Uvicorn](https://github.com/encode/uvicorn) | MIT; BSD-3-Clause | Embedded local API |
| [spaCy](https://github.com/explosion/spaCy) | MIT | Required by Argos Translate |
| [psutil](https://github.com/giampaolo/psutil) | BSD-3-Clause | Measuring memory and processor cores for the performance profile |
| [NumPy](https://github.com/numpy/numpy) | BSD-3-Clause and others | Audio and math |

## Models downloaded on first use

Models are not bundled. Each downloads from its original host when first needed (or from
**Manage Models**) and keeps its own licence:

| Model | Licence |
|---|---|
| Whisper (Systran faster-whisper conversions) | MIT |
| [OPUS-MT](https://huggingface.co/Helsinki-NLP) translation models (Language Technology Research Group, University of Helsinki) | Apache-2.0 or CC-BY-4.0, per model; converted to CTranslate2 on your computer after download |
| [NLLB-200 distilled 1.3B](https://huggingface.co/OpenNMT/nllb-200-distilled-1.3B-ct2-int8) (Meta) | [CC-BY-NC-4.0](https://creativecommons.org/licenses/by-nc/4.0/): non-commercial use only. The app asks you to accept it before the first download. |
| [MADLAD-400 3B](https://huggingface.co/santhosh/madlad400-3b-ct2) (Google) | Apache-2.0 |
| [Hy-MT2 1.8B](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF) (Tencent) | Apache-2.0 |
| [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2) (meaning check) | Apache-2.0 |
| Argos Translate language packages | Listed in each package's metadata |
| M2M100 Urdu ↔ Roman Urdu fine-tunes (Mavkif) | Apache-2.0 |
| Rekhta Hindi → Urdu transliteration | Unclear: its repository ships an empty licence file |
| [OmniVoice](https://huggingface.co/k2-fsa/OmniVoice) (k2-fsa) | Creative Commons Attribution-NonCommercial (CC-BY-NC), because of its training data: non-commercial use of the model and the audio it creates. The app asks you to accept it before the first download. |
| OmniVoice's audio codec (Higgs Audio V2 tokenizer, Boson AI; downloaded with OmniVoice) | Boson Higgs Audio 2 Community License, based on the Meta Llama 3 Community License; its full text downloads with the model (`audio_tokenizer/LICENSE`). See the attribution below. |
| [WavLM Base Plus SV](https://huggingface.co/microsoft/wavlm-base-plus-sv) (Microsoft; tells speakers apart for OmniVoice) | [CC-BY-SA-3.0](https://github.com/microsoft/UniSpeech/blob/main/LICENSE) |
| [XTTS-v2](https://huggingface.co/coqui/XTTS-v2) | [Coqui Public Model License](https://coqui.ai/cpml): non-commercial use of the model and the audio it creates. The app asks you to accept it before the first download. |
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) | Apache-2.0 |
| [Piper voices](https://huggingface.co/rhasspy/piper-voices) | Each voice's own licence, stated in its `MODEL_CARD` |

### Attribution for OmniVoice's audio codec

OmniVoice voice cloning is built with Higgs Materials licensed from Boson AI USA, Inc., Copyright
Boson AI USA, Inc., All Rights Reserved, and Meta Llama 3 licensed under the Meta Llama 3
Community License, Copyright Meta Platforms, Inc., All Rights Reserved.

- Meta Llama 3 is licensed under the Meta Llama 3 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved.
- Boson Higgs Audio 2 is licensed under the Boson Community License, Copyright © Boson AI USA, Inc. All Rights Reserved.

Use of the codec must follow the [Llama 3 Acceptable Use Policy](https://llama.meta.com/llama3/use-policy).
The licence asks products with more than 100,000 annual active users to request an expanded licence
from Boson AI.
