# workflow_ctrl.py - the Workflow tab: a user-built list of steps run on every queued file
#
# Steps are added, removed, and reordered freely. Each step names its input explicitly (the
# queued file or an earlier step), and references follow their step when steps move. A
# reference that would point at the step itself or a later one falls back to the nearest
# earlier step that produces text, so the list is always runnable or clearly blocked.
#
# The steps are remembered for the next launch, and a workflow can be saved by name and loaded
# again (ccgen/utils/workflow_presets.py, which `ccgen workflow --preset NAME` reads too).

from typing import Any, Optional

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    QTimer,
    Signal,
    Slot,
)

from ccgen.controllers.task_ctrl import TaskController
from ccgen.core import jobs
from ccgen.core.jobs import VOICE_RESETS, step_title
from ccgen.core.tasks.configs import INPUT_SOURCE
from ccgen.utils import workflow_presets

_UserRole = Qt.ItemDataRole.UserRole
# The steps are remembered for the next launch this long after the last edit.
_SAVE_DELAY_MS = 500

STEP_KINDS: list[dict[str, str]] = [
    {"kind": "generate", "label": "Generate subtitles", "icon": "mic"},
    {"kind": "translate", "label": "Translate", "icon": "globe"},
    {"kind": "transliterate", "label": "Transliterate", "icon": "characters"},
    {"kind": "dub", "label": "Dub", "icon": "speaker"},
]


def produces_text(step: dict[str, Any]) -> bool:
    """True for steps whose output another step can take as input (all but dubbing)."""
    return step["kind"] != "dub"


class WorkflowStepsModel(QAbstractListModel):
    """The workflow's steps, each with its options and the inputs it may choose from."""

    KindRole    = _UserRole + 1
    TitleRole   = _UserRole + 2
    OptionsRole = _UserRole + 3
    InputsRole  = _UserRole + 4

    countChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps: list[dict[str, Any]] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return len(self._steps)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._steps):
            return None
        step = self._steps[index.row()]
        match role:
            case self.KindRole:    return step["kind"]
            case self.TitleRole:   return step_title(step)
            case self.OptionsRole: return step
            case self.InputsRole:  return self._inputs_for(index.row())
        return None

    def roleNames(self) -> dict:
        return {
            self.KindRole: b"kind",
            self.TitleRole: b"stepTitle",
            self.OptionsRole: b"options",
            self.InputsRole: b"inputs",
        }

    @Property(int, notify=countChanged)
    def count(self) -> int:
        """Number of steps."""
        return len(self._steps)

    @property
    def steps(self) -> list[dict[str, Any]]:
        """The steps as plain dicts (read-only use)."""
        return self._steps

    def replace(self, steps: list[dict[str, Any]]) -> None:
        """Replace every step at once."""
        self.beginResetModel()
        self._steps = steps
        self.endResetModel()
        self.countChanged.emit()

    def append(self, step: dict[str, Any]) -> None:
        """Add a step at the end."""
        row = len(self._steps)
        self.beginInsertRows(QModelIndex(), row, row)
        self._steps.append(step)
        self.endInsertRows()
        self.countChanged.emit()

    def remove(self, row: int) -> None:
        """Remove a step and repoint inputs that referred to it or to later steps."""
        self.beginRemoveRows(QModelIndex(), row, row)
        self._steps.pop(row)
        self.endRemoveRows()
        self._remap({old: (old if old < row else old - 1) for old in range(len(self._steps) + 1) if old != row})
        self.countChanged.emit()

    def move(self, source: int, target: int) -> None:
        """Move a step, keeping each input attached to the same step where it still comes first."""
        order = list(range(len(self._steps)))
        order.insert(target, order.pop(source))
        self.beginResetModel()
        self._steps = [self._steps[i] for i in order]
        self.endResetModel()
        self._remap({old: new for new, old in enumerate(order)})

    def set_option(self, row: int, key: str, value: Any) -> None:
        """Change one option of one step."""
        step = self._steps[row]
        if key not in step or step[key] == value:
            return
        step[key] = value
        if step["kind"] == "dub":
            step.update(VOICE_RESETS.get(key, {}))
        self._refresh(row, row)
        # Titles of this step appear in later steps' input lists.
        self._refresh(row + 1, len(self._steps) - 1)

    def default_input(self, row: int) -> str:
        """The nearest earlier step that produces text, or the queued file."""
        for index in range(min(row, len(self._steps)) - 1, -1, -1):
            if produces_text(self._steps[index]):
                return f"step:{index}"
        return INPUT_SOURCE

    def _inputs_for(self, row: int) -> list[dict[str, str]]:
        """Inputs a step may use: the queued file, then each earlier text-producing step."""
        items = [{"label": "The queued file", "code": INPUT_SOURCE}]
        items += [
            {"label": f"Step {i + 1}: {step_title(s)}", "code": f"step:{i}"}
            for i, s in enumerate(self._steps[:row]) if produces_text(s)
        ]
        return items

    def _remap(self, mapping: dict[int, Optional[int]]) -> None:
        """Rewrite "step:N" inputs after steps moved or were removed."""
        for row, step in enumerate(self._steps):
            value = step.get("input")
            if not value or not value.startswith("step:"):
                continue
            target = mapping.get(int(value[5:]))
            if target is None or target >= row or not produces_text(self._steps[target]):
                step["input"] = self.default_input(row)
            else:
                step["input"] = f"step:{target}"
        self._refresh(0, len(self._steps) - 1)

    def _refresh(self, first: int, last: int) -> None:
        """Notify delegates that rows' titles, options, or input lists changed."""
        if 0 <= first <= last < len(self._steps):
            self.dataChanged.emit(self.index(first), self.index(last))


