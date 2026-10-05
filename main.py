# main.py - CLI entry point for CC-Gen-Ultimate (runs one task without the UI)

import argparse
import io
import json
import os
import sys
from typing import Any, Callable, NoReturn

from ccgen.api.schemas.job import parse_task_config
from ccgen.config.defaults import (
    ComputeDefaults,
    DubbingDefaults,
    ModelDefaults,
    OutputDefaults,
    TranslationDefaults,
    TransliterationDefaults,
)
from ccgen.config.translation_models import ENGINE_KEYS as TRANSLATION_ENGINE_KEYS
from ccgen.core.tasks import create_task
from ccgen.core.tasks.configs import SUBTITLE_FORMATS
from ccgen.utils.logging import configure_logging


def main() -> None:
    """Parse CLI arguments and run the chosen task on one file."""
    # Statuses and subtitles carry characters (→, Urdu, Devanagari) a legacy Windows console
    # code page can't encode; print a placeholder for those instead of raising mid-run.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    args = _parse_args()
    configure_logging(enabled=False)
    if not os.path.isfile(args.input):
        _fail(f"File not found: {args.input}")
    try:
        config = parse_task_config(args.build(args))
    except ValueError as e:
        _fail(str(e))
    task = create_task(config)
    try:
        task.prepare(status_cb=_print_progress)
    except Exception as e:
        _fail(str(e))

    result = task.run(status_cb=_print_progress)
    if not result.success:
        _fail(result.error)
    if result.detected_language:
        print(f"\nLanguage : {result.detected_language}")
    for warning in result.warnings:
        print(f"Warning  : {warning}")
    print("Output files:")
    for path in result.output_files:
        print(f"  {path}")


