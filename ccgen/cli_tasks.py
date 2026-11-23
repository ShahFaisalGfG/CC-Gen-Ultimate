# cli_tasks.py - the task and model commands of `ccgen` (see ccgen/cli.py)
#
# Each task command does what the app's tab does: the options start from the saved preferences,
# ccgen/core/jobs.py builds each file's job exactly as the tab builds it, and the files run one at a
# time on the same engine, holding the app's installer mutexes. This module loads the engine (torch,
# CTranslate2, the speech libraries) and the model catalog, so ccgen/cli.py imports it only for these
# commands.

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from typing import Any, Optional

from ccgen.api.schemas.job import parse_task_config
from ccgen.api.services import settings_service
from ccgen.api.services.job_manager import segment_event
from ccgen.cli import (
    AUTO,
    EXISTING,
    EXIT_FAILED,
    EXIT_OK,
    EXIT_STOPPED,
    Console,
    UsageError,
)
from ccgen.config import licences
from ccgen.config.defaults import DubbingDefaults, OutputDefaults
from ccgen.config.profiles import effective_profile
from ccgen.core import jobs
from ccgen.core.errors import describe, format_size
from ccgen.core.jobs import step_title
from ccgen.core.tasks import TaskResult, cancelled_result, create_task, failed_result
from ccgen.utils import asset_registry, workflow_presets
from ccgen.utils.app_mutex import hold_app_mutexes, release_app_mutexes
from ccgen.utils.helpers import duration_text, plural
from ccgen.utils.logging import get_log_file

_PROGRESS_EVERY_JSON = 0.5
_PROGRESS_EVERY_TEXT = 2.0


def run_tasks(args: argparse.Namespace, settings: dict[str, Any], console: Console) -> int:
    """Run a task on every usable file: as the app's tab does, one file at a time."""

    task = args.task
    if task == "workflow" and args.list:
        return _list_presets(console)
    if not args.inputs:
        raise UsageError("Name the files or folders to work on.")
    settings = _accept_terms(args.accept_terms, settings, console)
    files, unusable = jobs.expand_inputs(args.inputs, jobs.TASK_EXTS[task],
                                         lambda message: _warn(console, "", message))
    for path in unusable:
        _skip(console, path, _unusable_reason(path, task))
    if not files:
        raise UsageError(f"There's no {jobs.TASK_NOUNS[task]} to work on in {', '.join(args.inputs)}.")
    options = task_options(args, settings)
    steps = workflow_steps(args, settings) if task == "workflow" else None
    items = task_items(args, files)
    _check_runnable(task, items, options, settings, steps)
    bodies = _bodies(args, items, options, settings, steps)
    console_start(console, task, len(bodies))
    hold_app_mutexes()  # the installers wait while ccgen works, as they do for the app
    try:
        return _run_bodies(args, bodies, console)
    finally:
        release_app_mutexes()


def task_options(args: argparse.Namespace, settings: dict[str, Any]) -> dict[str, Any]:
    """The tab's options from the saved preferences, with the ones given on the command line."""
    options = jobs.TAB_OPTIONS[args.task](settings)
    given = {
        "output_dir": os.path.abspath(args.output_dir) if args.output_dir else None,
        "formats": _formats(args.formats) if getattr(args, "formats", None) else None,
        "max_line_length": getattr(args, "max_line_length", None),
        "max_lines": getattr(args, "max_lines", None),
        "model_name": getattr(args, "model", None),
        "device": getattr(args, "device", None),
        "compute_type": getattr(args, "compute_type", None),
        "beam_size": getattr(args, "beam_size", None),
        "vad_filter": getattr(args, "vad", None),
        "target_lang": getattr(args, "target_lang", None),
        "source_scheme": getattr(args, "source_scheme", None),
        "target_scheme": getattr(args, "target_scheme", None),
        "mode": getattr(args, "mode", None),
        "voice": getattr(args, "voice", None),
        "speakers": getattr(args, "speakers", None),
        "max_speakers": getattr(args, "max_speakers", None),
        "max_speedup": getattr(args, "max_speedup", None),
        "quality": getattr(args, "quality", None),
        "language": getattr(args, "dub_language", None),
    }
    if args.task in ("translate", "transliterate"):
        given["engine"] = args.engine
    spoken = getattr(args, "spoken_language", None)
    if spoken is not None:
        given["spoken_language" if args.task != "generate" else "language"] = "" if spoken == AUTO else spoken
    if getattr(args, "wav", False):
        given["output"] = DubbingDefaults.OUTPUT_WAV
    if getattr(args, "default_track", False):
        given["default_track"] = True
    if getattr(args, "cpu", False):
        given["device"] = DubbingDefaults.DEVICE_CPU
    for key, value in given.items():
        if value is not None and (key in options or key == "output_dir"):
            options[key] = value
    return options


