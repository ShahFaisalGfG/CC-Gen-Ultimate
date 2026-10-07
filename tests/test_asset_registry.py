# test_asset_registry.py - unit tests for ccgen.utils.asset_registry

from unittest.mock import MagicMock, patch

import pytest

from ccgen.utils.asset_registry import (
    CATEGORY_TRANSLATION,
    CATEGORY_TRANSLITERATION,
    CATEGORY_VOICES,
    CATEGORY_WHISPER,
    delete_asset,
    download_asset,
    list_assets,
)
from ccgen.config.capabilities import translation_asset_ids


@pytest.fixture(autouse=True)
def _no_local_voices():
    """Report every voice as missing so catalog tests never depend on this machine's files."""
    with patch("ccgen.utils.asset_registry.voice_files.engine_files_cached", return_value=False):
        yield


class _FakeRevision:
    def __init__(self, commit_hash):
        self.commit_hash = commit_hash


class _FakeRepo:
    def __init__(self, repo_id, size_on_disk=0, revisions=None):
        self.repo_id = repo_id
        self.size_on_disk = size_on_disk
        self.revisions = revisions or [_FakeRevision("abc123")]


class _FakePackage:
    def __init__(self, from_code, to_code, package_path="/fake/pkg"):
        self.from_code = from_code
        self.to_code = to_code
        self.package_path = package_path


def _fake_cache(repos):
    cache_info = MagicMock()
    cache_info.repos = repos
    return cache_info


