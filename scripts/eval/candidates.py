# candidates.py - translation engines the benchmark tries before the app adopts them
#
#   opus_mt_next  OPUS-MT with newer Helsinki models for the directions listed in NEXT_LEGS, and
#                 the shipped models everywhere else. Models download into the app's own
#                 translation folder under "eval-" keys, so the shipped ones are reused.

from typing import Callable

from ccgen.config import translation_models as catalog
from ccgen.config.translation_models import Ct2Model, OpusLeg
from ccgen.engines.translation import MeaningCheck, create_engine

Translator = Callable[[list[str]], list[str]]

# direction -> (Helsinki-NLP repo, pinned revision, target token). The tc-big Korean models
# (ko-en, en-ko) are left out: their Hugging Face ports kept only one of the model's two
# vocabularies, so most Korean pieces become <unk> and the output is unrelated text.
NEXT_LEGS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("en", "de"): ("opus-mt-tc-bible-big-deu_eng_fra_por_spa-gmw", "0a10a154b1d057720d03d8227bc59ea9633c590b", ">>deu<<"),
    ("en", "ru"): ("opus-mt-tc-big-en-zle", "708be1d372fe4c358a352f404e6dc9ca0126ba48", ">>rus<<"),
    ("en", "hi"): ("opus-mt-tc-bible-big-deu_eng_fra_por_spa-inc", "fbdbc7e254bd11292c751508ef52c2a52ef4694f", ">>hin<<"),
    ("en", "ur"): ("opus-mt-tc-bible-big-deu_eng_fra_por_spa-inc", "fbdbc7e254bd11292c751508ef52c2a52ef4694f", ">>urd<<"),
    ("en", "ar"): ("opus-mt-tc-bible-big-deu_eng_fra_por_spa-sem", "e9c62f2708b7a131fc17868ecc21931c269cdcff", ">>ara<<"),
    ("en", "zh"): ("opus-mt-en-zh", "408d9bc410a388e1d9aef112a2daba955b945255", ">>cmn_Hans<<"),
    ("en", "ja"): ("opus-mt-tc-bible-big-deu_eng_fra_por_spa-mul", "160f64269da14c836871f8acf97553b23c63b979", ">>jpn<<"),
    ("de", "en"): ("opus-mt-tc-bible-big-gmw-en", "5af4b912a33023bc682ee6f27456dab65dbeaa73", ""),
    ("es", "en"): ("opus-mt-tc-bible-big-roa-en", "4d4757865ab116b39daa3b4ca3cfe1e7daf43cbe", ""),
    ("hi", "en"): ("opus-mt-tc-bible-big-inc-en", "c6a5899e32ecdfbba984e8351d5353a9338630ea", ""),
    ("ur", "en"): ("opus-mt-tc-bible-big-inc-en", "c6a5899e32ecdfbba984e8351d5353a9338630ea", ""),
    ("ru", "en"): ("opus-mt-tc-big-zle-en", "09a40f722d6d8b76aaad6fe51a06c914622a13d1", ""),
    ("zh", "en"): ("opus-mt-tc-bible-big-zhx-en", "bfaecff42f39b9b328e481571f4f2ced201a68b7", ""),
    ("ja", "en"): ("opus-mt-tc-bible-big-mul-deu_eng_nld", "bb1ef830d540449c89c7ee5b9ea5b1fc666db3d5", ">>eng<<"),
    ("ko", "en"): ("opus-mt-tc-bible-big-mul-deu_eng_nld", "bb1ef830d540449c89c7ee5b9ea5b1fc666db3d5", ">>eng<<"),
}

def translator(engine: str, source: str, target: str, meaning: MeaningCheck) -> Translator:
    """A translator for a candidate engine."""
    if engine == "opus_mt_next":
        _use_next_legs(source, target)
        instance = create_engine(catalog.ENGINE_OPUS_MT, source, target, meaning)
        instance.ensure_model()

        def run(texts: list[str]) -> list[str]:
            segments = [{"id": i, "start": float(i), "end": i + 1.0, "text": t} for i, t in enumerate(texts)]
            return [s["translated"] for s in instance.translate_segments(segments)]  # type: ignore[arg-type]
        return run
    raise ValueError(f"Unknown candidate engine '{engine}'.")


def _use_next_legs(source: str, target: str) -> None:
    """Point the OPUS-MT catalog at the candidate models for this route (in this process only)."""
    for leg in ((source, target), (source, "en"), ("en", target)):
        if leg in NEXT_LEGS:
            repo, revision, prefix = NEXT_LEGS[leg]
            key = f"eval-{repo}"
            catalog.OPUS_MT_MODELS[key] = Ct2Model(
                key, catalog.ENGINE_OPUS_MT, f"Helsinki-NLP/{repo}", revision, repo, 0, True,
            )
            catalog.OPUS_MT_LEGS[leg] = OpusLeg(key, prefix)