def task_items(args: argparse.Namespace, files: list[str]) -> list[dict[str, Any]]:
    """The queued files as the job builders read them: subtitles with the language given for them,
    and for dubbing each video paired with the subtitle it speaks."""
    chosen = getattr(args, "subtitle_language", None) or ""
    if args.task != "dub":
        return [jobs.make_item(path, chosen if jobs.kind_of(path) == "subtitle" else "") for path in files]
    if args.subtitle:
        media = [p for p in files if jobs.ext_of(p) in jobs.MEDIA_EXTS]
        if len(media) != 1 or len(files) != 1:
            raise UsageError("--subtitle goes with one video or audio file.")
        if not os.path.isfile(args.subtitle) or jobs.ext_of(args.subtitle) not in jobs.SUBTITLE_EXTS:
            raise UsageError(f"{args.subtitle} isn't a subtitle file that's there.")
        return [jobs.make_item(media[0], chosen, os.path.abspath(args.subtitle))]
    media, companions, unpaired = jobs.pair_for_dub(files)
    items = [jobs.make_item(path, chosen if path in companions else "", companions.get(path, "")) for path in media]
    return items + [jobs.make_item(path, chosen) for path in unpaired]


def workflow_steps(args: argparse.Namespace, settings: dict[str, Any]) -> list[dict[str, Any]]:
    """The workflow's steps from --steps or --preset, each completed with the saved options."""
    if args.preset:
        steps = workflow_presets.get_preset(args.preset)
        if steps is None:
            names = workflow_presets.preset_names()
            known = f" Saved workflows: {', '.join(names)}." if names else " There are no saved workflows."
            raise UsageError(f'There\'s no saved workflow called "{args.preset}".{known}')
        raw: Any = steps
    else:
        try:
            with open(args.steps, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError) as error:
            raise UsageError(f"The steps file can't be read: {error}") from error
    if not isinstance(raw, list) or not raw:
        raise UsageError("The steps file holds a list of steps, such as [{\"kind\": \"generate\"}].")
    complete = []
    for number, step in enumerate(raw, 1):
        if not isinstance(step, dict) or step.get("kind") not in jobs.STEP_OPTIONS:
            raise UsageError(f"Step {number} needs a kind: {', '.join(jobs.STEP_OPTIONS)}.")
        default_input = "source" if number == 1 else f"step:{number - 2}"
        complete.append({**jobs.new_step(step["kind"], settings, default_input), **step})
    return complete


def _check_runnable(
    task: str, items: list[dict[str, Any]], options: dict[str, Any], settings: dict[str, Any],
    steps: Optional[list[dict[str, Any]]],
) -> None:
    """Refuse, in plain words, what the tab's Start button would refuse."""
    languages = tuple(lang for lang in (jobs.effective_language(i) or options.get("spoken_language", "")
                                        for i in items) if lang)
    pending = jobs.pending_licence(task, options, settings, languages, steps)
    if pending:
        terms = licences.TERMS[pending]
        raise UsageError(f"{terms.body} Ask the user whether they accept the {terms.title} ({terms.url}), and if "
                         f"they do, run the command again with --accept-terms {pending}.")
    problem = jobs.queue_blocker(task, items, options, settings, steps)
    if problem:
        raise UsageError(problem.replace(" in the queue", " with --subtitle-language"))