class TestListAssets:
    def test_catalog_has_expected_counts_per_category(self):
        with patch("ccgen.utils.asset_registry.model_status.whisper_cached", return_value=False):
            with patch(
                "ccgen.utils.asset_registry.model_status.translation_pair_cached", return_value=False
            ):
                with (
                    patch("ccgen.utils.asset_registry.model_status.neural_translit_cached", return_value=False),
                    patch("ccgen.utils.asset_registry.translation_files.is_ready", return_value=False),
                ):
                    assets = list_assets()

        whisper = [a for a in assets if a["category"] == CATEGORY_WHISPER]
        translation = [a for a in assets if a["category"] == CATEGORY_TRANSLATION]
        translit = [a for a in assets if a["category"] == CATEGORY_TRANSLITERATION]
        voices = [a for a in assets if a["category"] == CATEGORY_VOICES]
        assert len(whisper) == 6
        by_engine = {e: sum(a["engine"] == e for a in translation) for e in {a["engine"] for a in translation}}
        assert by_engine == {
            "OPUS-MT": 17,  # one model per English direction (some serve two languages)
            "NLLB-200 1.3B": 1,
            "MADLAD-400 3B": 1,
            "Hy-MT2 1.8B": 1,
            "Meaning check": 1,
            "Argos Translate": 24,  # each of the 12 non-English targets, to and from English
        }
        # OPUS-MT, which Automatic uses for most pairs, comes first in the tab.
        assert translation[0]["engine"] == "OPUS-MT"
        assert len(translit) == 3
        assert {a["engine"] for a in voices} == {"OmniVoice (voice cloning)", "XTTS-v2 (voice cloning)", "Kokoro", "Piper"}
        assert sum(a["engine"] == "Piper" for a in voices) > 50
        assert all(a["downloaded"] is False and a["size_bytes"] is None for a in assets)

    def test_whisper_asset_reports_approx_size_when_not_downloaded(self):
        with patch("ccgen.utils.asset_registry.model_status.whisper_cached", return_value=False):
            with patch(
                "ccgen.utils.asset_registry.model_status.translation_pair_cached", return_value=False
            ):
                with patch(
                    "ccgen.utils.asset_registry.model_status.neural_translit_cached", return_value=False
                ):
                    assets = list_assets()

        tiny = next(a for a in assets if a["id"] == "whisper:tiny")
        assert tiny["approx_size_mb"] == 75
        assert tiny["downloaded"] is False

    def test_downloaded_whisper_asset_reports_real_size(self):
        cache = _fake_cache([_FakeRepo("Systran/faster-whisper-tiny", size_on_disk=12345)])
        with patch("ccgen.utils.asset_registry.model_status.whisper_cached", return_value=True):
            with patch(
                "ccgen.utils.asset_registry.model_status.translation_pair_cached", return_value=False
            ):
                with patch(
                    "ccgen.utils.asset_registry.model_status.neural_translit_cached", return_value=False
                ):
                    with patch("ccgen.utils.asset_registry.scan_cache_dir", return_value=cache):
                        assets = list_assets()

        tiny = next(a for a in assets if a["id"] == "whisper:tiny")
        assert tiny["downloaded"] is True
        assert tiny["size_bytes"] == 12345

    def test_translation_asset_labels_include_english_source(self):
        with patch("ccgen.utils.asset_registry.model_status.whisper_cached", return_value=False):
            with patch(
                "ccgen.utils.asset_registry.model_status.translation_pair_cached", return_value=False
            ):
                with patch(
                    "ccgen.utils.asset_registry.model_status.neural_translit_cached", return_value=False
                ):
                    assets = list_assets()

        spanish = next(a for a in assets if a["id"] == "translation:en-es")
        assert spanish["label"] == "English → Spanish"
        back = next(a for a in assets if a["id"] == "translation:es-en")
        assert back["label"] == "Spanish → English"

    def test_not_downloaded_translation_and_transliteration_show_approx_size(self):
        # Argos/HF expose no size field for uninstalled packages, so these are measured
        # constants (see _TRANSLATION_APPROX_SIZES_MB/_TRANSLIT_APPROX_SIZES_MB) rather than
        # network-fetched or fabricated - this guards against them silently going missing.
        with patch("ccgen.utils.asset_registry.model_status.whisper_cached", return_value=False):
            with patch(
                "ccgen.utils.asset_registry.model_status.translation_pair_cached", return_value=False
            ):
                with patch(
                    "ccgen.utils.asset_registry.model_status.neural_translit_cached", return_value=False
                ):
                    assets = list_assets()

        spanish = next(a for a in assets if a["id"] == "translation:en-es")
        assert spanish["approx_size_mb"] == 92

        roman_ur = next(a for a in assets if a["id"] == "transliteration:roman-ur")
        assert roman_ur["approx_size_mb"] == 1856

        hi_ur = next(a for a in assets if a["id"] == "transliteration:hi-ur")
        assert hi_ur["approx_size_mb"] == 47

    def test_each_category_reports_its_engine(self):
        # Manage Models groups each category's rows by engine - today one engine per
        # category (two for transliteration), but the field exists so a future second
        # engine in any category doesn't need a schema change.
        with patch("ccgen.utils.asset_registry.model_status.whisper_cached", return_value=False):
            with patch(
                "ccgen.utils.asset_registry.model_status.translation_pair_cached", return_value=False
            ):
                with patch(
                    "ccgen.utils.asset_registry.model_status.neural_translit_cached", return_value=False
                ):
                    assets = list_assets()

        by_id = {a["id"]: a for a in assets}
        assert by_id["whisper:tiny"]["engine"] == "Faster Whisper"
        assert by_id["translation:en-es"]["engine"] == "Argos Translate"
        assert by_id["transliteration:roman-ur"]["engine"] == "Neural (M2M100)"
        assert by_id["transliteration:ur-roman"]["engine"] == "Neural (M2M100)"
        assert by_id["transliteration:hi-ur"]["engine"] == "Neural (Rekhta)"

    def test_transliteration_pair_size_includes_shared_tokenizer(self):
        cache = _fake_cache([
            _FakeRepo("Mavkif/m2m100_rup_rur_to_ur", size_on_disk=100),
            _FakeRepo("Mavkif/m2m100_rup_tokenizer_both", size_on_disk=10),
        ])
        with patch("ccgen.utils.asset_registry.model_status.whisper_cached", return_value=False):
            with patch(
                "ccgen.utils.asset_registry.model_status.translation_pair_cached", return_value=False
            ):
                with patch(
                    "ccgen.utils.asset_registry.model_status.neural_translit_cached",
                    side_effect=lambda s, t, cache_info=None: (s, t) == ("roman", "ur"),
                ):
                    with patch("ccgen.utils.asset_registry.scan_cache_dir", return_value=cache):
                        assets = list_assets()

        roman_ur = next(a for a in assets if a["id"] == "transliteration:roman-ur")
        assert roman_ur["downloaded"] is True
        assert roman_ur["size_bytes"] == 110


class TestTranslationAssetIds:
    def test_english_pairs_need_one_package(self):
        assert translation_asset_ids("en", "ur") == ["translation:en-ur"]
        assert translation_asset_ids("ur", "en") == ["translation:ur-en"]

    def test_other_pairs_need_both_legs_through_english(self):
        assert translation_asset_ids("ur", "fr") == ["translation:ur-en", "translation:en-fr"]

    def test_same_or_unknown_language_needs_nothing(self):
        assert translation_asset_ids("en", "en") == []
        assert translation_asset_ids("", "fr") == []


