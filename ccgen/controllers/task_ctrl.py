# task_ctrl.py - one tab's file queue, options, and queue runner (client of the embedded API)
#
# Every task tab (Generate, Translate, Transliterate, Dub, Workflow) owns one of these. Each file
# in the queue runs as its own API job, one after another: start job, stream its events, record
# the result on the file's row, move to the next file. Cancelling stops the running file at its
# next safe point and leaves it and the remaining files pending, so Start resumes where it stopped.
#
# A tab's options and the job body for each file come from ccgen/core/jobs.py, shared with the
# command line. Whether the options can run is decided by the API's own config validation
# (POST /jobs/validate), so the Start button and the backend can never disagree.
#
# Before a run, files whose results are already there are found, and the tab asks once what to do
# with them (replace, keep both, or skip); nothing is replaced without that answer.

import os
import time
from typing import Any, Optional

from PySide6.QtCore import Property, QObject, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWebSockets import QWebSocket

from ccgen.controllers.api_client import ApiClient
from ccgen.core import jobs
from ccgen.core.errors import describe
from ccgen.core.tasks.configs import EXISTING_CHOICES, EXISTING_KEEP_BOTH, EXISTING_SKIP, SUBTITLE_FORMATS
from ccgen.models.file_model import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PROCESSING,
    STATUS_SKIPPED,
    MediaFileModel,
)
from ccgen.services.folder_scanner import FolderScanWorker
from ccgen.utils.helpers import duration_text, plural, to_local_path
from ccgen.utils.model_needs import download_note, missing_models

_VALIDATE_DELAY_MS = 250
_CLOCK_MS = 1000
# The time left is only guessed once a run has gone this long and this far.
_ESTIMATE_AFTER_S = 15.0
_ESTIMATE_AFTER_PROGRESS = 0.03


