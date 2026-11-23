# model_needs.py - the models a run will download before it starts working, and how long that takes
#
# A first run downloads its models (a first dub with voice cloning: 3.7 GB), which looks like a hang
# when nobody says so. The tabs show this note beside Start. It covers the speech recognition and
# voice models, the large ones; translation and transliteration models are smaller and per language
# pair, and are left to the run's own status messages.

from typing import Any, Optional

from ccgen.config.defaults import DubbingDefaults, ModelDefaults, ModelRepos
from ccgen.config.profiles import dub_engine, effective_profile, whisper_model
from ccgen.core import jobs
from ccgen.core.errors import format_size
from ccgen.engines.speech import voice_files
from ccgen.utils import model_status

# The connection the estimate assumes, in bytes per second (50 Mbit/s).
ASSUMED_BYTES_PER_SECOND = 50_000_000 / 8
_VOICE_BYTES = {
    DubbingDefaults.MODE_OMNIVOICE: ModelRepos.OMNIVOICE_SIZE_BYTES + ModelRepos.SPEAKER_VECTORS_SIZE_BYTES,
    DubbingDefaults.MODE_XTTS: ModelRepos.XTTS_SIZE_BYTES,
    DubbingDefaults.MODE_KOKORO: sum(size for _, size, _ in ModelRepos.KOKORO_FILES),
}
_VOICE_NAMES = {
    DubbingDefaults.MODE_OMNIVOICE: "OmniVoice voice cloning",
    DubbingDefaults.MODE_XTTS: "XTTS-v2 voice cloning",
    DubbingDefaults.MODE_KOKORO: "Kokoro voices",
}


def missing_models(
    task: str, options: dict[str, Any], settings: dict[str, Any], has_media: bool,
    steps: Optional[list[dict[str, Any]]] = None,
) -> list[tuple[str, int]]:
    """(name, size in bytes) of each large model a run would download first.

    `has_media` says whether the queue holds video or audio, which is transcribed first.
    """
    profile = effective_profile(settings)
    whisper: list[str] = []
    voices: list[str] = []
    if task == "generate":
        whisper.append(str(options["model_name"]))
    elif task == "workflow":
        for step in steps or []:
            if step["kind"] == "generate":
                whisper.append(str(step["model_name"]))
            elif step["kind"] == "dub":
                voices.append(dub_engine(step["mode"], profile, step.get("quality", "auto")).mode)
    elif has_media:
        whisper.append(str(jobs.generate_step_options(settings)["model_name"]))
    if task == "dub":
        voices.append(dub_engine(options["mode"], profile, options.get("quality", "auto")).mode)
    missing: list[tuple[str, int]] = []
    for choice in dict.fromkeys(whisper):
        name = whisper_model(choice, profile)
        if not model_status.whisper_cached(name):
            missing.append((f"Whisper {name}", ModelDefaults.MODEL_SIZES_MB.get(name, 0) * 1_000_000))
    for engine in dict.fromkeys(voices):
        if engine in _VOICE_BYTES and not voice_files.engine_files_cached(engine):
            missing.append((_VOICE_NAMES[engine], _VOICE_BYTES[engine]))
    return missing


def download_note(missing: list[tuple[str, int]]) -> str:
    """One sentence for the run bar: what Start downloads first, and about how long it takes."""
    if not missing:
        return ""
    total = sum(size for _, size in missing)
    minutes = max(1, round(total / ASSUMED_BYTES_PER_SECOND / 60))
    names = ", ".join(f"{name} ({format_size(size)})" for name, size in missing)
    return f"Start downloads {names} first: about {minutes} min at 50 Mbit/s. It runs offline after that."