class TestVoiceAssets:
    def test_xtts_downloads_and_deletes_through_hf_cache(self):
        with patch("ccgen.utils.asset_registry.voice_files.ensure_xtts") as ensure:
            download_asset("voices:xtts")
        ensure.assert_called_once_with(None)
        cache = _fake_cache([_FakeRepo("coqui/XTTS-v2", revisions=[_FakeRevision("x1")])])
        with patch("ccgen.utils.asset_registry.scan_cache_dir", return_value=cache):
            delete_asset("voices:xtts")
        cache.delete_revisions.assert_called_once_with("x1")

    def test_piper_voice_downloads_and_removes_its_own_folder(self):
        with patch("ccgen.utils.asset_registry.voice_files.ensure_piper") as ensure:
            download_asset("voices:piper:ur_PK-fasih-medium")
        assert ensure.call_args.args[0].voice_id == "ur_PK-fasih-medium"
        with patch("ccgen.utils.asset_registry.voice_files.remove_engine_files") as remove:
            delete_asset("voices:piper:ur_PK-fasih-medium")
        assert remove.call_args.args[0] == "piper"

    def test_kokoro_downloads_its_model(self):
        with patch("ccgen.utils.asset_registry.voice_files.ensure_kokoro") as ensure:
            download_asset("voices:kokoro")
        ensure.assert_called_once_with(None)

    def test_unknown_piper_voice_is_rejected(self):
        with pytest.raises(RuntimeError, match="Unknown voice asset"):
            download_asset("voices:piper:nope")


class TestDownloadAsset:
    def test_whisper_dispatches_to_whisper_model(self):
        with patch("ccgen.utils.asset_registry.download_progress"):
            with patch("ccgen.utils.asset_registry.WhisperModel") as mock_model:
                download_asset("whisper:tiny")
        mock_model.assert_called_once_with("tiny", device="cpu", compute_type="int8")

    def test_translation_dispatches_to_install_pair(self):
        with patch("ccgen.utils.asset_registry.install_pair") as mock_install:
            download_asset("translation:en-es")
        mock_install.assert_called_once_with("en", "es", None, None)

    def test_transliteration_roman_ur_dispatches_to_neural_engine(self):
        with patch("ccgen.utils.asset_registry.NeuralEngine") as mock_engine_cls:
            download_asset("transliteration:roman-ur")
        mock_engine_cls.assert_called_once_with("roman", "ur")
        mock_engine_cls.return_value.ensure_loaded.assert_called_once_with(None, None)

    def test_transliteration_hi_ur_dispatches_to_rekhta_backend(self):
        with patch("ccgen.utils.asset_registry.RekhtaBackend") as mock_backend_cls:
            download_asset("transliteration:hi-ur")
        mock_backend_cls.return_value.load.assert_called_once_with(None, None)

    def test_unknown_category_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="Download failed"):
            download_asset("bogus:thing")

    def test_status_callback_fires_immediately_before_dispatch(self):
        # Guards against the UI staying on "Queued" for the whole transfer when a download
        # path (large multi-file Hugging Face repos in particular) reports byte progress late
        # or not at all - the very first status message must arrive before any real work runs.
        messages = []
        with patch("ccgen.utils.asset_registry.install_pair"):
            download_asset("translation:en-es", progress_cb=messages.append)
        assert messages == ["Downloading..."]

    def test_underlying_failure_wrapped_in_runtime_error(self):
        with patch("ccgen.utils.asset_registry.install_pair", side_effect=RuntimeError("no package")):
            with pytest.raises(RuntimeError, match="no package"):
                download_asset("translation:en-es")


class TestDeleteAsset:
    def test_whisper_deletes_matching_hf_repo(self):
        strategy = MagicMock()
        cache = _fake_cache([_FakeRepo("Systran/faster-whisper-tiny", revisions=[_FakeRevision("h1")])])
        cache.delete_revisions.return_value = strategy
        with patch("ccgen.utils.asset_registry.scan_cache_dir", return_value=cache):
            delete_asset("whisper:tiny")
        cache.delete_revisions.assert_called_once_with("h1")
        strategy.execute.assert_called_once()

    def test_whisper_delete_missing_repo_is_noop(self):
        with patch("ccgen.utils.asset_registry.scan_cache_dir", return_value=_fake_cache([])):
            delete_asset("whisper:tiny")  # must not raise

    def test_translation_uninstalls_matching_package(self):
        pkg = _FakePackage("en", "es")
        with patch(
            "ccgen.utils.asset_registry.argostranslate.package.get_installed_packages",
            return_value=[pkg],
        ):
            with patch("ccgen.utils.asset_registry.argostranslate.package.uninstall") as mock_uninstall:
                delete_asset("translation:en-es")
        mock_uninstall.assert_called_once_with(pkg)

    def test_transliteration_hi_ur_deletes_rekhta_repo(self):
        cache = _fake_cache([_FakeRepo("rekhtalabs/hi-2-ur-translit", revisions=[_FakeRevision("h2")])])
        with patch("ccgen.utils.asset_registry.scan_cache_dir", return_value=cache):
            delete_asset("transliteration:hi-ur")
        cache.delete_revisions.assert_called_once_with("h2")

    def test_unknown_category_raises_runtime_error(self):
        with pytest.raises(RuntimeError, match="Remove failed"):
            delete_asset("bogus:thing")
