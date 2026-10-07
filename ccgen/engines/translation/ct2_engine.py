# ct2_engine.py - OPUS-MT, NLLB-200, and MADLAD-400 translation on CTranslate2
#
# All three run on CTranslate2, the runtime faster-whisper already ships: 8-bit on the CPU, or
# float16 on an NVIDIA GPU when one works. Each family only differs in how text becomes tokens
# and how the target language is chosen (OPUS-MT: a >>urd<< token for multi-target models;
# NLLB: a target language prefix; MADLAD: a <2ur> tag). Sentences are translated in batches,
# and with the meaning check on, the last step asks for several candidates and keeps the one
# whose meaning stays closest to the original.

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

import ctranslate2

from ccgen.config.translation_models import (
    ENGINE_MADLAD,
    ENGINE_NLLB,
    ENGINE_OPUS_MT,
    MADLAD_CODES,
    NLLB_CODES,
    OPUS_MT_LEGS,
    Ct2Model,
    engine_info,
    models_for,
    route,
)
from ccgen.core import Segment, TranslatedSegment
from ccgen.engines.model_cache import ModelCache
from ccgen.engines.translation.base import TranslationEngine
from ccgen.engines.translation.fidelity import MeaningCheck
from ccgen.engines.translation.model_files import ensure_model, tokenizer_folder
from ccgen.utils.callbacks import JobCancelled, emit_progress, emit_segment, emit_status

_log = logging.getLogger(__name__)

# A pivot route (Chinese -> English -> Urdu) keeps both of its models loaded.
_models: ModelCache["_Loaded"] = ModelCache("Translation", capacity=2)
_BATCH = 8
_BEAM = 4
_CANDIDATES = 4
_MAX_TOKENS = 512


@dataclass
class _Loaded:
    """A model ready to translate: the CTranslate2 translator and its tokenizer."""

    translator: Any
    tokenizer: Any
    device: str


