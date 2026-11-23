---
name: ccgen
description: Make subtitles from videos and audio, translate them, convert them to another script (Urdu, Hindi, Roman), and dub videos in another language, offline on the user's PC, with ccgen, the command line of CC-Gen-Ultimate. Use it when the user asks to transcribe, caption, or subtitle a video or audio file or a folder of them, translate subtitles or speech, transliterate subtitles, or dub a video with cloned or stock voices.
license: MIT
compatibility: Windows 10 or 11 with CC-Gen-Ultimate installed or its portable .7z folder unpacked (ccgen.exe sits beside CC-Gen-Ultimate.exe); elsewhere from source with Python 3.12.
metadata:
  version: "1.0.0"
  homepage: https://github.com/ShahFaisalGfG/CC-Gen-Ultimate
---

# ccgen

`ccgen` does what CC-Gen-Ultimate's tabs do, on this PC with no upload: it makes subtitles from speech (Whisper), translates them (OPUS-MT, Hy-MT2, NLLB-200, MADLAD-400, Argos), writes them in another script, and dubs videos with cloned voices (OmniVoice, XTTS-v2) or stock voices (Kokoro, Piper). Each command takes files and folders (searched with their subfolders), starts from the options saved in the app's Preferences, and writes its results beside each file: `talk.srt`, `talk_ur.srt`, `talk_tr_ur_roman.srt`, `talk_dub_es.mkv`.

## Find the command

1. `ccgen --version`: the installers can add it to PATH.
2. Otherwise run it from the install folder:
   - `%APPDATA%\CC-Gen-Ultimate\ccgen.exe` (installed for one user)
   - `%ProgramFiles%\CC-Gen-Ultimate\ccgen.exe` (installed for all users)
   - `ccgen.exe` in the folder unpacked from the portable `.7z`
3. From a clone of the repository: `python -m ccgen` (Python 3.12, with `pip install -r requirements.txt`).

A one-file `CC-Gen-Ultimate.exe` built from source has no command line. If none of these is there, tell the user to install CC-Gen-Ultimate from https://github.com/ShahFaisalGfG/CC-Gen-Ultimate/releases.

## Common tasks

Always add `--json` and quote paths.

```powershell
ccgen generate "D:\Videos\talk.mp4" --json
ccgen generate "D:\Videos" --model small --formats srt,vtt --json
ccgen generate "D:\Videos\talk.mp4" --spoken-language ur --json
ccgen translate "D:\Videos\talk.mp4" --to ur --json
ccgen translate "D:\Subs\talk.srt" --subtitle-language en --to es --json
ccgen transliterate "D:\Subs\talk_ur.srt" --to roman --json
ccgen transliterate "D:\Videos\urdu-talk.mp4" --spoken-language ur --to roman --json
ccgen dub "D:\Videos\talk.mp4" --to es --voices kokoro --json
ccgen dub "D:\Videos\talk.mp4" --subtitle "D:\Videos\talk_es.srt" --to es --json
ccgen workflow "D:\Videos" --preset "Urdu subtitles" --json
ccgen workflow "D:\Videos\talk.mp4" --steps steps.json --json
```

- A video or audio file given to `translate`, `transliterate`, or `dub` is transcribed first, with the saved Generate model.
- A subtitle's language comes from its name (`talk_en.srt`, `talk.en.srt`); for other names add `--subtitle-language LANG`.
- Results already there are skipped (reported as `skipped`). `--existing replace` writes over them; `--existing keep-both` saves the new ones as `talk (2).srt`.
- `ccgen options --json` lists every language, model, script, voice, and format code; `ccgen hardware --json` shows the GPU and the recommended performance profile; `--profile light|balanced|quality` picks the automatic models for one run.

Every option is in [references/commands.md](references/commands.md).

## Read the result

With `--json`, stdout carries one JSON object per line and nothing else. Read the `file` events for the files written and the last line, the `done` event, for the outcome:

```json
{"event": "file", "input": "D:\\Videos\\talk.mp4", "path": "D:\\Videos\\talk.srt", "language": "en"}
{"event": "done", "ok": true, "exit_code": 0, "message": "1 done, 1 file written, in 42 s.", "done": 1, "failed": 0, "skipped": 0, "written": 1, "seconds": 41.6}
```

`error` events explain a failed file in plain words with what to do next (`kind` says which: `gpu_memory`, `disk_full`, `network`, `file_missing`, `unreadable_media`, ...). Every event and field is in [references/json-events.md](references/json-events.md).

## Exit status

| Code | Meaning |
|---|---|
| `0` | Every file was done. Files skipped because their results were already there don't count against it. |
| `1` | Some files failed; the others were done. |
| `2` | The input, an option, a model's licence, or a folder can't be used. Nothing ran. |
| `130` | Stopped with Ctrl+C. The file being processed stopped unfinished; run the same command to do it and the rest. |

## Rules for agents

- **Licences.** NLLB-200, OmniVoice, and XTTS-v2 allow non-commercial use only. When a command stops with exit 2 and says to accept a licence, show the user that message, ask whether they accept it, and only if they say yes run the command again with `--accept-terms nllb`, `--accept-terms omnivoice`, or `--accept-terms xtts`. Never accept a licence for the user.
- **Voice cloning.** Only clone voices the user has permission to use.
- **Time and downloads.** A first run downloads its models (Whisper small 466 MB; voice cloning 3.7 GB), and long videos take minutes to hours on a CPU. Run commands in the background or with a long timeout, and don't restart them to "fix" slowness. `ccgen models list --json` shows what is downloaded; `ccgen models download ID` fetches one ahead of time.
- **Folders.** A folder is searched with all its subfolders. Ask before running on a large folder, and prefer `--output-dir` when the user's folders shouldn't get new files.
- **One at a time.** Run one ccgen task at a time; the models share the GPU.
- **Settings.** `ccgen settings set` changes the defaults the app uses too. Change them only when the user asks; use command options for one run.

## The skill itself

```powershell
ccgen skill install
ccgen skill install --agent cursor
ccgen skill show
```

`ccgen skill install` copies this skill into `~/.agents/skills` and `~/.claude/skills`; `--agent NAME` or `--dir FOLDER` choose other folders, and `ccgen skill show` prints it for agents that can't load skills.
