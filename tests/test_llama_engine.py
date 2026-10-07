# test_llama_engine.py - Hy-MT2 translation on llama.cpp (with a fake model)

import pytest

from ccgen.config.capabilities import translation_asset_ids
from ccgen.config.defaults import LanguageOptions
from ccgen.config.translation_models import HYMT_MODEL, route
from ccgen.engines.translation import create_engine
from ccgen.engines.translation.llama_engine import LlamaEngine, prompt

_LANGUAGES = [code for _, code in LanguageOptions.TRANSLATION_TARGETS]


class _FakeLlama:
    """Answers every prompt with "[<last line of the prompt>]" and records the prompts."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def create_chat_completion(self, messages, temperature, max_tokens):
        text = messages[0]["content"]
        self.prompts.append(text)
        return {"choices": [{"message": {"content": f" [{text.splitlines()[-1]}] "}}]}


@pytest.fixture
def engine(monkeypatch):
    from ccgen.engines.translation import llama_engine

    model = _FakeLlama()
    monkeypatch.setattr(llama_engine, "ensure_gguf", lambda *a, **k: "model.gguf")
    monkeypatch.setattr(llama_engine._models, "get_or_load", lambda key, loader: model)
    built = LlamaEngine("en", "ur")
    built.ensure_model()
    return built, model


class TestLlamaEngine:
    def test_translates_each_sentence_and_keeps_empty_lines_empty(self, engine):
        translator, model = engine
        segments = [{"id": i, "start": float(i), "end": i + 1.0, "text": t, "words": [], "language": "en"}
                    for i, t in enumerate(["Hello there.", "  ", "Open GitHub."])]
        results = translator.translate_segments(segments)  # type: ignore[arg-type]
        assert [r["translated"] for r in results] == ["[Hello there.]", "", "[Open GitHub.]"]
        assert len(model.prompts) == 2

    def test_translating_before_loading_is_refused(self):
        with pytest.raises(RuntimeError, match="ensure_model"):
            LlamaEngine("en", "ur").translate_segments([])

    def test_registry_creates_it(self):
        assert isinstance(create_engine("hymt2", "en", "ja"), LlamaEngine)


class TestPrompt:
    def test_latin_terms_are_kept_as_written_in_a_non_latin_target(self):
        text = prompt("Open our GitHub page about ML Ops.", "en", "ur")
        assert "GitHub translates to GitHub" in text and "ML translates to ML" in text
        assert "into Urdu" in text and text.endswith("Open our GitHub page about ML Ops.")

    def test_latin_targets_need_no_glossary(self):
        assert "Reference" not in prompt("Open our GitHub page.", "ur", "en")

    def test_chinese_uses_the_chinese_prompt(self):
        assert prompt("Hello", "en", "zh").startswith("将以下文本翻译为中文")
        assert "参考下面的翻译" in prompt("Open GitHub", "ja", "zh")


class TestCatalog:
    def test_every_pair_is_direct(self):
        for source in _LANGUAGES:
            for target in _LANGUAGES:
                if source != target:
                    assert route("hymt2", source, target) == [(source, target)]

    def test_one_model_serves_every_pair(self):
        assert translation_asset_ids("ko", "ur", "hymt2") == [f"translation:{HYMT_MODEL.key}"]
        assert translation_asset_ids("", "ja", "hymt2") == [f"translation:{HYMT_MODEL.key}"]

    def test_download_and_readiness(self, monkeypatch, tmp_path):
        from ccgen.engines.translation import model_files

        monkeypatch.setattr(model_files, "translation_root", lambda: str(tmp_path))
        fetched = []

        def fake_download(repo, filename, revision, local_dir):
            fetched.append((repo, filename, revision))
            (tmp_path / HYMT_MODEL.key).mkdir(exist_ok=True)
            (tmp_path / HYMT_MODEL.key / filename).write_bytes(b"gguf")
            return str(tmp_path / HYMT_MODEL.key / filename)

        monkeypatch.setattr(model_files, "hf_hub_download", fake_download)
        path = model_files.ensure_gguf(HYMT_MODEL)
        assert path.endswith(HYMT_MODEL.filename) and model_files.is_ready(HYMT_MODEL.key, HYMT_MODEL.revision)
        model_files.ensure_gguf(HYMT_MODEL)
        assert len(fetched) == 1  # a finished download is reused
