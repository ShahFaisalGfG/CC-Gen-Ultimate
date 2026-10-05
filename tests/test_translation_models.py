# test_translation_models.py - translation model catalog, CTranslate2 engine, meaning check, model files

from types import SimpleNamespace

import numpy as np
import pytest

from ccgen.config.capabilities import translation_asset_ids
from ccgen.config.defaults import LanguageOptions
from ccgen.config.translation_models import (
    ENGINE_KEYS,
    MADLAD_CODES,
    NLLB_CODES,
    OPUS_MT_LEGS,
    OPUS_MT_MODELS,
    models_for,
    route,
)
from ccgen.engines.translation import ct2_engine, fidelity, model_files

_SOURCES = [code for _, code in LanguageOptions.TRANSCRIPTION if code]
_TARGETS = [code for _, code in LanguageOptions.TRANSLATION_TARGETS]


class TestCatalog:
    @pytest.mark.parametrize("engine", ["opus_mt", "nllb", "madlad"])
    def test_every_offered_pair_has_a_route(self, engine):
        for source in _SOURCES:
            for target in _TARGETS:
                if source != target:
                    assert route(engine, source, target), (engine, source, target)

    def test_opus_mt_goes_through_english_only_when_needed(self):
        assert route("opus_mt", "en", "ur") == [("en", "ur")]
        assert route("opus_mt", "zh", "ur") == [("zh", "en"), ("en", "ur")]

    def test_every_leg_points_at_a_catalog_model(self):
        assert {leg.model for leg in OPUS_MT_LEGS.values()} == set(OPUS_MT_MODELS)

    def test_language_tables_cover_every_language(self):
        assert set(_SOURCES) | set(_TARGETS) <= set(NLLB_CODES) == set(MADLAD_CODES)

    def test_shared_models_are_downloaded_once(self):
        assert [m.key for m in models_for("opus_mt", "hi", "ur")] == ["opus_mt-iir-en", "opus_mt-en-iir"]

    def test_asset_ids_follow_the_engine(self):
        assert translation_asset_ids("en", "ur", "opus_mt") == ["translation:opus_mt-en-iir"]
        assert translation_asset_ids("", "ur", "opus_mt") == ["translation:opus_mt-en-iir"]
        assert translation_asset_ids("fr", "ur", "nllb") == ["translation:nllb-1.3b"]
        assert translation_asset_ids("en", "ur", "argos") == ["translation:en-ur"]

    def test_engine_keys_are_the_settings_choices(self):
        assert ENGINE_KEYS[0] == "opus_mt" and set(ENGINE_KEYS) == {"opus_mt", "nllb", "madlad", "argos"}


class _FakeTokenizer:
    """Splits on spaces; token ids are the tokens themselves."""

    src_lang = ""

    def encode(self, text):
        return text.split()

    def convert_ids_to_tokens(self, ids):
        return list(ids)

    def convert_tokens_to_ids(self, tokens):
        return list(tokens)

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(t for t in ids if not (t.startswith(">>") or t.endswith("_Arab")))


class _FakeTranslator:
    """Records each batch and answers with numbered candidates."""

    def __init__(self, tag):
        self.tag = tag
        self.batches = []

    def translate_batch(self, batch, num_hypotheses=1, target_prefix=None, **options):
        self.batches.append((batch, target_prefix, num_hypotheses))
        prefix = target_prefix[0] if target_prefix else []
        return [
            SimpleNamespace(hypotheses=[prefix + [f"{self.tag}{n}"] + tokens for n in range(num_hypotheses)])
            for tokens in batch
        ]


class _PreferLast:
    """Meaning check stand-in that prefers each source's last candidate."""

    def ensure(self, status_cb=None, progress_cb=None):
        pass

    def choose(self, sources, candidates, target):
        return [(options[-1], 0.9) for options in candidates]


def _engine(name, source, target, meaning=None, monkeypatch=None):
    engine = ct2_engine.Ct2Engine(name, source, target, meaning)
    translators = {}

    def fake_ensure(model, status_cb=None, progress_cb=None):
        return f"/models/{model.key}"

    def fake_load(self, model, folder):
        translators[model.key] = _FakeTranslator(model.key.split("-")[-1] + ":")
        return ct2_engine._Loaded(translators[model.key], _FakeTokenizer(), "cpu")

    monkeypatch.setattr(ct2_engine, "ensure_model", fake_ensure)
    monkeypatch.setattr(ct2_engine.Ct2Engine, "_load", fake_load)
    monkeypatch.setattr(ct2_engine._models, "get_or_load", lambda key, loader: loader())
    return engine, translators


def _segments(*texts):
    return [{"id": i, "start": float(i), "end": i + 1.0, "text": t} for i, t in enumerate(texts)]


