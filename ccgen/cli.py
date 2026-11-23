"""ccgen - make, translate, transliterate, and dub subtitles offline from the command line.

The commands do what the app's tabs do, from the same saved preferences: `generate`, `translate`,
`transliterate`, `dub`, and `workflow` take files and folders; `models`, `options`, `hardware`, and
`settings` cover Manage Models and Preferences; `skill` installs the Agent Skill that teaches AI
coding agents to use ccgen.

With --json, stdout carries only JSON: one object for a short command, or one event per line for a
task (start, item, status, progress, segment, file, warning, skipped, error, and a closing done with
the exit status). Words for people always go to stderr.

Exit status: 0 when every file was done (files skipped because their results were already there
don't count against it), 1 when some files failed, 2 when the input, the options, a model's licence,
or a folder can't be used, 130 when stopped with Ctrl+C (the file being processed stops at its next
safe point; run the command again to do it).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections.abc import Sequence
from typing import Any, Optional, TextIO

from ccgen.api.services import settings_service
from ccgen.config import licences
from ccgen.config.defaults import (
    AUTO,
    AppInfo,
    ComputeDefaults,
    DubbingDefaults,
    LanguageOptions,
    ModelDefaults,
    OutputDefaults,
    TransliterationDefaults,
)
from ccgen.config.options import option_lists
from ccgen.config.profiles import PROFILE_KEYS
from ccgen.config.translation_models import ENGINE_KEYS as TRANSLATION_ENGINES
from ccgen.utils import agent_skills
from ccgen.utils.logging import configure_from_settings
from ccgen.utils.settings import load_settings

PROG = "ccgen"
EXIT_OK, EXIT_FAILED, EXIT_INVALID, EXIT_UNAVAILABLE, EXIT_STOPPED = 0, 1, 2, 3, 130
TASKS = ("generate", "translate", "transliterate", "dub", "workflow")
# What --existing takes, and the value the task configs use for it.
EXISTING = {"skip": "skip", "replace": "replace", "keep-both": "keep_both"}
_SPOKEN = [code for _, code in LanguageOptions.TRANSCRIPTION if code]
_TARGETS = [code for _, code in LanguageOptions.TRANSLATION_TARGETS]
_SCHEMES = [code for _, code in TransliterationDefaults.SCHEMES]

_EXAMPLES = """examples:
  ccgen generate "D:\\Videos\\talk.mp4" --json
  ccgen generate "D:\\Videos" --model small --formats srt,vtt --json
  ccgen translate "D:\\Videos\\talk.mp4" --to ur --json
  ccgen translate "D:\\Subs\\talk.srt" --subtitle-language en --to es --json
  ccgen transliterate "D:\\Subs\\talk_ur.srt" --to roman --json
  ccgen dub "D:\\Videos\\talk.mp4" --to es --voices kokoro --json
  ccgen workflow "D:\\Videos" --preset "Urdu subtitles" --json
  ccgen models list --json
  ccgen settings set translation.target_lang ur

agent skill (teaches AI coding agents to use ccgen):
  ccgen skill install           into ~/.agents/skills and ~/.claude/skills
  ccgen skill install --agent cursor
  ccgen skill show              print it, for agents that can't load skills
"""


class UsageError(Exception):
    """Input, options, a licence, or a folder that can't be used (exit status 2)."""


class Console:
    """Where the command's words go: plain lines for people on stderr (and the files it wrote on
    stdout), or with --json one JSON object per line on stdout, for scripts and AI agents."""

    def __init__(self, json_lines: bool = False, out: Optional[TextIO] = None, err: Optional[TextIO] = None) -> None:
        self.json = json_lines
        self._out = out
        self._err = err

    @property
    def out(self) -> TextIO:
        return self._out or sys.stdout

    @property
    def err(self) -> TextIO:
        return self._err or sys.stderr

    def emit(self, event: str, **fields: Any) -> None:
        """One JSON event line."""
        print(json.dumps({"event": event, **fields}, ensure_ascii=False), file=self.out, flush=True)

    def say(self, text: str) -> None:
        """A line for people (stderr), whatever the mode."""
        print(text, file=self.err, flush=True)

    def result(self, data: Any, text: str) -> None:
        """A short command's answer: `data` as one JSON object, or `text` on stdout for people."""
        if self.json:
            print(json.dumps(data, ensure_ascii=False), file=self.out, flush=True)
        else:
            print(text, file=self.out, flush=True)

    def fail(self, code: int, message: str, **fields: Any) -> int:
        """A command that couldn't run: an error object with --json, else the message on stderr."""
        if self.json:
            print(json.dumps({"ok": False, "exit_code": code, "error": message, **fields}, ensure_ascii=False),
                  file=self.out, flush=True)
        else:
            self.say(message)
        return code


