# task_ctrl.py - one tab's file queue, options, and queue runner (client of the embedded API)
#
# Every task tab (Generate, Translate, Transliterate, Dub, Workflow) owns one of these. Each file
# in the queue runs as its own API job, one after another: start job, stream its events, record
# the result on the file's row, move to the next file. Cancelling stops the running job and
# leaves the remaining files pending, so Start resumes where the run stopped.
#
# Options live in one map. Whether they can run is decided by the API's own config validation
# (POST /jobs/validate), so the Start button and the backend can never disagree.

import os
from typing import Any, Optional

from PySide6.QtCore import Property, QObject, QThreadPool, QTimer, Signal, Slot
from PySide6.QtWebSockets import QWebSocket

from ccgen.config.defaults import OutputDefaults
from ccgen.config.profiles import effective_profile
from ccgen.controllers.api_client import ApiClient
from ccgen.core.tasks.configs import SUBTITLE_FORMATS
from ccgen.models.file_model import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PROCESSING,
    MediaFileModel,
)
from ccgen.services.folder_scanner import FolderScanWorker
from ccgen.utils.helpers import plural, to_local_path

_VALIDATE_DELAY_MS = 250


class TaskController(QObject):
    """Runs one task over a queue of files. Subclasses define the options and the job body."""

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
        self._output_language: dict[str, str] = {}

        self._run_paths: list[str] = []
        self._run_index = -1
        self._run_ok = 0
        self._run_failed = 0
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

        self._scan: Optional[FolderScanWorker] = None
        self._scan_found = 0

        self._validate_timer = QTimer(self)
        self._validate_timer.setSingleShot(True)
        self._validate_timer.setInterval(_VALIDATE_DELAY_MS)
        self._validate_timer.timeout.connect(self._validate)
        self._file_model.countChanged.connect(lambda _count: self._schedule_validation())
        self._file_model.inputsChanged.connect(self._schedule_validation)

        self._api.get("/settings", self._on_defaults_fetched)

    # ── To override per task ────────────────────────────────────────────────

    def initial_options(self) -> dict[str, Any]:
        """Options before the saved preferences arrive."""
        return {}

    def options_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Map saved preferences onto this task's options."""
        return {}

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        """Build the API job body for one queued file (`item` is its row).

        Raises ValueError with a readable message when this file can't run. `validating` is
        True when checking the options against a placeholder file, so file-specific lookups
        should assume they will succeed.
        """
        raise NotImplementedError

    def _job(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        """The job body with the saved performance profile, which resolves every Automatic choice."""
        return {**self.job_body(item, validating), "profile": effective_profile(self._saved_settings)}

    def add_paths(self, paths: list[str]) -> None:
        """Add files to the queue (the Dub tab pairs subtitles with their media here)."""
        self._file_model.addFiles(paths)

    def extra_blocker(self) -> str:
        """A task-specific reason Start is unavailable, checked after the API's validation."""
        return ""

    def queue_blocker(self, items: list[dict[str, Any]]) -> str:
        """Why a queued file can't run with the current options, or "" when all of them can."""
        return ""

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
        if not self._run_paths:
            return 0.0
        return min(1.0, (max(0, self._run_index) + self._file_fraction()) / len(self._run_paths))

    @Property(str, notify=runStateChanged)
    def summary(self) -> str:
        """One-line result of the last finished run."""
        return self._summary

    @Property(str, notify=runStateChanged)
    def lastOutputFolder(self) -> str:
        """Folder holding the most recently written file."""
        return os.path.dirname(self._last_outputs[-1]) if self._last_outputs else ""

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

    @Property(str, notify=blockerChanged)
    def blocker(self) -> str:
        """Why Start is unavailable right now, or "" when the queue can run."""
        if self._scan is not None:
            return "Wait for the folder scan to finish (or stop it)."
        if self._file_model.count == 0:
            return f"Add a {self.file_noun} to the queue first."
        return self._server_errors[0] if self._server_errors else self.extra_blocker()

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
        files = [p for p in paths if p and p not in folders and os.path.splitext(p)[1].lower() in self.accepted_exts]
        skipped = len(paths) - len(folders) - len(files)
        before = self._file_model.count
        self.add_paths(files)
        if folders:
            self._start_scan(folders)
        if skipped:
            self.notice.emit(f"Skipped {plural(skipped, 'file')} this tab can't use.")
        elif files and self._file_model.count == before:
            self.notice.emit("Those files are already in the queue.")

    @Slot(list, str, list)
    def receiveFiles(self, paths: list, source: str, languages: list) -> None:
        """Take finished files handed over from another tab with each file's language."""
        known = dict(zip(paths, languages))
        usable = [p for p in paths if os.path.splitext(p)[1].lower() in self.accepted_exts]
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
        """Process every unfinished file in the queue (or all files when all are done)."""
        if self._busy:
            return
        if self.blocker:
            self.notice.emit(self.blocker)
            return
        paths = self._file_model.runnable_paths()
        self._file_model.reset_for_run(paths)
        self._run_paths = paths
        self._run_index = -1
        self._run_ok = self._run_failed = 0
        self._cancel_requested = False
        self._summary = ""
        self._last_outputs = []
        self._set_busy(True)
        self._start_next()

    @Slot()
    def cancelQueue(self) -> None:
        """Stop the running file and leave the rest of the queue pending."""
        if not self._busy or self._cancel_requested:
            return
        self._cancel_requested = True
        self._set_stage("Cancelling...", -1.0)
        if self._job_id is not None:
            self._api.post(f"/jobs/{self._job_id}/cancel")

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
            self._file_model.set_run_state(path, status=STATUS_PROCESSING, progress=0.0)
            self._set_stage("Starting...", -1.0)
            self.fileStarted.emit(path, os.path.basename(path))
            try:
                body = self._job(item)
            except ValueError as e:
                self._record_result({"success": False, "error": str(e)})
                continue
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
        self._on_file_finished({"success": False, "error": f"Lost connection to the processing service: {message}"})

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
        if success:
            self._run_ok += 1
            self._last_outputs.extend(outputs)
            languages = event.get("output_languages") or {}
            for output in outputs:
                self._output_language[_path_key(output)] = str(languages.get(output) or "")
            status, message = STATUS_DONE, f"{plural(len(outputs), 'file')} written"
            if warnings:
                message += f". Note: {warnings[0]}" + (f" (+{len(warnings) - 1} more)" if len(warnings) > 1 else "")
        elif self._cancel_requested or event.get("cancelled"):
            status, message = STATUS_CANCELLED, "Cancelled"
        else:
            self._run_failed += 1
            status, message = STATUS_ERROR, str(event.get("error") or "Unknown error")
        self._file_model.set_run_state(
            path, status=status, progress=1.0 if success else 0.0, message=message, outputs=outputs,
        )
        self._job_id = None

    def _finish_run(self) -> None:
        """Wrap up the run: summary, idle state, deferred preferences, and model release."""
        cancelled = self._cancel_requested
        summary = f"{self._run_ok} of {plural(len(self._run_paths), 'file')} done"
        if self._run_failed:
            summary += f", {self._run_failed} failed"
        self._summary = f"Cancelled. {summary}." if cancelled else f"{summary}."
        self._current_path = ""
        self._set_stage("", -1.0)
        self._set_busy(False)
        if self._deferred_settings is not None:
            settings, self._deferred_settings = self._deferred_settings, None
            self._apply_defaults(settings)
        # The API refuses while another tab's job is still running, so models stay loaded for it.
        self._api.post("/jobs/release-models")
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

    def _schedule_validation(self) -> None:
        """Re-check the options shortly after they stop changing."""
        self.blockerChanged.emit()
        self._validate_timer.start()

    def _validate(self) -> None:
        """Check every queued file, then ask the API whether the options can run on the first."""
        items = [i for i in map(self._file_model.item, self._file_model.runnable_paths()) if i is not None]
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


def subtitle_output_options() -> dict[str, Any]:
    """Default subtitle format, layout, and folder options shared by subtitle-writing tabs."""
    return {
        "formats": [OutputDefaults.DEFAULT_FORMAT],
        "max_line_length": OutputDefaults.MAX_LINE_LENGTH,
        "max_lines": OutputDefaults.MAX_LINES,
        "output_dir": OutputDefaults.DIRECTORY,
    }


def subtitle_output_from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Saved subtitle format, layout, and folder preferences."""
    output = settings.get("output", {})
    defaults = subtitle_output_options()
    return {
        "formats": [fmt for fmt in SUBTITLE_FORMATS if output.get(fmt, fmt in defaults["formats"])],
        "max_line_length": int(output.get("max_line_length", defaults["max_line_length"])),
        "max_lines": int(output.get("max_lines", defaults["max_lines"])),
        "output_dir": output.get("directory") or "",
    }


def subtitle_output_body(options: dict[str, Any], input_path: str) -> dict[str, Any]:
    """Job body fields for subtitle output; files go next to their input unless a folder is set."""
    return {
        "output_dir": options["output_dir"] or os.path.dirname(input_path) or None,
        "formats": list(options["formats"]),
        "max_line_length": int(options["max_line_length"]),
        "max_lines": int(options["max_lines"]),
    }