class WorkflowController(TaskController):
    """Workflow tab: run the user's list of steps on every queued file."""

    task_key = "workflow"
    accepted_exts = jobs.TASK_EXTS["workflow"]
    file_noun = jobs.TASK_NOUNS["workflow"]
    sample_input = "example.mp4"

    stepsChanged = Signal()
    presetsChanged = Signal()

    def __init__(self, base_url: str, parent=None):
        self._steps_model = WorkflowStepsModel()
        self._settings: dict[str, Any] = {}
        self._presets: list[str] = workflow_presets.preset_names()
        last = workflow_presets.load_store()["last"]
        # Until the user changes the steps, they follow the saved preferences as those load; steps
        # remembered from the last launch count as the user's.
        self._steps_edited = bool(last)
        super().__init__(base_url, parent)
        self._steps_model.setParent(self)
        self._steps_model.replace(last or self._starter_steps())
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(_SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self._remember_steps)
        self._steps_model.countChanged.connect(self.stepsChanged)
        self._steps_model.dataChanged.connect(lambda *_: self._schedule_validation())
        self._steps_model.modelReset.connect(self._schedule_validation)
        self._steps_model.countChanged.connect(self._schedule_validation)
        for signal in (self._steps_model.dataChanged, self._steps_model.modelReset, self._steps_model.countChanged):
            signal.connect(self.textLanguageChanged)

    @Property(QObject, constant=True)
    def steps(self) -> WorkflowStepsModel:
        """The workflow's steps."""
        return self._steps_model

    @Property(list, constant=True)
    def stepKinds(self) -> list:
        """Kinds of step that can be added, with labels and icons for the Add step menu."""
        return STEP_KINDS

    @Property(list, notify=presetsChanged)
    def presetNames(self) -> list:
        """Names of the saved workflows."""
        return list(self._presets)

    @Slot(str)
    def addStep(self, kind: str) -> None:
        """Append a step of `kind`, taking its input from the nearest earlier text step."""
        if kind in jobs.STEP_OPTIONS:
            self._edited_steps()
            self._steps_model.append(self._new_step(kind, len(self._steps_model.steps)))

    @Slot(int)
    def removeStep(self, row: int) -> None:
        """Remove one step."""
        if 0 <= row < len(self._steps_model.steps):
            self._edited_steps()
            self._steps_model.remove(row)

    @Slot(int, int)
    def moveStep(self, source: int, target: int) -> None:
        """Move a step up or down the list."""
        count = len(self._steps_model.steps)
        if 0 <= source < count and 0 <= target < count and source != target:
            self._edited_steps()
            self._steps_model.move(source, target)

    @Slot(int, str, "QVariant")
    def setStepOption(self, row: int, key: str, value: Any) -> None:
        """Change one option of one step."""
        if 0 <= row < len(self._steps_model.steps):
            self._edited_steps()
            self._steps_model.set_option(row, key, value)

    @Slot(str, result=bool)
    def savePreset(self, name: str) -> bool:
        """Save the steps as a workflow called `name` (replacing one of that name); False on failure."""
        try:
            saved = workflow_presets.save_preset(name, self._steps_model.steps)
        except ValueError as error:
            self.notice.emit(str(error))
            return False
        except OSError:
            self.notice.emit("The workflow couldn't be saved. Check that the app's settings folder can be written.")
            return False
        self._refresh_presets()
        self.notice.emit(f'Saved the workflow "{saved}".')
        return True

    @Slot(str)
    def loadPreset(self, name: str) -> None:
        """Replace the steps with a saved workflow."""
        steps = workflow_presets.get_preset(name)
        if steps is None:
            self.notice.emit(f'There is no saved workflow called "{name}".')
            self._refresh_presets()
            return
        self._edited_steps()
        self._steps_model.replace(steps)

    @Slot(str)
    def deletePreset(self, name: str) -> None:
        """Remove a saved workflow; the steps on the tab stay as they are."""
        try:
            removed = workflow_presets.delete_preset(name)
        except OSError:
            self.notice.emit("The workflow couldn't be removed. Check that the app's settings folder can be written.")
            return
        self._refresh_presets()
        if removed:
            self.notice.emit(f'Removed the workflow "{name}".')

    @Slot()
    def resetSteps(self) -> None:
        """Start over with the starter steps: subtitles, then their translation."""
        self._edited_steps()
        self._steps_model.replace(self._starter_steps())

    def job_steps(self) -> Optional[list[dict[str, Any]]]:
        return self._steps_model.steps

    def _edited_steps(self) -> None:
        """Note that the user changed the steps, and remember them shortly."""
        self._steps_edited = True
        self._save_timer.start()

    def _remember_steps(self) -> None:
        """Keep the steps for the next launch."""
        workflow_presets.save_last(self._steps_model.steps)

    def _refresh_presets(self) -> None:
        names = workflow_presets.preset_names()
        if names != self._presets:
            self._presets = names
            self.presetsChanged.emit()

    def _apply_defaults(self, settings: dict[str, Any]) -> None:
        """Remember the preferences for new steps, and refresh the starter steps if untouched."""
        self._settings = settings
        if not self._steps_edited:
            self._steps_model.replace(self._starter_steps())
        super()._apply_defaults(settings)

    def _starter_steps(self) -> list[dict[str, Any]]:
        """A new workflow starts as the most common chain: subtitles, then their translation."""
        return jobs.starter_steps(self._settings)

    def _new_step(self, kind: str, row: int) -> dict[str, Any]:
        """A step of `kind` with default options, reading from the nearest earlier text step."""
        return jobs.new_step(kind, self._settings, self._steps_model.default_input(row))

    def shutdown(self) -> None:
        """Remember a pending step change before the app exits."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._remember_steps()
        super().shutdown()
