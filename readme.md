<div align="center">

![CC-Gen-Ultimate Logo](ccgen/assets/icons/Square150x150Logo.scale-100.png)

# CC-Gen-Ultimate

**Free, open-source, fully offline subtitle and dubbing studio - transcribe, translate, transliterate, and dub any video or audio file, entirely on your machine.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D4.svg?logo=windows&logoColor=white)](#download--install)
[![Status](https://img.shields.io/badge/Status-Pre--release-orange.svg)](#roadmap)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB.svg?logo=python&logoColor=white)](pyproject.toml)

</div>

---

CC-Gen-Ultimate is a **free, open-source** desktop app that turns any video or audio file into accurate subtitles and dubbed audio - automatically, and **entirely offline**. It transcribes speech with OpenAI's Whisper, translates subtitles into another language, transliterates them into a different script (including natural, colloquial Roman Urdu - not academic transliteration), and dubs them back onto the video, cloning each original speaker's voice. Each job has its own tab, and the Workflow tab chains them: generate, translate, then dub, in one run. No account, no cloud upload, no subscription, no telemetry. Ever.

> *Your media. Your machine. Your subtitles.*

> **Status:** version 1.0.0 is the first Windows release (installers on GitHub Releases), with a [winget](#download--install) package to follow. See the [Roadmap](#roadmap) for what's next, including Linux, macOS, and Android.

---

## Table of Contents

- [CC-Gen-Ultimate](#cc-gen-ultimate)
  - [Table of Contents](#table-of-contents)
  - [Who Is This For?](#who-is-this-for)
  - [Why CC-Gen-Ultimate?](#why-cc-gen-ultimate)
  - [Features](#features)
  - [Download \& Install](#download--install)
    - [Option 1 - Windows Package Manager (Coming Soon)](#option-1---windows-package-manager-coming-soon)
    - [Option 2 - Installers](#option-2---installers)
  - [Quick Start](#quick-start)
  - [Screenshots](#screenshots)
  - [How It Works](#how-it-works)
    - [Performance Profiles](#performance-profiles)
    - [Whisper Model Sizes](#whisper-model-sizes)
    - [Supported Languages \& Scripts](#supported-languages--scripts)
    - [Translation Models](#translation-models)
    - [Transliteration Engines](#transliteration-engines)
    - [Dubbing Voices](#dubbing-voices)
  - [Privacy \& Offline Guarantees](#privacy--offline-guarantees)
  - [Settings \& Preferences](#settings--preferences)
  - [Building from Source](#building-from-source)
    - [Prerequisites](#prerequisites)
    - [Development Setup](#development-setup)
    - [Running Tests \& Checks](#running-tests--checks)
  - [Troubleshooting](#troubleshooting)
  - [Contributing](#contributing)
  - [Roadmap](#roadmap)
  - [License \& Credits](#license--credits)
  - [Support the Project](#support-the-project)

---

## Who Is This For?

CC-Gen-Ultimate is for anyone who needs subtitles without handing their media over to a cloud service:

- **Content creators & YouTubers** who need accurate captions without a subscription to a captioning SaaS
- **Journalists & researchers** transcribing interviews that can't leave their machine for confidentiality reasons
- **Language learners** who want to see foreign-language audio transcribed, translated, and romanized side by side
- **Urdu, Hindi, and Punjabi speakers** who want subtitles in their own script - or in natural Roman Urdu, not a robotic phonetic dump
- **Students & educators** captioning lecture recordings for accessibility
- **Creators reaching new audiences** who want a dubbed track that keeps each speaker's own voice
- **Anyone in a low-connectivity environment** who needs captioning tools that work with zero internet after setup

If you've ever thought *"I just need subtitles for this file, without uploading it anywhere"* - this is for you.

---

## Why CC-Gen-Ultimate?

Most auto-captioning tools are cloud services in disguise: upload your file, wait in a queue, pay per minute, and hope nothing sensitive was in the audio. CC-Gen-Ultimate runs the entire pipeline - transcription, translation, and transliteration - on your own hardware.

- 🔒 **100% offline** - no accounts, no cloud sync, no telemetry, models download once and never again
- 🎙️ **Whisper-accurate transcription** - powered by `faster-whisper`, from a 75 MB `tiny` model up to `large-v3`, including the fast `large-v3-turbo`, on CPU or NVIDIA GPU
- 🌍 **Built-in translation** - 13 target languages via fully offline neural machine translation; Automatic picks the best free model for each language pair (OPUS-MT, Hy-MT2), with NLLB-200, MADLAD-400, and Argos to choose from, plus a meaning check that keeps each line faithful to the original
- ✍️ **Real Roman Urdu, not academic transliteration** - a dedicated converter tuned for colloquial spelling ("kya haal hai", not diacritic-laden Sanskrit-style romanization)
- 🔀 **Two transliteration engines** - a fast rule-based converter and an optional neural engine for higher-quality output, your choice
- 🗣️ **Dubbing with voice cloning** - speak translated subtitles in each original speaker's voice with native pronunciation in all 13 languages, Urdu included (OmniVoice), or with XTTS-v2, natural Kokoro, or light Piper voices, added to the video as a new audio track
- 🖥️ **Tuned to your PC** - a performance profile, recommended from your GPU, memory, and processor, picks the best models a PC runs well: the largest on a strong NVIDIA GPU, lighter ones on an ordinary laptop
- ⚡ **Uses your GPU** - NVIDIA, AMD, Intel, and Apple Silicon GPUs speed up dubbing; Kokoro and Piper voices run on whichever device is fastest, OmniVoice uses a strong GPU straight away and times a smaller one against the CPU, and the CPU takes over if a GPU can't run a voice
- 🎨 **Modern, clean UI** - PySide6 + QML with System, Light, and Dark themes
- 📦 **Two install modes** - system-wide and per-user (no admin required)
- 📺 **Live progress** - watch each subtitle and its translation appear as it's produced, no black-box waiting

---

## Features

- **One tab per job** - Generate, Translate, Transliterate, and Dub each have their own queue, settings, and Start button, so one job never quietly depends on another
- **Generate** - drag in video/audio files, get word-timestamped subtitles via `faster-whisper`; runs on an NVIDIA GPU automatically when CUDA is available, otherwise on the CPU
- **Readable subtitle layout** - speech is split into cues of up to two balanced 42-character lines, breaking at sentence ends, commas, and pauses, with a comfortable minimum display time and no overlapping cues (line length and line count are configurable)
- **Translate** - translate subtitle files into any of 13 supported languages, fully offline, models auto-downloaded once; whole sentences are translated and mapped back onto the subtitle timing, and pairs without a direct model are bridged through English. The source language comes from names like `movie_en.srt`, from the tab a file was sent from, or your choice. See [Translation Models](#translation-models)
- **Transliterate** - convert subtitle files between 14 scripts, including a purpose-built Urdu ⇄ Roman Urdu converter, with a lightweight rule-based engine or a higher-quality neural engine
- **Dub** - speak a subtitle file and add the speech to its video as a new, language-tagged audio track (`movie_dub_es.mkv`), keeping the original audio, subtitles, and chapters; or save it as a separate WAV file. Every cloned line is heard back and spoken again if it came out garbled. See [Dubbing Voices](#dubbing-voices)
- **Performance profiles** - Maximum quality, Balanced, or Light, chosen for your PC on first start and changeable in Preferences, or Custom to choose every model yourself; every model picker's **Automatic** choice follows it, and picking a model yourself overrides it for that feature. See [Performance Profiles](#performance-profiles)
- **Workflow** - build a chain of steps (for example Generate, then Translate to Spanish, then Dub), add, remove, and reorder steps, and choose which earlier step each one reads; every queued file runs through every step
- **Send to another tab** - right-click a finished file to hand its results to Translate, Transliterate, or Dub, together with their language
- **Multi-file queues** - add files or entire folders (including subfolders; thousands of files load in about a second), drag-and-drop supported; files run one after another with per-file progress, errors, and notes, and Cancel keeps the rest of the queue for later. Tabs can run at the same time; their jobs take turns so they never compete for the GPU
- **Batch-friendly formats** - accepts MP4, MKV, AVI, MOV, WebM, FLV, WMV, TS, M2TS, MP3, WAV, M4A, FLAC, AAC, OGG, WMA, and subtitle files (SRT, VTT, LRC, ASS, SSA, SBV)
- **Standard subtitle output** - SRT, WebVTT, ASS, SBV (YouTube), and LRC, saved next to each source file or in a folder you choose
- **Live results** - each line, its translation, and its transliteration appear in the Results view as they're produced
- **Global Settings** - persisted defaults for every tab, so new jobs and new workflow steps start exactly how you like them
- **Detailed logging** - warnings-only or full activity logs saved locally, openable and clearable from Preferences
- **Live theme switching** - System / Light / Dark, following Windows changes while the app is open
- **Keyboard friendly** - every action has a shortcut or is reachable with Tab, with visible focus and tooltips on every control

---

## Download & Install

### Option 1 - Windows Package Manager (Coming Soon)

```powershell
winget install gfgRoyal.CCGenUltimate
```

*(Package submission follows the initial GitHub release - see [Roadmap](#roadmap).)*

### Option 2 - Installers

Once published, installers will be available on the [Releases](https://github.com/ShahFaisalGfG/CC-Gen-Ultimate/releases) page:

| Package | Admin Required | Best For |
| --- | :---: | --- |
| `CC-Gen-Ultimate_<version>_system_installer.exe` | ✅ | Shared / corporate machines |
| `CC-Gen-Ultimate_<version>_user_installer.exe` | ❌ | Personal machines - recommended |

Each installer comes in three editions, which differ only in the GPUs that speech recognition and voice cloning can use:

| Edition | File names | GPUs for speech recognition and voice cloning |
|---|---|---|
| Standard | `..._installer.exe` | NVIDIA GeForce GTX 10 series up to RTX 50 |
| Legacy NVIDIA | `..._nvidia_legacy_..._installer.exe` | Older NVIDIA GPUs such as the GTX 750 and 900 series and the GeForce 940MX, up to RTX 40 |
| Intel GPU | `..._intel_gpu_..._installer.exe` | Intel Arc and Core Ultra graphics |

Every edition runs Piper and Kokoro voices on any DirectX 12 GPU (NVIDIA, AMD, or Intel), and everything falls back to the CPU when no GPU is available. If your NVIDIA GPU is outside an edition's range, **Preferences > Performance** says which edition can use it.

Models (`faster-whisper`, translation models, transliteration models, and dubbing voices) download automatically on first use and are cached locally - no repeated downloads, no internet required afterward. **Models** in the title bar lists them all, with download and remove buttons.

---

## Quick Start

1. **Generate** - on the **Generate** tab, drag & drop videos or folders (or use **Add files** / **Add folder**), check the model and language, and click **Start** (or press **Ctrl+Enter**). Subtitles stream into **Results**
2. **Translate** - right-click a finished file and choose **Send the result to > Translate tab**, pick the target language, and click **Start**
3. **Dub** - send the translation to the **Dub** tab; it pairs with its video automatically. Pick the voices (voice cloning is the default) and click **Start**
4. **Or do it all at once** - on the **Workflow** tab, keep the starter steps (Generate, then Translate), add a **Dub** step, queue your videos, and click **Start**

Output files are written next to the input (or to the folder chosen under **Output > Save to**), named by what they contain: `video.srt` (original), `video_ur.srt` (translated to Urdu), `video_tr_ur_roman.srt` (transliterated Urdu → Roman), `video_dub_ur.mkv` (dubbed in Urdu). When the run ends, **Open output folder** takes you straight to them.

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| **Ctrl+O** / **Ctrl+Shift+O** | Add files / add a folder |
| **Ctrl+Enter** or **F5** | Start processing the queue |
| **Esc** | Cancel (the remaining files stay queued) |
| **Ctrl+1** to **Ctrl+5** | Generate / Translate / Transliterate / Dub / Workflow tab |
| **Ctrl+,** / **Ctrl+M** / **F1** | Preferences / Manage Models / About |
| **Up/Down**, **Shift+Up/Down**, **Space**, **Ctrl+A**, **Delete** | Move, extend, toggle, select all, and remove files in the queue |
| **Menu key** or **Shift+F10** | Context menu for the current file |

---

## Screenshots

> 📸 Screenshots will be added here closer to the Windows release.

---

## How It Works

Every tab runs one task; the Workflow tab runs several in the order you set, passing text from step to step in memory:

```
Generate       video/audio ─► decode (PyAV) ─► transcribe (faster-whisper) ─► readable cues ─► video.srt
Translate      subtitles ─► translate whole sentences (best model for the pair + meaning check) ─► video_<lang>.srt
Transliterate  subtitles ─► convert script (rule or neural engine) ─► video_tr_<source>_<target>.srt
Dub            subtitles + video ─► find speakers ─► speak each sentence at its time, hear it back ─► video_dub_<lang>.mkv
```

### Performance Profiles

Every model picker offers **Automatic**, which follows the performance profile under **Preferences > Performance**. The first time the app starts on a PC it measures the GPU, memory, and processor, chooses a profile, and says so; it measures again on every start and follows hardware changes unless you picked a profile yourself.

| Profile | Recommended for | Subtitles | Translation | Transliteration | Dubbing |
|---|---|---|---|---|---|
| **Maximum quality** | NVIDIA GPU with 8 GB or more | Whisper large-v3 | Best free model for each pair | Neural where available | OmniVoice, full quality |
| **Balanced** | GPU with 4-8 GB, or 8+ CPU cores and 16 GB RAM | Whisper large-v3-turbo | Best free model for each pair | Neural where available | OmniVoice, fast mode |
| **Light** | Any other PC | Whisper small | Best free model for each pair | Rule-based | OmniVoice, fast mode |

Choosing a specific model on any tab or in Preferences overrides the profile for that feature only, and the Performance page marks it as chosen by hand. The **Custom** profile puts every choice on the Performance page: the model for subtitle generation, translation, transliteration, and dubbing, and the **Voice cloning quality** (full quality or fast mode). Its Automatic choices follow the profile recommended for this PC, and it is kept when the hardware changes. **Use Automatic for every model** hands every choice back to the profile. The choices come from the quality benchmark in [`scripts/eval`](scripts/eval/README.md), which scores each model on professional reference translations (FLORES-200) and on native speakers (FLEURS) in every supported language.

### Whisper Model Sizes

| Model | Size | Speed (CPU) | Quality |
|-------|------|-------------|---------|
| tiny | 75 MB | Fastest | Basic |
| base | 145 MB | Fast | Good for clear speech |
| small | 466 MB | Moderate | Good - Automatic on the Light profile |
| medium | 1.5 GB | Slow | High |
| large-v3-turbo | 1.6 GB | Moderate | Near-best - Automatic on the Balanced profile |
| large-v3 | 3.0 GB | Very slow | Best - Automatic on the Maximum quality profile |

### Supported Languages & Scripts

| Stage | Options |
|---|---|
| **Transcription** | Auto-detect, Arabic, Chinese, English, French, German, Hindi, Japanese, Korean, Portuguese, Russian, Spanish, Turkish, Urdu |
| **Translation targets** | Arabic, Chinese, English, French, German, Hindi, Japanese, Korean, Portuguese, Russian, Spanish, Turkish, Urdu |
| **Dubbing** | Arabic, Chinese, English, French, German, Hindi, Japanese, Korean, Portuguese, Russian, Spanish, Turkish, Urdu (see [Dubbing Voices](#dubbing-voices) for which voices speak each) |
| **Transliteration scripts** | Roman/Latin, Urdu (Nastaliq), Hindi (Devanagari), Bengali, Gujarati, Punjabi (Gurmukhi), Tamil, Telugu, Kannada, Malayalam, Odia, Sinhala, Thai, Burmese |

### Translation Models

Choose the model under **Preferences > Translation** (or per session on the Translate tab). Every model is free and runs offline on CTranslate2 - 8-bit on the CPU, or on an NVIDIA GPU when one works.

| Model | Quality | Speed (CPU) | Download | Licence |
|---|---|---|---|---|
| **Automatic** *(default, recommended)* | The best free model for each language pair: OPUS-MT, with Hy-MT2 into Japanese, Korean, and Chinese and from Japanese and Korean | As below | As below | Free for any use |
| **OPUS-MT** | Accurate; keeps names and technical terms such as GitHub | Fast (about half a second per sentence) | 300-900 MB per direction, stored at a quarter of that | Apache-2.0 / CC-BY-4.0 |
| **NLLB-200 1.3B** | Equally faithful, strongest from Urdu into English; every pair directly | About 2x slower | 1.3 GB once | CC-BY-NC-4.0 (non-commercial use; asks once for your agreement) |
| **Hy-MT2 1.8B** | Most accurate into Japanese, Korean, and Chinese and from Japanese and Korean; keeps names and technical terms; every pair directly | A few seconds per sentence | 1.1 GB once | Apache-2.0 |
| **MADLAD-400 3B** | Good; every pair directly | Slow without an NVIDIA GPU (several seconds per sentence) | 2.8 GB once | Apache-2.0 |
| **Argos Translate (light)** | Rougher; can mistranslate terms | Fast | About 100 MB per direction | MIT / CC-BY |

- **Through English** - OPUS-MT and Argos have one model per direction to or from English; other pairs (for example Urdu to French) are translated through English. OPUS-MT has no Japanese, Korean, or Chinese target and no usable Korean model, and translates Japanese less accurately, so Automatic uses Hy-MT2 there. From Chinese, OPUS-MT kept the meaning better.
- **For dubbing** - when a workflow dubs a translation, the meaning check also prefers, among nearly equally faithful candidates, the one that takes about as long to say as the original line, so the dub needs less speeding up.
- **Meaning check** - always on. The last step produces several candidate translations, and a small multilingual model (120 MB) keeps the one whose meaning stays closest to the original sentence, preferring candidates that keep names and technical terms. Lines that may still drift are listed in a note on the file so you can review them. It catches invented or dropped content; a single mistranslated word inside an otherwise faithful sentence is up to the model itself.

### Transliteration Engines

Urdu's Arabic-derived script doesn't romanize the way a purely academic transliteration scheme assumes - "کیا حال ہے پیارے؟" should read as **"kya haal hai piyare?"**, not a string of diacritics. CC-Gen-Ultimate ships two engines so you can pick the right trade-off:

| Engine | Speed | Download | Best For |
|---|:---:|---|---|
| **Automatic** *(default)* | Follows the profile | As below | Neural where a model exists, except on the Light profile |
| **Rule-based** | Fast | None - built in | Offline-first use, older PCs, instant results |
| **Neural** | Slower | ~50 MB - 2 GB on first use, per direction | Higher-quality, more natural output |

> **Note:** the neural engine's Hindi→Urdu model is distributed under an unclear license (its upstream repository ships an empty `LICENSE` file). It's included because it's currently the only option for that direction, but if you have licensing concerns, stick to the rule-based engine - it's fully open-source (0BSD) and available offline by default.

### Dubbing Voices

The Dub tab (and Dub workflow steps) offers these voices:

| Voices | Sounds like | Speed | Download | Languages |
|---|---|---|---|---|
| **Automatic** *(default)* | Each original speaker, through OmniVoice | Follows the profile | As below | All |
| **Voice cloning (OmniVoice)** | Each original speaker, with native pronunciation | Best with an NVIDIA GPU; on a CPU, several minutes per minute of speech in fast mode | 3.7 GB once | All, including Urdu |
| **Voice cloning (XTTS-v2)** | Each original speaker | Slow without a GPU | 1.9 GB once | All except Urdu |
| **Natural voices (Kokoro)** | Natural stock voices | Fast on any computer | 350 MB once | English, Spanish, French, Hindi, Portuguese |
| **Light voices (Piper)** | Clear but more synthetic stock voices | Fast | About 60 MB per voice | All except Japanese and Chinese, including Urdu |

Japanese and Chinese are dubbed with voice cloning only: their stock voices need pronunciation dictionaries the app doesn't include, and without them they can't read kanji or hanzi.

- **Speakers** - voice cloning listens to the original audio, tells the speakers apart, and gives each one their own cloned voice. Choose **One voice for everyone** to skip that.
- **Timing** - speech is spoken a sentence at a time, so a sentence split over several subtitles is said once, with natural intonation, in the time of all of them. Each sentence starts exactly when its first subtitle does. A sentence that doesn't fit before the next one is spoken faster, up to the **Fastest speech** limit (1.35x by default); if it is still too long, it may run up to a second into the next sentence's time, which then starts a little later. Only beyond that, or past the end of the video, is it cut short, with a note on the file. OmniVoice knows how long a line will take before speaking it, so it speaks the line at the right speed in one pass; XTTS-v2 reuses the work already done for a line, so speeding it up costs a fraction of speaking it again.
- **Devices** - with **Run on: Automatic**, Kokoro and Piper voices time a short sample on each GPU and the CPU and use the fastest (small voices often run faster on the CPU than on integrated graphics). The choice is kept until the app closes, so later jobs start sooner. A strong NVIDIA GPU (GTX 16 series or newer with 8 GB or more) runs OmniVoice straight away; any other GPU is timed against the CPU on a short line, and the faster one is kept. On a GPU with too little memory for the whole model, only the part that does most of the work moves to the GPU. XTTS-v2 uses the first GPU that loads it. Speech recognition and translation time an older NVIDIA GPU that can only run them at full precision against the CPU in the same way. A GPU that fails on a line hands the rest of the job to the CPU.
- **Fast mode** - OmniVoice refines each line in 32 steps on the Maximum quality profile and in 8 on the others, unless the Custom profile sets the voice cloning quality. The benchmark measured the same intelligibility and speaker similarity in Urdu at a quarter of the time.
- **Line check** - cloned voices are sampled, so now and then a line comes out garbled or keeps talking past its text. Every cloned line is transcribed back with Whisper; one that doesn't match its text is spoken again (up to twice) and the best take is kept. Lines still unclear afterwards are listed in a note on the file.
- **Fallback** - if the chosen voices can't speak a language (XTTS-v2 has no Urdu, for example), the first stock voice that can is used and the file shows a note saying so.
- **Result** - the dub is added as a new audio track in a copy of the video (`movie_dub_es.mkv`), tagged with its language and kept beside the original track; turn on **Play the dub by default** to make players start with it. A subtitle file on its own becomes a WAV file.
- **Licence** - OmniVoice's model is released under a Creative Commons Attribution-NonCommercial licence and XTTS-v2 under the [Coqui Public Model License](https://coqui.ai/cpml); both allow non-commercial use of the model and the audio it creates. The app asks you to accept each one once before its first use. Kokoro and Piper voices don't have this limit. Only clone voices you have permission to use.

---

## Privacy & Offline Guarantees

- ❌ No telemetry or usage reporting
- ❌ No cloud sync, no file uploads
- ❌ No accounts or registration required
- ❌ No third-party analytics or tracking
- ✅ All processing - transcription, translation, transliteration, dubbing - runs on your own CPU or GPU
- ✅ Models are downloaded once, from their original open-source hosts, and cached locally forever after

CC-Gen-Ultimate's UI talks to a small local backend embedded in the same app process, bound only to `127.0.0.1` - nothing ever leaves your machine.

---

## Settings & Preferences

| Section | Contents |
|---|---|
| **Performance** | This PC's hardware (with **Detect again**), the performance profile, what each feature uses on it (or, on Custom, a picker for each model and the voice cloning quality), and **Use Automatic for every model** |
| **Appearance** | Theme: System / Light / Dark |
| **Transcription** | Default model and spoken language, compute device (Automatic / CPU / NVIDIA GPU), skip silence and music (voice activity filter) |
| **Translation** | Translation model, default source language (or detect from each file), and target language |
| **Transliteration** | Default source/target script and engine (rule/neural) |
| **Dubbing** | Default voices, speakers, fastest speech, how the dub is saved, whether it plays by default, and the device it runs on |
| **Subtitles** | Default formats, characters per line, lines per subtitle, default save folder |
| **Advanced** | Logging on/off, log detail (warnings and errors / everything), open or clear the log files |

All settings persist to `%APPDATA%\CC-Gen-Ultimate\settings.json` and apply to every tab and new workflow step automatically; changes you make on a tab stay in place for that session. Logs are written to `%APPDATA%\CC-Gen-Ultimate\logs`. Piper and Kokoro voices are stored in `%LOCALAPPDATA%\CC-Gen-Ultimate\voices` and translation models in `%LOCALAPPDATA%\CC-Gen-Ultimate\translation`; the other models live in the Hugging Face and Argos caches in your user folder.

---

## Building from Source

### Prerequisites

- Python 3.12+
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) and Visual Studio Build Tools (for the Explorer context-menu DLL) - only needed to build installers
### Development Setup

```powershell
# 1. Clone the repository
git clone https://github.com/ShahFaisalGfG/CC-Gen-Ultimate.git
cd CC-Gen-Ultimate

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the GUI
python app.py

# ...or run one task without the UI
python main.py generate path\to\video.mp4 --formats srt,vtt   # --model small|large-v3-turbo|..., --profile light|balanced|quality
python main.py translate path\to\video_en.srt --target-lang ur   # --engine nllb|madlad|argos
python main.py dub path\to\video.mp4 --subtitle path\to\video_ur.srt   # --mode omnivoice|xtts|kokoro|piper, --quality full|fast
python main.py workflow path\to\video.mp4 steps.json   # e.g. [{"kind": "generate"}, {"kind": "translate", "input": "step:0", "target_lang": "ur"}]
python main.py --help   # every task and its options
```

### Running Tests & Checks

```powershell
pytest tests/ -v
pyright ccgen/ app.py main.py server.py
cd ccgen/qml; pyside6-qmllint -I . -I components main.qml PreferencesWindow.qml ManageModelsWindow.qml components/*.qml pages/*.qml
```

### Building Installers

```powershell
pip install "pyinstaller>=6.17"
.\scripts\build.ps1                  # both installers and the portable exe (standard NVIDIA edition)
.\scripts\build.ps1 -LegacyNvidia    # the same, plus the Legacy NVIDIA edition of each
.\scripts\build.ps1 -Gpu xpu         # the Intel GPU edition (-Gpu legacy builds only the Legacy one)
.\scripts\build_user_installer.ps1   # or just one of them (also takes -Gpu and -LegacyNvidia)
```

Each build first installs the PyTorch build for its GPU edition and the DirectML build of ONNX Runtime into the active environment (see `Install-GpuRuntime` in `scripts/bundle.ps1`): PyTorch 2.8.0 for CUDA 12.8 in the standard edition, 2.8.0 for Intel XPU in the Intel GPU edition, and 2.7.1 for CUDA 12.6 in the Legacy NVIDIA edition, the newest PyTorch that still runs Maxwell GPUs. With `-LegacyNvidia`, the Legacy edition is built first, so the environment ends on the other edition's PyTorch.

The PyInstaller options live in `scripts/bundle.ps1`, shared by every build script and the release workflow. After bundling, each build runs the app with `--self-test`, which imports every engine, loads the native libraries, decodes a short audio clip, loads the dubbing voices' pronunciation data and dictionaries, starts the local API, and compiles every QML screen. It also lists the GPUs each runtime can use. A module or DLL missing from the bundle stops the build with a report instead of reaching users. You can run the same check on any build yourself: `CC-Gen-Ultimate.exe --self-test report.txt`.

Every icon size and `CCGenUltimate.ico` are drawn by `scripts/make_icons.py`; after changing it, run `python scripts/make_icons.py` to regenerate them.
---

## Troubleshooting

| Issue | Solution |
|---|---|
| First run is slow | The selected Whisper/translation/transliteration model is downloading - this only happens once per model |
| Translation/transliteration fails with a language-pair error | Not every language pair has a pre-trained offline model; try translating to/from English as an intermediate step, or pick Hy-MT2, NLLB-200, or MADLAD-400, which translate every pair directly |
| "may not say the same as the original" | The meaning check found lines whose translation drifted; review those subtitles, or try another model under **Preferences > Translation** |
| GUI window doesn't appear | Check the log output for "Embedded API server failed to start" - another process may be holding the local port |
| Slow transcription on CPU | Use a smaller model (`base`/`small`), or `large-v3-turbo` on an NVIDIA GPU, or the Light profile under **Preferences > Performance** |
| Dubbing takes a long time | Voice cloning is heavy on a CPU; OmniVoice's fast mode (Light and Balanced profiles) takes a quarter of the full-quality time, and Kokoro or Piper voices run faster than real time |
| GPU isn't used | Install the CUDA 12 and cuDNN 9 runtime libraries; with **Run on: Automatic** the app falls back to the CPU when they're missing (the status line shows "Model ready (CPU)"). An older NVIDIA GPU may also be slower than the CPU, which Automatic measures and avoids |
| "needs the Legacy NVIDIA edition" | Your NVIDIA GPU is older than this edition supports (for example a GeForce 940MX or GTX 900 series card); install the Legacy NVIDIA edition to use it |
| Cancel takes a few seconds | Transcription stops at the end of the current 30-second audio window; the status shows "Cancelling..." until then |
| A file shows "Failed" | Hover it to read the error; failed files run again on the next Start |
| "has no audio track" | The video has no sound stream (for example a screen recording made with audio off); there is nothing to caption or clone |
| Dubbing with voice cloning is slow | XTTS-v2 needs a GPU to be quick; on a CPU expect several times the video's length. Kokoro and Piper voices are much faster |
| Dub tab says to accept the XTTS-v2 licence | Click **Review licence** under **Voices** and accept it, or choose Kokoro or Piper voices |
| "line(s) were too long for their time" | Those lines ran more than a second past their time even at the fastest speech, so they were cut short. Raise **Fastest speech**, or shorten the subtitle text |
| "No subtitle found" on the Dub tab | Add the subtitle with its video (`movie.mp4` + `movie_es.srt` pair up), or right-click the video and choose **Choose subtitle to speak...** |
| "has no language in its name" | Pick the subtitle's language in the tab's settings instead of the automatic choice, or rename the file with a language suffix such as `movie_en.srt` |
| "Nothing was written in ..., so the text is unchanged" | The subtitles are in a different script from the one chosen under **Scripts**; pick the script they are written in |
| Dubbing doesn't use the GPU | The self-test (`CC-Gen-Ultimate.exe --self-test report.txt`) lists the devices found. Use the Intel GPU edition for Intel Arc or Core Ultra graphics |

Still stuck? [Open an issue](https://github.com/ShahFaisalGfG/CC-Gen-Ultimate/issues) with your log output and CC-Gen-Ultimate version - I'll get back to you.

---

## Contributing

Contributions of all kinds are welcome - bug reports, fixes, new features, translations, or just improving a sentence in the docs.

1. **Fork** the repository and clone your fork
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes and ensure:
   - `pytest` passes
   - `pyright` passes on all edited Python files
   - `qmllint` passes on all edited `.qml` files
4. Commit with a clear message and open a **Pull Request** targeting the `development` branch

For significant changes, please [open an issue](https://github.com/ShahFaisalGfG/CC-Gen-Ultimate/issues) first to discuss the approach.

---

## Roadmap

| Target | Plan |
|---|---|
| **v1.0.0** | Initial Windows release - system & user Inno Setup installers on GitHub Releases |
| **Shortly after** | `winget` package submission |
| **Later** | Linux packages (Flatpak / AppImage) |
| **Later** | macOS package (`.dmg` / Homebrew) |
| **Later** | Android release |

Have a feature idea or a use case not covered above? [Start a discussion](https://github.com/ShahFaisalGfG/CC-Gen-Ultimate/discussions).

---

## License & Credits

The source code is released under the [MIT License](LICENSE) - free to use, modify, and distribute. The installers bundle GPL-3.0 dubbing components (Piper and eSpeak NG), so the distributed app is conveyed under GPL-3.0-or-later terms; see [Third-Party Notices](THIRD_PARTY_NOTICES.md) for every bundled library and downloaded model and its licence.

Built with faster-whisper, CTranslate2, OPUS-MT (University of Helsinki), Hy-MT2 (Tencent) on llama.cpp, NLLB-200, MADLAD-400, sentence-transformers' multilingual MiniLM, argostranslate, indic-transliteration, the transformers/PyTorch ecosystem, OmniVoice (k2-fsa), Coqui XTTS-v2, Kokoro, and Piper. OmniVoice's audio codec is built with Higgs Materials licensed from Boson AI USA, Inc. and Meta Llama 3 (see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)).

Built with ❤️ by **Shah Faisal** · [Portfolio](https://shahfaisalgfg.github.io/shahfaisal/) · [shahfaisalgfg@outlook.com](mailto:shahfaisalgfg@outlook.com)

---

## Support the Project

CC-Gen-Ultimate is free and will always stay free. If it's saved you time or helped you caption something that mattered, here are a few ways to give back:

- ⭐ **Star the repo** - it takes two seconds and helps others find the project
- 🐛 **Report a bug** - honest feedback makes the tool better for everyone
- 💡 **Suggest a feature** - if you need it, chances are someone else does too
- 🔁 **Share it** - tell a friend, post it in a forum, or mention it in a blog post
- 🛠️ **Contribute code** - PRs are always welcome; see [Contributing](#contributing)

**[★ Star CC-Gen-Ultimate on GitHub](https://github.com/ShahFaisalGfG/CC-Gen-Ultimate)**

---

*Your media. Your machine. Your subtitles.* 🎬