class Ct2Engine(TranslationEngine):
    """Translates with one of the CTranslate2 model families, through English when needed."""

    def __init__(
        self,
        engine: str,
        source_lang: str,
        target_lang: str,
        meaning: Optional[MeaningCheck] = None,
        for_speech: bool = False,
    ) -> None:
        self._engine = engine
        self._source_lang = source_lang
        self._target_lang = target_lang
        self._meaning = meaning
        # The translation will be dubbed: prefer candidates that take as long to say as the original.
        self._for_speech = for_speech
        self._legs: list[tuple[str, str]] = []
        self._loaded: dict[str, _Loaded] = {}

    def set_pair(self, source: str, target: str) -> None:
        """Change languages; models load again on the next ensure_model()."""
        self._source_lang = source
        self._target_lang = target
        self._legs = []
        self._loaded = {}

    def ensure_model(
        self,
        progress_cb: Optional[Callable[[str], None]] = None,
        progress_num_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Download the models this pair needs on first use, then load them."""
        try:
            self._legs = route(self._engine, self._source_lang, self._target_lang)
            for model in models_for(self._engine, self._source_lang, self._target_lang):
                folder = ensure_model(model, progress_cb, progress_num_cb)
                self._loaded[model.key] = _models.get_or_load(model.key, lambda m=model, f=folder: self._load(m, f))
            if self._meaning is not None:
                self._meaning.ensure(progress_cb, progress_num_cb)
            label = engine_info(self._engine).label
            devices = sorted({loaded.device for loaded in self._loaded.values()})
            emit_status(progress_cb, f"{label} ready on {', '.join(devices).upper()}.")
        except (ValueError, JobCancelled):
            raise
        except Exception as e:
            _log.error("Translation model setup failed: %r", e, exc_info=True)
            raise RuntimeError(f"Translation model setup failed: {e}") from e

    def translate_segments(
        self,
        segments: list[Segment],
        progress_cb: Optional[Callable[[str], None]] = None,
        progress_num_cb: Optional[Callable[[int, int], None]] = None,
        segment_cb: Optional[Callable[[TranslatedSegment], None]] = None,
    ) -> list[TranslatedSegment]:
        """Translate sentence by sentence in batches, streaming each result as it is ready."""
        if not self._legs or not self._loaded:
            raise RuntimeError("Call ensure_model() before translate_segments().")
        results: list[TranslatedSegment] = []
        total = len(segments)
        for start in range(0, total, _BATCH):
            batch = segments[start:start + _BATCH]
            translations = self._translate_texts([seg["text"].strip() for seg in batch])
            for seg, translated in zip(batch, translations):
                result = TranslatedSegment(
                    id=seg["id"], start=seg["start"], end=seg["end"],
                    original=seg["text"].strip(), translated=translated, language=self._target_lang,
                )
                results.append(result)
                emit_segment(segment_cb, result)
                emit_progress(progress_num_cb, len(results), total)
        return results

    def _translate_texts(self, texts: list[str]) -> list[str]:
        """Run texts through every leg of the route; empty texts stay empty."""
        filled = [i for i, text in enumerate(texts) if text]
        current = [texts[i] for i in filled]
        for index, leg in enumerate(self._legs):
            last = index == len(self._legs) - 1
            rerank = last and self._meaning is not None
            candidates = self._translate_leg(leg, current, _CANDIDATES if rerank else 1)
            if rerank:
                assert self._meaning is not None
                originals = [texts[i] for i in filled]
                spoken_from = self._source_lang if self._for_speech else None
                chosen = self._meaning.choose(originals, candidates, self._target_lang, spoken_from)
                current = [best for best, _ in chosen]
            else:
                current = [options[0] for options in candidates]
        out = [""] * len(texts)
        for i, text in zip(filled, current):
            out[i] = text.strip()
        return out

    def _translate_leg(self, leg: tuple[str, str], texts: list[str], candidates: int) -> list[list[str]]:
        """Translate texts along one direction, returning `candidates` options for each."""
        if not texts:
            return []
        source, target = leg
        options: dict[str, Any] = {
            "beam_size": max(_BEAM, candidates), "num_hypotheses": candidates,
            "max_input_length": _MAX_TOKENS, "max_decoding_length": _MAX_TOKENS,
        }
        if self._engine == ENGINE_OPUS_MT:
            loaded = self._loaded[OPUS_MT_LEGS[leg].model]
            prefix = OPUS_MT_LEGS[leg].prefix
            tk = loaded.tokenizer
            batch = [tk.convert_ids_to_tokens(tk.encode(f"{prefix} {text}" if prefix else text)) for text in texts]
            results = loaded.translator.translate_batch(batch, **options)
            return [[tk.decode(tk.convert_tokens_to_ids(h), skip_special_tokens=True) for h in r.hypotheses] for r in results]
        if self._engine == ENGINE_NLLB:
            loaded = next(iter(self._loaded.values()))
            tk = loaded.tokenizer
            tk.src_lang = NLLB_CODES[source]
            batch = [tk.convert_ids_to_tokens(tk.encode(text)) for text in texts]
            prefix = [[NLLB_CODES[target]]] * len(batch)
            results = loaded.translator.translate_batch(batch, target_prefix=prefix, **options)
            # Each hypothesis starts with the target language code.
            return [[tk.decode(tk.convert_tokens_to_ids(h[1:]), skip_special_tokens=True) for h in r.hypotheses] for r in results]
        if self._engine == ENGINE_MADLAD:
            loaded = next(iter(self._loaded.values()))
            sp = loaded.tokenizer
            batch = [sp.encode(f"<2{MADLAD_CODES[target]}> {text}", out_type=str) for text in texts]
            # MADLAD repeats phrases without a penalty (OpenNMT's published setting).
            results = loaded.translator.translate_batch(batch, repetition_penalty=2.0, **options)
            return [[sp.decode(h) for h in r.hypotheses] for r in results]
        raise ValueError(f"Unknown translation model: '{self._engine}'.")

    def _load(self, model: Ct2Model, folder: str) -> _Loaded:
        """Open a model on an NVIDIA GPU when one works, otherwise on the CPU."""
        translator, device = _open_translator(folder)
        return _Loaded(translator, _load_tokenizer(model), device)


def _open_translator(folder: str) -> tuple[Any, str]:
    """A CTranslate2 translator in float16 on CUDA, or 8-bit on the CPU."""
    try:
        if ctranslate2.get_cuda_device_count() > 0:
            return ctranslate2.Translator(folder, device="cuda", compute_type="float16"), "gpu"
    except Exception as e:  # missing CUDA libraries or too little GPU memory
        _log.warning("Translation on the GPU failed, using the CPU: %r", e)
    return ctranslate2.Translator(folder, device="cpu", compute_type="int8"), "cpu"


def _load_tokenizer(model: Ct2Model) -> Any:
    """The tokenizer for a model family (loaded lazily: transformers is slow to import)."""
    folder = tokenizer_folder(model)
    if model.engine == ENGINE_OPUS_MT:
        from transformers import MarianTokenizer

        return MarianTokenizer.from_pretrained(folder)
    if model.engine == ENGINE_NLLB:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(folder)
    if model.engine == ENGINE_MADLAD:
        import sentencepiece

        processor = sentencepiece.SentencePieceProcessor()
        processor.Load(os.path.join(folder, "sentencepiece.model"))
        return processor
    raise ValueError(f"No tokenizer for '{model.engine}'.")
