# workflow_ctrl.py - the Workflow tab: a user-built list of steps run on every queued file
#
# Steps are added, removed, and reordered freely. Each step names its input explicitly (the
# queued file or an earlier step), and references follow their step when steps move. A
# reference that would point at the step itself or a later one falls back to the nearest
# earlier step that produces text, so the list is always runnable or clearly blocked.

import os
from typing import Any, Optional

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
    Slot,
)

from ccgen.config.defaults import DubbingDefaults, LanguageOptions, TransliterationDefaults
from ccgen.config.translation_models import ENGINE_NLLB
from ccgen.config.voices import ENGINE_LABELS, ENGINE_XTTS
from ccgen.controllers.task_ctrl import TaskController, subtitle_output_body, subtitle_output_from_settings
from ccgen.controllers.task_tabs import (
    MEDIA_EXTS,
    NLLB_TERMS_BLOCKER,
    VOICE_RESETS,
    XTTS_TERMS_BLOCKER,
    DubController,
    GenerateController,
    TranslateController,
    TransliterateController,
    nllb_terms_accepted,
    xtts_terms_accepted,
)
from ccgen.core.tasks.configs import INPUT_SOURCE
from ccgen.models.file_model import SUBTITLE_EXTS

_UserRole = Qt.ItemDataRole.UserRole

STEP_KINDS: list[dict[str, str]] = [
    {"kind": "generate", "label": "Generate subtitles", "icon": "mic"},
    {"kind": "translate", "label": "Translate", "icon": "globe"},
    {"kind": "transliterate", "label": "Transliterate", "icon": "characters"},
    {"kind": "dub", "label": "Dub", "icon": "speaker"},
]
_DEFAULTS = {
    "generate": GenerateController.step_options,
    "translate": TranslateController.step_options,
    "transliterate": TransliterateController.step_options,
    "dub": DubController.step_options,
}
_LANGUAGES = {code: label for label, code in LanguageOptions.TRANSCRIPTION + LanguageOptions.TRANSLATION_TARGETS if code}
_SCRIPTS = {code: label for label, code in TransliterationDefaults.SCHEMES}


