# Quality benchmark

Developer tools that measure translation and dubbing quality for every language CC-Gen-Ultimate supports. They are not part of the app or its installers. Model choices (which translation model serves each direction, which voice engine dubs each language) are made from these numbers.

Test data and results are downloaded to `%LOCALAPPDATA%\CC-Gen-Ultimate\eval` and never committed:

- **FLORES-200** devtest (CC-BY-SA-4.0): the same sentences professionally translated into all 13 languages.
- **FLEURS** test (CC-BY-4.0): native speakers reading those sentences. They are the known-good speech every dub is compared with, and the voices the cloning engines imitate.

Run everything from the project root with the project's virtual environment.

## Translation

```bash
python scripts/eval/translation_bench.py --engines opus_mt,hymt2,nllb,madlad --count 40
```

Scores each engine on every direction to and from English plus six pairs that need a pivot: chrF against the reference (identical to sacreBLEU's chrF), the app's meaning score, the output/reference length ratio, and seconds per sentence. Results are cached per engine and direction; `--rerun` ignores the cache and `--directions en-ur,ja-en` limits the run.

The engines are the app's own (`opus_mt`, `hymt2`, `nllb`, `madlad`, `argos`), plus the candidate `opus_mt_next` from `candidates.py`: OPUS-MT with newer Helsinki-NLP models for the directions in `NEXT_LEGS`.

## Subtitle generation

```bash
python scripts/eval/asr_bench.py --models small,large-v3-turbo,large-v3 --count 10
```

Runs the app's own Whisper engine (CPU, int8) on native FLEURS recordings in every language and reports the mean CER and the real-time factor (seconds of work per second of audio), which set each performance profile's Whisper model.

## Speech

First check that the metrics can tell native speech from a dub listeners rejected:

```bash
python scripts/eval/calibrate.py --bad-media "1. Intro_dub_hi.mkv" --bad-track 1 --bad-subtitles "1. Intro_hi.srt" --bad-language hi --original "1. Intro.mp4" --native ur,en
```

Then score the voices:

```bash
python scripts/eval/speech_bench.py --engines native,xtts,kokoro,piper --languages ur,hi --count 12
```

The app's own OmniVoice engine (`ccgen/engines/speech/omnivoice`) is the same model as the `omnivoice` worker, adapted to the app's transformers; the adaptation reproduces the original's audio codes and model outputs exactly.

Per clip: character error rate from Whisper large-v3-turbo, extra speech beyond the text (babble), seconds per character, and WavLM speaker similarity to the cloned voice. Per engine and language: mean CER, the share of failed lines (CER above 0.5), the share of babbling lines, and the speaking rate against native speakers. Each FLEURS speaker is cloned to read the next recording's sentence, so every engine reads the same text in the same voices. The whole recording is the reference, so its transcript matches what is heard.

The app's own engines run in the project environment: `xtts`, `kokoro`, `piper`, and `omnivoice_app`, which is the shipped OmniVoice in the fast mode of the Balanced and Light profiles and builds its voice prompt as a dub does.

Candidate engines run through `workers/` in their own environments, chosen with an environment variable:

| Engine | Worker | Environment |
|---|---|---|
| `omnivoice`, `omnivoice16`, `omnivoice8` | `omnivoice_worker.py` | `EVAL_OMNIVOICE_PYTHON`: a separate venv with `torch==2.8.0`, `torchaudio==2.8.0` (CPU index) and `omnivoice==0.2.1`. The variants run 32, 16, and 8 denoising steps |
| `omnivoice8_onnx`, `omnivoice16_onnx` | `omnivoice_worker.py` | As above plus `onnxruntime`; the transformer runs as the INT8 graph from `gaber/OmniVoice-ONNX-CPU-INT8` |
| `qwen3tts` | `qwen3tts_worker.py` | The project environment with `qwen-tts==0.1.1`, `einops`, and `sox` installed with `--no-deps --target` and added to `PYTHONPATH` |
| `xtts_urdu` | `xtts_urdu_worker.py` | The project environment |

## Report

```bash
python scripts/eval/report.py
```

Writes `results\report.md` in the benchmark folder with the calibration verdicts and the translation, Whisper, and speech tables. Synthesized clips stay next to their results for listening.