class TestCt2Engine:
    def test_opus_mt_adds_the_target_token(self, monkeypatch):
        engine, translators = _engine("opus_mt", "en", "ur", monkeypatch=monkeypatch)
        engine.ensure_model()
        out = engine.translate_segments(_segments("hello world"))
        batch, _, _ = translators["opus_mt-en-iir"].batches[0]
        assert batch == [[">>urd<<", "hello", "world"]]
        assert out[0]["translated"] == "iir:0 hello world"

    def test_pivot_route_runs_both_models_in_order(self, monkeypatch):
        engine, translators = _engine("opus_mt", "zh", "ur", monkeypatch=monkeypatch)
        engine.ensure_model()
        out = engine.translate_segments(_segments("ni hao"))
        assert translators["opus_mt-zh-en"].batches[0][0] == [["ni", "hao"]]
        assert out[0]["translated"] == "iir:0 en:0 ni hao"

    def test_nllb_uses_its_language_codes(self, monkeypatch):
        engine, translators = _engine("nllb", "en", "ur", monkeypatch=monkeypatch)
        engine.ensure_model()
        out = engine.translate_segments(_segments("hello"))
        assert translators["nllb-1.3b"].batches[0][1] == [["urd_Arab"]]
        assert out[0]["translated"] == "1.3b:0 hello"

    def test_meaning_check_picks_among_candidates_on_the_last_step(self, monkeypatch):
        engine, translators = _engine("opus_mt", "zh", "ur", _PreferLast(), monkeypatch)
        engine.ensure_model()
        out = engine.translate_segments(_segments("ni hao"))
        assert translators["opus_mt-zh-en"].batches[0][2] == 1
        assert translators["opus_mt-en-iir"].batches[0][2] == ct2_engine._CANDIDATES
        assert out[0]["translated"].startswith(f"iir:{ct2_engine._CANDIDATES - 1} ")

    def test_empty_lines_stay_empty_and_are_not_translated(self, monkeypatch):
        engine, translators = _engine("opus_mt", "en", "fr", monkeypatch=monkeypatch)
        engine.ensure_model()
        out = engine.translate_segments(_segments("", "hi"))
        assert [o["translated"] for o in out] == ["", "fr:0 hi"]
        assert translators["opus_mt-en-fr"].batches[0][0] == [["hi"]]

    def test_translating_before_loading_is_refused(self, monkeypatch):
        engine, _ = _engine("opus_mt", "en", "fr", monkeypatch=monkeypatch)
        with pytest.raises(RuntimeError, match="ensure_model"):
            engine.translate_segments(_segments("hi"))


class _FakeMeaning(fidelity.MeaningCheck):
    """Embeds by a fixed table so similarities are exact."""

    def __init__(self, vectors):
        super().__init__()
        self.vectors = vectors

    def _embed(self, texts):
        rows = np.array([self.vectors[t] for t in texts], dtype=np.float32)
        return rows / np.linalg.norm(rows, axis=1, keepdims=True)


class TestMeaningCheck:
    def test_keeps_the_candidate_closest_in_meaning(self):
        check = _FakeMeaning({"Good links": [1, 0], "اچھے لنکس": [1, 0.1], "اچھے رشتے": [0.2, 1]})
        [(best, score)] = check.choose(["Good links"], [["اچھے رشتے", "اچھے لنکس"]], "ur")
        assert best == "اچھے لنکس" and score > 0.9

    def test_an_untranslated_copy_is_penalised(self):
        assert fidelity._penalty("Good links", "Good links", "ur") >= fidelity._WRONG_SCRIPT_PENALTY
        assert fidelity._penalty("Good links", "Bons liens", "fr") == 0

    def test_lost_terms_and_odd_lengths_are_penalised(self):
        assert fidelity._penalty("Open our GitHub page", "ہمارا صفحہ کھولیں", "ur") == pytest.approx(fidelity._LOST_TERM_PENALTY)
        assert fidelity._penalty("A long sentence about many things", "ہاں", "ur") >= fidelity._LENGTH_PENALTY


class TestModelFiles:
    def test_ready_only_with_a_matching_marker(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert not model_files.is_ready("opus_mt-en-fr", "abc")
        (tmp_path / "CC-Gen-Ultimate" / "translation" / "opus_mt-en-fr").mkdir(parents=True)
        model_files._mark_ready("opus_mt-en-fr", "abc")
        assert model_files.is_ready("opus_mt-en-fr", "abc")
        assert not model_files.is_ready("opus_mt-en-fr", "newer")

    def test_remove_stays_inside_the_translation_folder(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        folder = tmp_path / "CC-Gen-Ultimate" / "translation" / "opus_mt-en-fr"
        folder.mkdir(parents=True)
        (folder / "model.bin").write_bytes(b"x")
        model_files.remove_model("opus_mt-en-fr")
        assert not folder.exists()
        with pytest.raises(ValueError, match="Refusing"):
            model_files.remove_model("..")
