# asset_registry.py - catalog of every downloadable model/engine/language asset, plus the
# blocking download/delete actions the "Manage Models" screen drives through asset_manager.py,
# and the free-space check the app and the command line run before a download

import errno
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

import argostranslate.package
import argostranslate.settings
from faster_whisper import WhisperModel
from huggingface_hub import constants as hf_constants
from huggingface_hub import scan_cache_dir

from ccgen.config.capabilities import PIVOT_LANGUAGE as _PIVOT_LANG
from ccgen.config.defaults import DubbingDefaults, LanguageOptions, ModelDefaults, ModelRepos
from ccgen.config.translation_models import (
    CT2_MODELS,
    ENGINE_HYMT,
    ENGINE_OPUS_MT,
    HYMT_MODEL,
    MEANING_MODEL,
    engine_info,
)
from ccgen.config.voices import (
    ENGINE_KOKORO,
    ENGINE_OMNIVOICE,
    ENGINE_PIPER,
    ENGINE_XTTS,
    VOICES,
    VoiceOption,
    voice_by_key,
)
from ccgen.core.errors import disk_full_message
from ccgen.engines.transliteration.neural_engine import NeuralEngine
from ccgen.engines.transliteration.rekhta_backend import RekhtaBackend
from ccgen.engines.speech import voice_files
from ccgen.engines.translation import model_files as translation_files
from ccgen.engines.translation.argos_engine import install_pair
from ccgen.utils import model_status
from ccgen.utils.callbacks import emit_status
from ccgen.utils.download_progress import cancellable, download_progress

_log = logging.getLogger(__name__)

CATEGORY_WHISPER = "whisper"
CATEGORY_TRANSLATION = "translation"
CATEGORY_TRANSLITERATION = "transliteration"
CATEGORY_VOICES = "voices"

# The groups each category tab of Manage Models shows, named as the app's pickers name them: the
# translation models as in Preferences > Translation, the voices as the Dub tab's choices, and the
# transliteration models as the Neural engine.
ENGINE_WHISPER_GROUP = "Whisper"
ENGINE_ARGOS_TRANSLATE = "Argos Translate"
ENGINE_MEANING_CHECK = "Meaning check"
ENGINE_NEURAL_GROUP = "Neural"
_DUB_MODE_LABELS = {code: label for label, code, _ in DubbingDefaults.MODES}


# Approximate sizes for not-yet-downloaded assets, in MB. Unlike Whisper's well-published
# sizes, Argos and these vendored repos expose no size field for uninstalled packages, so
# these are measured directly from each repo's Hugging Face file metadata (or, for Argos,
# from a real installed package) rather than guessed.
_TRANSLATION_APPROX_SIZES_MB: dict[str, int] = {
    "ar": 92, "fr": 79, "de": 157, "hi": 112, "pt": 79,
    "ru": 207, "es": 92, "tr": 129, "ur": 80,
}
_TRANSLIT_APPROX_SIZES_MB: dict[str, int] = {
    "roman-ur": 1856, "ur-roman": 1856, "hi-ur": 47,
}

# The space a download needs beyond its size: an Argos package is downloaded as an archive and
# unpacked, and an OPUS-MT checkpoint is converted to a copy about a quarter of its size before
# the original weights are deleted.
_UNPACK_FACTOR = 2.0
_CONVERT_FACTOR = 1.25
# Left free after a download, so a model never fills the drive to the last byte.
_HEADROOM_BYTES = 100_000_000


class AssetInfo(TypedDict):
    """One row in the Manage Models catalog."""

    id: str
    category: str
    engine: str
    label: str
    # The asset in a sentence, e.g. "Whisper small" in "Downloading Whisper small".
    name: str
    downloaded: bool
    size_bytes: Optional[int]
    approx_size_mb: Optional[int]


