# ccgen command reference

```text
ccgen generate|translate|transliterate|dub INPUT... [options]
ccgen workflow INPUT... (--steps FILE | --preset NAME) [options]
ccgen workflow --list
ccgen models {list,download,delete} [options]
ccgen options [--json]
ccgen hardware [--json]
ccgen settings {list,get,set,reset} [options]
ccgen skill {install,uninstall,path,show} [options]
ccgen --version
```

`INPUT` is a file or a folder; a folder is searched with its subfolders. Options left out take the value saved in the app's Preferences, as the app's tabs do. `ccgen options --json` lists every code the options take.

## Every task command

| Option | Default | What it does |
|---|---|---|
| `--json` | | One JSON event per line on stdout (see json-events.md) |
| `--output-dir FOLDER` | beside each file | Where to write the results |
| `--profile light\|balanced\|quality` | the saved one | The performance profile that picks every automatic model |
| `--existing skip\|replace\|keep-both` | `skip` | Results already there: skip the file, write over them, or save the new ones as `name (2).srt` |
| `--accept-terms nllb\|omnivoice\|xtts` | | Accept a model's licence on this PC, after the user agreed (repeatable) |
| `--segments` | | With `--json`, also report each subtitle line as a `segment` event |

## Speech in videos and audio

`generate` takes these; `translate`, `transliterate`, and `dub` take them for the videos and audio they transcribe first.

| Option | What it does |
|---|---|
| `--model auto\|tiny\|base\|small\|medium\|large-v3-turbo\|large-v3` | Whisper model; `auto` follows the profile (light: small, balanced: large-v3-turbo, quality: large-v3) |
| `--spoken-language LANG` | The language spoken, or `auto` to detect it (`generate` also takes `--language`) |
| `--device auto\|cpu\|cuda` | Where Whisper runs |
| `--compute-type auto\|int8\|float16\|float32` | Whisper's number format |
| `--beam-size N` | Search width; higher is slower and steadier |
| `--no-vad` | Transcribe silent parts too |

## Subtitle files

`generate`, `translate`, `transliterate`, and `workflow` take these.

| Option | What it does |
|---|---|
| `--formats LIST` | Comma-separated: `srt`, `vtt`, `lrc`, `ass`, `sbv` |
| `--max-line-length N` | Characters per line, 20 to 80 |
| `--max-lines N` | Lines per subtitle, 1 to 3 |

## generate

Makes subtitles from videos and audio: `talk.mp4` gives `talk.srt`. Subtitle files given to it are skipped.

## translate

| Option | What it does |
|---|---|
| `--to LANG` | Language to translate into: `ar`, `zh`, `en`, `fr`, `de`, `hi`, `ja`, `ko`, `pt`, `ru`, `es`, `tr`, `ur` |
| `--engine auto\|opus_mt\|hymt2\|nllb\|madlad\|argos` | Translation model; `auto` picks one free for any use for each language pair. `nllb` needs `--accept-terms nllb` |
| `--subtitle-language LANG` | The language of subtitle files whose names don't say it (`talk_en.srt` does) |

Writes `talk_ur.srt`. Videos and audio are transcribed first.

## transliterate

| Option | What it does |
|---|---|
| `--from SCRIPT` | The script of the subtitles, or `auto` to take it from their language: `roman`, `ur`, `hi`, `bn`, `gu`, `pa`, `ta`, `te`, `kn`, `ml`, `or`, `si`, `th`, `my` |
| `--to SCRIPT` | The script to write in |
| `--engine auto\|rule\|neural` | `rule` is fast; `neural` is better for Urdu, Roman Urdu, and Hindi |
| `--subtitle-language LANG` | The language of subtitle files whose names don't say it (used with `--from auto`) |

Writes `talk_tr_ur_roman.srt`. Speech is transcribed in its own script and converted from it; when it is already in the `--to` script, it is converted to the `--from` script instead.

## dub

| Option | What it does |
|---|---|
| `--to LANG` | The language to speak, or `auto` for the language of the text |
| `--voices auto\|omnivoice\|xtts\|kokoro\|piper` | `omnivoice` and `xtts` clone the original voices (non-commercial licences); `kokoro` and `piper` are stock voices; `auto` clones with OmniVoice, or uses Kokoro and Piper on the light profile |
| `--voice KEY` | A Kokoro or Piper voice, such as `piper:ur_PK-fasih-medium` (`ccgen options --json` lists them) |
| `--speakers auto\|single` | Clone each speaker, or one voice for everyone |
| `--max-speakers N` | Most speakers to tell apart, 1 to 6 |
| `--max-speedup X` | Fastest speech allowed to fit a line's time, 1.0 to 2.0 |
| `--quality auto\|full\|fast` | How carefully OmniVoice refines each line |
| `--wav` | Write a separate WAV file instead of a new audio track |
| `--default-track` | Make the dub the video's default audio track |
| `--cpu` | Never use the GPU for the voices |
| `--subtitle FILE` | Speak this subtitle file (with one video or audio file) |
| `--reference FILE` | A recording of the voice to clone, for a subtitle file on its own |
| `--subtitle-language LANG` | The language of subtitle files whose names don't say it |

