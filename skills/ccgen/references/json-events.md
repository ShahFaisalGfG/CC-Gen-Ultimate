# ccgen --json output

With `--json`, stdout carries only JSON. Words for people, and anything the speech and translation libraries print, go to stderr. Options that argparse rejects print usage to stderr with no JSON, and the exit status is 2.

## Task commands

`generate`, `translate`, `transliterate`, `dub`, and `workflow` print one event per line. Read them as they come, or wait for the last line, which is always a `done` event. Paths are absolute.

| Event | When | Fields |
|---|---|---|
| `start` | The run begins | `command`, `files` (how many will run), `log` (the log file) |
| `item` | A file starts | `input`, `index` and `count` (its place in the run, from 1) |
| `status` | A file moves to a new stage | `input`, `message` ("Loading speech recognition model...", "Step 2 of 3: Translating"), `step` and `steps` (its stages, from 1) |
| `progress` | At most twice a second while a stage can be measured | `input`, `index`, `count`, `step`, `steps`, `stage` (`load`, `transcribe`, `translate`, `transliterate`, `speakers`, `speak`, `write`), `step_fraction` (0 to 1, this stage), `fraction` (0 to 1, this file), `overall` (0 to 1, the run) |
| `segment` | With `--segments`: a subtitle line was made | `input`, `kind` (`transcript`, `translation`, `transliteration`), `stage`, `step`, `id`, `start` and `end` (seconds), `text` |
| `file` | A file was written | `input`, `path`, `language` (the language of its text) |
| `warning` | Something to know that didn't stop the file (no speech found, a sentence whose translation drifted, a result already there that was kept, a licence accepted) | `input` ("" for the run), `message` |
| `skipped` | A file that didn't run: its results are already there (see `--existing`), or it isn't a file this command takes | `input`, `reason` |
| `error` | A file failed | `input`, `kind`, `message` (plain words with what to do next), `detail` (the original error text, for the log or a bug report) |
| `done` | Always last | `ok`, `exit_code`, `message`, and once files ran: `done`, `failed`, `skipped`, `written`, `seconds` |

`kind` is `gpu_memory`, `memory`, `disk_full`, `access_denied`, `in_use`, `network`, `file_missing`, `unreadable_media`, `language_pair`, `invalid`, or `unknown`.

When the command can't start (exit 2: no usable files, a model licence not accepted, an option a file can't use), the only line is `done` with `ok` false and the reason in `message`.

### Example

```json
{"event": "start", "command": "translate", "files": 1, "log": "C:\\Users\\me\\AppData\\Roaming\\CC-Gen-Ultimate\\logs\\ccgen.log"}
{"event": "item", "input": "D:\\Videos\\talk.mp4", "index": 1, "count": 1}
{"event": "status", "input": "D:\\Videos\\talk.mp4", "message": "Loading speech recognition model...", "step": 1, "steps": 3}
{"event": "status", "input": "D:\\Videos\\talk.mp4", "message": "Step 1 of 2: Making subtitles", "step": 1, "steps": 3}
{"event": "progress", "input": "D:\\Videos\\talk.mp4", "index": 1, "count": 1, "step": 2, "steps": 3, "stage": "transcribe", "step_fraction": 0.5, "fraction": 0.5, "overall": 0.5}
{"event": "status", "input": "D:\\Videos\\talk.mp4", "message": "Step 2 of 2: Translating", "step": 3, "steps": 3}
{"event": "file", "input": "D:\\Videos\\talk.mp4", "path": "D:\\Videos\\talk_ur.srt", "language": "ur"}
{"event": "done", "ok": true, "exit_code": 0, "message": "1 done, 1 file written, in 2 min.", "done": 1, "failed": 0, "skipped": 0, "written": 1, "seconds": 131.4}
```

## models download

| Event | Fields |
|---|---|
| `item` | `id` (a download starts) |
| `progress` | `id`, `downloaded` and `total` in bytes, `fraction` (-1 while the size is unknown) |
| `file` | `id` (downloaded) |
| `error` | `id`, `message`, `detail` |
| `done` | `ok`, `exit_code`, `message`, `done`, `failed` |

## Short commands

The other commands print one JSON object:

- `models list`: `{"models": [{"id", "category", "engine", "label", "downloaded", "size_bytes", "approx_size_mb", ...}]}`
- `models delete`: `{"ok", "deleted": [ids], "failed": [{"id", "error"}]}`
- `options`: every option list by name (`languages`, `translation_targets`, `translation_engines`, `translit_schemes`, `dub_modes`, `voices`, `profiles`, `licences`, ...), each item with `label` and `code`
- `hardware`: `{"gpu", "vram_gb", "ram_gb", "physical_cores", "gpu_note", "summary", "recommended", "profile", "effective_profile"}`
- `settings list`: the whole settings object; `settings get`: `{"key", "value"}`; `settings set`: `{"ok", "key", "value"}`; `settings reset`: `{"ok", "reset"}`
- `workflow --list`: `{"presets": [{"name", "steps"}]}`
- A short command that can't run prints `{"ok": false, "exit_code": 2, "error": "..."}`.

The `skill` command's `--json` prints `{"skill": "ccgen", "installed": [paths], "failed": [{"path", "error"}]}` for install, `removed` and `not_installed` for uninstall, `folders` (`path`, `installed`) for path, and `files` (name to text) for show.
