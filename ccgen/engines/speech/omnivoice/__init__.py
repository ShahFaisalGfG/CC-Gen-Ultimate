# omnivoice - OmniVoice text-to-speech inference, vendored from the omnivoice package
#
# Source: https://github.com/k2-fsa/OmniVoice, package version 0.2.1 (Apache-2.0, copyright Xiaomi
# Corp.); higgs_codec.py is ported from transformers 5 models/higgs_audio_v2_tokenizer
# (Apache-2.0, copyright The HuggingFace Team). The model weights (k2-fsa/OmniVoice) are licensed
# CC-BY-NC separately and downloaded on first use.
#
# The package itself needs transformers 5.3 or newer, while the app ships 4.57 (XTTS-v2 and the
# Qwen tokenizers depend on it), and it pulls in gradio and the training stack. Only the
# inference modules are copied here, nearly verbatim; every change is marked "CC-Gen:":
#   - model.py: imports are package-relative; the audio codec comes from higgs_codec.py; the
#     backbone's rope_theta is read from transformers 5's rope_parameters; the tokenizer's
#     special-token list is dropped (its tokens are already in tokenizer.json); the codec is
#     moved to its device without device_map (which needs accelerate).
#   - audio.py: pydub's silence detection is replaced by numpy versions of the same algorithms.
#   - higgs_codec.py: an inference-only port of the codec to transformers 4.57's base classes.
# The port reproduces transformers 5's audio codes and backbone logits exactly.
