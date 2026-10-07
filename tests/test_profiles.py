# test_profiles.py - performance profiles: recommendation, Automatic resolution, licences, hardware

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ccgen.config import licences, profiles
from ccgen.config.defaults import DubbingDefaults, LanguageOptions, get_default_settings
from ccgen.config.translation_models import CONCRETE_ENGINE_KEYS, route

_LANGUAGES = [code for _, code in LanguageOptions.TRANSLATION_TARGETS]


class TestRecommend:
    @pytest.mark.parametrize("vram, ram, cores, profile", [
        (12, 32, 8, "quality"),
        (8, 16, 4, "quality"),
        (6, 16, 6, "balanced"),
        (0, 32, 8, "balanced"),
        (0, 8, 16, "light"),
        (0, 32, 4, "light"),
        (2, 64, 4, "light"),
    ])
    def test_thresholds(self, vram, ram, cores, profile):
        assert profiles.recommend(vram, ram, cores) == profile

    def test_unknown_or_missing_profile_falls_back_to_light(self):
        assert profiles.normalize("") == profiles.normalize("turbo") == "light"
        assert profiles.profile_info("turbo").key == "light"

    def test_saved_profile(self):
        assert profiles.saved_profile({"performance": {"profile": "balanced"}}) == "balanced"
        assert profiles.saved_profile({}) == ""


class TestResolution:
    def test_whisper_model_per_profile(self):
        assert [profiles.whisper_model("auto", p) for p in ("quality", "balanced", "light", "")] == [
            "large-v3", "large-v3-turbo", "small", "small",
        ]
        assert profiles.whisper_model("medium", "quality") == "medium"

    @pytest.mark.parametrize("source", _LANGUAGES)
    @pytest.mark.parametrize("target", _LANGUAGES)
    def test_every_translation_pair_resolves_to_an_engine_that_can_translate_it(self, source, target):
        if source == target:
            return
        for profile in profiles.PROFILE_KEYS:
            engine = profiles.translation_engine("auto", profile, source, target)
            assert engine in CONCRETE_ENGINE_KEYS
            route(engine, source, target)  # raises when the engine can't reach the pair

    def test_automatic_translation_avoids_licence_gated_models(self):
        for source in _LANGUAGES:
            for target in _LANGUAGES:
                if source != target:
                    assert profiles.translation_engine("auto", "quality", source, target) not in licences.TERMS

    def test_opus_mt_gaps_go_to_hymt2(self):
        assert profiles.translation_engine("auto", "light", "en", "ur") == "opus_mt"
        assert profiles.translation_engine("auto", "light", "ur", "fr") == "opus_mt"
        assert profiles.translation_engine("auto", "light", "en", "ja") == "hymt2"
        assert profiles.translation_engine("auto", "light", "ko", "en") == "hymt2"
        assert profiles.translation_engine("auto", "light", "ja", "de") == "hymt2"
        assert profiles.translation_engine("auto", "light", "zh", "en") == "opus_mt"  # keeps the meaning better
        assert profiles.translation_engine("nllb", "light", "en", "ja") == "nllb"

    def test_translation_engines_cover_every_known_source(self):
        assert profiles.translation_engines("auto", "", "auto", "ur", ("ko", "en")) == {"hymt2", "opus_mt"}
        assert profiles.translation_engines("auto", "", "auto", "ur") == {"opus_mt"}
        assert profiles.translation_engines("auto", "", "auto", "en", ("en",)) == set()
        # A model chosen by hand runs whatever the pair, so its licence is always checked.
        assert profiles.translation_engines("nllb", "", "auto", "en") == {"nllb"}

    def test_transliteration_is_neural_only_off_the_light_profile_and_where_a_model_exists(self):
        assert profiles.transliteration_engine("auto", "light", "hi", "ur") == "rule"
        assert profiles.transliteration_engine("auto", "balanced", "hi", "ur") == "neural"
        assert profiles.transliteration_engine("auto", "quality", "roman", "hi") == "rule"
        assert profiles.transliteration_engine("neural", "light", "hi", "ur") == "neural"

    def test_dubbing_clones_with_omnivoice_fast_except_on_maximum_quality(self):
        assert profiles.dub_engine("auto", "quality") == profiles.DubChoice(DubbingDefaults.MODE_OMNIVOICE, False)
        assert profiles.dub_engine("auto", "light") == profiles.DubChoice(DubbingDefaults.MODE_OMNIVOICE, True)
        assert profiles.dub_engine("piper", "quality").mode == "piper"

    def test_dubbing_quality_overrides_the_profile(self):
        assert profiles.dub_engine("auto", "light", "full").fast is False
        assert profiles.dub_engine("auto", "quality", "fast").fast is True
        assert profiles.dub_engine("xtts", "light", "auto") == profiles.DubChoice("xtts", True)

    def test_describe_names_every_feature(self):
        for profile in profiles.PROFILE_KEYS:
            assert [feature for feature, _ in profiles.describe(profile)] == [
                "Subtitle generation", "Translation", "Transliteration", "Dubbing",
            ]


