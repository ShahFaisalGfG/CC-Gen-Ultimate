# model_files.py - download, prepare, and remove CTranslate2 translation models
#
# Each model lives in its own folder under %LOCALAPPDATA%\CC-Gen-Ultimate\translation. Repos
# that already hold a CTranslate2 model (NLLB, MADLAD) are downloaded as they are. OPUS-MT
# publishes Transformers checkpoints, so after downloading one it is converted once to an 8-bit
# CTranslate2 model (about a quarter of the size) and the original weights are deleted; its
# tokenizer files stay. A small marker records the finished revision, so an interrupted
# download or conversion is never mistaken for a ready model.

import json
import logging
import os
import shutil
from typing import Callable, Optional

from huggingface_hub import list_repo_files, snapshot_download

from ccgen.config.defaults import AppInfo
from ccgen.config.translation_models import MEANING_MODEL, Ct2Model
from ccgen.utils.callbacks import emit_status
from ccgen.utils.download_progress import download_progress, retry_hf_load

_log = logging.getLogger(__name__)

StatusCb = Optional[Callable[[str], None]]
ProgressCb = Optional[Callable[[int, int], None]]

_MARKER = "ready.json"
_SOURCE = "source"
_CT2 = "ct2"
_WEIGHTS = ("model.safetensors", "pytorch_model.bin")


def translation_root() -> str:
    """Folder holding every downloaded CTranslate2 translation model and the meaning check."""
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, AppInfo.APP_NAME, "translation")


def model_folder(key: str) -> str:
    """Folder of one model, by its catalog key."""
    return os.path.join(translation_root(), key)


def ct2_folder(model: Ct2Model) -> str:
    """Folder CTranslate2 loads the model from."""
    folder = model_folder(model.key)
    return os.path.join(folder, _CT2) if model.convert else folder


def tokenizer_folder(model: Ct2Model) -> str:
    """Folder holding the model's tokenizer files."""
    folder = model_folder(model.key)
    return os.path.join(folder, _SOURCE) if model.convert else folder


def is_ready(key: str, revision: str) -> bool:
    """True when the model's folder holds a finished download of `revision`."""
    try:
        with open(os.path.join(model_folder(key), _MARKER), encoding="utf-8") as fh:
            return json.load(fh).get("revision") == revision
    except (OSError, ValueError):
        return False


def ensure_model(model: Ct2Model, status_cb: StatusCb = None, progress_cb: ProgressCb = None) -> str:
    """Download (and for OPUS-MT, convert) a model when needed; return its CTranslate2 folder."""
    if not is_ready(model.key, model.revision):
        emit_status(status_cb, f"Downloading translation model ({model.label})...")
        folder = model_folder(model.key)
        if os.path.isdir(folder):
            shutil.rmtree(folder)  # a previous attempt stopped part way
        if model.convert:
            _download_and_convert(model, status_cb, progress_cb)
        else:
            with download_progress(progress_cb):
                retry_hf_load(lambda: snapshot_download(model.repo, revision=model.revision, local_dir=folder))
        _mark_ready(model.key, model.revision)
        _log.info("Translation model ready: %s", model.key)
    return ct2_folder(model)


def ensure_meaning_model(status_cb: StatusCb = None, progress_cb: ProgressCb = None) -> str:
    """Download the meaning-check model when needed; return its folder."""
    folder = model_folder(MEANING_MODEL.key)
    if not is_ready(MEANING_MODEL.key, MEANING_MODEL.revision):
        emit_status(status_cb, "Downloading the meaning check...")
        with download_progress(progress_cb):
            retry_hf_load(lambda: snapshot_download(
                MEANING_MODEL.repo, revision=MEANING_MODEL.revision,
                allow_patterns=list(MEANING_MODEL.files), local_dir=folder,
            ))
        _mark_ready(MEANING_MODEL.key, MEANING_MODEL.revision)
    return folder


def remove_model(key: str) -> None:
    """Delete one model's folder, refusing anything outside the translation folder."""
    root = os.path.realpath(translation_root())
    target = os.path.realpath(model_folder(key))
    if os.path.commonpath((root, target)) != root or target == root:
        raise ValueError("Refusing to delete outside the translation models folder.")
    if os.path.isdir(target):
        shutil.rmtree(target)


def folder_size(key: str) -> int:
    """Bytes the model takes on disk (0 when it isn't downloaded)."""
    return sum(
        os.path.getsize(os.path.join(base, name))
        for base, _, names in os.walk(model_folder(key))
        for name in names
    )


def _download_and_convert(model: Ct2Model, status_cb: StatusCb, progress_cb: ProgressCb) -> None:
    """Fetch an OPUS-MT checkpoint, convert it to an 8-bit CTranslate2 model, drop the weights."""
    import ctranslate2  # the converter pulls in torch and transformers, only needed here

    source = os.path.join(model_folder(model.key), _SOURCE)
    files = retry_hf_load(lambda: list_repo_files(model.repo, revision=model.revision))
    # Repos often carry the same weights twice; one copy is enough.
    weights = next((name for name in _WEIGHTS if name in files), _WEIGHTS[-1])
    patterns = ["*.json", "*.spm", weights]
    with download_progress(progress_cb):
        retry_hf_load(lambda: snapshot_download(
            model.repo, revision=model.revision, allow_patterns=patterns, local_dir=source,
        ))
    emit_status(status_cb, f"Preparing translation model ({model.label}), once only...")
    target = os.path.join(model_folder(model.key), _CT2)
    ctranslate2.converters.TransformersConverter(source).convert(target, quantization="int8", force=True)
    os.remove(os.path.join(source, weights))
    shutil.rmtree(os.path.join(source, ".cache"), ignore_errors=True)


def _mark_ready(key: str, revision: str) -> None:
    """Record that the model's folder holds a finished download of `revision`."""
    with open(os.path.join(model_folder(key), _MARKER), "w", encoding="utf-8") as fh:
        json.dump({"revision": revision}, fh)