def list_assets() -> list[AssetInfo]:
    """Build the full catalog of downloadable assets with their current cached state.

    The Hugging Face cache is scanned once and shared by every row, since each scan walks the
    whole cache directory and the catalog checks a dozen repos.
    """
    cache_info = _scan_cache()
    return (
        _whisper_assets(cache_info) + _translation_assets()
        + _transliteration_assets(cache_info) + _voice_assets(cache_info)
    )


def required_bytes(asset_id: str) -> int:
    """Free space, in bytes, a download of `asset_id` needs on its drive (0 when its size is unknown).

    That is the download's approximate size, doubled for an Argos package (archive and unpacked
    copy) and raised a quarter for OPUS-MT (converted copy), plus 100 MB left free. It reads only
    built-in size tables, so it is fast and never touches the network.
    """
    category, key = _split_id(asset_id)
    try:
        size_mb = _approx_mb(category, key)
    except ValueError:
        return 0
    if not size_mb:
        return 0
    factor = 1.0
    if category == CATEGORY_TRANSLATION and key in CT2_MODELS and CT2_MODELS[key].convert:
        factor = _CONVERT_FACTOR
    elif category == CATEGORY_TRANSLATION and not _is_model_folder(key):
        factor = _UNPACK_FACTOR
    return int(size_mb * 1_000_000 * factor) + _HEADROOM_BYTES


def download_folder(asset_id: str) -> str:
    """The folder `asset_id` downloads into. Raises ValueError for an unknown category.

    Whisper, the neural transliteration models, OmniVoice, and XTTS-v2 go to the Hugging Face
    cache; the CTranslate2 translation models, Hy-MT2, and the meaning check to the app's
    translation folder; Argos packages to Argos's package folder; Kokoro and Piper to the app's
    voices folder.
    """
    category, key = _split_id(asset_id)
    if category == CATEGORY_TRANSLATION:
        if _is_model_folder(key):
            return translation_files.model_folder(key)
        return str(argostranslate.settings.package_data_dir)
    if category == CATEGORY_VOICES and key not in (ENGINE_OMNIVOICE, ENGINE_XTTS):
        return voice_files.voices_root()
    if category in (CATEGORY_WHISPER, CATEGORY_TRANSLITERATION, CATEGORY_VOICES):
        return hf_constants.HF_HUB_CACHE
    raise ValueError(f"Unknown asset id: {asset_id}")


def check_free_space(asset_id: str) -> None:
    """Check the drive `asset_id` downloads to, before downloading it. Needs no Qt and no network.

    Returns when the drive has room, and also when the asset's size or the drive's free space
    can't be told. Otherwise raises OSError(errno.ENOSPC, sentence): its strerror is one plain
    sentence for the user, made by ccgen.core.errors.disk_full_message() with the space needed
    (required_bytes()) and the folder (download_folder()). download_asset() runs this check first
    and raises that sentence as a RuntimeError; the command line calls it before
    `ccgen models download`.
    """
    needed = required_bytes(asset_id)
    if needed <= 0:
        return
    folder = download_folder(asset_id)
    try:
        free = shutil.disk_usage(_existing_folder(folder)).free
    except OSError:
        _log.debug("Couldn't read the free space for %s", folder, exc_info=True)
        return
    if free < needed:
        _log.warning("Not enough space for %s in %s: %d bytes free, %d needed", asset_id, folder, free, needed)
        raise OSError(errno.ENOSPC, disk_full_message(needed, os.path.normpath(folder), other_folder=False))