class TestCustomProfile:
    def test_custom_is_offered_after_the_presets(self):
        assert [p.key for p in profiles.PROFILE_CHOICES] == ["quality", "balanced", "light", "custom"]
        assert profiles.profile_info("custom").label == "Custom"
        assert "custom" not in profiles.PROFILE_KEYS  # jobs always carry a preset

    def test_custom_resolves_automatic_with_this_pcs_recommendation(self):
        assert profiles.effective_profile({"performance": {"profile": "custom", "recommended": "balanced"}}) == "balanced"
        assert profiles.effective_profile({"performance": {"profile": "custom", "recommended": ""}}) == ""
        assert profiles.effective_profile({"performance": {"profile": "light", "recommended": "quality"}}) == "light"
        assert profiles.saved_profile({"performance": {"profile": "custom"}}) == "custom"


class TestLicences:
    def test_every_licence_setting_exists_in_the_defaults(self):
        settings = get_default_settings()
        for terms in licences.TERMS.values():
            section, key = terms.setting.split(".")
            assert settings[section][key] is False

    def test_pending_and_blocker(self):
        settings = {"dubbing": {"omnivoice_terms_accepted": True}}
        assert licences.pending(settings, ["opus_mt", "omnivoice", "xtts"]) == "xtts"
        assert "XTTS-v2" in licences.blocker(settings, ["xtts"])
        assert licences.blocker(settings, ["omnivoice", "piper"]) == ""

    def test_terms_dict_for_the_dialog(self):
        assert licences.terms_dict("nllb")["setting"] == "translation.nllb_terms_accepted"
        assert licences.terms_dict("opus_mt") == {}


class TestHardware:
    def _detect(self, cuda=None, xpu=None, dml=False, cores=4, ram_gb=16):
        from ccgen.engines import hardware

        torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=lambda: cuda is not None, get_device_properties=lambda i: cuda),
            xpu=SimpleNamespace(is_available=lambda: xpu is not None, get_device_properties=lambda i: xpu),
        )
        ort = SimpleNamespace(get_available_providers=lambda: ["DmlExecutionProvider"] if dml else [])
        memory = SimpleNamespace(total=ram_gb * 1024 ** 3)
        with (
            patch.dict("sys.modules", {"torch": torch, "onnxruntime": ort}),
            patch.object(hardware.psutil, "cpu_count", return_value=cores),
            patch.object(hardware.psutil, "virtual_memory", return_value=memory),
        ):
            return hardware.detect()

    def test_nvidia_gpu_memory_decides(self):
        gpu = SimpleNamespace(name="NVIDIA RTX 4070", total_memory=12 * 1024 ** 3)
        profile = self._detect(cuda=gpu, cores=8, ram_gb=32)
        assert (profile.recommended, profile.summary) == ("quality", "NVIDIA RTX 4070 (12 GB), 32 GB RAM, 8 CPU cores")

    def test_directml_gpu_is_named_but_not_counted(self):
        profile = self._detect(dml=True)
        assert (profile.gpu, profile.vram_gb, profile.recommended) == ("DirectML GPU", 0.0, "light")

    def test_intel_xpu_counts(self):
        gpu = SimpleNamespace(name="Intel Arc A770", total_memory=16 * 1024 ** 3)
        assert self._detect(xpu=gpu).recommended == "quality"

    def test_fingerprint_changes_with_the_hardware(self):
        assert self._detect(ram_gb=16).fingerprint != self._detect(ram_gb=32).fingerprint
