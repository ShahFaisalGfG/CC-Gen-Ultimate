# tasks - independent units of work (generate, translate, transliterate, dub, workflow)

from typing import Annotated, Callable, Union

from pydantic import Field, TypeAdapter

from ccgen.core.tasks.base import CANCELLED_MESSAGE, Task, TaskResult, Track, cancelled_result, failed_result
from ccgen.core.tasks.configs import (
    DubConfig,
    GenerateConfig,
    TaskConfigBase,
    TranslateConfig,
    TransliterateConfig,
    WorkflowConfig,
)
from ccgen.core.tasks.dub import DubTask
from ccgen.core.tasks.generate import GenerateTask
from ccgen.core.tasks.translate import TranslateTask
from ccgen.core.tasks.transliterate import TransliterateTask
from ccgen.core.tasks.workflow import WorkflowTask

TaskConfig = Annotated[
    Union[GenerateConfig, TranslateConfig, TransliterateConfig, DubConfig, WorkflowConfig],
    Field(discriminator="task"),
]
# Validates a JSON request body into the matching config dataclass; used by the API and the CLI.
TASK_CONFIG = TypeAdapter(TaskConfig)

_TASKS: dict[type, Callable[..., Task]] = {
    GenerateConfig: GenerateTask,
    TranslateConfig: TranslateTask,
    TransliterateConfig: TransliterateTask,
    DubConfig: DubTask,
    WorkflowConfig: WorkflowTask,
}


def create_task(config: TaskConfigBase) -> Task:
    """Instantiate the task that runs `config`."""
    factory = _TASKS.get(type(config))
    if factory is None:
        raise ValueError(f"No task runs {type(config).__name__}.")
    return factory(config)


__all__ = [
    "CANCELLED_MESSAGE", "TASK_CONFIG", "Task", "TaskConfig", "TaskResult", "Track",
    "cancelled_result", "create_task", "failed_result",
]