def download_asset(
    asset_id: str,
    progress_cb: Optional[Callable[[str], None]] = None,
    progress_num_cb: Optional[Callable[[int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    """Download one catalog asset by id. Raises RuntimeError on failure.

    A drive without room for it stops the download before it starts, with check_free_space()'s
    sentence as the error.
    """
    try:
        check_free_space(asset_id)
    except OSError as e:
        raise RuntimeError(e.strerror) from None  # already one plain sentence, with the size needed
    try:
        category, key = _split_id(asset_id)
        # Sent before any category-specific work so the UI leaves "Queued" the moment the
        # worker starts, rather than waiting on a first byte-progress tick that some
        # download paths (large multi-file Hugging Face repos in particular) may report late
        # or not at all.
        emit_status(progress_cb, "Downloading...")
        with cancellable(cancel_check):
            if category == CATEGORY_WHISPER:
                _download_whisper(key, progress_num_cb)
            elif category == CATEGORY_TRANSLATION and key in CT2_MODELS:
                translation_files.ensure_model(CT2_MODELS[key], progress_cb, progress_num_cb)
            elif category == CATEGORY_TRANSLATION and key == MEANING_MODEL.key:
                translation_files.ensure_meaning_model(progress_cb, progress_num_cb)
            elif category == CATEGORY_TRANSLATION and key == HYMT_MODEL.key:
                translation_files.ensure_gguf(HYMT_MODEL, progress_cb, progress_num_cb)
            elif category == CATEGORY_TRANSLATION:
                install_pair(*_translation_pair(key), progress_num_cb, progress_cb)
            elif category == CATEGORY_TRANSLITERATION:
                _download_transliteration(key, progress_cb, progress_num_cb)
            elif category == CATEGORY_VOICES:
                _download_voice(key, progress_num_cb)
            else:
                raise ValueError(f"Unknown asset id: {asset_id}")
    except RuntimeError:
        raise
    except Exception as e:
        _log.error("Asset download failed (%s): %r", asset_id, e, exc_info=True)
        raise RuntimeError(f"Download failed: {e}") from e


def delete_asset(asset_id: str) -> None:
    """Remove one downloaded catalog asset from local storage. Raises RuntimeError on failure."""
    try:
        category, key = _split_id(asset_id)
        if category == CATEGORY_WHISPER:
            _delete_hf_repo(ModelRepos.WHISPER[key])
        elif category == CATEGORY_TRANSLATION and _is_model_folder(key):
            translation_files.remove_model(key)
        elif category == CATEGORY_TRANSLATION:
            _delete_translation_pair(*_translation_pair(key))
        elif category == CATEGORY_TRANSLITERATION:
            _delete_transliteration(key)
        elif category == CATEGORY_VOICES:
            _delete_voice(key)
        else:
            raise ValueError(f"Unknown asset id: {asset_id}")
    except Exception as e:
        _log.error("Asset delete failed (%s): %r", asset_id, e, exc_info=True)
        raise RuntimeError(f"Remove failed: {e}") from e


def _whisper_assets(cache_info: Optional[Any]) -> list[AssetInfo]:
    """Build the Whisper Models category rows."""
    assets: list[AssetInfo] = []
    for name in ModelDefaults.SUPPORTED_MODELS:
        downloaded = model_status.whisper_cached(name, cache_info=cache_info)
        assets.append(AssetInfo(
            id=f"{CATEGORY_WHISPER}:{name}",
            category=CATEGORY_WHISPER,
            engine=ENGINE_WHISPER_GROUP,
            label=name,
            name=f"Whisper {name}",
            downloaded=downloaded,
            size_bytes=_hf_repo_size(ModelRepos.WHISPER[name], cache_info) if downloaded else None,
            approx_size_mb=_approx_mb(CATEGORY_WHISPER, name),
        ))
    return assets


def _translation_assets() -> list[AssetInfo]:
    """Build the Translation category rows: CTranslate2 models, Hy-MT2, the meaning check, then Argos."""
    assets: list[AssetInfo] = []
    for model in CT2_MODELS.values():
        downloaded = translation_files.is_ready(model.key, model.revision)
        engine = engine_info(model.engine).label
        assets.append(AssetInfo(
            id=f"{CATEGORY_TRANSLATION}:{model.key}",
            category=CATEGORY_TRANSLATION,
            engine=engine,
            label=model.label,
            # OPUS-MT has one model per direction; NLLB and MADLAD each cover every pair.
            name=f"{engine} {model.label}" if model.engine == ENGINE_OPUS_MT else engine,
            downloaded=downloaded,
            size_bytes=translation_files.folder_size(model.key) if downloaded else None,
            approx_size_mb=_approx_mb(CATEGORY_TRANSLATION, model.key),
        ))
    hymt_ready = translation_files.is_ready(HYMT_MODEL.key, HYMT_MODEL.revision)
    assets.append(AssetInfo(
        id=f"{CATEGORY_TRANSLATION}:{HYMT_MODEL.key}",
        category=CATEGORY_TRANSLATION,
        engine=engine_info(ENGINE_HYMT).label,
        label=HYMT_MODEL.label,
        name=engine_info(ENGINE_HYMT).label,
        downloaded=hymt_ready,
        size_bytes=translation_files.folder_size(HYMT_MODEL.key) if hymt_ready else None,
        approx_size_mb=_approx_mb(CATEGORY_TRANSLATION, HYMT_MODEL.key),
    ))
    meaning_ready = translation_files.is_ready(MEANING_MODEL.key, MEANING_MODEL.revision)
    assets.append(AssetInfo(
        id=f"{CATEGORY_TRANSLATION}:{MEANING_MODEL.key}",
        category=CATEGORY_TRANSLATION,
        engine=ENGINE_MEANING_CHECK,
        label="Compares each translation with the original (50+ languages)",
        name="the meaning check model",
        downloaded=meaning_ready,
        size_bytes=translation_files.folder_size(MEANING_MODEL.key) if meaning_ready else None,
        approx_size_mb=_approx_mb(CATEGORY_TRANSLATION, MEANING_MODEL.key),
    ))
    for name, code in LanguageOptions.TRANSLATION_TARGETS:
        if code == _PIVOT_LANG:
            continue  # "English → English" isn't a real, installable pair
        for source, target, label in (
            (_PIVOT_LANG, code, f"English → {name}"),
            (code, _PIVOT_LANG, f"{name} → English"),
        ):
            downloaded = model_status.translation_pair_cached(source, target)
            assets.append(AssetInfo(
                id=f"{CATEGORY_TRANSLATION}:{source}-{target}",
                category=CATEGORY_TRANSLATION,
                engine=ENGINE_ARGOS_TRANSLATE,
                label=label,
                name=f"{ENGINE_ARGOS_TRANSLATE} {label}",
                downloaded=downloaded,
                size_bytes=_installed_pair_size(source, target) if downloaded else None,
                approx_size_mb=_approx_mb(CATEGORY_TRANSLATION, f"{source}-{target}"),
            ))
    return assets


def _translation_pair(key: str) -> tuple[str, str]:
    """Split a translation asset key like "en-ur" into (source, target)."""
    source, _, target = key.partition("-")
    if not source or not target:
        raise ValueError(f"Unknown translation asset: {key}")
    return source, target


def _transliteration_assets(cache_info: Optional[Any]) -> list[AssetInfo]:
    """Build the Transliteration Models category rows."""
    assets: list[AssetInfo] = []
    for key, pair, label in (
        ("roman-ur", ("roman", "ur"), "Roman → Urdu"),
        ("ur-roman", ("ur", "roman"), "Urdu → Roman"),
    ):
        downloaded = model_status.neural_translit_cached(*pair, cache_info=cache_info)
        assets.append(AssetInfo(
            id=f"{CATEGORY_TRANSLITERATION}:{key}",
            category=CATEGORY_TRANSLITERATION,
            engine=ENGINE_NEURAL_GROUP,
            label=label,
            name=f"the {label} transliteration model",
            downloaded=downloaded,
            size_bytes=_translit_pair_size(ModelRepos.M2M100[pair], cache_info) if downloaded else None,
            approx_size_mb=_approx_mb(CATEGORY_TRANSLITERATION, key),
        ))
    rekhta_downloaded = model_status.neural_translit_cached("hi", "ur", cache_info=cache_info)
    assets.append(AssetInfo(
        id=f"{CATEGORY_TRANSLITERATION}:hi-ur",
        category=CATEGORY_TRANSLITERATION,
        engine=ENGINE_NEURAL_GROUP,
        label="Hindi/Punjabi → Urdu",
        name="the Hindi/Punjabi → Urdu transliteration model",
        downloaded=rekhta_downloaded,
        size_bytes=_hf_repo_size(ModelRepos.REKHTA, cache_info) if rekhta_downloaded else None,
        approx_size_mb=_approx_mb(CATEGORY_TRANSLITERATION, "hi-ur"),
    ))
    return assets


def _voice_assets(cache_info: Optional[Any]) -> list[AssetInfo]:
    """Build the Voices category rows: the OmniVoice and XTTS checkpoints, Kokoro's model, and each
    Piper voice, grouped under the Dub tab's names for them."""
    omnivoice_downloaded = voice_files.engine_files_cached(ENGINE_OMNIVOICE)
    xtts_downloaded = voice_files.engine_files_cached(ENGINE_XTTS)
    kokoro_downloaded = voice_files.engine_files_cached(ENGINE_KOKORO)
    kokoro_dir = os.path.dirname(voice_files.kokoro_paths()[0])
    assets = [
        AssetInfo(
            id=f"{CATEGORY_VOICES}:{ENGINE_OMNIVOICE}",
            category=CATEGORY_VOICES,
            engine=_DUB_MODE_LABELS[ENGINE_OMNIVOICE],
            label="Voice cloning model for every language, with its speaker detector",
            name="OmniVoice",
            downloaded=omnivoice_downloaded,
            size_bytes=sum(
                _hf_repo_size(repo, cache_info) or 0 for repo in (ModelRepos.OMNIVOICE, ModelRepos.SPEAKER_VECTORS)
            ) if omnivoice_downloaded else None,
            approx_size_mb=_approx_mb(CATEGORY_VOICES, ENGINE_OMNIVOICE),
        ),
        AssetInfo(
            id=f"{CATEGORY_VOICES}:{ENGINE_XTTS}",
            category=CATEGORY_VOICES,
            engine=_DUB_MODE_LABELS[ENGINE_XTTS],
            label="Voice cloning model",
            name="XTTS-v2",
            downloaded=xtts_downloaded,
            size_bytes=_hf_repo_size(ModelRepos.XTTS, cache_info) if xtts_downloaded else None,
            approx_size_mb=_approx_mb(CATEGORY_VOICES, ENGINE_XTTS),
        ),
        AssetInfo(
            id=f"{CATEGORY_VOICES}:{ENGINE_KOKORO}",
            category=CATEGORY_VOICES,
            engine=_DUB_MODE_LABELS[ENGINE_KOKORO],
            label=f"Kokoro model and all {sum(v.engine == ENGINE_KOKORO for v in VOICES)} voices",
            name="the Kokoro voices",
            downloaded=kokoro_downloaded,
            size_bytes=voice_files.folder_size(kokoro_dir) if kokoro_downloaded else None,
            approx_size_mb=_approx_mb(CATEGORY_VOICES, ENGINE_KOKORO),
        ),
    ]
    for voice in VOICES:
        if voice.engine != ENGINE_PIPER:
            continue
        downloaded = voice_files.engine_files_cached(ENGINE_PIPER, voice)
        assets.append(AssetInfo(
            id=f"{CATEGORY_VOICES}:{voice.key}",
            category=CATEGORY_VOICES,
            engine=_DUB_MODE_LABELS[ENGINE_PIPER],
            label=voice.label,
            name=f"the Piper voice {voice.label}",
            downloaded=downloaded,
            size_bytes=voice_files.folder_size(voice_files.voice_dir(voice)) if downloaded else None,
            approx_size_mb=_approx_mb(CATEGORY_VOICES, voice.key),
        ))
    return assets


def _approx_mb(category: str, key: str) -> Optional[int]:
    """Approximate download size of one asset in MB, None when unknown; ValueError for a bad key."""
    if category == CATEGORY_WHISPER:
        return ModelDefaults.MODEL_SIZES_MB.get(key)
    if category == CATEGORY_TRANSLATION:
        if _is_model_folder(key):
            model = CT2_MODELS.get(key) or (HYMT_MODEL if key == HYMT_MODEL.key else MEANING_MODEL)
            return model.download_mb
        source, target = _translation_pair(key)
        # An Argos package is about the same size in both directions.
        return _TRANSLATION_APPROX_SIZES_MB.get(target if source == _PIVOT_LANG else source)
    if category == CATEGORY_TRANSLITERATION:
        return _TRANSLIT_APPROX_SIZES_MB.get(key)
    if category == CATEGORY_VOICES:
        if key == ENGINE_OMNIVOICE:
            return round((ModelRepos.OMNIVOICE_SIZE_BYTES + ModelRepos.SPEAKER_VECTORS_SIZE_BYTES) / 1_000_000)
        if key == ENGINE_XTTS:
            return round(ModelRepos.XTTS_SIZE_BYTES / 1_000_000)
        if key == ENGINE_KOKORO:
            return round(sum(size for _, size, _ in ModelRepos.KOKORO_FILES) / 1_000_000)
        return round(_piper_voice(key).approx_size_bytes / 1_000_000) or None
    return None


def _is_model_folder(key: str) -> bool:
    """True for a translation asset kept in the app's translation folder rather than by Argos."""
    return key in CT2_MODELS or key in (MEANING_MODEL.key, HYMT_MODEL.key)


def _existing_folder(folder: str) -> str:
    """`folder`, or its nearest parent that exists (a model's folder is made by its first download)."""
    path = os.path.abspath(folder)
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def _download_voice(key: str, progress_num_cb: Optional[Callable[[int, int], None]]) -> None:
    """Download the OmniVoice or XTTS checkpoint, Kokoro's model, or one Piper voice."""
    if key == ENGINE_OMNIVOICE:
        voice_files.ensure_omnivoice(progress_num_cb)
        voice_files.ensure_speaker_vectors(progress_num_cb)
    elif key == ENGINE_XTTS:
        voice_files.ensure_xtts(progress_num_cb)
    elif key == ENGINE_KOKORO:
        voice_files.ensure_kokoro(progress_num_cb)
    else:
        voice_files.ensure_piper(_piper_voice(key), progress_num_cb)


def _delete_voice(key: str) -> None:
    """Remove the OmniVoice or XTTS checkpoint, Kokoro's model, or one Piper voice."""
    if key == ENGINE_OMNIVOICE:
        _delete_hf_repo(ModelRepos.OMNIVOICE)
        _delete_hf_repo(ModelRepos.SPEAKER_VECTORS)
    elif key == ENGINE_XTTS:
        _delete_hf_repo(ModelRepos.XTTS)
    elif key == ENGINE_KOKORO:
        voice_files.remove_engine_files(ENGINE_KOKORO)
    else:
        voice_files.remove_engine_files(ENGINE_PIPER, _piper_voice(key))


def _piper_voice(key: str) -> VoiceOption:
    """Resolve a "piper:<voice id>" asset key to its catalog voice."""
    voice = voice_by_key(key)
    if voice is None or voice.engine != ENGINE_PIPER:
        raise ValueError(f"Unknown voice asset: {key}")
    return voice


def _download_whisper(model_name: str, progress_num_cb: Optional[Callable[[int, int], None]]) -> None:
    """Trigger a faster-whisper model download by instantiating it once."""
    with download_progress(progress_num_cb):
        WhisperModel(model_name, device="cpu", compute_type="int8")


def _download_transliteration(
    key: str,
    progress_cb: Optional[Callable[[str], None]],
    progress_num_cb: Optional[Callable[[int, int], None]],
) -> None:
    """Download one transliteration asset: an M2M100 direction pair or the Rekhta model."""
    if key == "roman-ur":
        NeuralEngine("roman", "ur").ensure_loaded(progress_cb, progress_num_cb)
    elif key == "ur-roman":
        NeuralEngine("ur", "roman").ensure_loaded(progress_cb, progress_num_cb)
    elif key == "hi-ur":
        RekhtaBackend().load(progress_cb, progress_num_cb)
    else:
        raise ValueError(f"Unknown transliteration asset: {key}")


def _delete_transliteration(key: str) -> None:
    """Delete one transliteration asset's model repo (the shared tokenizer is left in place)."""
    if key == "roman-ur":
        _delete_hf_repo(ModelRepos.M2M100[("roman", "ur")])
    elif key == "ur-roman":
        _delete_hf_repo(ModelRepos.M2M100[("ur", "roman")])
    elif key == "hi-ur":
        _delete_hf_repo(ModelRepos.REKHTA)
    else:
        raise ValueError(f"Unknown transliteration asset: {key}")


def _delete_hf_repo(repo_id: str) -> None:
    """Delete every cached revision of one Hugging Face repo, if present."""
    cache_info = scan_cache_dir()
    repo = next((r for r in cache_info.repos if r.repo_id == repo_id), None)
    if repo is None:
        return
    hashes = [rev.commit_hash for rev in repo.revisions]
    cache_info.delete_revisions(*hashes).execute()


def _delete_translation_pair(source: str, target: str) -> None:
    """Uninstall the Argos package for one language pair, if installed."""
    installed = argostranslate.package.get_installed_packages()
    pkg = next((p for p in installed if p.from_code == source and p.to_code == target), None)
    if pkg is not None:
        argostranslate.package.uninstall(pkg)


def _scan_cache() -> Optional[Any]:
    """Scan the Hugging Face cache once for a catalog build; None when the scan fails."""
    try:
        return scan_cache_dir()
    except Exception:
        _log.debug("Failed to scan Hugging Face cache", exc_info=True)
        return None


def _hf_repo_size(repo_id: str, cache_info: Optional[Any] = None) -> Optional[int]:
    """Return the on-disk size of a cached Hugging Face repo, or None when not cached."""
    try:
        if cache_info is None:
            cache_info = scan_cache_dir()
        repo = next((r for r in cache_info.repos if r.repo_id == repo_id), None)
        return repo.size_on_disk if repo else None
    except Exception:
        _log.debug("Failed to size Hugging Face repo %s", repo_id, exc_info=True)
        return None


def _translit_pair_size(model_repo: str, cache_info: Optional[Any] = None) -> Optional[int]:
    """Return the combined size of an M2M100 direction repo plus the shared tokenizer repo."""
    model_size = _hf_repo_size(model_repo, cache_info)
    if model_size is None:
        return None
    return model_size + (_hf_repo_size(ModelRepos.M2M100_TOKENIZER, cache_info) or 0)


def _installed_pair_size(source: str, target: str) -> Optional[int]:
    """Return the on-disk size of an installed Argos package, or None when not installed."""
    try:
        installed = argostranslate.package.get_installed_packages()
        pkg = next((p for p in installed if p.from_code == source and p.to_code == target), None)
        if pkg is None:
            return None
        return sum(f.stat().st_size for f in Path(pkg.package_path).rglob("*") if f.is_file())
    except Exception:
        _log.debug("Failed to size Argos package %s→%s", source, target, exc_info=True)
        return None


def _split_id(asset_id: str) -> tuple[str, str]:
    """Split an asset id like 'whisper:tiny' into (category, key)."""
    category, _, key = asset_id.partition(":")
    return category, key