class TaskController(QObject):
    """Runs one task over a queue of files. Subclasses name the task; ccgen/core/jobs.py shapes it."""

    # Overridden by each task tab.
    task_key = ""
    accepted_exts: frozenset[str] = frozenset()
    file_noun = "file"
    # Placeholder input for validating options while the queue is empty.
    sample_input = "example.mp4"
    # Options that only make sense with another option's current value: changing the key
    # resets the listed options (e.g. a Piper voice after switching to Kokoro).
    option_resets: dict[str, dict[str, Any]] = {}

    busyChanged       = Signal(bool)
    optionsChanged    = Signal()
    runStateChanged   = Signal()
    scanChanged       = Signal()
    blockerChanged    = Signal()
    segmentAdded      = Signal(int, float, float, str, str, int)  # (id, start, end, text, kind, step)
    fileStarted       = Signal(str, str)        # (path, file name)
    notice            = Signal(str)             # one-off message shown to the user
    textLanguageChanged = Signal()
    # Files in the run already have results: (how many, one of their names). Answer with startWith().
    existingFound     = Signal(int, str)
    # A run ended: (summary, files done, files failed, seconds it took, cancelled).
    runFinished       = Signal(str, int, int, float, bool)

    def __init__(self, base_url: str, parent=None):
        super().__init__(parent)
        self._api = ApiClient(base_url, self)
        self._file_model = MediaFileModel(self)
        self._socket: Optional[QWebSocket] = None
        self._job_id: Optional[str] = None
        self._busy = False

        self._options: dict[str, Any] = self.initial_options()
        self._edited: set[str] = set()
        self._deferred_settings: Optional[dict[str, Any]] = None
        self._saved_settings: dict[str, Any] = {}
        self._server_errors: list[str] = []
        self._download_note = ""
        self._output_language: dict[str, str] = {}

        self._run_paths: list[str] = []
        self._run_index = -1
        self._run_ok = 0
        self._run_failed = 0
        self._run_skipped = 0
        self._existing = EXISTING_KEEP_BOTH
        # The files a run waits to start on while the user answers existingFound.
        self._pending_paths: list[str] = []
        self._cancel_requested = False
        self._current_path = ""
        self._stage = ""
        self._stage_progress = -1.0
        self._step = 0
        self._steps = 1
        # How far the current step got; kept when a status message makes its progress unknown.
        self._step_done = 0.0
        self._summary = ""
        self._last_outputs: list[str] = []
        self._failed: list[dict[str, str]] = []
        self._started_at = 0.0
        self._elapsed = 0.0

        self._scan: Optional[FolderScanWorker] = None
        self._scan_found = 0

        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(_VALIDATE_DELAY_MS)
        self._validate_timer.timeout.connect(self._validate)
        # Ticks the elapsed time while a run goes on.
        self._clock = QTimer(self)
        self._clock.setInterval(_CLOCK_MS)
        self._clock.timeout.connect(self.runStateChanged)
        self._file_model.countChanged.connect(lambda _count: self._schedule_validation())
        self._file_model.inputsChanged.connect(self._schedule_validation)
        self.optionsChanged.connect(self.textLanguageChanged)

        self._api.get("/settings", self._on_defaults_fetched)

    # ── Task shape (ccgen/core/jobs.py) ──────────────────────────────────────

    def initial_options(self) -> dict[str, Any]:
        """Options before the saved preferences arrive."""
        return self.options_from_settings({})

    def options_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Map saved preferences onto this task's options."""
        return jobs.TAB_OPTIONS[self.task_key](settings)

    def job_steps(self) -> Optional[list[dict[str, Any]]]:
        """The workflow's steps (the Workflow tab only)."""
        return None

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        """The API job body for one queued file (`item` is its row), with the saved performance profile.

        Raises ValueError with a readable message when this file can't run. `validating` is
        True when checking the options against a placeholder file.
        """
        return jobs.task_job(self.task_key, item, self._options, self._saved_settings, self.job_steps(), validating)

    def _job(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        """The job body with this run's answer for results that are already there."""
        return {**self.job_body(item, validating), "existing": self._existing}

    def add_paths(self, paths: list[str]) -> None:
        """Add files to the queue (the Dub tab pairs subtitles with their media here)."""
        self._file_model.addFiles(paths)

    def extra_blocker(self) -> str:
        """A licence that must be accepted before Start, checked after the API's validation."""
        return jobs.licence_blocker(self.task_key, self._options, self._saved_settings, (), self.job_steps())

    def queue_blocker(self, items: list[dict[str, Any]]) -> str:
        """Why a queued file can't run with the current options, or "" when all of them can."""
        return jobs.queue_blocker(self.task_key, items, self._options, self._saved_settings, self.job_steps())

    def needs_text_language(self) -> bool:
        """Whether every subtitle's language must be known to run with the current options."""
        return jobs.needs_text_language(self.task_key, self._options, self.job_steps())

    # ── Queue and status properties ──────────────────────────────────────────

    @Property(str, constant=True)
    def taskKey(self) -> str:
        """Which task this controller runs ("generate", "translate", ...)."""
        return self.task_key

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        """True while the queue is being processed."""
        return self._busy

    @Property(QObject, constant=True)
    def fileModel(self) -> MediaFileModel:
        """This tab's file queue."""
        return self._file_model

    @Property(list, constant=True)
    def acceptedExtensions(self) -> list:
        """File extensions this tab accepts, without dots, for the file picker."""
        return sorted(ext.lstrip(".") for ext in self.accepted_exts)

    @Property(str, constant=True)
    def fileNoun(self) -> str:
        """What this tab works on, e.g. "video or audio file", for prompts."""
        return self.file_noun

    @Property(bool, notify=scanChanged)
    def scanning(self) -> bool:
        """True while a folder scan is adding files in the background."""
        return self._scan is not None

    @Property(int, notify=scanChanged)
    def scanFound(self) -> int:
        """Files found so far by the running folder scan."""
        return self._scan_found

    @Property(str, notify=runStateChanged)
    def currentFile(self) -> str:
        """Name of the file being processed, empty when idle."""
        return os.path.basename(self._current_path)

    @Property(int, notify=runStateChanged)
    def runPosition(self) -> int:
        """1-based position of the current file within this run."""
        return self._run_index + 1 if self._busy else 0

    @Property(int, notify=runStateChanged)
    def runTotal(self) -> int:
        """Number of files in the current run."""
        return len(self._run_paths)

    @Property(str, notify=runStateChanged)
    def stage(self) -> str:
        """What the current file is doing (loading a model, transcribing, speaking...)."""
        return self._stage

    @Property(float, notify=runStateChanged)
    def stageProgress(self) -> float:
        """Progress of the current step from 0 to 1, or -1 when it can't be measured."""
        return self._stage_progress

    @Property(float, notify=runStateChanged)
    def fileProgress(self) -> float:
        """Progress of the current file across all of its steps, from 0 to 1."""
        return self._file_fraction()

    @Property(float, notify=runStateChanged)
    def overallProgress(self) -> float:
        """Progress of the whole run from 0 to 1; never moves backwards between steps."""
        return self._overall()

    @Property(str, notify=runStateChanged)
    def timeText(self) -> str:
        """Elapsed and estimated remaining time during a run ("4 min so far, about 6 min left"),
        then how long the last run took."""
        if not self._busy:
            return f"Took {duration_text(self._elapsed)}." if self._elapsed >= 1 else ""
        elapsed = self._seconds_running()
        text = f"{duration_text(elapsed)} so far"
        progress = self._overall()
        if elapsed >= _ESTIMATE_AFTER_S and progress >= _ESTIMATE_AFTER_PROGRESS:
            text += f", about {duration_text(elapsed * (1 - progress) / progress)} left"
        return text

    @Property(str, notify=runStateChanged)
    def summary(self) -> str:
        """One-line result of the last finished run."""
        return self._summary

    @Property(str, notify=runStateChanged)
    def lastOutputFolder(self) -> str:
        """Folder holding the most recently written file."""
        return os.path.dirname(self._last_outputs[-1]) if self._last_outputs else ""

    @Property(list, notify=runStateChanged)
    def lastOutputs(self) -> list:
        """Every file the last run wrote, for "Send all results to"."""
        return list(self._last_outputs)

    @Property(list, notify=runStateChanged)
    def failedFiles(self) -> list:
        """The files the last run couldn't finish: [{path, name, message}]."""
        return list(self._failed)

    # ── Options ──────────────────────────────────────────────────────────────

    @Property("QVariantMap", notify=optionsChanged)  # type: ignore[arg-type]
    def options(self) -> dict:
        """Every option of this task, by name."""
        return self._options

    @Slot(str, "QVariant")
    def setOption(self, key: str, value: Any) -> None:
        """Change one option for this session; it stays as set when preferences are saved."""
        if key not in self._options:
            return
        if key == "output_dir":
            value = to_local_path(value) if value else ""
        self._edited.add(key)
        if self._options[key] != value:
            self._options[key] = value
            for dependent, reset in self.option_resets.get(key, {}).items():
                self._options[dependent] = reset
            self.optionsChanged.emit()
            self._schedule_validation()

    @Slot(str, bool)
    def setFormat(self, fmt: str, enabled: bool) -> None:
        """Turn one subtitle format on or off."""
        if fmt not in SUBTITLE_FORMATS or "formats" not in self._options:
            return
        formats = [f for f in self._options["formats"] if f != fmt]
        if enabled:
            formats.append(fmt)
        self.setOption("formats", [f for f in SUBTITLE_FORMATS if f in formats])

    @Slot()
    def reloadDefaults(self) -> None:
        """Re-seed options from saved preferences, keeping any option changed in this session."""
        self._api.get("/settings", self._on_defaults_fetched)

    @Property(bool, notify=textLanguageChanged)
    def needsSubtitleLanguage(self) -> bool:
        """True when a subtitle row without a known language blocks Start (its picker is required)."""
        return self.needs_text_language()

    @Property(str, notify=blockerChanged)
    def blocker(self) -> str:
        """Why Start is unavailable right now, or "" when the queue can run."""
        if self._scan is not None:
            return "Wait for the folder scan to finish (or stop it)."
        if self._file_model.count == 0:
            return f"Add a {self.file_noun} to the queue first."
        return self._server_errors[0] if self._server_errors else self.extra_blocker()

    @Property(str, notify=blockerChanged)
    def pendingLicence(self) -> str:
        """The model whose licence Start waits for ("" when none), so the run bar can offer it."""
        if self._scan is not None or self._file_model.count == 0:
            return ""
        items = self._runnable_items()
        languages = tuple(lang for lang in (jobs.effective_language(i) or self._options.get("spoken_language", "")
                                            for i in items) if lang)
        return jobs.pending_licence(self.task_key, self._options, self._saved_settings, languages, self.job_steps())

    @Property(str, notify=blockerChanged)
    def downloadNote(self) -> str:
        """What Start downloads before it works, and about how long that takes ("" when nothing)."""
        return self._download_note

    @Property(str, notify=blockerChanged)
    def blockingPath(self) -> str:
        """The queued subtitle whose language must be chosen before Start ("" when none)."""
        if not self.needs_text_language():
            return ""
        for item in self._runnable_items():
            if jobs.has_text(item) and not jobs.effective_language(item):
                return str(item["path"])
        return ""

    @Property(str, notify=blockerChanged)
    def reliesOn(self) -> str:
        """The saved choices this tab runs with besides its own options, in a sentence ("" for none)."""
        return jobs.relies_on(self.task_key, self._options, self._saved_settings)

    @Slot(str, result=str)
    def outputLanguage(self, path: str) -> str:
        """Language of the text written for a finished file ("" when unknown)."""
        return self._output_language.get(_path_key(path), "")

    # ── File queue slots ─────────────────────────────────────────────────────

    @Slot(list)
    def addFiles(self, urls: list) -> None:
        """Add dropped or picked files; folders among them are scanned in the background."""
        paths = [to_local_path(u) for u in urls]
        folders = [p for p in paths if p and os.path.isdir(p)]
        files = [p for p in paths if p and p not in folders and jobs.ext_of(p) in self.accepted_exts]
        skipped = [p for p in paths if p and p not in folders and p not in files]
        before = self._file_model.count
        self.add_paths(files)
        if folders:
            self._start_scan(folders)
        if skipped:
            self.notice.emit(self._skipped_notice(skipped))
        elif files and self._file_model.count == before:
            self.notice.emit("Those files are already in the queue.")

    def _skipped_notice(self, skipped: list[str]) -> str:
        """Say how many files were left out, and which tab takes them when one does."""
        text = f"Skipped {plural(len(skipped), 'file')} this tab can't use"
        if all(jobs.ext_of(p) in jobs.SUBTITLE_EXTS for p in skipped):
            return text + "; subtitle files go to Translate, Transliterate, or Dub."
        return text + "."

    @Slot(list, str, list)
    def receiveFiles(self, paths: list, source: str, languages: list) -> None:
        """Take finished files handed over from another tab with each file's language."""
        known = dict(zip(paths, languages))
        usable = [p for p in paths if jobs.ext_of(p) in self.accepted_exts]
        if not usable:
            self.notice.emit(f"None of those files can be used here; this tab needs a {self.file_noun}.")
            return
        self.add_paths(usable)
        for path in usable:
            self._file_model.set_language(path, str(known.get(path) or ""))
        self.notice.emit(f"Added {plural(len(usable), 'file')}.")

    @Slot(str)
    def addFolder(self, folder_url: str) -> None:
        """Scan a folder and its subfolders for usable files, in the background."""
        folder = to_local_path(folder_url)
        if folder and os.path.isdir(folder):
            self._start_scan([folder])

    @Slot()
    def cancelScan(self) -> None:
        """Stop the running folder scan; files already found stay in the queue."""
        if self._scan is not None:
            self._scan.cancel()

    @Slot()
    def clearQueue(self) -> None:
        """Stop any folder scan and remove every file that isn't being processed."""
        self.cancelScan()
        self._file_model.clearAll()

    # ── Processing slots ─────────────────────────────────────────────────────

    @Slot()
    def startQueue(self) -> None:
        """Process every unfinished file in the queue (or all files when all are done).

        When some of them already have results, existingFound asks first; startWith() answers.
        """
        self._start(self._file_model.runnable_paths(), ask=True)

    @Slot(str)
    def startWith(self, existing: str) -> None:
        """Start the run after the question about existing results: replace, keep_both, or skip."""
        if existing in EXISTING_CHOICES:
            paths, self._pending_paths = self._pending_paths or self._file_model.runnable_paths(), []
            self._start(paths, ask=False, existing=existing)

    @Slot()
    def retryFailed(self) -> None:
        """Run only the files the last run couldn't finish."""
        self._start([f["path"] for f in self._failed if self._file_model.item(f["path"]) is not None], ask=True)

    @Slot(str)
    def retryFile(self, path: str) -> None:
        """Run one file again."""
        if self._file_model.item(path) is not None:
            self._start([path], ask=True)

    @Slot()
    def cancelQueue(self) -> None:
        """Stop the running file at its next safe point; it and the rest stay in the queue."""
        if not self._busy or self._cancel_requested:
            return
        self._cancel_requested = True
        self._set_stage("Stopping...", -1.0)
        if self._job_id is not None:
            self._api.post(f"/jobs/{self._job_id}/cancel")

    def _start(self, paths: list[str], ask: bool, existing: str = EXISTING_KEEP_BOTH) -> None:
        """Start a run over `paths`, first asking what to do with results already there."""
        if self._busy:
            return
        if self.blocker:
            self.notice.emit(self.blocker)
            return
        if not paths:
            return
        if ask:
            clashes = self._files_with_results(paths)
            if clashes:
                self._pending_paths = paths
                self.existingFound.emit(len(clashes), os.path.basename(clashes[0]))
                return
        self._existing = existing
        self._file_model.reset_for_run(paths)
        self._run_paths = paths
        self._run_index = -1
        self._run_ok = self._run_failed = self._run_skipped = 0
        self._cancel_requested = False
        self._summary = ""
        self._last_outputs = []
        self._failed = []
        self._started_at = jobs_clock()
        self._elapsed = 0.0
        self._set_busy(True)
        self._clock.start()
        self._start_next()

    def _files_with_results(self, paths: list[str]) -> list[str]:
        """The files among `paths` whose results (as far as they can be told) are already there."""
        found = []
        for path in paths:
            item = self._file_model.item(path)
            if item is None:
                continue
            try:
                body = self._job(item)
            except ValueError:
                continue
            if jobs.existing_outputs(body):
                found.append(path)
        return found

    # ── Queue runner ─────────────────────────────────────────────────────────

    def _start_next(self) -> None:
        """Start the next file still in the queue, or finish the run.

        Files that can't even start (e.g. a dub with no subtitle) are recorded in this loop
        rather than by recursion, so a queue of thousands of them can't overflow the stack.
        """
        while True:
            self._run_index += 1
            if self._cancel_requested or self._run_index >= len(self._run_paths):
                self._finish_run()
                return
            path = self._run_paths[self._run_index]
            item = self._file_model.item(path)
            if item is None:
                continue
            self._current_path = path
            self._job_id = None
            self._step, self._steps, self._step_done = 0, 1, 0.0
            try:
                body = self._job(item)
            except ValueError as e:
                self._file_model.set_run_state(path, status=STATUS_PROCESSING, progress=0.0)
                self._record_result({"success": False, "error": str(e)})
                continue
            if self._existing == EXISTING_SKIP and _all_there(body):
                self._run_skipped += 1
                self._file_model.set_run_state(path, status=STATUS_SKIPPED, progress=0.0,
                                               message="Skipped: its results are already there.", detail="")
                continue
            self._file_model.set_run_state(path, status=STATUS_PROCESSING, progress=0.0)
            self._set_stage("Starting...", -1.0)
            self.fileStarted.emit(path, os.path.basename(path))
            self._api.post("/jobs", body, self._on_job_started)
            return

    def _on_job_started(self, data: Any, error: str) -> None:
        """Open the job's event stream, or record the failure and move on."""
        if error or not isinstance(data, dict) or "job_id" not in data:
            self._on_file_finished({"success": False, "error": error or "The job could not be started."})
            return
        self._job_id = str(data["job_id"])
        if self._cancel_requested:
            self._api.post(f"/jobs/{self._job_id}/cancel")
        self._socket = self._api.open_stream(f"/jobs/{self._job_id}/stream", self._on_stream_event)
        self._socket.errorOccurred.connect(self._on_stream_error)

    def _on_stream_event(self, event: dict[str, Any]) -> None:
        """Route one job event to the matching signal and row update."""
        kind = event.get("event")
        if kind == "segment":
            self.segmentAdded.emit(
                int(event["id"]), float(event["start"]), float(event["end"]),
                str(event["text"]), str(event.get("kind", "transcript")), int(event.get("step", 0)),
            )
        elif kind == "progress":
            done, total = int(event["done"]), int(event["total"])
            self._enter_step(event)
            fraction = min(1.0, done / total) if total > 0 else -1.0
            self._step_done = max(self._step_done, fraction)
            self._set_stage(self._stage, fraction)
            self._file_model.set_run_state(self._current_path, progress=self._file_fraction())
        elif kind == "status":
            self._enter_step(event)
            self._set_stage(str(event.get("message", "")), -1.0)
            self._file_model.set_run_state(self._current_path, progress=self._file_fraction())
        elif kind == "finished":
            self._close_stream()
            self._on_file_finished(event)

    def _on_stream_error(self, *_args) -> None:
        """Treat a dropped event stream as a failed file so the run never stalls."""
        if self._socket is None:
            return
        message = self._socket.errorString()
        self._close_stream()
        # The job may still be running on the server, holding the run slot the next file needs.
        if self._job_id is not None:
            self._api.post(f"/jobs/{self._job_id}/cancel")
        self._on_file_finished({
            "success": False,
            "error": "The app lost track of this file while it was processing. Try again.",
            "error_detail": f"Event stream: {message}",
        })

    def _on_file_finished(self, event: dict[str, Any]) -> None:
        """Record one file's result and continue with the next file."""
        self._record_result(event)
        self._start_next()

    def _record_result(self, event: dict[str, Any]) -> None:
        """Store a finished (or failed) file's status, message, outputs, and their languages."""
        path = self._current_path
        success = bool(event.get("success"))
        outputs = [str(p) for p in event.get("output_files") or []]
        warnings = [str(w) for w in event.get("warnings") or []]
        detail = ""
        if success:
            self._run_ok += 1
            self._last_outputs.extend(outputs)
            languages = event.get("output_languages") or {}
            for output in outputs:
                self._output_language[_path_key(output)] = str(languages.get(output) or "")
            status = STATUS_DONE
            message = f"{plural(len(outputs), 'file')} written" if outputs else "Nothing new written"
            if warnings:
                message += f". Note: {warnings[0]}" + (f" (+{len(warnings) - 1} more)" if len(warnings) > 1 else "")
                detail = "\n".join(warnings)
        elif self._cancel_requested or event.get("cancelled"):
            status, message = STATUS_CANCELLED, "Stopped before it finished"
        else:
            self._run_failed += 1
            problem = describe(str(event.get("error") or "Unknown error"), path)
            status, message = STATUS_ERROR, problem.message
            detail = str(event.get("error_detail") or problem.detail or "")
            self._failed.append({"path": path, "name": os.path.basename(path), "message": message})
        self._file_model.set_run_state(
            path, status=status, progress=1.0 if success else 0.0, message=message, outputs=outputs, detail=detail,
        )
        self._job_id = None

    def _finish_run(self) -> None:
        """Wrap up the run: summary, idle state, deferred preferences, and model release."""
        cancelled = self._cancel_requested
        self._elapsed = self._seconds_running()
        self._clock.stop()
        total = len(self._run_paths)
        summary = f"{self._run_ok} of {plural(total, 'file')} done"
        if self._run_failed:
            summary += f", {self._run_failed} failed"
        if self._run_skipped:
            summary += f", {self._run_skipped} skipped (results already there)"
        self._summary = f"Stopped. {summary}." if cancelled else f"{summary}."
        self._current_path = ""
        self._set_stage("", -1.0)
        self._set_busy(False)
        if self._deferred_settings is not None:
            settings, self._deferred_settings = self._deferred_settings, None
            self._apply_defaults(settings)
        # The API refuses while another tab's job is still running, so models stay loaded for it.
        self._api.post("/jobs/release-models")
        self.runFinished.emit(self._summary, self._run_ok, self._run_failed, self._elapsed, cancelled)
        self.notice.emit(self._summary)

    def _close_stream(self) -> None:
        """Close and release the current job's WebSocket."""
        socket, self._socket = self._socket, None
        if socket is not None:
            socket.errorOccurred.disconnect(self._on_stream_error)
            socket.close()
            socket.deleteLater()

    def _enter_step(self, event: dict[str, Any]) -> None:
        """Follow the step an event belongs to, starting its progress over when it changes."""
        step = int(event.get("step", self._step))
        if step != self._step:
            self._step, self._step_done = step, 0.0
        self._steps = max(1, int(event.get("steps", self._steps)))

    def _file_fraction(self) -> float:
        """How far the current file is through all of its steps, from 0 to 1."""
        return min(1.0, (self._step + self._step_done) / max(1, self._steps))

    def _overall(self) -> float:
        """How far the whole run is, from 0 to 1."""
        if not self._run_paths:
            return 0.0
        return min(1.0, (max(0, self._run_index) + self._file_fraction()) / len(self._run_paths))

    def _seconds_running(self) -> float:
        """Seconds since the run started."""
        return max(0.0, jobs_clock() - self._started_at) if self._started_at else 0.0

    def _set_stage(self, stage: str, progress: float) -> None:
        """Update the stage label and progress, notifying QML."""
        self._stage = stage
        self._stage_progress = progress
        self.runStateChanged.emit()

    def _set_busy(self, value: bool) -> None:
        """Update busy state and emit busyChanged."""
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit(value)
            self.runStateChanged.emit()

    # ── Validation ───────────────────────────────────────────────────────────

    def _runnable_items(self) -> list[dict[str, Any]]:
        """The rows the next Start would run."""
        return [i for i in map(self._file_model.item, self._file_model.runnable_paths()) if i is not None]

    def _schedule_validation(self) -> None:
        """Re-check the options shortly after they stop changing."""
        self.blockerChanged.emit()
        self._validate_timer.start()

    def _validate(self) -> None:
        """Check every queued file, then ask the API whether the options can run on the first."""
        items = self._runnable_items()
        self._update_download_note(items)
        problem = self.queue_blocker(items)
        if problem:
            self._set_server_errors([problem])
            return
        item = items[0] if items else {"path": self.sample_input, "language": "", "companion": "", "kind": ""}
        try:
            body = self._job(item, validating=True)
        except ValueError as e:
            self._set_server_errors([str(e)])
            return
        self._api.post("/jobs/validate", body, self._on_validated)

    def _update_download_note(self, items: list[dict[str, Any]]) -> None:
        """Say what Start would download first, for the files and options as they are now."""
        note = ""
        if items and not self._busy:
            has_media = any(not jobs.has_text(i) for i in items)
            note = download_note(missing_models(
                self.task_key, self._options, self._saved_settings, has_media, self.job_steps()))
        if note != self._download_note:
            self._download_note = note
            self.blockerChanged.emit()

    def _on_validated(self, data: Any, error: str) -> None:
        """Store the API's verdict on the current options."""
        if error or not isinstance(data, dict):
            return
        self._set_server_errors([str(e) for e in data.get("errors") or []])

    def _set_server_errors(self, errors: list[str]) -> None:
        if errors != self._server_errors:
            self._server_errors = errors
            self.blockerChanged.emit()

    # ── Folder scanning ──────────────────────────────────────────────────────

    def _start_scan(self, folders: list[str]) -> None:
        """Scan folders on the thread pool, replacing any scan already running."""
        self.cancelScan()
        worker = FolderScanWorker(folders, self.accepted_exts)
        worker.signals.batchFound.connect(self._on_scan_batch)
        worker.signals.progress.connect(self._on_scan_progress)
        worker.signals.error.connect(self.notice)
        worker.signals.finished.connect(lambda found, cancelled, w=worker: self._on_scan_finished(w, found, cancelled))
        self._scan = worker
        self._scan_found = 0
        self.scanChanged.emit()
        self.blockerChanged.emit()
        QThreadPool.globalInstance().start(worker)

    def _on_scan_batch(self, entries: list) -> None:
        """Insert one batch of scanned files."""
        self._file_model.addScanned(entries)

    def _on_scan_progress(self, found: int) -> None:
        """Track the running file count for the scanning indicator."""
        self._scan_found = found
        self.scanChanged.emit()

    def _on_scan_finished(self, worker: FolderScanWorker, found: int, cancelled: bool) -> None:
        """Clear scan state and tell the user what the scan found."""
        if self._scan is worker:
            self._scan = None
            self.scanChanged.emit()
            self._schedule_validation()
        if cancelled:
            return
        self.notice.emit(f"Found {plural(found, 'usable file')}." if found else "No usable files in that folder.")

    def shutdown(self) -> None:
        """Stop the folder scan before the app exits so the thread pool can drain quickly.

        Running jobs are cancelled by the app itself (see app.py), since a request sent from
        here would never leave once the event loop has stopped.
        """
        self.cancelScan()
        self._clock.stop()

    # ── Defaults ─────────────────────────────────────────────────────────────

    def _on_defaults_fetched(self, settings: Any, error: str) -> None:
        """Seed options from persisted preferences, waiting for a running queue to finish."""
        if error or not isinstance(settings, dict):
            return
        self._saved_settings = settings
        self.blockerChanged.emit()
        if self._busy:
            self._deferred_settings = settings
            return
        self._apply_defaults(settings)

    def _apply_defaults(self, settings: dict[str, Any]) -> None:
        """Copy the saved defaults into every option not changed in this session."""
        for key, value in self.options_from_settings(settings).items():
            if key in self._options and key not in self._edited:
                self._options[key] = value
        self.optionsChanged.emit()
        self._schedule_validation()


def _path_key(path: str) -> str:
    """Comparable form of a path, for looking files up by name."""
    return os.path.normcase(os.path.normpath(path))


def _all_there(body: dict[str, Any]) -> bool:
    """True when every result a job body plans is already there (so skipping it loses nothing)."""
    planned = jobs.planned_outputs(body)
    return bool(planned) and all(os.path.exists(p) for p in planned)


def jobs_clock() -> float:
    """The clock run times are measured with (a function so tests can replace it)."""
    return time.monotonic()