# ── Arguments ─────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Every command and option; the defaults come from the app's saved preferences."""
    parser = argparse.ArgumentParser(
        prog=PROG, description=f"{AppInfo.APP_DESCRIPTION}, from the command line of {AppInfo.APP_NAME}.",
        epilog=_EXAMPLES, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {AppInfo.APP_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    generate = _task_parser(commands, "generate", "Make subtitles from videos and audio.",
                            "INPUT is a video or audio file, or a folder (searched with its subfolders).")
    _transcription_options(generate, primary=True)
    _subtitle_options(generate)

    translate = _task_parser(commands, "translate", "Translate subtitles, or the speech in videos and audio.",
                             "Videos and audio are transcribed first, with the saved Generate settings.")
    translate.add_argument("--to", "--target-lang", dest="target_lang", choices=_TARGETS, metavar="LANG",
                           help=f"language to translate into: {', '.join(_TARGETS)} (default: the saved one)")
    translate.add_argument("--engine", choices=TRANSLATION_ENGINES,
                           help="translation model; auto picks for each language pair (default: the saved one)")
    _text_language_option(translate)
    _transcription_options(translate)
    _subtitle_options(translate)

    transliterate = _task_parser(
        commands, "transliterate", "Write subtitles, or the speech in videos and audio, in another script.",
        "Speech is transcribed in its own script and converted from it; when it is already in the --to script, "
        "it is converted to the --from script instead.")
    transliterate.add_argument("--from", "--source", dest="source_scheme", metavar="SCRIPT",
                               choices=[TransliterationDefaults.SOURCE_AUTO, *_SCHEMES],
                               help="script the subtitles are written in; auto reads it from their language "
                                    f"(default: the saved one): auto, {', '.join(_SCHEMES)}")
    transliterate.add_argument("--to", "--target", dest="target_scheme", choices=_SCHEMES, metavar="SCRIPT",
                               help="script to convert into (default: the saved one)")
    transliterate.add_argument("--engine", choices=[code for _, code in TransliterationDefaults.ENGINES],
                               help="auto, rule (fast), or neural (higher quality) (default: the saved one)")
    _text_language_option(transliterate)
    _transcription_options(transliterate)
    _subtitle_options(transliterate)

    dub = _task_parser(
        commands, "dub", "Speak videos, audio, or subtitles in another language, as a new audio track.",
        "A video or audio file is transcribed, translated, and spoken; a subtitle beside its video (movie.mp4 and "
        "movie_es.srt) is spoken instead, and a subtitle on its own becomes a WAV file.")
    dub.add_argument("--to", dest="dub_language", metavar="LANG",
                     choices=[DubbingDefaults.LANGUAGE_AUTO, *_SPOKEN],
                     help="language to speak; auto keeps the spoken one (default: the saved translation language)")
    dub.add_argument("--voices", "--mode", dest="mode", choices=[code for _, code, _ in DubbingDefaults.MODES],
                     help="omnivoice or xtts clone the original voices; kokoro or piper use stock voices; auto "
                          "follows the performance profile (default: the saved one)")
    dub.add_argument("--voice", help="a Kokoro or Piper voice, such as piper:ur_PK-fasih-medium (`ccgen options`)")
    dub.add_argument("--speakers", choices=[code for _, code in DubbingDefaults.SPEAKERS],
                     help="clone each speaker (auto) or one voice for everyone (single)")
    dub.add_argument("--max-speakers", type=int, metavar="N", help=f"most speakers to tell apart, 1 to "
                     f"{DubbingDefaults.MAX_SPEAKERS} (default: {DubbingDefaults.MAX_SPEAKERS})")
    dub.add_argument("--max-speedup", type=float, metavar="X",
                     help="fastest speech allowed to fit a line's time, 1.0 to 2.0 (default: the saved one)")
    dub.add_argument("--quality", choices=[code for _, code, _ in DubbingDefaults.QUALITIES],
                     help="OmniVoice's care per line: full, fast, or auto from the profile")
    dub.add_argument("--wav", action="store_true", help="write a separate WAV file instead of adding a track")
    dub.add_argument("--default-track", action="store_true", help="make the dub the video's default audio track")
    dub.add_argument("--cpu", action="store_true", help="never use the GPU for the voices")
    dub.add_argument("--subtitle", metavar="FILE", help="the subtitle file to speak (with one video or audio file)")
    dub.add_argument("--reference", metavar="FILE",
                     help="a recording of the voice to clone, for a subtitle file on its own")
    _text_language_option(dub)
    _transcription_options(dub)

    workflow = _task_parser(commands, "workflow", "Run a chain of steps on every file.",
                            "The steps come from a JSON file or a workflow saved in the app's Workflow tab.")
    source = workflow.add_mutually_exclusive_group(required=True)
    source.add_argument("--steps", metavar="FILE",
                        help='JSON file with the steps, e.g. [{"kind": "generate"}, '
                             '{"kind": "translate", "input": "step:0", "target_lang": "ur"}]')
    source.add_argument("--preset", metavar="NAME", help="a workflow saved in the app (`ccgen workflow --list`)")
    source.add_argument("--list", action="store_true", help="list the saved workflows and stop")
    _text_language_option(workflow)
    _subtitle_options(workflow)

    _models_parser(commands)
    options = commands.add_parser("options", help="list every choice the task options take",
                                  description="List every choice the task options take: languages, models, "
                                              "scripts, voices, formats, profiles, and licences.")
    options.add_argument("--json", action="store_true", help="print one JSON object")
    hardware = commands.add_parser("hardware", help="show this PC's GPU, memory, and recommended profile",
                                   description="Show this PC's GPU, memory, and CPU cores, and the performance "
                                               "profile recommended for them.")
    hardware.add_argument("--json", action="store_true", help="print one JSON object")
    _settings_parser(commands)
    skill = commands.add_parser("skill", help="install the Agent Skill that teaches AI coding agents to use ccgen",
                                description="The Agent Skill that teaches AI coding agents to use ccgen.")
    agent_skills.add_skill_commands(skill, PROG)
    return parser


def _task_parser(commands: Any, name: str, text: str, detail: str) -> argparse.ArgumentParser:
    """A task command with the inputs and the options every task shares."""
    parser = commands.add_parser(name, help=text[0].lower() + text[1:].rstrip("."), description=f"{text} {detail}")
    if name == "workflow":
        parser.add_argument("inputs", nargs="*", metavar="INPUT", help="files or folders")
    else:
        parser.add_argument("inputs", nargs="+", metavar="INPUT", help="files or folders")
    parser.add_argument("--output-dir", metavar="FOLDER", help="where to write (default: beside each file)")
    parser.add_argument("--profile", choices=PROFILE_KEYS,
                        help="performance profile that picks every automatic model (default: the saved one)")
    parser.add_argument("--existing", choices=sorted(EXISTING), default="skip",
                        help="results already there: skip the file (default), replace them, or keep-both "
                             "(the new file gets \" (2)\")")
    parser.add_argument("--accept-terms", action="append", default=[], choices=sorted(licences.TERMS),
                        metavar="MODEL", help="accept a model's licence for this PC (ask the user first): "
                                              f"{', '.join(sorted(licences.TERMS))}")
    parser.add_argument("--segments", action="store_true", help="with --json, also report each subtitle line")
    parser.add_argument("--json", action="store_true",
                        help="print one JSON event per line on stdout, for scripts and AI agents; the last is "
                             "a done event with ok and exit_code")
    parser.set_defaults(task=name)
    return parser


def _transcription_options(parser: argparse.ArgumentParser, primary: bool = False) -> None:
    """How speech is transcribed (videos and audio)."""
    group = parser.add_argument_group("speech" if primary else "speech in videos and audio")
    group.add_argument("--model", choices=[AUTO, *ModelDefaults.SUPPORTED_MODELS],
                       help="Whisper model; auto follows the performance profile (default: the saved one)")
    names = ("--spoken-language", "--language") if primary else ("--spoken-language",)
    group.add_argument(*names, dest="spoken_language", metavar="LANG",
                       choices=[AUTO, *_SPOKEN],
                       help=f"language spoken, or auto to detect it: {', '.join(_SPOKEN)} (default: the saved one)")
    group.add_argument("--device", choices=ComputeDefaults.SUPPORTED_DEVICES, help="auto, cpu, or cuda")
    group.add_argument("--compute-type", choices=ComputeDefaults.SUPPORTED_COMPUTE_TYPES,
                       help="auto, int8, float16, or float32")
    group.add_argument("--beam-size", type=int, metavar="N", help="search width; higher is slower and steadier")
    group.add_argument("--no-vad", dest="vad", action="store_false", default=None,
                       help="transcribe silent parts too (voice detection off)")


def _subtitle_options(parser: argparse.ArgumentParser) -> None:
    """The subtitle files a task writes."""
    group = parser.add_argument_group("subtitle files")
    group.add_argument("--formats", metavar="LIST",
                       help=f"comma-separated: {', '.join(OutputDefaults.FORMATS)} (default: the saved ones)")
    group.add_argument("--max-line-length", type=int, metavar="N",
                       help="characters per line, 20 to 80 (default: the saved one)")
    group.add_argument("--max-lines", type=int, metavar="N", help="lines per subtitle, 1 to 3 (default: the saved one)")


def _text_language_option(parser: argparse.ArgumentParser) -> None:
    """The language of subtitle files whose names don't carry one (movie_en.srt does)."""
    parser.add_argument("--subtitle-language", "--source-lang", dest="subtitle_language", metavar="LANG",
                        choices=_TARGETS, help="language of subtitle files whose names don't say it")


def _models_parser(commands: Any) -> None:
    models = commands.add_parser("models", help="list, download, or delete models (Manage Models)",
                                 description="List, download, or delete the models and voices the app uses.")
    actions = models.add_subparsers(dest="models_action", required=True, metavar="ACTION")
    listing = actions.add_parser("list", help="list every model with its size and whether it is downloaded")
    listing.add_argument("--category", choices=("whisper", "translation", "transliteration", "voices"))
    listing.add_argument("--downloaded", action="store_true", help="only the downloaded ones")
    listing.add_argument("--json", action="store_true", help="print one JSON object")
    download = actions.add_parser("download", help="download models by id (from `ccgen models list`)")
    download.add_argument("ids", nargs="+", metavar="ID")
    download.add_argument("--json", action="store_true", help="print one JSON event per line")
    delete = actions.add_parser("delete", help="delete downloaded models by id")
    delete.add_argument("ids", nargs="+", metavar="ID")
    delete.add_argument("--json", action="store_true", help="print one JSON object")


def _settings_parser(commands: Any) -> None:
    settings = commands.add_parser("settings", help="read or change the app's saved preferences",
                                   description="Read or change the preferences the app and these commands start "
                                               "from. Keys are dot-separated, such as translation.target_lang.")
    actions = settings.add_subparsers(dest="settings_action", required=True, metavar="ACTION")
    listing = actions.add_parser("list", help="every setting and its value")
    listing.add_argument("--json", action="store_true", help="print one JSON object")
    get = actions.add_parser("get", help="one setting's value")
    get.add_argument("key")
    get.add_argument("--json", action="store_true", help="print one JSON object")
    change = actions.add_parser("set", help="change a setting (`ccgen options` lists the choices)")
    change.add_argument("key")
    change.add_argument("value")
    change.add_argument("--json", action="store_true", help="print one JSON object")
    reset = actions.add_parser("reset", help="put every setting back to its default (asks first on a terminal)")
    reset.add_argument("--yes", action="store_true", help="don't ask")
    reset.add_argument("--json", action="store_true", help="print one JSON object")


# ── Entry ─────────────────────────────────────────────────────────────────────


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run one command; returns its exit status."""
    console_safe()
    args = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    parsed = parser.parse_args(args)
    if argv is None and getattr(parsed, "json", False):
        _keep_stdout_for_json()
    console = Console(bool(getattr(parsed, "json", False)))
    settings = load_settings()
    configure_from_settings(settings, console=False)
    try:
        if parsed.command in TASKS or parsed.command == "models":
            # The tasks and the model catalog load torch, CTranslate2, and the download libraries,
            # which take seconds; only these commands import them, so the others stay quick.
            from ccgen import cli_tasks

            if parsed.command == "models":
                return cli_tasks.run_models(parsed, console)
            return cli_tasks.run_tasks(parsed, settings, console)
        if parsed.command == "options":
            return run_options(console)
        if parsed.command == "hardware":
            return run_hardware(settings, console)
        if parsed.command == "settings":
            return run_settings(parsed, console)
        return agent_skills.run_skill_command(parsed, PROG)
    except UsageError as error:
        if console.json and parsed.command in TASKS:
            console.emit("done", ok=False, exit_code=EXIT_INVALID, message=str(error))
            return EXIT_INVALID
        return console.fail(EXIT_INVALID, str(error))
    except KeyboardInterrupt:
        message = "Stopped."
        if console.json and parsed.command in TASKS:
            console.emit("done", ok=False, exit_code=EXIT_STOPPED, message=message)
            return EXIT_STOPPED
        return console.fail(EXIT_STOPPED, message)


def console_safe() -> None:
    """Statuses and subtitles carry characters (Urdu, Devanagari, arrows) a legacy Windows console code
    page can't encode; print a placeholder for those instead of failing mid-run."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")


def _keep_stdout_for_json() -> None:
    """Send everything but the JSON lines to stderr, including what libraries print to stdout.

    The real stdout is kept for the events; file descriptor 1 is pointed at stderr, so native code
    that writes to it can't break the JSON stream either.
    """
    try:
        sys.stdout.flush()
        events = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8", errors="replace", buffering=1)
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    except (OSError, ValueError, io.UnsupportedOperation):
        return
    sys.stdout = events


# ── Options, hardware, settings ───────────────────────────────────────────────


def run_options(console: Console) -> int:
    """Every choice the task options take."""
    lists = option_lists()
    lines = []
    for name, items in lists.items():
        if name == "voices":
            continue
        codes = [str(item.get("code", "")) if isinstance(item, dict) else str(item) for item in items]
        lines.append(f"{name}: {', '.join(code or 'auto' for code in codes)}")
    lines.append(f"voices: {len(lists['voices'])} (see --json)")
    console.result(lists, "\n".join(lines))
    return EXIT_OK


def run_hardware(settings: dict[str, Any], console: Console) -> int:
    """This PC's GPU, memory, and cores, and the profile recommended for them."""
    # Detection imports torch to find the GPU.
    from ccgen.config.profiles import effective_profile, profile_info, saved_profile
    from ccgen.engines import hardware

    found = hardware.detect()
    saved = saved_profile(settings)
    data = {
        "gpu": found.gpu, "vram_gb": round(found.vram_gb, 1), "ram_gb": round(found.ram_gb, 1),
        "physical_cores": found.physical_cores, "gpu_note": found.gpu_note, "summary": found.summary,
        "recommended": found.recommended, "profile": saved, "effective_profile": effective_profile(settings),
    }
    text = (f"{found.summary}\nRecommended profile: {profile_info(found.recommended).label}"
            f"\nSaved profile: {profile_info(saved).label if saved else 'not chosen yet'}")
    console.result(data, text)
    return EXIT_OK


def run_settings(args: argparse.Namespace, console: Console) -> int:
    """List, read, change, or reset the saved preferences."""
    action = args.settings_action
    if action == "list":
        settings = settings_service.get_all()
        flat = settings_service.flatten(settings)
        console.result(settings, "\n".join(f"{key} = {_shown(value)}" for key, value in flat.items()))
        return EXIT_OK
    if action == "get":
        flat = settings_service.flatten(settings_service.get_all())
        if args.key not in flat:
            raise UsageError(f"Unknown setting: {args.key}. `ccgen settings list` shows every setting.")
        console.result({"key": args.key, "value": flat[args.key]}, _shown(flat[args.key]))
        return EXIT_OK
    if action == "set":
        if args.key in {terms.setting for terms in licences.TERMS.values()}:
            raise UsageError("Licences are accepted with --accept-terms on a task, after asking the user.")
        try:
            value = settings_service.parse_value(args.key, args.value)
            settings_service.set_many({args.key: value})
        except ValueError as error:
            raise UsageError(str(error)) from error
        except OSError as error:
            raise UsageError(f"The settings file couldn't be written: {error}") from error
        console.result({"ok": True, "key": args.key, "value": value}, f"{args.key} = {_shown(value)}")
        return EXIT_OK
    if not args.yes:
        if not sys.stdin.isatty():
            raise UsageError("settings reset puts every preference back to its default; add --yes to do it.")
        answer = input("Put every preference back to its default? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            return console.fail(EXIT_OK, "Nothing was changed.")
    try:
        settings_service.reset_defaults()
    except OSError as error:
        raise UsageError(f"The settings file couldn't be written: {error}") from error
    console.result({"ok": True, "reset": True}, "Every preference is back to its default.")
    return EXIT_OK


def _shown(value: Any) -> str:
    """A setting's value as typed back into `ccgen settings set`."""
    if value is None:
        return "auto"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


if __name__ == "__main__":
    sys.exit(main())
