# licences.py - models whose licence must be accepted once before they run
#
# These models allow non-commercial use only. The app shows each licence once (the
# ModelTermsDialog) and records the answer in settings; tasks that would run an unaccepted model
# are held back with the blocker message. Automatic choices are resolved first (see profiles.py),
# so a profile that picks one of these models asks for its licence too.

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from ccgen.config.defaults import DubbingDefaults
from ccgen.config.translation_models import ENGINE_NLLB, NLLB_TERMS_SETTING


@dataclass(frozen=True)
class ModelTerms:
    """The licence notice for one model and where its acceptance is saved."""

    key: str
    setting: str
    title: str
    body: str
    note: str
    url: str
    site: str
    blocker: str


TERMS: dict[str, ModelTerms] = {
    ENGINE_NLLB: ModelTerms(
        key=ENGINE_NLLB, setting=f"translation.{NLLB_TERMS_SETTING}", title="NLLB-200 licence",
        body="The NLLB-200 translation model by Meta is released under the Creative Commons Attribution-"
             "NonCommercial 4.0 licence. It allows personal, research, and other non-commercial use of the "
             "model. Commercial use isn't allowed.",
        note="OPUS-MT, MADLAD-400, and Argos Translate have no such limits.",
        url="https://creativecommons.org/licenses/by-nc/4.0/", site="creativecommons.org",
        blocker="Accept the NLLB-200 licence to translate this language pair (see the notice under Translation).",
    ),
    DubbingDefaults.MODE_OMNIVOICE: ModelTerms(
        key=DubbingDefaults.MODE_OMNIVOICE, setting="dubbing.omnivoice_terms_accepted", title="OmniVoice licence",
        body="Voice cloning uses the OmniVoice model by k2-fsa, released under the Creative Commons Attribution-"
             "NonCommercial licence. It allows personal, research, and other non-commercial use of the model "
             "and of the audio it creates. Commercial use isn't allowed. Its audio codec is built with Higgs "
             "Materials licensed from Boson AI USA, Inc. under the Boson Higgs Audio 2 Community License, based "
             "on Meta Llama 3 (Copyright Meta Platforms, Inc.), and follows the Llama 3 Acceptable Use Policy.",
        note="Only clone voices you have permission to use. Kokoro and Piper voices have no such limits.",
        url="https://huggingface.co/k2-fsa/OmniVoice", site="huggingface.co/k2-fsa/OmniVoice",
        blocker="Accept the OmniVoice licence to use voice cloning (see the notice under Voices).",
    ),
    DubbingDefaults.MODE_XTTS: ModelTerms(
        key=DubbingDefaults.MODE_XTTS, setting="dubbing.xtts_terms_accepted", title="XTTS-v2 licence",
        body="Voice cloning uses the XTTS-v2 model by Coqui, released under the Coqui Public Model License. "
             "It allows personal, research, and other non-commercial use of the model and of the audio it "
             "creates. Commercial use needs a separate licence.",
        note="Only clone voices you have permission to use. Kokoro and Piper voices have no such limits.",
        url="https://coqui.ai/cpml", site="coqui.ai/cpml",
        blocker="Accept the XTTS-v2 licence to use voice cloning (see the notice under Voices).",
    ),
}


def accepted(settings: dict[str, Any], key: str) -> bool:
    """True when `key` needs no licence or its licence was accepted."""
    terms = TERMS.get(key)
    if terms is None:
        return True
    section, name = terms.setting.split(".")
    return bool(settings.get(section, {}).get(name))


def pending(settings: dict[str, Any], keys: Iterable[str]) -> str:
    """The first of `keys` whose licence still has to be accepted, or ""."""
    return next((key for key in keys if not accepted(settings, key)), "")


def blocker(settings: dict[str, Any], keys: Iterable[str]) -> str:
    """Why a task can't start yet because of an unaccepted licence, or ""."""
    key = pending(settings, keys)
    return TERMS[key].blocker if key else ""


def terms_dict(key: str) -> dict[str, str]:
    """A licence notice as plain values for the QML dialog ({} for an unknown key)."""
    terms = TERMS.get(key)
    return asdict(terms) if terms else {}