def step_title(step: dict[str, Any]) -> str:
    """Short heading for a step card, e.g. "Translate to Urdu"."""
    kind = step["kind"]
    if kind == "generate":
        return "Generate subtitles"
    if kind == "translate":
        return f"Translate to {_LANGUAGES.get(step['target_lang'], step['target_lang'])}"
    if kind == "transliterate":
        return f"Transliterate to {_SCRIPTS.get(step['target_scheme'], step['target_scheme'])}"
    return f"Dub with {ENGINE_LABELS.get(step['mode'], step['mode'])}"


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
    accepted_exts = MEDIA_EXTS | SUBTITLE_EXTS
    file_noun = "video, audio, or subtitle file"
    sample_input = "example.mp4"

    stepsChanged = Signal()

    def __init__(self, base_url: str, parent=None):
        self._steps_model = WorkflowStepsModel()
        self._settings: dict[str, Any] = {}
        # Until the user changes the steps, they follow the saved preferences as those load.
        self._steps_edited = False
        super().__init__(base_url, parent)
        self._steps_model.setParent(self)
        self._steps_model.replace(self._starter_steps())
        self._steps_model.countChanged.connect(self.stepsChanged)
        self._steps_model.dataChanged.connect(lambda *_: self._schedule_validation())
        self._steps_model.modelReset.connect(self._schedule_validation)
        self._steps_model.countChanged.connect(self._schedule_validation)

    @Property(QObject, constant=True)
    def steps(self) -> WorkflowStepsModel:
        """The workflow's steps."""
        return self._steps_model

    @Property(list, constant=True)
    def stepKinds(self) -> list:
        """Kinds of step that can be added, with labels and icons for the Add step menu."""
        return STEP_KINDS

    @Slot(str)
    def addStep(self, kind: str) -> None:
        """Append a step of `kind`, taking its input from the nearest earlier text step."""
        if kind in _DEFAULTS:
            self._steps_edited = True
            self._steps_model.append(self._new_step(kind, len(self._steps_model.steps)))

    @Slot(int)
    def removeStep(self, row: int) -> None:
        """Remove one step."""
        if 0 <= row < len(self._steps_model.steps):
            self._steps_edited = True
            self._steps_model.remove(row)

    @Slot(int, int)
    def moveStep(self, source: int, target: int) -> None:
        """Move a step up or down the list."""
        count = len(self._steps_model.steps)
        if 0 <= source < count and 0 <= target < count and source != target:
            self._steps_edited = True
            self._steps_model.move(source, target)

    @Slot(int, str, "QVariant")
    def setStepOption(self, row: int, key: str, value: Any) -> None:
        """Change one option of one step."""
        if 0 <= row < len(self._steps_model.steps):
            self._steps_edited = True
            self._steps_model.set_option(row, key, value)

    def extra_blocker(self) -> str:
        uses_cloning = any(s["kind"] == "dub" and s["mode"] == ENGINE_XTTS for s in self._steps_model.steps)
        if uses_cloning and not xtts_terms_accepted(self._saved_settings):
            return XTTS_TERMS_BLOCKER
        uses_nllb = any(s["kind"] == "translate" and s.get("engine") == ENGINE_NLLB for s in self._steps_model.steps)
        if uses_nllb and not nllb_terms_accepted(self._saved_settings):
            return NLLB_TERMS_BLOCKER
        return ""

    def queue_blocker(self, items: list[dict[str, Any]]) -> str:
        unknown = next((i for i in items if i.get("kind") == "subtitle" and not i.get("language")), None)
        if unknown is None:
            return ""
        for number, step in enumerate(self._steps_model.steps, start=1):
            detects = (step["kind"] == "translate" and step["source_lang"] == "auto") \
                or (step["kind"] == "dub" and step["language"] == DubbingDefaults.LANGUAGE_AUTO)
            if detects and step.get("input") == INPUT_SOURCE:
                return (
                    f"{os.path.basename(unknown['path'])} has no language in its name. Choose the language "
                    f"in step {number} ({step_title(step)}), or rename it with a suffix such as movie_en.srt."
                )
        return ""

    def initial_options(self) -> dict[str, Any]:
        return subtitle_output_from_settings({})

    def options_from_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        return subtitle_output_from_settings(settings)

    def _apply_defaults(self, settings: dict[str, Any]) -> None:
        """Remember the preferences for new steps, and refresh the starter steps if untouched."""
        self._settings = settings
        if not self._steps_edited:
            self._steps_model.replace(self._starter_steps())
        super()._apply_defaults(settings)

    def _starter_steps(self) -> list[dict[str, Any]]:
        """A new workflow starts as the most common chain: subtitles, then their translation."""
        first = self._new_step("generate", 0)
        second = self._new_step("translate", 1)
        second["input"] = "step:0"
        return [first, second]

    def _new_step(self, kind: str, row: int) -> dict[str, Any]:
        """A step of `kind` with default options, reading from the nearest earlier text step."""
        step: dict[str, Any] = {"kind": kind, **_DEFAULTS[kind](self._settings)}
        if kind != "generate":
            step["input"] = self._steps_model.default_input(row)
        if kind != "dub":
            step["write_output"] = True
        return step

    def job_body(self, item: dict[str, Any], validating: bool = False) -> dict[str, Any]:
        steps = []
        for step in self._steps_model.steps:
            body = dict(step)
            if step["kind"] == "generate":
                body.update(GenerateController.step_body(step))
            elif step["kind"] == "translate" and step["source_lang"] == "auto" \
                    and step.get("input") == INPUT_SOURCE and item.get("language"):
                body["source_lang"] = item["language"]
            elif step["kind"] == "dub" and step["language"] == DubbingDefaults.LANGUAGE_AUTO \
                    and step.get("input") == INPUT_SOURCE and item.get("language"):
                body["language"] = item["language"]
            steps.append(body)
        return {
            "task": self.task_key,
            "input_path": item["path"],
            **subtitle_output_body(self._options, item["path"]),
            "steps": steps,
        }
