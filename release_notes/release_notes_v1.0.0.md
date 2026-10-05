# CC-Gen-Ultimate 1.0.0

The first Windows release of CC-Gen-Ultimate: a free, fully offline subtitle and dubbing studio. Drop in video, audio, or subtitle files and get subtitles, translations, transliterations, and dubbed audio without uploading anything.

## Highlights

- **Dubbing with voice cloning.** The new Dub tab speaks subtitles and adds the speech to the video as a new audio track, keeping the original. XTTS-v2 clones each original speaker's voice (it tells the speakers apart on its own); Kokoro and Piper offer fast stock voices. Urdu can be dubbed with cloned voices too: XTTS-v2 reads Urdu lines in Hindi script, or Piper's Urdu voices can be used instead. Lines start exactly on their subtitle's time and are sped up a little when they would overrun.
- **A tab for every job.** Generate, Translate, Transliterate, and Dub each have their own queue, settings, and Start button, so no step quietly depends on another. Finished results can be sent to another tab with their language.
- **Workflows.** The Workflow tab chains steps you choose, for example Generate, Translate to Spanish, then Dub, and runs every queued file through all of them. Steps can be added, removed, and reordered, and each one says which text it uses.
- **Readable subtitles out of the box.** Speech is split into proper subtitle cues using word timings: two balanced lines of up to 42 characters, breaks at sentence ends, commas, and pauses, a comfortable minimum display time, and no overlapping cues. Long sentences are split evenly instead of leaving a one-word cue behind.
- **More accurate transcription.** Long recordings no longer drift into repeated or invented text, silent stretches are skipped safely, and language detection listens to more than the first 30 seconds so music intros don't fool it.
- **New `large-v3-turbo` model.** Close to `large-v3` accuracy at a fraction of the time.
- **Better translations.** OPUS-MT is the new default translation model: it keeps technical terms and names (GitHub, ML Ops) and the meaning of each sentence far better than before, and runs fast on any computer. NLLB-200 and MADLAD-400 can be chosen in Preferences, and Argos Translate stays as a light option. A meaning check picks, among several candidate translations, the one closest to the original sentence and lists lines that may still drift. Whole sentences are translated and then mapped back onto the subtitle timing, and pairs without a direct model (for example Urdu to French) work through English.
- **GPU support.** With an NVIDIA GPU and CUDA installed, transcription runs on the GPU automatically. Dubbing uses NVIDIA, AMD, Intel, or Apple GPUs: Kokoro and Piper voices pick whichever device runs them fastest, voice cloning runs on the first GPU that works, and an Intel GPU edition runs transcription and voice cloning on Intel Arc and Core Ultra graphics. If a GPU can't be used, the app falls back to the CPU on its own.
- **Real batch processing.** Every file in the queue is processed, one after another, with per-file progress, status, and error messages. Cancel stops the current file and keeps the rest queued; Start picks up where you left off.
- **No separate ffmpeg install.** Audio is decoded inside the app, so video and audio files work right after installing, with no temporary audio files written to disk. Videos without a sound track now fail with a clear message.
- **Large folders load instantly.** Adding a folder scans it and all subfolders in the background. Thousands of files appear within a second while the window stays responsive.

## Redesigned interface

- New layout: one tab per job, each with its queue on the left, Settings and live Results on the right, and an action bar with overall progress, the current step, and Start / Cancel. Overall progress counts every step of a file, so it never jumps backwards.
- Live results show each subtitle with its translation underneath as it is produced, and stay visible after the run.
- Choose where subtitles are saved, or keep them next to each source file. "Open output folder" appears when a run finishes.
- Every window resizes from any edge, follows the Windows light or dark theme (including switching while the app is open), and uses consistent icons and colors with readable contrast.
- Tooltips explain every option, and download badges show which models are already on this computer.
- Keyboard shortcuts: **Ctrl+O** add files, **Ctrl+Shift+O** add folder, **Ctrl+Enter** start, **Esc** cancel, **Ctrl+,** preferences, **Ctrl+M** manage models, **Ctrl+1 to Ctrl+5** switch tabs, **Delete** remove selected files, **F1** about.
- Preferences are organized into Appearance, Transcription, Translation, Transliteration, Dubbing, Subtitles, and Advanced, and are saved together in one step. Options changed on a tab stay as set when preferences are saved.

## Fixes

- Fixed only the first file in the queue being processed when several were added.
- Fixed Cancel having no effect once transcription had started.
- Fixed long speech being cut off in subtitle files (text past two lines was dropped).
- Fixed preferences occasionally being lost when saving, and settings.json being left damaged after a crash during a save.
- Fixed the logging preferences having no effect; logs are now written to `%APPDATA%\CC-Gen-Ultimate\logs` and can be opened or cleared from Preferences.
- Fixed models being reloaded for every file and kept in memory after processing finished.
- Fixed the window freezing while checking which models are downloaded.
- Fixed Start being available with no output format selected.
- Fixed SRT cue numbers skipping values and WebVTT files breaking on `<` or `&` in the text.
- The Hindi/Punjabi to Urdu neural engine no longer cuts off long lines and runs noticeably faster.

## Known limitations

- Cancelling during transcription takes effect at the end of the current 30-second audio window, which can take several seconds on a CPU with larger models.
- GPU acceleration needs an NVIDIA GPU with the CUDA 12 and cuDNN 9 runtime libraries installed; otherwise the CPU is used.
- Translating a subtitle file (SRT, VTT, and so on) needs its language: from a name like `movie_en.srt`, from the tab it was sent from, or chosen on the Translate tab, since text can't be auto-detected.
- Voice cloning is slow without a GPU, and its XTTS-v2 model allows non-commercial use only. Background music in the original audio can make cloned voices less clear.

## Install

Download one of the installers below. The per-user installer needs no administrator rights. Models download once, the first time each one is used, and work offline afterwards.