def _bodies(
    args: argparse.Namespace, items: list[dict[str, Any]], options: dict[str, Any], settings: dict[str, Any],
    steps: Optional[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Each file's job body, checked by the task configs before anything runs."""
    profile = {"profile": args.profile} if args.profile else {}
    bodies = []
    for item in items:
        try:
            if args.task == "dub" and args.reference:
                body = _reference_dub(args, item, options, settings)
            else:
                body = jobs.task_job(args.task, item, options, settings, steps)
            body = {**body, **profile, "existing": EXISTING[args.existing]}
            parse_task_config(body)
        except ValueError as error:
            raise UsageError(f"{os.path.basename(item['path'])}: {error}") from error
        bodies.append(body)
    return bodies


def _reference_dub(
    args: argparse.Namespace, item: dict[str, Any], options: dict[str, Any], settings: dict[str, Any],
) -> dict[str, Any]:
    """A subtitle spoken in the voice of a separate recording (the app's Dub tab has no such choice)."""
    if item["kind"] != "subtitle":
        raise ValueError("--reference is for a subtitle file on its own.")
    language = jobs.effective_language(item) or DubbingDefaults.LANGUAGE_AUTO
    if options["language"] not in (DubbingDefaults.LANGUAGE_AUTO, language):
        raise ValueError("--reference speaks the subtitle's own language; translate it first.")
    return {
        "task": "dub", "input_path": item["path"], "output_dir": options["output_dir"] or None,
        "language": language, "mode": options["mode"], "voice": options["voice"], "speakers": options["speakers"],
        "max_speakers": int(options["max_speakers"]), "max_speedup": float(options["max_speedup"]),
        "output": DubbingDefaults.OUTPUT_WAV, "default_track": False, "device": options["device"],
        "quality": options["quality"], "reference_audio": os.path.abspath(args.reference),
        "profile": effective_profile(settings),
    }


def _accept_terms(keys: list[str], settings: dict[str, Any], console: Console) -> dict[str, Any]:
    """Record the licences accepted with --accept-terms, as the app's licence notice does."""
    new = [key for key in dict.fromkeys(keys) if not licences.accepted(settings, key)]
    if not new:
        return settings
    try:
        settings = settings_service.set_many({licences.TERMS[key].setting: True for key in new})
    except (OSError, ValueError) as error:
        raise UsageError(f"The licence couldn't be recorded in the settings file: {error}") from error
    for key in new:
        _warn(console, "", f"Accepted the {licences.TERMS[key].title} on this PC.")
    return settings


def _run_bodies(args: argparse.Namespace, bodies: list[dict[str, Any]], console: Console) -> int:
    """Run each job in turn and report how it went; returns the exit status."""
    done = failed = skipped = 0
    written: list[str] = []
    started = time.monotonic()
    for index, body in enumerate(bodies, 1):
        path = body["input_path"]
        if body["existing"] == "skip":
            planned = jobs.planned_outputs(body)
            if planned and all(os.path.exists(p) for p in planned):
                skipped += 1
                _skip(console, path, "Its results are already there. Use --existing replace or --existing "
                                     "keep-both to make them again.")
                continue
        try:
            result = run_job(body, console, index, len(bodies), args.segments)
        except KeyboardInterrupt:
            return _finish(console, EXIT_STOPPED, done, failed, skipped, written, started, stopped=True)
        if result.cancelled:
            return _finish(console, EXIT_STOPPED, done, failed, skipped, written, started, stopped=True)
        for warning in result.warnings:
            _warn(console, path, warning)
        if result.success:
            done += 1
            for output in result.output_files:
                written.append(output)
                language = result.output_languages.get(output, "")
                if console.json:
                    console.emit("file", input=path, path=output, language=language)
                else:
                    print(output, file=console.out, flush=True)
        else:
            failed += 1
            # The task names the kind of problem; a result from elsewhere is classified by its text.
            kind = result.error_kind or describe(result.error_detail or result.error or "Unknown error", path).kind
            if console.json:
                console.emit("error", input=path, kind=kind, message=result.error, detail=result.error_detail)
            else:
                console.say(f"{os.path.basename(path)}: {result.error}")
    code = EXIT_FAILED if failed else EXIT_OK
    return _finish(console, code, done, failed, skipped, written, started)


def console_start(console: Console, task: str, count: int) -> None:
    """The run's first word."""
    if console.json:
        console.emit("start", command=task, files=count, log=get_log_file())
    else:
        console.say(f"{task.capitalize()}: {plural(count, 'file')}.")


def _finish(
    console: Console, code: int, done: int, failed: int, skipped: int, written: list[str], started: float,
    stopped: bool = False,
) -> int:
    """The run's last word: the done event, or a summary line on stderr; returns `code`."""
    seconds = time.monotonic() - started
    parts = [f"{done} done"]
    if failed:
        parts.append(f"{failed} failed")
    if skipped:
        parts.append(f"{skipped} skipped")
    summary = ", ".join(parts) + f", {plural(len(written), 'file')} written, in {duration_text(seconds)}."
    message = f"Stopped. Run the command again to do the rest. {summary}" if stopped else summary
    if failed and not stopped:
        message += f" The log has the details: {get_log_file()}"
    if console.json:
        console.emit("done", ok=code == EXIT_OK, exit_code=code, message=message, done=done, failed=failed,
                     skipped=skipped, written=len(written), seconds=round(seconds, 1))
    else:
        console.say(message)
    return code


def run_job(body: dict[str, Any], console: Console, index: int, count: int, segments: bool = False) -> TaskResult:
    """Run one job body on a worker thread, reporting its progress; returns its TaskResult.

    Ctrl+C cancels the task, which stops at its next safe point, and is raised again once it has.
    """
    path = body["input_path"]
    task = create_task(parse_task_config(body))
    progress = _Progress(console, task, path, index, count, segments)
    outcome: dict[str, Any] = {}

    def work() -> None:
        try:
            task.prepare(progress.status, progress.progress)
            outcome["result"] = cancelled_result(path) if task.cancelled else \
                task.run(progress.status, progress.segment if segments else None, progress.progress)
        except Exception as error:  # prepare() raises on a model that fails to load
            outcome["result"] = cancelled_result(path) if task.cancelled else failed_result(path, error)

    progress.begin()
    worker = threading.Thread(target=work, name="ccgen-task", daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            time.sleep(0.1)  # sleeping, unlike join(), wakes for Ctrl+C on Windows
    except KeyboardInterrupt:
        task.cancel()
        console.say("Stopping at the next safe point...")
        while worker.is_alive():
            time.sleep(0.1)
        raise
    return outcome["result"]


class _Progress:
    """One file's status, progress (across its steps), and lines, as events or lines for people."""

    def __init__(self, console: Console, task: Any, path: str, index: int, count: int, segments: bool) -> None:
        self._console = console
        self._task = task
        self._path = path
        self._name = os.path.basename(path)
        self._index = index
        self._count = count
        self._segments = segments
        self._step = 0
        self._step_done = 0.0
        self._last = 0.0
        self._status = ""

    def begin(self) -> None:
        if self._console.json:
            self._console.emit("item", input=self._path, index=self._index, count=self._count)
        else:
            self._console.say(f"[{self._index}/{self._count}] {self._name}")

    def status(self, message: str) -> None:
        self._enter_step()
        if message == self._status:
            return
        self._status = message
        if self._console.json:
            self._console.emit("status", input=self._path, message=message, step=self._task.step + 1,
                               steps=len(self._task.stages))
        else:
            self._console.say(f"  {message}")

    def progress(self, done: int, total: int) -> None:
        self._enter_step()
        if total > 0:
            self._step_done = max(self._step_done, min(1.0, done / total))
        now = time.monotonic()
        every = _PROGRESS_EVERY_JSON if self._console.json else _PROGRESS_EVERY_TEXT
        if now - self._last < every and not (total > 0 and done >= total):
            return
        self._last = now
        steps = max(1, len(self._task.stages))
        fraction = min(1.0, (self._step + self._step_done) / steps)
        overall = min(1.0, (self._index - 1 + fraction) / max(1, self._count))
        if self._console.json:
            self._console.emit("progress", input=self._path, index=self._index, count=self._count,
                               step=self._step + 1, steps=steps, stage=self._task.stage,
                               step_fraction=round(self._step_done, 4), fraction=round(fraction, 4),
                               overall=round(overall, 4))
        else:
            self._console.say(f"  {round(fraction * 100)}%  {self._status}".rstrip())

    def segment(self, segment: Any) -> None:
        if self._console.json and self._segments:
            event = segment_event(segment, self._task.stage, self._task.step + 1)
            event.pop("event", None)
            self._console.emit("segment", input=self._path, **event)

    def _enter_step(self) -> None:
        step = self._task.step
        if step != self._step:
            self._step, self._step_done = step, 0.0


def _skip(console: Console, path: str, reason: str) -> None:
    if console.json:
        console.emit("skipped", input=path, reason=reason)
    else:
        console.say(f"Skipped {os.path.basename(path) or path}: {reason}")


def _warn(console: Console, path: str, message: str) -> None:
    if console.json:
        console.emit("warning", input=path, message=message)
    else:
        console.say(f"{os.path.basename(path)}: {message}" if path else message)


def _unusable_reason(path: str, task: str) -> str:
    if not os.path.exists(path):
        return "It isn't there."
    if task == "generate" and jobs.ext_of(path) in jobs.SUBTITLE_EXTS:
        return "generate makes subtitles from video or audio; use translate, transliterate, or dub for subtitles."
    return f"{task} needs a {jobs.TASK_NOUNS[task]}."


def _formats(text: str) -> list[str]:
    formats = [part.strip().lower().lstrip(".") for part in text.split(",") if part.strip()]
    unknown = [f for f in formats if f not in OutputDefaults.FORMATS]
    if unknown:
        raise UsageError(f"Unknown subtitle format: {', '.join(unknown)}. Use {', '.join(OutputDefaults.FORMATS)}.")
    return formats


def _list_presets(console: Console) -> int:
    store = workflow_presets.load_store()
    presets = {name: [step_title(step) for step in steps] for name, steps in sorted(store["presets"].items())}
    text = "\n".join(f"{name}: {', then '.join(titles)}" for name, titles in presets.items()) \
        or "There are no saved workflows. Save one in the app's Workflow tab."
    console.result({"presets": [{"name": name, "steps": store["presets"][name]} for name in presets]}, text)
    return EXIT_OK


# ── Models ────────────────────────────────────────────────────────────────────


def run_models(args: argparse.Namespace, console: Console) -> int:
    """List, download, or delete models, as Manage Models does."""
    if args.models_action == "list":
        rows = [dict(row) for row in asset_registry.list_assets()
                if (not args.category or row["category"] == args.category)
                and (not args.downloaded or row["downloaded"])]
        text = "\n".join(_model_line(row) for row in rows) or "No models match."
        console.result({"models": rows}, text)
        return EXIT_OK
    known = {row["id"] for row in asset_registry.list_assets()}
    unknown = [asset for asset in args.ids if asset not in known]
    if unknown:
        raise UsageError(f"Unknown model: {', '.join(unknown)}. `ccgen models list` shows the ids.")
    if args.models_action == "delete":
        return _delete_models(args.ids, console)
    return _download_models(args.ids, console)


def _model_line(row: dict[str, Any]) -> str:
    size = row.get("size_bytes") or (row.get("approx_size_mb") or 0) * 1_000_000
    state = "downloaded" if row["downloaded"] else "not downloaded"
    return f"{row['id']:<34} {row['engine']}: {row['label']}  ({format_size(size)}, {state})"


def _delete_models(ids: list[str], console: Console) -> int:
    deleted, failed = [], []
    for asset in ids:
        try:
            asset_registry.delete_asset(asset)
            deleted.append(asset)
        except RuntimeError as error:
            failed.append({"id": asset, "error": describe(error).message})
    lines = [f"Deleted {asset}" for asset in deleted] + [f"Couldn't delete {f['id']}: {f['error']}" for f in failed]
    console.result({"ok": not failed, "deleted": deleted, "failed": failed}, "\n".join(lines))
    return EXIT_FAILED if failed else EXIT_OK


def _download_models(ids: list[str], console: Console) -> int:
    done, failed = 0, 0
    hold_app_mutexes()
    try:
        for asset in ids:
            if _download_one(asset, console):
                done += 1
            else:
                failed += 1
    except KeyboardInterrupt:
        return _models_done(console, EXIT_STOPPED, done, failed, "Stopped. Run the command again to finish.")
    finally:
        release_app_mutexes()
    return _models_done(console, EXIT_FAILED if failed else EXIT_OK, done, failed,
                        f"{done} downloaded" + (f", {failed} failed." if failed else "."))


def _download_one(asset: str, console: Console) -> bool:
    """Download one model with progress; True when it finished. Ctrl+C cancels it and is raised again."""
    cancel = threading.Event()
    last = [0.0]

    def progress(done: int, total: int) -> None:
        now = time.monotonic()
        if now - last[0] < (_PROGRESS_EVERY_JSON if console.json else _PROGRESS_EVERY_TEXT) and done < total:
            return
        last[0] = now
        if console.json:
            console.emit("progress", id=asset, downloaded=done, total=total,
                         fraction=round(done / total, 4) if total else -1)
        elif total:
            console.say(f"  {round(done / total * 100)}%  {format_size(done)} of {format_size(total)}")

    try:
        asset_registry.check_free_space(asset)
    except OSError as error:  # its strerror says how much space the download needs, and where
        _model_error(console, asset, error.strerror or describe(error).message, str(error))
        return False
    if console.json:
        console.emit("item", id=asset)
    else:
        console.say(f"Downloading {asset}")
    outcome: dict[str, Any] = {}

    def work() -> None:
        try:
            asset_registry.download_asset(asset, None, progress, cancel.is_set)
        except Exception as error:
            outcome["error"] = error

    worker = threading.Thread(target=work, name="ccgen-download", daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            time.sleep(0.1)
    except KeyboardInterrupt:
        cancel.set()
        console.say("Stopping the download...")
        while worker.is_alive():
            time.sleep(0.1)
        raise
    error = outcome.get("error")
    if error is not None:
        problem = describe(error)
        _model_error(console, asset, problem.message, problem.detail)
        return False
    if console.json:
        console.emit("file", id=asset)
    else:
        console.say(f"Downloaded {asset}")
    return True


def _model_error(console: Console, asset: str, message: str, detail: str) -> None:
    if console.json:
        console.emit("error", id=asset, message=message, detail=detail)
    else:
        console.say(f"{asset}: {message}")


def _models_done(console: Console, code: int, done: int, failed: int, message: str) -> int:
    if console.json:
        console.emit("done", ok=code == EXIT_OK, exit_code=code, message=message, done=done, failed=failed)
    else:
        console.say(message)
    return code
