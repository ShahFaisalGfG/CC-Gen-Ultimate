# base.py - shared run contract for every task: cancellation, staged progress, and results
#
# A task runs in two calls, prepare() then run(), on a worker thread. Every callback it invokes
# goes through RunContext, which checks for cancellation first, so long engine loops stop at
# their next segment. run() never raises; failures and cancellations come back as a TaskResult.

import logging
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Generic, Optional, TypeVar

from ccgen.core import AnySegment, Segment
from ccgen.core.errors import describe
from ccgen.core.tasks.configs import TaskConfigBase
from ccgen.utils.callbacks import JobCancelled, emit_progress, emit_segment, emit_status
from ccgen.utils.download_progress import cancellable

_log = logging.getLogger(__name__)

CANCELLED_MESSAGE = "Cancelled by user."

StatusCb = Optional[Callable[[str], None]]
ProgressCb = Optional[Callable[[int, int], None]]
SegmentCb = Optional[Callable[[AnySegment], None]]

_C = TypeVar("_C", bound=TaskConfigBase)


@dataclass
class Track:
    """Timed text handed between tasks.

    `cues` carry this track's own text in their "text" field (a translation's cues hold the
    translated text). `language` is the spoken language ("" when unknown) and `script` the
    writing system after transliteration ("" when the text uses its language's usual script).
    """

    cues: list[Segment]
    language: str = ""
    script: str = ""


@dataclass
class TaskResult:
    """Outcome of one task run on one input file."""

    success: bool
    input_path: str
    output_files: list[str] = field(default_factory=list)
    detected_language: str = ""
    # A plain sentence with the next step (ccgen/core/errors.py), and the original text for the log.
    error: str = ""
    error_detail: str = ""
    # Which kind of problem it was (ccgen/core/errors.py KIND_*), for scripts that act on it.
    error_kind: str = ""
    cancelled: bool = False
    warnings: list[str] = field(default_factory=list)
    # Language of the text in each written file, so another tab can take them over correctly.
    output_languages: dict[str, str] = field(default_factory=dict)


class RunContext:
    """Callbacks for one task run, guarded by cancellation and tagged with the current stage."""

    def __init__(
        self,
        task: "Task",
        status_cb: StatusCb,
        progress_cb: ProgressCb,
        segment_cb: SegmentCb = None,
    ) -> None:
        self._task = task
        self._status_cb = status_cb
        self._progress_cb = progress_cb
        self._segment_cb = segment_cb
        self.warnings: list[str] = []

    def begin(self, stage: str, message: str) -> None:
        """Enter the next stage of the run and report its status message."""
        self._task.enter_stage(stage)
        self.status(message)

    def status(self, message: str) -> None:
        """Report a human-readable status message."""
        self.check_cancelled()
        emit_status(self._status_cb, message)

    def progress(self, done: int, total: int) -> None:
        """Report progress within the current stage."""
        self.check_cancelled()
        emit_progress(self._progress_cb, done, total)

    def segment(self, segment: AnySegment) -> None:
        """Stream one finished cue to the caller."""
        self.check_cancelled()
        emit_segment(self._segment_cb, segment)

    def warn(self, message: str) -> None:
        """Record a non-fatal problem the user should see in the run summary."""
        _log.warning(message)
        self.warnings.append(message)

    def check_cancelled(self) -> None:
        """Raise JobCancelled once the task has been cancelled."""
        if self._task.cancelled:
            raise JobCancelled()

    def is_cancelled(self) -> bool:
        """True once the task has been cancelled, for loops that stop on their own terms."""
        return self._task.cancelled


class Task(ABC, Generic[_C]):
    """One unit of work on one input file, run as prepare() then run()."""

    def __init__(self, config: _C) -> None:
        self.config = config
        self._cancel_event = threading.Event()
        self._stage = ""
        self._step = -1
        self._ctx: Optional[RunContext] = None

    @property
    @abstractmethod
    def stages(self) -> list[str]:
        """Names of the stages this run goes through, in order, for overall progress."""

    @property
    def stage(self) -> str:
        """Name of the stage currently running ("" before the first one)."""
        return self._stage

    @property
    def step(self) -> int:
        """Zero-based index of the current stage within `stages`."""
        return max(self._step, 0)

    def enter_stage(self, stage: str) -> None:
        """Advance to `stage`; progress events report it so the caller can track overall progress."""
        self._stage = stage
        self._step = min(self._step + 1, len(self.stages) - 1)

    def cancel(self) -> None:
        """Ask a running prepare()/run() to stop at the next segment or download chunk."""
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        """True once cancel() has been called."""
        return self._cancel_event.is_set()

    def prepare(self, status_cb: StatusCb = None, progress_cb: ProgressCb = None) -> None:
        """Load the models this task needs, downloading them on first use.

        Raises RuntimeError on load failure and JobCancelled when cancelled mid-download.
        """
        self._ctx = RunContext(self, status_cb, progress_cb)
        with cancellable(self._cancel_event.is_set):
            self._prepare(self._ctx)

    def run(
        self,
        status_cb: StatusCb = None,
        segment_cb: SegmentCb = None,
        progress_cb: ProgressCb = None,
    ) -> TaskResult:
        """Execute the task. Never raises; returns a TaskResult on success, failure, or cancel."""
        input_path = self.config.input_path
        _log.info("%s starting: %s", type(self).__name__, os.path.basename(input_path))
        ctx = RunContext(self, status_cb, progress_cb, segment_cb)
        if self._ctx is not None:
            ctx.warnings.extend(self._ctx.warnings)
        try:
            if not os.path.isfile(input_path):
                raise FileNotFoundError(2, "File not found", input_path)
            with cancellable(self._cancel_event.is_set):
                result = self._run(ctx)
            result.warnings = ctx.warnings + result.warnings
            # Unguarded: the outputs are written, so a late cancel must not turn this into a failure.
            emit_status(status_cb, "Done.")
            return result
        except JobCancelled:
            _log.info("%s cancelled: %s", type(self).__name__, input_path)
            return cancelled_result(input_path)
        except Exception as e:
            if self.cancelled:
                return cancelled_result(input_path)
            _log.error("%s failed for %s: %r", type(self).__name__, input_path, e, exc_info=True)
            return failed_result(input_path, e, ctx.warnings)

    def _prepare(self, ctx: RunContext) -> None:
        """Load models before run(); tasks without models keep this no-op."""

    @abstractmethod
    def _run(self, ctx: RunContext) -> TaskResult:
        """Do the work; may raise, run() turns exceptions into a failed result."""


def failed_result(input_path: str, error: BaseException, warnings: Optional[list[str]] = None) -> TaskResult:
    """The result of a run that raised: the error in plain words, its original text kept as detail."""
    problem = describe(error, input_path)
    return TaskResult(
        success=False, input_path=input_path, error=problem.message, error_detail=problem.detail,
        error_kind=problem.kind, warnings=list(warnings or []),
    )


def cancelled_result(input_path: str = "") -> TaskResult:
    """Build the result reported for a task cancelled before or during its run."""
    return TaskResult(success=False, input_path=input_path, error=CANCELLED_MESSAGE, cancelled=True)