def _parse_args() -> argparse.Namespace:
    """Build and return the parsed CLI argument namespace."""
    parser = argparse.ArgumentParser(
        prog="ccgen",
        description="Generate, translate, transliterate, and dub subtitles offline.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    generate = _command(commands, "generate", "Transcribe a video or audio file into subtitles.", _generate_body)
    generate.add_argument(
        "--model", default=ModelDefaults.DEFAULT_MODEL, choices=ModelDefaults.SUPPORTED_MODELS,
        help=f"Whisper model (default: {ModelDefaults.DEFAULT_MODEL}).",
    )
    generate.add_argument(
        "--device", default=ComputeDefaults.DEFAULT_DEVICE, choices=ComputeDefaults.SUPPORTED_DEVICES,
        help="Compute device; auto uses a CUDA GPU when available (default: auto).",
    )
    generate.add_argument(
        "--compute-type", default=ComputeDefaults.DEFAULT_COMPUTE_TYPE,
        choices=ComputeDefaults.SUPPORTED_COMPUTE_TYPES,
        help="CTranslate2 compute type; auto picks float16 on GPU, int8 on CPU (default: auto).",
    )
    generate.add_argument("--language", default=None, help="Spoken language code, e.g. en. Default: auto-detect.")

    translate = _command(commands, "translate", "Translate a subtitle file.", _translate_body)
    translate.add_argument(
        "--source-lang", default=TranslationDefaults.DEFAULT_SOURCE_LANG,
        help="Language of the subtitles; auto reads a _xx file-name suffix (default: auto).",
    )
    translate.add_argument(
        "--target-lang", default=TranslationDefaults.DEFAULT_TARGET_LANG,
        help=f"Language to translate into (default: {TranslationDefaults.DEFAULT_TARGET_LANG}).",
    )
    translate.add_argument(
        "--engine", choices=TRANSLATION_ENGINE_KEYS, default=TranslationDefaults.DEFAULT_ENGINE,
        help=f"Translation model (default: {TranslationDefaults.DEFAULT_ENGINE}).",
    )
    translate.add_argument(
        "--no-meaning-check", action="store_true",
        help="Skip comparing each translation with the original sentence.",
    )

    transliterate = _command(
        commands, "transliterate", "Convert a subtitle file to another script.", _transliterate_body,
    )
    transliterate.add_argument(
        "--source", default=TransliterationDefaults.DEFAULT_SOURCE,
        help=f"Script the subtitles are written in (default: {TransliterationDefaults.DEFAULT_SOURCE}).",
    )
    transliterate.add_argument(
        "--target", default=TransliterationDefaults.DEFAULT_TARGET,
        help=f"Script to convert into (default: {TransliterationDefaults.DEFAULT_TARGET}).",
    )
    transliterate.add_argument(
        "--engine", default=TransliterationDefaults.DEFAULT_ENGINE,
        choices=[TransliterationDefaults.ENGINE_RULE, TransliterationDefaults.ENGINE_NEURAL],
        help=f"Transliteration engine (default: {TransliterationDefaults.DEFAULT_ENGINE}).",
    )

    dub = _command(
        commands, "dub", "Speak a subtitle file and add it to a video or audio file as a new track.",
        _dub_body, subtitles=False,
    )
    dub.add_argument("--subtitle", default=None, help="Subtitle file to speak (required for video/audio input).")
    dub.add_argument(
        "--language", default=DubbingDefaults.LANGUAGE_AUTO,
        help="Language of the subtitles; auto reads a _xx file-name suffix (default: auto).",
    )
    dub.add_argument(
        "--mode", default=DubbingDefaults.DEFAULT_MODE, choices=[code for _, code, _ in DubbingDefaults.MODES],
        help="xtts clones the original voices; kokoro and piper use stock voices (default: xtts).",
    )
    dub.add_argument("--voice", default=DubbingDefaults.VOICE_AUTO, help="Kokoro/Piper voice key, e.g. piper:ur_PK-fasih-medium.")
    dub.add_argument(
        "--speakers", default=DubbingDefaults.DEFAULT_SPEAKERS, choices=[code for _, code in DubbingDefaults.SPEAKERS],
        help="Clone each detected speaker, or one voice for everyone (default: auto).",
    )
    dub.add_argument(
        "--max-speedup", type=float, default=DubbingDefaults.MAX_SPEEDUP,
        help=f"Fastest speech allowed to fit a line's time (default: {DubbingDefaults.MAX_SPEEDUP}).",
    )
    dub.add_argument("--wav", action="store_true", help="Write a separate WAV file instead of adding a track.")
    dub.add_argument("--default-track", action="store_true", help="Make the dub the default audio track.")
    dub.add_argument("--cpu", action="store_true", help="Never use the GPU.")
    dub.add_argument(
        "--no-script-bridge", action="store_true",
        help="With xtts, dub Urdu with a Piper voice instead of reading it in Hindi script.",
    )
    dub.add_argument("--reference", default=None, help="Recording of the voice to clone (for subtitle-only input).")

    workflow = _command(commands, "workflow", "Run a chain of steps described in a JSON file.", _workflow_body)
    workflow.add_argument(
        "steps", help='JSON file with the step list, e.g. [{"kind": "generate"}, '
                      '{"kind": "translate", "input": "step:0", "target_lang": "ur"}]',
    )
    return parser.parse_args()


def _command(
    commands: Any,
    name: str,
    description: str,
    build: Callable[[argparse.Namespace], dict[str, Any]],
    subtitles: bool = True,
) -> argparse.ArgumentParser:
    """Add a subcommand with the input and output options, plus subtitle layout when it writes subtitles."""
    parser = commands.add_parser(name, help=description, description=description)
    parser.set_defaults(build=build)
    parser.add_argument("input", help="File to process")
    parser.add_argument("--output-dir", default=None, help="Folder for output files (default: next to the input).")
    if not subtitles:
        return parser
    parser.add_argument(
        "--formats", default=OutputDefaults.DEFAULT_FORMAT,
        help=f"Comma-separated subtitle formats: {', '.join(SUBTITLE_FORMATS)} (default: srt).",
    )
    parser.add_argument(
        "--max-line-length", type=int, default=OutputDefaults.MAX_LINE_LENGTH,
        help=f"Characters per subtitle line (default: {OutputDefaults.MAX_LINE_LENGTH}).",
    )
    parser.add_argument(
        "--max-lines", type=int, default=OutputDefaults.MAX_LINES,
        help=f"Lines per subtitle cue (default: {OutputDefaults.MAX_LINES}).",
    )
    return parser


def _common_body(args: argparse.Namespace, task: str) -> dict[str, Any]:
    """Request fields shared by every subtitle-writing task."""
    return {
        "task": task,
        "input_path": os.path.abspath(args.input),
        "output_dir": args.output_dir,
        "formats": [f.strip().lower() for f in args.formats.split(",") if f.strip()],
        "max_line_length": args.max_line_length,
        "max_lines": args.max_lines,
    }


def _generate_body(args: argparse.Namespace) -> dict[str, Any]:
    """Request body for the generate subcommand."""
    return {
        **_common_body(args, "generate"),
        "model_name": args.model, "device": args.device,
        "compute_type": args.compute_type, "language": args.language,
    }


def _translate_body(args: argparse.Namespace) -> dict[str, Any]:
    """Request body for the translate subcommand."""
    return {
        **_common_body(args, "translate"), "source_lang": args.source_lang, "target_lang": args.target_lang,
        "engine": args.engine, "meaning_check": not args.no_meaning_check,
    }


def _transliterate_body(args: argparse.Namespace) -> dict[str, Any]:
    """Request body for the transliterate subcommand."""
    return {
        **_common_body(args, "transliterate"),
        "source_scheme": args.source, "target_scheme": args.target, "engine": args.engine,
    }


def _dub_body(args: argparse.Namespace) -> dict[str, Any]:
    """Request body for the dub subcommand."""
    return {
        "task": "dub", "input_path": os.path.abspath(args.input), "output_dir": args.output_dir,
        "subtitle_path": os.path.abspath(args.subtitle) if args.subtitle else None,
        "language": args.language, "mode": args.mode, "voice": args.voice, "speakers": args.speakers,
        "max_speedup": args.max_speedup,
        "output": DubbingDefaults.OUTPUT_WAV if args.wav else DubbingDefaults.OUTPUT_TRACK,
        "default_track": args.default_track,
        "device": DubbingDefaults.DEVICE_CPU if args.cpu else DubbingDefaults.DEVICE_AUTO,
        "script_bridge": not args.no_script_bridge,
        "reference_audio": os.path.abspath(args.reference) if args.reference else None,
    }


def _workflow_body(args: argparse.Namespace) -> dict[str, Any]:
    """Request body for the workflow subcommand, reading its steps from a JSON file."""
    try:
        with open(args.steps, encoding="utf-8") as fh:
            steps = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        _fail(f"Can't read the steps file: {e}")
    return {**_common_body(args, "workflow"), "steps": steps}


def _print_progress(msg: str) -> None:
    """Print a task status message to stdout."""
    print(f"  {msg}")


def _fail(message: str) -> NoReturn:
    """Print an error and exit with a failure status."""
    print(f"[ERROR] {message}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