A video alone is transcribed, translated into `--to`, and spoken: `talk_dub_es.mkv` (`.mka` for audio). A subtitle beside its video (`talk.mp4` and `talk_es.srt`, both given) is spoken instead of a transcript. A subtitle on its own becomes `talk_dub_es.wav`.

## workflow

| Option | What it does |
|---|---|
| `--steps FILE` | A JSON list of steps (below) |
| `--preset NAME` | A workflow saved in the app's Workflow tab |
| `--list` | List the saved workflows and stop |
| `--subtitle-language LANG` | The language of subtitle files whose names don't say it |

A step is an object with `kind` (`generate`, `translate`, `transliterate`, or `dub`), the options of that task (the field names are those of `ccgen settings list` without the section, such as `target_lang`, `engine`, `target_scheme`, `mode`), and `input`: `"source"` for the queued file or `"step:N"` for the text of step N (counted from 0). Steps write their subtitles unless `"write_output": false`.

```json
[
  {"kind": "generate"},
  {"kind": "translate", "input": "step:0", "target_lang": "ur"},
  {"kind": "dub", "input": "step:1", "language": "ur", "mode": "piper"}
]
```

## models

| Command | What it does |
|---|---|
| `ccgen models list [--category whisper\|translation\|transliteration\|voices] [--downloaded]` | Every model with its id, size, and whether it is downloaded |
| `ccgen models download ID...` | Download models ahead of time, such as `whisper:small` or `voices:kokoro` (the free space is checked first) |
| `ccgen models delete ID...` | Delete downloaded models |

Each takes `--json`.

## options, hardware

`ccgen options` lists the codes every option takes (languages, Whisper models, translation models, scripts, dubbing modes and qualities, voices, devices, formats, profiles, licences). `ccgen hardware` shows the GPU, memory, CPU cores, the profile recommended for them, and the saved profile. Both take `--json`.

## settings

| Command | What it does |
|---|---|
| `ccgen settings list` | Every setting, by its dot-separated key |
| `ccgen settings get KEY` | One setting, such as `translation.target_lang` |
| `ccgen settings set KEY VALUE` | Change one setting; the value is checked against the choices it takes. `auto` sets the spoken language to detection |
| `ccgen settings reset --yes` | Put every setting back to its default (without `--yes` it asks on a terminal, and refuses elsewhere) |

Each takes `--json`. Licences can't be set here; they are accepted with `--accept-terms` on a task.

## The skill command

| Command | What it does |
|---|---|
| `ccgen skill install` | Copy this skill into `~/.agents/skills/ccgen` and `~/.claude/skills/ccgen` |
| `ccgen skill install --agent AGENT` | Into one agent's own folder (repeatable): `agents`, `amp`, `augment`, `claude`, `codex`, `continue`, `copilot`, `cursor`, `droid`, `gemini`, `goose`, `junie`, `kilo`, `kiro`, `opencode`, `openhands`, `qwen`, `roo`, `trae`, `windsurf` |
| `ccgen skill install --dir FOLDER` | Into a skills folder of your own (the skill goes in `FOLDER\ccgen`) |
| `ccgen skill uninstall` | Remove it again (same `--agent` and `--dir` choices) |
| `ccgen skill path` | List the folders it goes in and whether it is there |
| `ccgen skill show` | Print the skill and its references |

Each takes `--json`.

## Examples

```powershell
ccgen generate "D:\Lectures" --model large-v3-turbo --formats srt,vtt --output-dir "D:\Subtitles" --json
ccgen translate "D:\Subs\talk_en.srt" --to ur --engine nllb --accept-terms nllb --json
ccgen transliterate "D:\Subs\song_hi.srt" --from auto --to ur --engine neural --json
ccgen dub "D:\Videos\talk.mp4" --to ur --voices piper --voice piper:ur_PK-fasih-medium --json
ccgen dub "D:\Subs\intro_en.srt" --reference "D:\Audio\my-voice.wav" --voices xtts --json
ccgen workflow --list --json
ccgen models download whisper:small --json
ccgen settings set transcription.language auto
```
